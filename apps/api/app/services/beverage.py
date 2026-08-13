"""BeverageService — cria beverage_records de bebidas COM calorias.

Const. Art. IV §13-14 / INV-3: bebida calórica **nunca** contribui para
`water_ml` (schema separa em tabelas distintas). Macros e micros são
resolvidos via NutritionCatalog + NutritionCalculator, exatamente igual
ao MealService.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationAppError
from app.integrations.nutrition.catalog import LookupQuery, NutritionCatalog
from app.integrations.nutrition.normalize import normalize_name
from app.models import BeverageRecord, User
from app.repositories.beverage import BeverageRecordRepository
from app.repositories.food import AuditEventRepository
from app.schemas.llm import LLMEnvelope
from app.services.nutrition_calculator import NutritionCalculator

LOW_CONFIDENCE_THRESHOLD = Decimal("0.5")


@dataclass(slots=True)
class BeverageResult:
    record: BeverageRecord
    warnings: list[dict[str, Any]]


class BeverageService:
    def __init__(self, session: AsyncSession, catalog: NutritionCatalog) -> None:
        self.session = session
        self.catalog = catalog
        self.records = BeverageRecordRepository(session)
        self.audit = AuditEventRepository(session)

    async def create_from_llm(
        self,
        *,
        user: User,
        day_log_id: uuid.UUID,
        message_id: uuid.UUID | None,
        envelope: LLMEnvelope,
        occurred_at: datetime | None = None,
    ) -> BeverageResult:
        if envelope.beverage is None:
            raise ValidationAppError(
                "envelope missing beverage block",
                code="invalid_beverage_envelope",
            )

        entry = envelope.beverage
        normalized = normalize_name(entry.detected_name)
        hit = await self.catalog.lookup(LookupQuery(name=normalized, brand=entry.brand))

        volume_ml = Decimal(str(entry.volume_ml))
        # Beverage sempre calcula por volume (basis per_100ml). Se o catálogo
        # tiver per_100g, cai em `unknown_basis` (raro para bebidas).
        computed = NutritionCalculator.compute(hit=hit, grams=None, ml=volume_ml)
        confidence = Decimal(str(entry.confidence))

        # Bloco 5 revisão v1.12: `needs_confirmation` deixou de ser setado.
        # Ver comentário análogo em MealService._create_item.
        occurred = occurred_at or envelope.occurred_at_hint or datetime.now(UTC)
        record = await self.records.create(
            user_id=user.id,
            day_log_id=day_log_id,
            message_id=message_id,
            occurred_at=occurred,
            detected_name=entry.detected_name,
            normalized_name=normalized,
            brand=entry.brand,
            volume_ml=int(entry.volume_ml),
            source="llm",
            confidence=confidence,
            is_estimate=False,
            needs_confirmation=False,
            catalog_ref_id=uuid.UUID(hit.fact_id) if hit else None,
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

        warnings: list[dict[str, Any]] = []
        if hit is None:
            warnings.append(
                {
                    "code": "no_catalog_hit",
                    "record_id": str(record.id),
                    "detected_name": entry.detected_name,
                }
            )
        if confidence < LOW_CONFIDENCE_THRESHOLD:
            warnings.append(
                {
                    "code": "low_confidence_item",
                    "record_id": str(record.id),
                    "confidence": float(confidence),
                }
            )

        await self.audit.record(
            user_id=user.id,
            entity_type="beverage_record",
            entity_id=record.id,
            action="create",
            actor="llm",
            message_id=message_id,
            after={
                "volume_ml": record.volume_ml,
                "detected_name": entry.detected_name,
                "occurred_at": occurred.isoformat(),
            },
        )
        return BeverageResult(record=record, warnings=warnings)
