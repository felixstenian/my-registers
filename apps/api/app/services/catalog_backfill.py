"""Backfill de itens legados zerados + reconciliação do catálogo TBCA.

Motivação (investigação 2026-08-14): o banco de dev/prod foi seedado de uma
versão ANTIGA do `seed_tbca.csv` — faltam fatos no `nutrient_facts` (DB tinha
35; CSV atual tem 65). Consequência: `food_items` vivos com `kcal=0` porque o
lookup (`LocalTBCACatalog`) perdeu no momento do registro (ex.: `pepino`,
`cuscuz`, `granola`, `pão ceda`, `chocolate ao leite`).

Observação de naming: NÃO há drift de `canonical_name`. `seed.py` normaliza o
nome no ingest (`normalize_name`), então `brocolis_cozido` vira
`brocoll_cozido` no banco — e o lookup também normaliza a query. Renomear
esses nomes quebraria o matching. O fix é re-seedar + religar itens zerados.

Este service expõe:

1. `reseed_catalog()` — roda `seed_from_csv` (upsert idempotente) para inserir
   os fatos faltantes. Depois disso o lookup volta a bater.
2. `backfill_zeroed_items()` — para cada `food_item` vivo com `kcal=0`: faz
   lookup no catálogo, liga `catalog_ref_id`, preenche `grams`/`ml` a partir
   do `serving_grams` quando ambos estão ausentes (`is_estimate` vira `true`),
   recomputa macros (Const. Art. II §5/§10), grava `audit_events`
   (Const. Art. III §11) e recomputa o snapshot do dia.

Dias fechados são pulados por padrão (INV-5, Art. VIII §28); `include_closed`
permite corrigir histórico de forma explícita (decisão do operador).

Este arquivo NUNCA roda migrations nem toca infra — é só dados, via sessão.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.nutrition.catalog import LookupQuery
from app.integrations.nutrition.local_tbca import LocalTBCACatalog
from app.models import DayLog, FoodItem, FoodRecord, NutrientFact
from app.repositories.food import AuditEventRepository
from app.services.daily_recompute import DailyRecomputeService
from app.services.nutrition_calculator import NutritionCalculator

_MACRO_FIELDS = (
    "kcal",
    "protein_g",
    "carbs_g",
    "fat_g",
    "fiber_g",
    "sodium_mg",
    "calcium_mg",
    "iron_mg",
    "potassium_mg",
)


@dataclass(slots=True)
class ReseedResult:
    seed_inserted: int = 0
    seed_updated: int = 0


@dataclass(slots=True)
class BackfillResult:
    scanned: int = 0
    fixed: int = 0
    unresolved: list[str] = field(default_factory=list)
    skipped_closed: list[str] = field(default_factory=list)
    recomputed_days: int = 0


def _dec(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


class CatalogBackfillService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def reseed_catalog(self) -> ReseedResult:
        """Re-roda o seed TBCA (upsert idempotente) para inserir fatos
        faltantes e atualizar valores já existentes."""
        from app.integrations.nutrition.seed import seed_from_csv

        seed_result = await seed_from_csv(self.session)
        await self.session.flush()
        return ReseedResult(
            seed_inserted=seed_result.inserted,
            seed_updated=seed_result.updated,
        )

    async def backfill_zeroed_items(
        self,
        *,
        include_closed: bool = False,
    ) -> BackfillResult:
        """Recupera `food_items` vivos com `kcal=0` ligando ao catálogo.

        - Skip silencioso de itens em dias fechados (INV-5) a menos que
          `include_closed=True`.
        - Sem hit no catálogo → item vai para `unresolved` (o operador
          decide: card de recovery no chat, ou novo fato manual).
        - Com hit: liga `catalog_ref_id`; se `grams` e `ml` ambos ausentes,
          preenche com `serving_grams` do fato (e marca `is_estimate`).
        - Grava audit `action='correct'`, `actor='user'`, `message_id=None`
          e recomputa o snapshot do dia ao final (uma vez por dia).
        """
        catalog = LocalTBCACatalog(self.session)
        audit = AuditEventRepository(self.session)
        recompute = DailyRecomputeService(self.session)

        rows = (
            await self.session.execute(
                select(FoodItem, FoodRecord, DayLog)
                .join(FoodRecord, FoodRecord.id == FoodItem.food_record_id)
                .join(DayLog, DayLog.id == FoodRecord.day_log_id)
                .where(
                    FoodItem.deleted_at.is_(None),
                    (FoodItem.kcal == 0) | (FoodItem.kcal.is_(None)),
                )
            )
        ).all()

        result = BackfillResult(scanned=len(rows))
        affected_days: set[uuid.UUID] = set()

        for item, food_record, day_log in rows:
            if day_log.status == "closed" and not include_closed:
                result.skipped_closed.append(item.detected_name)
                continue

            hit = await catalog.lookup(LookupQuery(name=item.normalized_name, brand=item.brand))
            if hit is None:
                result.unresolved.append(item.detected_name)
                continue

            fact = await self.session.get(NutrientFact, uuid.UUID(hit.fact_id))
            grams = item.grams
            ml = item.ml
            needs_estimate = False
            if grams is None and ml is None and fact is not None and fact.serving_grams:
                if hit.basis == "per_100g":
                    grams = fact.serving_grams
                elif hit.basis == "per_100ml":
                    ml = fact.serving_grams
                needs_estimate = True

            computed = NutritionCalculator.compute(hit=hit, grams=grams, ml=ml)
            before = {
                "catalog_ref_id": str(item.catalog_ref_id) if item.catalog_ref_id else None,
                "kcal": _dec(item.kcal),
                "grams": _dec(item.grams),
                "ml": _dec(item.ml),
            }

            item.catalog_ref_id = uuid.UUID(hit.fact_id)
            if grams is not None:
                item.grams = grams
            if ml is not None:
                item.ml = ml
            for field_name in _MACRO_FIELDS:
                setattr(item, field_name, getattr(computed, field_name))
            item.needs_confirmation = False
            item.source = "user_corrected"
            if needs_estimate:
                item.is_estimate = True
            await self.session.flush()

            await audit.record(
                user_id=food_record.user_id,
                entity_type="food_item",
                entity_id=item.id,
                action="correct",
                actor="user",
                message_id=None,
                before=before,
                after={
                    "catalog_ref_id": str(item.catalog_ref_id),
                    "kcal": _dec(item.kcal),
                    "grams": _dec(item.grams),
                    "ml": _dec(item.ml),
                    "backfill": True,
                    "estimate_serving": needs_estimate,
                },
            )

            result.fixed += 1
            affected_days.add(food_record.day_log_id)

        for day_id in affected_days:
            await recompute.recompute(day_id)
        result.recomputed_days = len(affected_days)
        await self.session.flush()
        return result
