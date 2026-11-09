"""Bon de commande : page imprimable (HTML autonome, mise en page A4) et e-mail au fournisseur.

Rien ici ne touche la base : le service prépare un ``BonDoc`` et ces fonctions le mettent en forme.
Tout texte inséré est échappé ; aucune ressource distante.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List, Optional, Tuple

from app.services.email_layout import Details, Stat, Status, render_email

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]
_SANS_DECIMALES = {"XAF", "XOF", "JPY", "KRW", "RWF", "GNF"}


@dataclass
class DocLigne:
    reference: Optional[str]
    nom: str
    quantite: Decimal
    unite: str
    prix_unitaire: Optional[Decimal]
    total: Decimal


@dataclass
class BonDoc:
    numero: str
    cree_le: date
    date_livraison_prevue: Optional[date]
    note: Optional[str]
    devise: str
    total: Decimal
    restaurant_nom: str
    restaurant_telephone: Optional[str]
    restaurant_adresse: Optional[str]
    fournisseur_nom: str
    fournisseur_contact: Optional[str]
    fournisseur_email: Optional[str]
    fournisseur_telephone: Optional[str]
    fournisseur_adresse: Optional[str]
    conditions_paiement: Optional[str]
    lignes: List[DocLigne] = field(default_factory=list)


def date_fr(valeur: Optional[date]) -> str:
    return f"{valeur.day} {MOIS[valeur.month - 1]} {valeur.year}" if valeur else "—"


def quantite_fr(valeur: Decimal) -> str:
    texte = f"{Decimal(valeur):,.3f}".rstrip("0").rstrip(".")
    return texte.replace(",", " ").replace(".", ",")


def montant_fr(valeur: Optional[Decimal], devise: str) -> str:
    if valeur is None:
        return "—"
    places = 0 if devise in _SANS_DECIMALES else 2
    texte = f"{Decimal(valeur):,.{places}f}".replace(",", " ").replace(".", ",")
    return f"{texte} {'FCFA' if devise in ('XAF', 'XOF') else devise}"


def _e(valeur: object) -> str:
    return html.escape("" if valeur is None else str(valeur), quote=True)


def _multiligne(valeur: Optional[str]) -> str:
    return _e(valeur).replace("\n", "<br>")


# ------------------------------------------------------------------------------ page imprimable


_STYLE = """
@page { size: A4; margin: 16mm; }
* { box-sizing: border-box; }
body { margin: 0; color: #23232e; font: 13px/1.5 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #f3f1ee; }
.page { max-width: 794px; margin: 24px auto; background: #fff; padding: 40px 44px; border: 1px solid #ebe5de; border-radius: 12px; }
.top { display: flex; justify-content: space-between; align-items: flex-start; gap: 24px; }
h1 { margin: 0; font-size: 22px; letter-spacing: .01em; }
.muted { color: #7a7168; }
.num { font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: #B85F0F; font-weight: 700; }
.cols { display: flex; gap: 24px; margin-top: 28px; }
.box { flex: 1; border: 1px solid #ece6df; border-radius: 10px; padding: 14px 16px; }
.box h2 { margin: 0 0 6px; font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: #9a9188; }
table { width: 100%; border-collapse: collapse; margin-top: 26px; }
th { text-align: left; font-size: 11px; letter-spacing: .06em; text-transform: uppercase; color: #9a9188; border-bottom: 1px solid #23232e; padding: 8px 6px; }
td { padding: 9px 6px; border-bottom: 1px solid #efe7de; vertical-align: top; }
.r { text-align: right; white-space: nowrap; }
.total td { border-bottom: 0; font-weight: 700; font-size: 15px; padding-top: 14px; }
.note { margin-top: 22px; padding: 12px 14px; background: #faf6f1; border-radius: 10px; }
.sign { margin-top: 48px; display: flex; gap: 24px; }
.sign div { flex: 1; border-top: 1px solid #cfc6bc; padding-top: 6px; font-size: 11px; color: #9a9188; }
.actions { max-width: 794px; margin: 16px auto 0; text-align: right; }
.actions button { font: inherit; padding: 9px 18px; border: 0; border-radius: 10px; background: #E67E22; color: #fff; font-weight: 600; cursor: pointer; }
@media print { body { background: #fff; } .page { margin: 0; border: 0; padding: 0; max-width: none; } .actions { display: none; } }
"""


def render_bon_html(doc: BonDoc) -> str:
    rows = "".join(
        "<tr>"
        f"<td class=\"muted\">{_e(l.reference) or '&nbsp;'}</td>"
        f"<td>{_e(l.nom)}</td>"
        f"<td class=\"r\">{_e(quantite_fr(l.quantite))} {_e(l.unite)}</td>"
        f"<td class=\"r\">{_e(montant_fr(l.prix_unitaire, doc.devise))}</td>"
        f"<td class=\"r\">{_e(montant_fr(l.total, doc.devise))}</td>"
        "</tr>"
        for l in doc.lignes
    )
    contact = " · ".join(x for x in (doc.fournisseur_contact, doc.fournisseur_telephone, doc.fournisseur_email) if x)
    note = f'<div class="note"><strong>Remarques</strong><br>{_multiligne(doc.note)}</div>' if doc.note else ""
    paiement = (
        f'<div class="muted" style="margin-top:6px">Paiement : {_e(doc.conditions_paiement)}</div>'
        if doc.conditions_paiement else ""
    )
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bon de commande {_e(doc.numero)}</title><style>{_STYLE}</style></head>
<body>
<div class="actions"><button type="button" onclick="window.print()">Imprimer</button></div>
<div class="page">
  <div class="top">
    <div><div class="num">Bon de commande</div><h1>{_e(doc.numero)}</h1>
      <div class="muted">Établi le {_e(date_fr(doc.cree_le))}</div></div>
    <div style="text-align:right"><strong>{_e(doc.restaurant_nom)}</strong>
      <div class="muted">{_multiligne(doc.restaurant_adresse)}</div>
      <div class="muted">{_e(doc.restaurant_telephone)}</div></div>
  </div>
  <div class="cols">
    <div class="box"><h2>Fournisseur</h2><strong>{_e(doc.fournisseur_nom)}</strong>
      <div class="muted">{_multiligne(doc.fournisseur_adresse)}</div>
      <div class="muted">{_e(contact)}</div>{paiement}</div>
    <div class="box"><h2>Livraison souhaitée</h2><strong>{_e(date_fr(doc.date_livraison_prevue))}</strong>
      <div class="muted">{_e(doc.restaurant_nom)}</div></div>
  </div>
  <table>
    <thead><tr><th>Réf.</th><th>Désignation</th><th class="r">Quantité</th><th class="r">Prix unitaire</th><th class="r">Total</th></tr></thead>
    <tbody>{rows}
      <tr class="total"><td colspan="4" class="r">Total estimé</td><td class="r">{_e(montant_fr(doc.total, doc.devise))}</td></tr>
    </tbody>
  </table>
  {note}
  <div class="sign"><div>Établi par</div><div>Accusé de réception du fournisseur</div></div>
</div>
</body></html>"""


# ---------------------------------------------------------------------------------------- e-mail


def build_bon_email(doc: BonDoc, message: Optional[str] = None) -> Tuple[str, str, str]:
    """Retourne ``(objet, texte brut, html)`` : lignes, total et date de livraison souhaitée."""
    paragraphs = [
        f"Veuillez trouver ci-dessous notre bon de commande {doc.numero}.",
        "Merci de nous confirmer la disponibilité et la date de livraison en répondant à cet e-mail"
        + (f" ou au {doc.restaurant_telephone}." if doc.restaurant_telephone else "."),
    ]
    if message:
        paragraphs.insert(0, message)
    rows = [
        (
            f"{l.nom}" + (f" (réf. {l.reference})" if l.reference else ""),
            f"{quantite_fr(l.quantite)} {l.unite}",
        )
        for l in doc.lignes
    ]
    details = Details(title="Articles commandés", badge=f"{len(doc.lignes)} ligne{'s' if len(doc.lignes) > 1 else ''}", rows=rows)
    stats = [
        Stat("Livraison souhaitée", date_fr(doc.date_livraison_prevue)),
        Stat("Total estimé", montant_fr(doc.total, doc.devise)),
    ]
    if doc.note:
        paragraphs.append(f"Remarques : {doc.note}")
    texte, page = render_email(
        title=f"Bon de commande {doc.numero}",
        greeting=f"Bon de commande {doc.numero}",
        paragraphs=paragraphs,
        status=Status("Nouvelle commande", "brand"),
        details=details,
        stats=stats,
        signature=doc.restaurant_nom,
        reference=doc.numero,
    )
    objet = f"Bon de commande {doc.numero} — {doc.restaurant_nom}"
    return objet, texte, page
