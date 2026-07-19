"""LabelCatalogService — Fase 4.b / SP-30..SP-35.

Cadastra `nutrient_facts` com `source='label_ocr'` a partir de fotos de
rótulo, opcionalmente registra o consumo (`also_consumed`) na mesma
transação. Const. Art. III §35:

- **Precedência de lookup** (SP-35): (1) marca casada; (2) TBCA_2023 >
  label_ocr > manual; (3) verified_by_user=true > false; (4) mais
  recente. Já é garantida pelo `LocalTBCACatalog`. Aqui apenas nos
  preocupamos em NÃO duplicar entradas de mesma marca+produto quando o
  usuário refoto — `barcode` (se presente) ou `(canonical_name, brand)`
  como chave de idempotência.
- **Normalização determinística** (SP-32): `per_serving` com
  `serving_size_*` é escalado para `per_100g|per_100ml` no upsert. A
  validação de "per_serving sem tamanho" já vive no
  `NutritionLabelIn.model_validator`.
- **Micros ausentes** (SP-34): rótulos brasileiros geralmente não
  reportam Ca/Fe/K. Guardamos `null` e emitimos warning
  `micros_missing_for_product` no retorno do service para o handler
  incluir no assistant message.
- **Consumo opcional** (SP-31): `also_consumed` gera 1 food_record + 1
  food_item apontando para o fact recém-criado. O cálculo usa
  `NutritionCalculator.compute` — mesma engine determinística do
  MealService (INV-1).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.nutrition.catalog import CatalogHit
from app.integrations.nutrition.normalize import normalize_name
from app.models import FoodItem, FoodRecord, NutrientFact, User
from app.repositories.food import AuditEventRepository, FoodItemRepository, FoodRecordRepository
from app.schemas.llm import NutritionLabelAlsoConsumed, NutritionLabelIn
from app.services.nutrition_calculator import NutritionCalculator

_NUTRIENT_FIELDS: tuple[str, ...] = (
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

# Micros que rótulos BR quase nunca informam (RDC 429/2020).
_MICRO_FIELDS: tuple[str, ...] = ("calcium_mg", "iron_mg", "potassium_mg")


@dataclass(slots=True)
class LabelResult:
    fact: NutrientFact
    warnings: list[dict[str, Any]] = field(default_factory=list)
    consumed_item: FoodItem | None = None
    consumed_record: FoodRecord | None = None


class LabelCatalogService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditEventRepository(session)
        self.food_records = FoodRecordRepository(session)
        self.food_items = FoodItemRepository(session)

    async def upsert_from_label(
        self,
        *,
        user: User,
        label: NutritionLabelIn,
        label_media_id: uuid.UUID | None,
        message_id: uuid.UUID | None,
    ) -> LabelResult:
        """Cria ou atualiza um `nutrient_facts` com `source='label_ocr'`.

        Idempotência: se existir um fact `label_ocr` com o mesmo `barcode`
        (quando o rótulo trouxer) ou o mesmo `(canonical_name, brand)`, o
        upsert **atualiza** valores em vez de duplicar. `verified_by_user`
        NUNCA é rebaixado por reupload — se estava `true`, permanece `true`.
        """
        basis, scale = _resolve_basis_and_scale(label)
        scaled = {field: _scale_or_none(getattr(label, field), scale) for field in _NUTRIENT_FIELDS}

        canonical = normalize_name(label.product_name)
        # Aliases básicos: canonical + variação sem marca (se marca existir).
        aliases = sorted({canonical, normalize_name(label.product_name)})

        existing = await self._find_existing_label_fact(
            canonical=canonical, brand=label.brand, barcode=label.barcode
        )

        if existing is None:
            fact = NutrientFact(
                canonical_name=canonical,
                aliases=aliases,
                brand=label.brand,
                source="label_ocr",
                basis=basis,
                barcode=label.barcode,
                label_media_id=label_media_id,
                verified_by_user=False,
                **scaled,
            )
            self.session.add(fact)
            await self.session.flush()
            action = "create"
            before: dict[str, Any] | None = None
        else:
            before = {
                "basis": existing.basis,
                **{f: _dec_or_none(getattr(existing, f)) for f in _NUTRIENT_FIELDS},
            }
            existing.basis = basis
            existing.aliases = aliases
            if label.brand and existing.brand != label.brand:
                existing.brand = label.brand
            if label.barcode and existing.barcode != label.barcode:
                existing.barcode = label.barcode
            if label_media_id is not None:
                existing.label_media_id = label_media_id
            for k, v in scaled.items():
                setattr(existing, k, v)
            fact = existing
            await self.session.flush()
            action = "update"

        after = {
            "basis": fact.basis,
            **{f: _dec_or_none(getattr(fact, f)) for f in _NUTRIENT_FIELDS},
        }
        await self.audit.record(
            user_id=user.id,
            entity_type="nutrient_fact",
            entity_id=fact.id,
            action=action,
            actor="llm",
            message_id=message_id,
            before=before,
            after=after,
        )

        warnings: list[dict[str, Any]] = []
        missing_micros = [f for f in _MICRO_FIELDS if getattr(fact, f) is None]
        if missing_micros:
            warnings.append(
                {
                    "code": "micros_missing_for_product",
                    "fact_id": str(fact.id),
                    "product_name": label.product_name,
                    "missing": missing_micros,
                }
            )

        return LabelResult(fact=fact, warnings=warnings)

    async def register_consumption(
        self,
        *,
        user: User,
        day_log_id: uuid.UUID,
        message_id: uuid.UUID | None,
        fact: NutrientFact,
        consumed: NutritionLabelAlsoConsumed,
        meal_slot: str = "unspecified",
    ) -> tuple[FoodRecord, FoodItem]:
        """SP-31: cria food_record + food_item apontando para o `fact`."""
        grams, ml = _resolve_consumed_amount(fact, consumed)

        record = await self.food_records.create(
            user_id=user.id,
            day_log_id=day_log_id,
            message_id=message_id,
            meal_slot=meal_slot,
            occurred_at=datetime.now(UTC),
        )

        hit = CatalogHit.from_model(fact)
        computed = NutritionCalculator.compute(hit=hit, grams=grams, ml=ml)

        item = await self.food_items.create(
            food_record_id=record.id,
            detected_name=fact.canonical_name,
            normalized_name=fact.canonical_name,
            brand=fact.brand,
            quantity=Decimal(str(consumed.quantity)),
            unit=consumed.unit,
            grams=grams,
            ml=ml,
            source="catalog",
            confidence=Decimal("0.95"),
            is_estimate=False,
            needs_confirmation=False,
            catalog_ref_id=fact.id,
            kcal=computed.kcal,
            protein_g=computed.protein_g,
            carbs_g=computed.carbs_g,
            fat_g=computed.fat_g,
            fiber_g=computed.fiber_g,
            sodium_mg=computed.sodium_mg,
            calcium_mg=computed.calcium_mg,
            iron_mg=computed.iron_mg,
            potassium_mg=computed.potassium_mg,
        )

        await self.audit.record(
            user_id=user.id,
            entity_type="food_record",
            entity_id=record.id,
            action="create",
            actor="llm",
            message_id=message_id,
            after={"meal_slot": meal_slot, "item_ids": [str(item.id)], "from_label": True},
        )
        return record, item

    async def _find_existing_label_fact(
        self, *, canonical: str, brand: str | None, barcode: str | None
    ) -> NutrientFact | None:
        # `barcode` (quando presente) é chave forte — usa direto.
        if barcode:
            stmt = select(NutrientFact).where(
                NutrientFact.source == "label_ocr", NutrientFact.barcode == barcode
            )
            fact = (await self.session.execute(stmt)).scalar_one_or_none()
            if fact is not None:
                return fact
        # Fallback: canonical_name + brand (ambos comparados normalizados).
        stmt = select(NutrientFact).where(
            NutrientFact.source == "label_ocr", NutrientFact.canonical_name == canonical
        )
        if brand is None:
            stmt = stmt.where(NutrientFact.brand.is_(None))
        else:
            stmt = stmt.where(NutrientFact.brand == brand)
        return (await self.session.execute(stmt)).scalar_one_or_none()


def _resolve_basis_and_scale(label: NutritionLabelIn) -> tuple[str, Decimal]:
    if label.basis == "per_100g":
        return "per_100g", Decimal(1)
    if label.basis == "per_100ml":
        return "per_100ml", Decimal(1)
    # per_serving — Pydantic garante serving_size_g|ml preenchido.
    if label.serving_size_g:
        return "per_100g", Decimal(100) / Decimal(str(label.serving_size_g))
    if label.serving_size_ml:
        return "per_100ml", Decimal(100) / Decimal(str(label.serving_size_ml))
    # Não deveria acontecer (validator do schema bloqueia), mas defendemos.
    raise ValueError("per_serving requer serving_size_g ou serving_size_ml")


def _scale_or_none(value: float | None, scale: Decimal) -> Decimal | None:
    if value is None:
        return None
    return (Decimal(str(value)) * scale).quantize(Decimal("0.01"))


def _dec_or_none(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _resolve_consumed_amount(
    fact: NutrientFact, consumed: NutritionLabelAlsoConsumed
) -> tuple[Decimal | None, Decimal | None]:
    """Devolve `(grams, ml)` a serem passados para o `NutritionCalculator`.

    Prioridade: campo explícito (`grams` ou `ml`) > `servings * serving_grams`
    > fallback pela base do fact (`per_100g` → grams; `per_100ml` → ml).
    """
    if consumed.grams is not None:
        return Decimal(str(consumed.grams)), None
    if consumed.ml is not None:
        return None, Decimal(str(consumed.ml))
    if consumed.servings is not None and fact.serving_grams is not None:
        return Decimal(str(consumed.servings)) * fact.serving_grams, None
    # Interpreta `quantity` pelo basis do fact.
    quantity = Decimal(str(consumed.quantity))
    if fact.basis == "per_100g":
        # Sem `grams` explícito → usa quantity como gramas diretas.
        return quantity, None
    if fact.basis == "per_100ml":
        return None, quantity
    return None, None
