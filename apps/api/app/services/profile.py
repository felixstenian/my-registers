"""ProfileService — atualiza campos de perfil corporal em `users` via chat.

Fecha o loop do SP-61 (Fase 5): quando o usuário responde "peso 65 kg",
a LLM classifica como `intent=set_profile` e aqui a gente aplica o diff
+ grava audit_event (INV-10). Nenhuma recompute é disparado — perfil não
afeta snapshots já materializados (activity_records guardam met_value e
kcal_burned no momento da criação, SP-64).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationAppError
from app.models import User
from app.repositories.food import AuditEventRepository
from app.schemas.llm import LLMEnvelope


@dataclass(slots=True)
class ProfileUpdateResult:
    user: User
    changed_fields: dict[str, tuple[Any, Any]]  # {field: (before, after)}


class ProfileService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditEventRepository(session)

    async def update_from_llm(
        self,
        *,
        user: User,
        envelope: LLMEnvelope,
        message_id: Any | None,
    ) -> ProfileUpdateResult:
        if envelope.profile_update is None:
            raise ValidationAppError(
                "envelope missing profile_update block",
                code="invalid_profile_envelope",
            )
        pu = envelope.profile_update

        # Aplicar apenas campos preenchidos; capturar before/after para audit.
        changed: dict[str, tuple[Any, Any]] = {}

        if pu.weight_kg is not None:
            new = Decimal(str(pu.weight_kg))
            if user.weight_kg != new:
                changed["weight_kg"] = (
                    _serialize(user.weight_kg),
                    float(new),
                )
                user.weight_kg = new
        if pu.height_cm is not None:
            new = Decimal(str(pu.height_cm))
            if user.height_cm != new:
                changed["height_cm"] = (
                    _serialize(user.height_cm),
                    float(new),
                )
                user.height_cm = new
        if pu.birthdate is not None:
            new_date: date = pu.birthdate
            if user.birthdate != new_date:
                changed["birthdate"] = (
                    _serialize(user.birthdate),
                    new_date.isoformat(),
                )
                user.birthdate = new_date
        if pu.sex is not None and user.sex != pu.sex:
            changed["sex"] = (user.sex, pu.sex)
            user.sex = pu.sex

        if not changed:
            raise ValidationAppError("profile_update has no new values", code="profile_no_change")

        await self.session.flush()

        await self.audit.record(
            user_id=user.id,
            entity_type="user",
            entity_id=user.id,
            action="update",
            actor="llm",
            message_id=message_id,
            before={k: v[0] for k, v in changed.items()},
            after={k: v[1] for k, v in changed.items()},
        )
        return ProfileUpdateResult(user=user, changed_fields=changed)


def _serialize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    return value
