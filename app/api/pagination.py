"""Pagination bornée des listes.

Toute route qui liste des données d'un restaurant accepte ``skip`` et ``limit`` et ne
renvoie jamais plus de ``MAX_PAGE_SIZE`` lignes : le coût d'une requête est borné par
la page demandée, pas par la taille de la table. Les lignes sont triées sur une clé
stable (``created_at`` puis ``id``) pour que deux pages ne se recoupent pas.
"""

from dataclasses import dataclass

from fastapi import Query

DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500


@dataclass(frozen=True)
class Page:
    skip: int = 0
    limit: int = DEFAULT_PAGE_SIZE


def page_params(
    skip: int = Query(0, ge=0, le=100_000, description="Nombre de lignes à sauter"),
    limit: int = Query(
        DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description=f"Nombre de lignes à renvoyer (maximum {MAX_PAGE_SIZE})",
    ),
) -> Page:
    return Page(skip=skip, limit=limit)
