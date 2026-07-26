"""ActivityService — persiste activity_records com kcal_burned determinístico.

SP-60..64.

- Se `users.weight_kg` está null e o envelope NÃO trouxe
  `kcal_burned_reported`, lança `WeightRequired` (SP-61) — sem peso não
  dá para calcular por MET.
- Se o envelope trouxer `kcal_burned_reported` (LLM extraiu de print de
  smartwatch/app), esse valor é fonte de verdade: `calc_method='user_manual'`
  (Const. Art. III §10 — recompute mantém o valor materializado, sem
  refazer MET). Aqui não precisa de peso — o dispositivo já resolveu.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationAppError
from app.integrations.nutrition.normalize import normalize_name
from app.models import ActivityRecord, User
from app.repositories.activity import ActivityRecordRepository
from app.repositories.food import AuditEventRepository
from app.schemas.llm import LLMEnvelope
from app.services.activity_calculator import ActivityCalculator

LOW_CONFIDENCE_THRESHOLD = Decimal("0.5")


class WeightRequired(Exception):
    """SP-61: usuário sem `weight_kg` — não dá para calcular METs."""


@dataclass(slots=True)
class ActivityResult:
    record: ActivityRecord
    warnings: list[dict[str, Any]]


class ActivityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.records = ActivityRecordRepository(session)
        self.audit = AuditEventRepository(session)

    async def create_from_llm(
        self,
        *,
        user: User,
        day_log_id: uuid.UUID,
        message_id: uuid.UUID | None,
        envelope: LLMEnvelope,
        occurred_at: datetime | None = None,
    ) -> ActivityResult:
        if envelope.activity is None:
            raise ValidationAppError(
                "envelope missing activity block",
                code="invalid_activity_envelope",
            )

        entry = envelope.activity
        has_reported_kcal = entry.kcal_burned_reported is not None

        # SP-61 só se aplica quando NÃO há kcal reportado do dispositivo.
        if not has_reported_kcal and user.weight_kg is None:
            raise WeightRequired()

        duration_dec = Decimal(str(entry.duration_minutes))

        # SP-63: sem duration mas com distance → estimar por velocidade média.
        if duration_dec <= 0 and entry.distance_km is not None:
            estimated = ActivityCalculator.estimate_duration_from_distance(
                entry.activity_type, Decimal(str(entry.distance_km))
            )
            if estimated is not None:
                duration_dec = estimated

        # SP-62: intensity ausente/unknown para strength → moderate default no
        # cálculo, mantendo `unknown` no registro para auditoria.
        intensity_for_calc = entry.intensity
        if entry.activity_type == "strength" and entry.intensity == "unknown":
            intensity_for_calc = "moderate"

        if has_reported_kcal:
            # Valor autoritativo do dispositivo/foto. Mantemos `met_value` do
            # lookup como contexto para auditoria (se houver match), mas o
            # kcal_burned vem intacto do reportado.
            kcal_burned = Decimal(str(entry.kcal_burned_reported))
            met_value = ActivityCalculator.lookup_met(entry.activity_type, intensity_for_calc)
            calc_method = "user_manual"
            computation_reasons: list[str] = []
        else:
            computation = ActivityCalculator.compute(
                activity_type=entry.activity_type,
                intensity=intensity_for_calc,
                duration_minutes=duration_dec,
                weight_kg=Decimal(str(user.weight_kg)),
            )
            kcal_burned = computation.kcal_burned
            met_value = computation.met_value
            calc_method = computation.calc_method
            computation_reasons = computation.reasons

        confidence = Decimal(str(entry.confidence))
        occurred = occurred_at or envelope.occurred_at_hint or datetime.now(UTC)

        record = await self.records.create(
            user_id=user.id,
            day_log_id=day_log_id,
            message_id=message_id,
            occurred_at=occurred,
            detected_name=entry.detected_name,
            normalized_name=normalize_name(entry.detected_name),
            activity_type=entry.activity_type,
            duration_minutes=duration_dec,
            distance_km=(
                Decimal(str(entry.distance_km)) if entry.distance_km is not None else None
            ),
            intensity=entry.intensity,
            met_value=met_value,
            kcal_burned=kcal_burned,
            calc_method=calc_method,
            confidence=confidence,
        )

        warnings: list[dict[str, Any]] = []
        if confidence < LOW_CONFIDENCE_THRESHOLD:
            warnings.append(
                {
                    "code": "low_confidence_item",
                    "record_id": str(record.id),
                    "confidence": float(confidence),
                }
            )
        for reason in computation_reasons:
            warnings.append({"code": reason, "record_id": str(record.id)})

        await self.audit.record(
            user_id=user.id,
            entity_type="activity_record",
            entity_id=record.id,
            action="create",
            actor="llm",
            message_id=message_id,
            after={
                "activity_type": entry.activity_type,
                "duration_minutes": float(duration_dec),
                "kcal_burned": float(kcal_burned),
                "calc_method": calc_method,
                "occurred_at": occurred.isoformat(),
            },
        )
        return ActivityResult(record=record, warnings=warnings)
