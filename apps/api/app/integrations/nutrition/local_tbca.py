"""Catálogo local baseado em `nutrient_facts` (seed TBCA + rótulos OCR).

Precedência (Const. Art. III §35 / app_plan §6 nutrient_facts):
1. marca casada exata (quando fornecida na query)
2. `TBCA_2023` > `label_ocr` > `manual`
3. `verified_by_user=true` > `false`
4. mais recente (`created_at DESC`)
"""

from __future__ import annotations

from sqlalchemy import case, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.integrations.nutrition.catalog import CatalogHit, LookupQuery, NutritionCatalog
from app.integrations.nutrition.normalize import normalize_name
from app.models import NutrientFact

_SOURCE_RANK = case(
    (NutrientFact.source == "TBCA_2023", 3),
    (NutrientFact.source == "label_ocr", 2),
    (NutrientFact.source == "manual", 1),
    else_=0,
)


class LocalTBCACatalog(NutritionCatalog):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def lookup(self, query: LookupQuery) -> CatalogHit | None:
        normalized = normalize_name(query.name)
        if not normalized:
            return None

        stmt = (
            select(NutrientFact)
            .where(
                or_(
                    NutrientFact.aliases.any(normalized),
                    NutrientFact.canonical_name == normalized,
                )
            )
            .order_by(
                # marca exata primeiro (quando brand foi passada)
                case(
                    (
                        (NutrientFact.brand.is_not(None))
                        & (query.brand is not None)
                        & (NutrientFact.brand == query.brand),
                        1,
                    ),
                    else_=0,
                ).desc(),
                _SOURCE_RANK.desc(),
                NutrientFact.verified_by_user.desc(),
                NutrientFact.created_at.desc(),
            )
            .limit(1)
        )
        fact = (await self.session.execute(stmt)).scalar_one_or_none()
        return CatalogHit.from_model(fact) if fact else None

    async def bulk_lookup(self, queries: list[LookupQuery]) -> list[CatalogHit | None]:
        return [await self.lookup(q) for q in queries]
