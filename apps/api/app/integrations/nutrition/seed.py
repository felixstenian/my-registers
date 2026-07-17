"""Seeder do catálogo local a partir de `seed_tbca.csv`.

Idempotente: para cada linha, faz UPSERT por `canonical_name` (unique
por convenção; se colidir com outro fact do mesmo nome e mesma marca,
atualiza os valores nutricionais).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.integrations.nutrition.normalize import normalize_name
from app.models import NutrientFact

_SEED_PATH = Path(__file__).parent / "seed_tbca.csv"


@dataclass(slots=True)
class SeedResult:
    inserted: int
    updated: int


def _parse_dec(value: str) -> Decimal | None:
    value = value.strip()
    if not value:
        return None
    return Decimal(value)


async def seed_from_csv(
    session: AsyncSession, *, path: Path | None = None
) -> SeedResult:
    csv_path = path or _SEED_PATH
    inserted = 0
    updated = 0

    with csv_path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            canonical = normalize_name(row["canonical_name"])
            aliases_raw = row.get("aliases", "") or ""
            aliases = sorted(
                {
                    normalize_name(a)
                    for a in aliases_raw.split(";")
                    if a.strip()
                }
                | {canonical}
            )

            stmt = select(NutrientFact).where(
                NutrientFact.canonical_name == canonical,
                NutrientFact.source == "TBCA_2023",
                NutrientFact.brand.is_(None),
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()

            payload = dict(
                canonical_name=canonical,
                aliases=aliases,
                source="TBCA_2023",
                serving_grams=_parse_dec(row.get("serving_grams") or ""),
                basis=row["basis"].strip(),
                kcal=_parse_dec(row.get("kcal") or ""),
                protein_g=_parse_dec(row.get("protein_g") or ""),
                carbs_g=_parse_dec(row.get("carbs_g") or ""),
                fat_g=_parse_dec(row.get("fat_g") or ""),
                fiber_g=_parse_dec(row.get("fiber_g") or ""),
                sodium_mg=_parse_dec(row.get("sodium_mg") or ""),
                calcium_mg=_parse_dec(row.get("calcium_mg") or ""),
                iron_mg=_parse_dec(row.get("iron_mg") or ""),
                potassium_mg=_parse_dec(row.get("potassium_mg") or ""),
            )
            if existing is None:
                session.add(NutrientFact(**payload))
                inserted += 1
            else:
                for key, value in payload.items():
                    setattr(existing, key, value)
                updated += 1

    await session.flush()
    return SeedResult(inserted=inserted, updated=updated)
