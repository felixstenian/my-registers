"""Promoção de food_item legado (kcal=0 / catalog_ref_id=NULL) para um
nutrient_fact recém-criado.

Consumido em dois lugares:
- `POST /nutrient-facts/manual` com `promote_food_item_id` (SP-142).
- `POST /chat/messages` com `promote_food_item_id` + foto de rótulo, após
  `LabelCatalogService.upsert_from_label` retornar o fact criado
  (SP-143 / T-B521).

Idempotente: se o item já tinha `catalog_ref_id`, o audit registra o
`before` com o valor antigo e sobrescreve para o novo fact.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.nutrition.catalog import CatalogHit
from app.models import DayLog, FoodItem, FoodRecord, NutrientFact, User
from app.repositories.food import AuditEventRepository
from app.services.daily_recompute import DailyRecomputeService
from app.services.nutrition_calculator import NutritionCalculator

# Motivos padronizados de falha silenciosa. Frontend usa como discriminante.
PROMOTION_ITEM_NOT_FOUND = "promotion_failed:item_not_found"
PROMOTION_ITEM_DELETED = "promotion_failed:item_deleted"
PROMOTION_DAY_CLOSED = "promotion_failed:day_closed"

_ITEM_FIELDS = (
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


def _dec(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


async def try_promote_food_item(
    *,
    session: AsyncSession,
    user: User,
    item_id: uuid.UUID,
    fact: NutrientFact,
    message_id: uuid.UUID | None = None,
    promoted_from: str = "manual_catalog",
) -> tuple[str | None, uuid.UUID | None]:
    """Retorna `(warning, promoted_id)`.

    - Sucesso: `(None, item.id)`. Item atualizado (`catalog_ref_id`, macros,
      source), audit gravado, snapshot recomputado.
    - Falha silenciosa: `(warning_code, None)`. Nada é modificado no item;
      o caller decide se registra audit próprio de `promotion_failed`.

    `promoted_from` vira campo `after.promoted_from` no audit — útil
    pra distinguir promoção manual (SP-142) de promoção via foto de
    rótulo (SP-143).
    """
    stmt = (
        select(FoodItem, FoodRecord)
        .join(FoodRecord, FoodRecord.id == FoodItem.food_record_id)
        .where(FoodItem.id == item_id, FoodRecord.user_id == user.id)
    )
    row = (await session.execute(stmt)).one_or_none()
    if row is None:
        return (PROMOTION_ITEM_NOT_FOUND, None)
    item, food_record = row
    if item.deleted_at is not None:
        return (PROMOTION_ITEM_DELETED, None)

    day_log = await session.get(DayLog, food_record.day_log_id)
    if day_log is not None and day_log.status == "closed":
        return (PROMOTION_DAY_CLOSED, None)

    before: dict[str, Any] = {
        "catalog_ref_id": str(item.catalog_ref_id) if item.catalog_ref_id else None,
        "kcal": _dec(item.kcal),
        "needs_confirmation": item.needs_confirmation,
    }

    computed = NutritionCalculator.compute(
        hit=CatalogHit.from_model(fact), grams=item.grams, ml=item.ml
    )
    item.catalog_ref_id = fact.id
    for field in _ITEM_FIELDS:
        setattr(item, field, getattr(computed, field))
    item.needs_confirmation = False
    item.source = "user_corrected"
    await session.flush()

    await AuditEventRepository(session).record(
        user_id=user.id,
        entity_type="food_item",
        entity_id=item.id,
        action="correct",
        actor="user",
        message_id=message_id,
        before=before,
        after={
            "catalog_ref_id": str(fact.id),
            "kcal": _dec(item.kcal),
            "needs_confirmation": False,
            "promoted_from": promoted_from,
        },
    )
    await DailyRecomputeService(session).recompute(food_record.day_log_id)
    return (None, item.id)
