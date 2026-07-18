"""Interface do catálogo nutricional.

Implementações concretas: `LocalTBCACatalog` (busca em `nutrient_facts`).
`LLMFallbackCatalog` fica para pós-MVP conforme app_plan §9.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app.models import NutrientFact


@dataclass(slots=True, frozen=True)
class LookupQuery:
    name: str
    brand: str | None = None


@dataclass(slots=True)
class CatalogHit:
    """Resultado de lookup — expõe apenas o subset que o calculator precisa."""

    fact_id: str
    canonical_name: str
    basis: str  # 'per_100g' ou 'per_100ml'
    kcal: Decimal | None
    protein_g: Decimal | None
    carbs_g: Decimal | None
    fat_g: Decimal | None
    fiber_g: Decimal | None
    sodium_mg: Decimal | None
    calcium_mg: Decimal | None
    iron_mg: Decimal | None
    potassium_mg: Decimal | None
    source: str
    verified_by_user: bool

    @classmethod
    def from_model(cls, fact: NutrientFact) -> CatalogHit:
        return cls(
            fact_id=str(fact.id),
            canonical_name=fact.canonical_name,
            basis=fact.basis,
            kcal=fact.kcal,
            protein_g=fact.protein_g,
            carbs_g=fact.carbs_g,
            fat_g=fact.fat_g,
            fiber_g=fact.fiber_g,
            sodium_mg=fact.sodium_mg,
            calcium_mg=fact.calcium_mg,
            iron_mg=fact.iron_mg,
            potassium_mg=fact.potassium_mg,
            source=fact.source,
            verified_by_user=fact.verified_by_user,
        )


class NutritionCatalog(Protocol):
    async def lookup(self, query: LookupQuery) -> CatalogHit | None: ...

    async def bulk_lookup(
        self, queries: list[LookupQuery]
    ) -> list[CatalogHit | None]: ...
