"""Tarification d'un pressing : tarifs, articles, combinaisons, aperçu de commande.

Couche service (accès base + journal d'audit). Les règles de calcul sont dans
``pressing_calcul`` (pur). Le service ne valide jamais de commit : la requête s'en charge.

Erreurs : ``NotFoundError`` (404), ``ConflictError`` (409, nom en double),
``PressingRegleError`` (422, règle métier).
"""

from __future__ import annotations

import uuid
from typing import Dict, Iterable, List, Optional

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.pressing import (
    PressingArticle,
    PressingCombinaison,
    PressingCombinaisonLigne,
    PressingTarif,
)
from app.repositories.ros_repository import RosAuditLogRepository
from app.services import pressing_calcul as calc
from app.services.pressing_calcul import PressingRegleError
from app.utils.exceptions import ConflictError, NotFoundError

PRIX_KG_DEFAUT = 500
PAS_DEFAUT = 1000
MODE_DEFAUT = "superieur"
PRIX_MAX = 100_000_000


class PressingService:
    def __init__(self, db: Session, restaurant_id: uuid.UUID, actor_id=None):
        self.db = db
        self.restaurant_id = restaurant_id
        self.actor_id = actor_id
        self._audit = RosAuditLogRepository(db)

    # ------------------------------------------------------------------ audit
    def _log(self, action, entity_name, entity_id, before, after):
        self._audit.log_action(
            restaurant_id=self.restaurant_id,
            action=action,
            entity_name=entity_name,
            entity_id=entity_id,
            actor_id=self.actor_id,
            before_state=before,
            after_state=after,
        )

    # ----------------------------------------------------------------- tarifs
    def get_tarif(self) -> PressingTarif:
        """Tarif du restaurant ; la ligne est créée avec les défauts à la première lecture."""
        tarif = self._find_tarif()
        if tarif is None:
            # ON CONFLICT : deux premières lectures simultanées ne se gênent pas.
            self.db.execute(
                pg_insert(PressingTarif.__table__)
                .values(
                    id=uuid.uuid4(),
                    restaurant_id=self.restaurant_id,
                    prix_kg=PRIX_KG_DEFAUT,
                    prix_sechage_kg=None,
                    arrondi_pas_grammes=PAS_DEFAUT,
                    arrondi_mode=MODE_DEFAUT,
                )
                .on_conflict_do_nothing(index_elements=["restaurant_id"])
            )
            tarif = self._find_tarif()
        return tarif

    def _find_tarif(self) -> Optional[PressingTarif]:
        return (
            self.db.query(PressingTarif)
            .filter(PressingTarif.restaurant_id == self.restaurant_id)
            .first()
        )

    @staticmethod
    def tarif_state(tarif: PressingTarif) -> dict:
        return {
            "prix_kg": tarif.prix_kg,
            "prix_sechage_kg": tarif.prix_sechage_kg,
            "arrondi": {
                "pas_grammes": tarif.arrondi_pas_grammes,
                "mode": tarif.arrondi_mode,
            },
        }

    def update_tarif(
        self, prix_kg: int, prix_sechage_kg: Optional[int], pas_grammes: int, mode: str
    ) -> PressingTarif:
        tarif = self.get_tarif()
        before = self.tarif_state(tarif)
        tarif.prix_kg = prix_kg
        tarif.prix_sechage_kg = prix_sechage_kg
        tarif.arrondi_pas_grammes = pas_grammes
        tarif.arrondi_mode = mode
        self.db.flush()
        self._log(
            "PRESSING_TARIF_UPDATE", "PressingTarif", tarif.id, before, self.tarif_state(tarif)
        )
        return tarif

    # --------------------------------------------------------------- articles
    @staticmethod
    def article_state(article: PressingArticle) -> dict:
        return {
            "nom": article.nom,
            "prix_unitaire": article.prix_unitaire,
            "categorie": article.categorie,
            "actif": article.actif,
        }

    def list_articles(self, actif: Optional[bool] = None) -> List[PressingArticle]:
        query = self.db.query(PressingArticle).filter(
            PressingArticle.restaurant_id == self.restaurant_id
        )
        if actif is not None:
            query = query.filter(PressingArticle.actif.is_(actif))
        return query.order_by(func.lower(PressingArticle.nom), PressingArticle.id).all()

    def get_article(self, article_id: uuid.UUID) -> PressingArticle:
        article = (
            self.db.query(PressingArticle)
            .filter(
                PressingArticle.id == article_id,
                PressingArticle.restaurant_id == self.restaurant_id,
            )
            .first()
        )
        if article is None:
            raise NotFoundError("Article introuvable")
        return article

    def _article_by_name(self, nom: str) -> Optional[PressingArticle]:
        return (
            self.db.query(PressingArticle)
            .filter(
                PressingArticle.restaurant_id == self.restaurant_id,
                func.lower(PressingArticle.nom) == nom.lower(),
            )
            .first()
        )

    def create_article(
        self, nom: str, prix_unitaire: int, categorie: Optional[str], actif: bool = True
    ) -> PressingArticle:
        if self._article_by_name(nom) is not None:
            raise ConflictError(f"Un article nommé « {nom} » existe déjà")
        article = PressingArticle(
            restaurant_id=self.restaurant_id,
            nom=nom,
            prix_unitaire=prix_unitaire,
            categorie=categorie,
            actif=actif,
        )
        self._flush_unique(article, f"Un article nommé « {nom} » existe déjà")
        self._log(
            "PRESSING_ARTICLE_CREATE", "PressingArticle", article.id, None,
            self.article_state(article),
        )
        return article

    def update_article(
        self, article_id: uuid.UUID, nom: str, prix_unitaire: int,
        categorie: Optional[str], actif: bool,
    ) -> PressingArticle:
        article = self.get_article(article_id)
        other = self._article_by_name(nom)
        if other is not None and other.id != article.id:
            raise ConflictError(f"Un article nommé « {nom} » existe déjà")
        before = self.article_state(article)
        article.nom = nom
        article.prix_unitaire = prix_unitaire
        article.categorie = categorie
        article.actif = actif
        self._flush_unique(article, f"Un article nommé « {nom} » existe déjà")
        self._log(
            "PRESSING_ARTICLE_UPDATE", "PressingArticle", article.id, before,
            self.article_state(article),
        )
        return article

    def deactivate_article(self, article_id: uuid.UUID) -> None:
        article = self.get_article(article_id)
        if not article.actif:
            return
        before = self.article_state(article)
        article.actif = False
        self.db.flush()
        self._log(
            "PRESSING_ARTICLE_DEACTIVATE", "PressingArticle", article.id, before,
            self.article_state(article),
        )

    def _flush_unique(self, obj, message: str) -> None:
        """Flush dans un point de sauvegarde : un doublon concurrent devient un 409 propre."""
        try:
            with self.db.begin_nested():
                self.db.add(obj)
                self.db.flush()
        except IntegrityError as exc:
            raise ConflictError(message) from exc

    # ----------------------------------------------------------- combinaisons
    def combinaison_state(self, combinaison: PressingCombinaison) -> dict:
        return {
            "nom": combinaison.nom,
            "prix": combinaison.prix,
            "actif": combinaison.actif,
            "lignes": [
                {"article_id": str(l.article_id), "quantite": l.quantite}
                for l in sorted(combinaison.lignes_cache, key=lambda l: str(l.article_id))
            ],
        }

    def _lignes_of(self, combinaison_id: uuid.UUID) -> List[PressingCombinaisonLigne]:
        return (
            self.db.query(PressingCombinaisonLigne)
            .filter(
                PressingCombinaisonLigne.restaurant_id == self.restaurant_id,
                PressingCombinaisonLigne.combinaison_id == combinaison_id,
            )
            .order_by(PressingCombinaisonLigne.id)
            .all()
        )

    def list_combinaisons(self) -> List[PressingCombinaison]:
        combinaisons = (
            self.db.query(PressingCombinaison)
            .filter(PressingCombinaison.restaurant_id == self.restaurant_id)
            .order_by(func.lower(PressingCombinaison.nom), PressingCombinaison.id)
            .all()
        )
        self._attach_lignes(combinaisons)
        return combinaisons

    def get_combinaison(self, combinaison_id: uuid.UUID) -> PressingCombinaison:
        combinaison = (
            self.db.query(PressingCombinaison)
            .filter(
                PressingCombinaison.id == combinaison_id,
                PressingCombinaison.restaurant_id == self.restaurant_id,
            )
            .first()
        )
        if combinaison is None:
            raise NotFoundError("Combinaison introuvable")
        self._attach_lignes([combinaison])
        return combinaison

    def _attach_lignes(self, combinaisons: List[PressingCombinaison]) -> None:
        """Deux requêtes pour toute la liste (lignes + articles), pas une par combinaison."""
        ids = [c.id for c in combinaisons]
        par_combinaison: Dict[uuid.UUID, list] = {i: [] for i in ids}
        if ids:
            rows = (
                self.db.query(PressingCombinaisonLigne, PressingArticle)
                .join(PressingArticle, PressingArticle.id == PressingCombinaisonLigne.article_id)
                .filter(
                    PressingCombinaisonLigne.restaurant_id == self.restaurant_id,
                    PressingCombinaisonLigne.combinaison_id.in_(ids),
                )
                .order_by(func.lower(PressingArticle.nom), PressingArticle.id)
                .all()
            )
            for ligne, article in rows:
                ligne.article_nom = article.nom
                ligne.prix_unitaire_reference = article.prix_unitaire
                par_combinaison[ligne.combinaison_id].append(ligne)
        for combinaison in combinaisons:
            combinaison.lignes_cache = par_combinaison[combinaison.id]

    def _resolve_lignes(
        self, lignes: Iterable[tuple], deja_presents: Iterable[uuid.UUID] = ()
    ) -> List[tuple]:
        """Valide ``[(article_id, quantite)]`` : même restaurant, actifs, sans doublon.

        Un article déjà dans la combinaison peut y rester même désactivé.
        """
        lignes = list(lignes)
        if not lignes:
            return []
        ids = [article_id for article_id, _ in lignes]
        if len(set(ids)) != len(ids):
            raise PressingRegleError("Un article ne peut apparaître qu'une fois par combinaison")
        articles = {
            a.id: a
            for a in self.db.query(PressingArticle)
            .filter(
                PressingArticle.restaurant_id == self.restaurant_id,
                PressingArticle.id.in_(ids),
            )
            .all()
        }
        gardes = set(deja_presents)
        for article_id, quantite in lignes:
            article = articles.get(article_id)
            if article is None:
                raise PressingRegleError(
                    f"Article introuvable pour ce restaurant : {article_id}"
                )
            if not article.actif and article_id not in gardes:
                raise PressingRegleError(f"L'article « {article.nom} » est désactivé")
            if quantite < 1:
                raise PressingRegleError("Les quantités doivent être d'au moins 1")
        return lignes

    def _combinaison_by_name(self, nom: str) -> Optional[PressingCombinaison]:
        return (
            self.db.query(PressingCombinaison)
            .filter(
                PressingCombinaison.restaurant_id == self.restaurant_id,
                func.lower(PressingCombinaison.nom) == nom.lower(),
            )
            .first()
        )

    def create_combinaison(
        self, nom: str, prix: int, lignes: Iterable[tuple], actif: bool = True
    ) -> PressingCombinaison:
        if self._combinaison_by_name(nom) is not None:
            raise ConflictError(f"Une combinaison nommée « {nom} » existe déjà")
        resolved = self._resolve_lignes(lignes)
        if not resolved:
            raise PressingRegleError("Une combinaison contient au moins un article")
        combinaison = PressingCombinaison(
            restaurant_id=self.restaurant_id, nom=nom, prix=prix, actif=actif
        )
        self._flush_unique(combinaison, f"Une combinaison nommée « {nom} » existe déjà")
        self._write_lignes(combinaison, resolved)
        self._log(
            "PRESSING_COMBINAISON_CREATE", "PressingCombinaison", combinaison.id, None,
            self.combinaison_state(combinaison),
        )
        return combinaison

    def update_combinaison(
        self, combinaison_id: uuid.UUID, nom: str, prix: int, lignes: Iterable[tuple],
        actif: bool,
    ) -> PressingCombinaison:
        combinaison = self.get_combinaison(combinaison_id)
        other = self._combinaison_by_name(nom)
        if other is not None and other.id != combinaison.id:
            raise ConflictError(f"Une combinaison nommée « {nom} » existe déjà")
        resolved = self._resolve_lignes(
            lignes, deja_presents=[l.article_id for l in combinaison.lignes_cache]
        )
        if not resolved:
            raise PressingRegleError("Une combinaison contient au moins un article")
        before = self.combinaison_state(combinaison)
        combinaison.nom = nom
        combinaison.prix = prix
        combinaison.actif = actif
        self._flush_unique(combinaison, f"Une combinaison nommée « {nom} » existe déjà")
        self._write_lignes(combinaison, resolved)
        self._log(
            "PRESSING_COMBINAISON_UPDATE", "PressingCombinaison", combinaison.id, before,
            self.combinaison_state(combinaison),
        )
        return combinaison

    def deactivate_combinaison(self, combinaison_id: uuid.UUID) -> None:
        combinaison = self.get_combinaison(combinaison_id)
        if not combinaison.actif:
            return
        before = self.combinaison_state(combinaison)
        combinaison.actif = False
        self.db.flush()
        self._log(
            "PRESSING_COMBINAISON_DEACTIVATE", "PressingCombinaison", combinaison.id,
            before, self.combinaison_state(combinaison),
        )

    def _write_lignes(self, combinaison: PressingCombinaison, resolved: List[tuple]) -> None:
        self.db.query(PressingCombinaisonLigne).filter(
            PressingCombinaisonLigne.restaurant_id == self.restaurant_id,
            PressingCombinaisonLigne.combinaison_id == combinaison.id,
        ).delete(synchronize_session=False)
        for article_id, quantite in resolved:
            self.db.add(
                PressingCombinaisonLigne(
                    restaurant_id=self.restaurant_id,
                    combinaison_id=combinaison.id,
                    article_id=article_id,
                    quantite=quantite,
                )
            )
        self.db.flush()
        self._attach_lignes([combinaison])

    # ----------------------------------------------------------------- calcul
    def calculer(self, demande: calc.DemandeCalcul) -> dict:
        """Aperçu : lit le tarif (créé à la volée si absent) mais n'écrit aucune commande."""
        tarif = self.get_tarif()
        article_ids = [i for i, _ in demande.articles]
        combinaison_ids = [i for i, _ in demande.combinaisons]
        articles = {}
        if article_ids:
            articles = {
                a.id: calc.ArticleTarifie(a.nom, a.prix_unitaire, a.actif)
                for a in self.db.query(PressingArticle)
                .filter(
                    PressingArticle.restaurant_id == self.restaurant_id,
                    PressingArticle.id.in_(article_ids),
                )
                .all()
            }
        combinaisons = {}
        if combinaison_ids:
            combinaisons = {
                c.id: calc.CombinaisonTarifee(c.nom, c.prix, c.actif)
                for c in self.db.query(PressingCombinaison)
                .filter(
                    PressingCombinaison.restaurant_id == self.restaurant_id,
                    PressingCombinaison.id.in_(combinaison_ids),
                )
                .all()
            }
        return calc.calculer(
            calc.Tarif(
                tarif.prix_kg, tarif.prix_sechage_kg, tarif.arrondi_pas_grammes,
                tarif.arrondi_mode,
            ),
            demande,
            articles,
            combinaisons,
        )
