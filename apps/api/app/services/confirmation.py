"""ConfirmationService — SP-24 (parte de chat).

Fluxo: quando um item foi registrado com `needs_confirmation=true` (por
baixa confidência ou catálogo faltando), o usuário pode dizer "confirmo",
"está certo", "isso mesmo" ou nomear item específico ("confirma o pão").
Este service marca `needs_confirmation=false` sem alterar macros.

Regras:
- Dia fechado (INV-5 / Const. Art. VIII §28) → `DayClosedError`.
- Sem itens pendentes → `NoPendingConfirmation` (o handler transforma
  em clarify amigável).
- `scope='all'`: confirma todos os itens vivos (`deleted_at IS NULL`) do
  dia com `needs_confirmation=true`.
- `scope='specific'`: usa o `TargetMatcher` para cada hint; ignora hints
  que não batem (não bloqueia — o resto ainda é confirmado).
- Audit trail: uma entrada por entidade confirmada
  (`action='confirm'`, INV-10 / Const. §22).
- **Não recomputa snapshot** — confirmação não altera valores nutricionais;
  só remove o warning `needs_confirmation`. Nas leituras subsequentes, o
  próprio agregador de warnings ignora esses itens.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models import (
    BeverageRecord,
    DayLog,
    FoodItem,
    FoodRecord,
    User,
)
from app.repositories.food import AuditEventRepository
from app.schemas.llm import LLMEnvelope
from app.services.correction import DayClosedError
from app.services.correction_matcher import (
    AmbiguousTarget,
    Candidate,
    NoTargetFound,
    TargetKind,
    TargetMatcher,
)


class NoPendingConfirmation(AppError):
    status_code = 422
    code = "no_pending_confirmation"


@dataclass(slots=True)
class ConfirmedEntity:
    kind: TargetKind
    entity_id: uuid.UUID
    detected_name: str


@dataclass(slots=True)
class ConfirmationResult:
    confirmed: list[ConfirmedEntity]
    unmatched_hints: list[str]


class ConfirmationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditEventRepository(session)

    async def apply_from_llm(
        self,
        *,
        user: User,
        day_log_id: uuid.UUID,
        message_id: uuid.UUID | None,
        envelope: LLMEnvelope,
    ) -> ConfirmationResult:
        day_log = await self.session.get(DayLog, day_log_id)
        if day_log is None or day_log.user_id != user.id:
            raise NoPendingConfirmation(
                "day_log not found for user", code="no_pending_confirmation"
            )
        if day_log.status == "closed":
            raise DayClosedError(day_log_id)

        confirmation = envelope.confirmation
        # Envelope sem bloco `confirmation` = usuário disse algo curto tipo
        # "confirmo/sim/ok"; assumimos `scope='all'` como padrão gentil.
        scope = "all" if confirmation is None else confirmation.scope
        target_hints = list(confirmation.target_hints) if confirmation else []

        pending_food = await self._list_pending_food(day_log_id)
        pending_beverage = await self._list_pending_beverage(day_log_id)
        if not pending_food and not pending_beverage:
            raise NoPendingConfirmation(
                "no items awaiting confirmation on this day",
                code="no_pending_confirmation",
            )

        if scope == "all":
            confirmed = await self._confirm_batch(
                user_id=user.id,
                message_id=message_id,
                food_items=pending_food,
                beverage_records=pending_beverage,
            )
            return ConfirmationResult(confirmed=confirmed, unmatched_hints=[])

        # scope='specific': para cada hint, resolve com TargetMatcher.
        matcher = TargetMatcher(self.session)
        unmatched: list[str] = []
        picked: dict[tuple[TargetKind, uuid.UUID], Candidate] = {}
        for hint in target_hints:
            if not hint.strip():
                continue
            try:
                candidate = await matcher.resolve(day_log_id=day_log_id, target_hint=hint)
            except NoTargetFound:
                unmatched.append(hint)
                continue
            except AmbiguousTarget:
                # Ambiguidade em confirmação não é fatal: pulamos e o
                # handler chat-side vai avisar via `unmatched_hints`.
                unmatched.append(hint)
                continue
            # Só faz sentido confirmar itens que estão pendentes.
            if not _entity_needs_confirmation(candidate):
                unmatched.append(hint)
                continue
            key = (candidate.kind, candidate.entity.id)
            picked[key] = candidate

        if not picked:
            # Nada bateu com hint específico → sinaliza para clarify em vez
            # de silenciosamente confirmar tudo (evita falso positivo).
            return ConfirmationResult(confirmed=[], unmatched_hints=unmatched)

        food_ids = {c.entity.id for c in picked.values() if c.kind == TargetKind.FOOD}
        bev_ids = {c.entity.id for c in picked.values() if c.kind == TargetKind.BEVERAGE}
        selected_food = [f for f in pending_food if f.id in food_ids]
        selected_beverage = [b for b in pending_beverage if b.id in bev_ids]

        confirmed = await self._confirm_batch(
            user_id=user.id,
            message_id=message_id,
            food_items=selected_food,
            beverage_records=selected_beverage,
        )
        return ConfirmationResult(confirmed=confirmed, unmatched_hints=unmatched)

    async def _list_pending_food(self, day_log_id: uuid.UUID) -> list[FoodItem]:
        stmt = (
            select(FoodItem)
            .join(FoodRecord, FoodRecord.id == FoodItem.food_record_id)
            .where(
                FoodRecord.day_log_id == day_log_id,
                FoodRecord.deleted_at.is_(None),
                FoodItem.deleted_at.is_(None),
                FoodItem.needs_confirmation.is_(True),
            )
        )
        return list((await self.session.execute(stmt)).scalars())

    async def _list_pending_beverage(self, day_log_id: uuid.UUID) -> list[BeverageRecord]:
        stmt = select(BeverageRecord).where(
            BeverageRecord.day_log_id == day_log_id,
            BeverageRecord.deleted_at.is_(None),
            BeverageRecord.needs_confirmation.is_(True),
        )
        return list((await self.session.execute(stmt)).scalars())

    async def _confirm_batch(
        self,
        *,
        user_id: uuid.UUID,
        message_id: uuid.UUID | None,
        food_items: list[FoodItem],
        beverage_records: list[BeverageRecord],
    ) -> list[ConfirmedEntity]:
        confirmed: list[ConfirmedEntity] = []
        for item in food_items:
            before: dict[str, Any] = {"needs_confirmation": True}
            item.needs_confirmation = False
            await self.audit.record(
                user_id=user_id,
                entity_type="food_item",
                entity_id=item.id,
                action="confirm",
                actor="user",
                message_id=message_id,
                before=before,
                after={"needs_confirmation": False},
            )
            confirmed.append(
                ConfirmedEntity(
                    kind=TargetKind.FOOD,
                    entity_id=item.id,
                    detected_name=item.detected_name,
                )
            )
        for bev in beverage_records:
            before = {"needs_confirmation": True}
            bev.needs_confirmation = False
            await self.audit.record(
                user_id=user_id,
                entity_type="beverage_record",
                entity_id=bev.id,
                action="confirm",
                actor="user",
                message_id=message_id,
                before=before,
                after={"needs_confirmation": False},
            )
            confirmed.append(
                ConfirmedEntity(
                    kind=TargetKind.BEVERAGE,
                    entity_id=bev.id,
                    detected_name=bev.detected_name,
                )
            )
        await self.session.flush()
        return confirmed


def _entity_needs_confirmation(candidate: Candidate) -> bool:
    entity = candidate.entity
    if candidate.kind == TargetKind.FOOD:
        return bool(getattr(entity, "needs_confirmation", False))
    if candidate.kind == TargetKind.BEVERAGE:
        return bool(getattr(entity, "needs_confirmation", False))
    # Water/activity não têm needs_confirmation no MVP.
    return False
