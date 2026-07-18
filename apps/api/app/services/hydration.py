"""HydrationService — cria water_records de água PURA.

Const. Art. IV §12-14 e INV-2: schema já bloqueia kcal/macros em
water_records; aqui a validação semântica é apenas defensiva. Se a LLM
mandou `intent=log_water` mas o item parece calórico (café, leite,
suco…), o backend rejeita — evita dupla contagem se o modelo tomar
liberdades com o intent.
"""

from __future__ import annotations

import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationAppError
from app.models import User, WaterRecord
from app.repositories.food import AuditEventRepository
from app.repositories.hydration import WaterRecordRepository
from app.schemas.llm import LLMEnvelope


def _strip_accents(text: str) -> str:
    """Remove combining marks (`café` → `cafe`) para o casamento com hints."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))

# Palavras que denunciam bebida com calorias mesmo se a LLM disser log_water.
_NON_WATER_HINTS = {
    "cafe",
    "cafezinho",
    "leite",
    "suco",
    "refrigerante",
    "cha",
    "cerveja",
    "vinho",
    "acucar",
    "mel",
    "leite_condensado",
}


@dataclass(slots=True)
class HydrationResult:
    record: WaterRecord


class HydrationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.records = WaterRecordRepository(session)
        self.audit = AuditEventRepository(session)

    async def create_from_llm(
        self,
        *,
        user: User,
        day_log_id: uuid.UUID,
        message_id: uuid.UUID | None,
        envelope: LLMEnvelope,
        occurred_at: datetime | None = None,
    ) -> HydrationResult:
        if envelope.water is None:
            raise ValidationAppError(
                "envelope missing water block", code="invalid_water_envelope"
            )

        summary = _strip_accents((envelope.user_text_summary or "").lower())
        for hint in _NON_WATER_HINTS:
            if hint in summary:
                # SP-41 / Art. IV §14: reclassifica como beverage se o resumo
                # da própria LLM indica algo calórico.
                raise ValidationAppError(
                    f"log_water rejected: '{hint}' in summary suggests beverage",
                    code="water_intent_rejected",
                )

        occurred = occurred_at or envelope.occurred_at_hint or datetime.now(UTC)
        record = await self.records.create(
            user_id=user.id,
            day_log_id=day_log_id,
            message_id=message_id,
            occurred_at=occurred,
            volume_ml=int(envelope.water.volume_ml),
            source="llm",
            confidence=Decimal(str(envelope.water.confidence)),
            is_estimate=False,
        )
        await self.audit.record(
            user_id=user.id,
            entity_type="water_record",
            entity_id=record.id,
            action="create",
            actor="llm",
            message_id=message_id,
            after={
                "volume_ml": record.volume_ml,
                "occurred_at": occurred.isoformat(),
            },
        )
        return HydrationResult(record=record)
