"""MessageProcessor — worker que roda em `BackgroundTasks` após POST /chat/messages.

Fluxo (SP-13, SP-14):
1. Carrega a mensagem do usuário e a mídia anexada.
2. Baixa os bytes de cada media do MinIO (para envio base64 à Anthropic).
3. Chama `AnthropicClient.call_record_intent` (com retry semântico embutido).
4. Se o envelope volta válido → passa pelo `IntentDispatcher`.
   - `clarify` / `unknown` → cria `messages(role='assistant', content=...)`.
   - `log_food` etc. → `IntentNotImplemented` (Fase 4+); vira pedido genérico
     de reformulação enquanto essas fases não chegam.
5. Se a chamada falhou (timeout, 5xx, validation exhausted) → cria mensagem
   amigável e grava `raw_llm_response.error` (SP-14).

O background task cria sua própria `AsyncSession` porque a sessão da
request original já fechou quando ele executa.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.exceptions import ValidationAppError
from app.integrations.anthropic.client import AnthropicClient, LLMCallResult
from app.integrations.nutrition.local_tbca import LocalTBCACatalog
from app.integrations.storage.minio import MinioStorage
from app.models import Media, Message, MessageMedia, User
from app.repositories.message import MessageRepository
from app.services.activity import ActivityResult, ActivityService, WeightRequired
from app.services.beverage import BeverageResult, BeverageService
from app.services.daily_recompute import DailyRecomputeService, RecomputeResult
from app.services.hydration import HydrationResult, HydrationService
from app.services.intent_dispatcher import (
    DispatchResult,
    IntentDispatcher,
    IntentNotImplemented,
)
from app.services.meal import MealResult, MealService
from app.services.profile import ProfileService, ProfileUpdateResult

logger = logging.getLogger("app.message_processor")

_FALLBACK_LLM_ERROR = (
    "Não consegui interpretar sua mensagem agora. Pode reformular?"
)
_FALLBACK_NOT_IMPLEMENTED = (
    "Recebi sua mensagem, mas o registro dessa categoria ainda não está "
    "disponível — está previsto para uma fase futura."
)


class MessageProcessor:
    def __init__(
        self,
        *,
        session: AsyncSession,
        anthropic: AnthropicClient,
        storage: MinioStorage,
    ) -> None:
        self.session = session
        self.anthropic = anthropic
        self.storage = storage
        self.messages = MessageRepository(session)
        self.dispatcher = IntentDispatcher()

    async def process(self, message_id: uuid.UUID) -> Message | None:
        stmt = select(Message).where(Message.id == message_id)
        user_message = (await self.session.execute(stmt)).scalar_one_or_none()
        if user_message is None or user_message.role != "user":
            logger.warning(
                "process_missing_user_message",
                extra={"event": "message_processor", "message_id": str(message_id)},
            )
            return None

        images = await self._load_media(message_id)

        result = await self.anthropic.call_record_intent(
            user_text=user_message.content,
            images=images,
        )

        if result.error == "no_queued_result":
            # Sentinela usado pelo FakeAnthropicClient nos testes que exercem
            # apenas o pipeline de chat (SP-10..SP-12) e não configuram
            # resposta da LLM. Em produção esse code nunca acontece.
            logger.info(
                "processor_skipped_no_queued_result",
                extra={"event": "message_processor", "message_id": str(message_id)},
            )
            return None

        if result.error is not None or result.envelope is None:
            return await self._record_error(user_message, result)

        # set_profile (SP-61 fechamento): atualiza users.weight_kg/etc via chat.
        # Não precisa de day_log_id e não dispara recompute (perfil não afeta
        # snapshot; activity_records guardam met/kcal_burned no momento).
        if result.envelope.intent == "set_profile":
            return await self._handle_set_profile(user_message, result)

        # Intents com persistência custom + recompute:
        # SP-20..26 log_food; SP-40..42 log_water; SP-50..52 log_beverage;
        # SP-60..64 log_activity. Todos exigem day_log_id + user.
        if result.envelope.intent in {
            "log_food",
            "log_water",
            "log_beverage",
            "log_activity",
        }:
            return await self._handle_registration(user_message, result)

        try:
            dispatch = self.dispatcher.dispatch(result.envelope)
        except IntentNotImplemented as exc:
            logger.info(
                "intent_not_implemented",
                extra={"event": "intent_dispatch", "intent": exc.intent},
            )
            return await self._record_not_implemented(user_message, result, exc.intent)

        return await self._record_success(user_message, result, dispatch)

    async def _handle_registration(
        self, user_message: Message, result: LLMCallResult
    ) -> Message:
        envelope = result.envelope
        if envelope is None:
            return await self._record_error(user_message, result)
        if user_message.day_log_id is None:
            logger.warning(
                "registration_missing_day_log",
                extra={"event": "message_processor", "message_id": str(user_message.id)},
            )
            return await self._record_error(user_message, result)

        user = await self.session.get(User, user_message.user_id)
        if user is None:
            return await self._record_error(user_message, result)

        catalog = LocalTBCACatalog(self.session)
        recompute_service = DailyRecomputeService(self.session)

        dispatch_meta: dict[str, Any] = {}
        content: str
        try:
            if envelope.intent == "log_food":
                if not envelope.food_items:
                    return await self._record_error(user_message, result)
                meal = await MealService(self.session, catalog).create_from_llm(
                    user=user,
                    day_log_id=user_message.day_log_id,
                    message_id=user_message.id,
                    envelope=envelope,
                )
                recompute = await recompute_service.recompute(user_message.day_log_id)
                dispatch_meta["meal"] = {
                    "food_record_id": str(meal.food_record.id),
                    "item_ids": [str(i.id) for i in meal.items],
                    "warnings": meal.warnings,
                }
                content = _compose_meal_summary(meal, recompute)
            elif envelope.intent == "log_water":
                if envelope.water is None:
                    return await self._record_error(user_message, result)
                hydration = await HydrationService(self.session).create_from_llm(
                    user=user,
                    day_log_id=user_message.day_log_id,
                    message_id=user_message.id,
                    envelope=envelope,
                )
                recompute = await recompute_service.recompute(user_message.day_log_id)
                dispatch_meta["water"] = {"record_id": str(hydration.record.id)}
                content = _compose_water_summary(hydration, recompute)
            elif envelope.intent == "log_beverage":
                if envelope.beverage is None:
                    return await self._record_error(user_message, result)
                beverage = await BeverageService(self.session, catalog).create_from_llm(
                    user=user,
                    day_log_id=user_message.day_log_id,
                    message_id=user_message.id,
                    envelope=envelope,
                )
                recompute = await recompute_service.recompute(user_message.day_log_id)
                dispatch_meta["beverage"] = {
                    "record_id": str(beverage.record.id),
                    "warnings": beverage.warnings,
                }
                content = _compose_beverage_summary(beverage, recompute)
            elif envelope.intent == "log_activity":
                if envelope.activity is None:
                    return await self._record_error(user_message, result)
                try:
                    activity = await ActivityService(self.session).create_from_llm(
                        user=user,
                        day_log_id=user_message.day_log_id,
                        message_id=user_message.id,
                        envelope=envelope,
                    )
                except WeightRequired:
                    # SP-61: sem weight_kg → não persiste; clarify amigável.
                    return await self._record_clarify(
                        user_message,
                        result,
                        "Antes de calcular as calorias gastas, me diga seu peso "
                        "atual em kg. Você pode dizer, por exemplo, \"peso 78 kg\".",
                        code="weight_kg_required",
                    )
                recompute = await recompute_service.recompute(user_message.day_log_id)
                dispatch_meta["activity"] = {
                    "record_id": str(activity.record.id),
                    "warnings": activity.warnings,
                }
                content = _compose_activity_summary(activity, recompute)
            else:  # pragma: no cover — guarded by the branch above
                return await self._record_error(user_message, result)
        except ValidationAppError as exc:
            # SP-41 / INV-2: rejeições semânticas (ex.: log_water com bebida
            # calórica) viram clarify em vez de erro genérico.
            return await self._record_clarify(
                user_message,
                result,
                _clarify_from_validation(exc),
                code=exc.code,
            )

        raw = _pack_raw(result)
        raw["dispatch"] = {
            **dispatch_meta,
            "snapshot_version": recompute.snapshot.version,
        }
        return await self.messages.create(
            user_id=user_message.user_id,
            day_log_id=user_message.day_log_id,
            role="assistant",
            content=content,
            llm_intent=envelope.intent,
            llm_model=result.model,
            llm_prompt_version=result.prompt_version,
            llm_confidence=envelope.confidence,
            raw_llm_response=raw,
            tokens_input=result.tokens_input,
            tokens_output=result.tokens_output,
        )

    async def _handle_set_profile(
        self, user_message: Message, result: LLMCallResult
    ) -> Message:
        envelope = result.envelope
        if envelope is None or envelope.profile_update is None:
            return await self._record_error(user_message, result)

        user = await self.session.get(User, user_message.user_id)
        if user is None:
            return await self._record_error(user_message, result)

        try:
            profile = await ProfileService(self.session).update_from_llm(
                user=user, envelope=envelope, message_id=user_message.id
            )
        except ValidationAppError as exc:
            return await self._record_clarify(
                user_message,
                result,
                _clarify_from_validation(exc),
                code=exc.code,
            )

        raw = _pack_raw(result)
        raw["dispatch"] = {
            "profile": {
                "changed": {
                    k: {"before": v[0], "after": v[1]}
                    for k, v in profile.changed_fields.items()
                }
            }
        }
        content = _compose_profile_summary(profile)
        return await self.messages.create(
            user_id=user_message.user_id,
            day_log_id=user_message.day_log_id,
            role="assistant",
            content=content,
            llm_intent="set_profile",
            llm_model=result.model,
            llm_prompt_version=result.prompt_version,
            llm_confidence=envelope.confidence,
            raw_llm_response=raw,
            tokens_input=result.tokens_input,
            tokens_output=result.tokens_output,
        )

    async def _record_clarify(
        self,
        user_message: Message,
        result: LLMCallResult,
        content: str,
        *,
        code: str,
    ) -> Message:
        raw = _pack_raw(result)
        raw["dispatch"] = {"clarify_reason": code}
        return await self.messages.create(
            user_id=user_message.user_id,
            day_log_id=user_message.day_log_id,
            role="assistant",
            content=content,
            llm_intent="clarify",
            llm_model=result.model,
            llm_prompt_version=result.prompt_version,
            llm_confidence=result.envelope.confidence if result.envelope else None,
            raw_llm_response=raw,
            tokens_input=result.tokens_input,
            tokens_output=result.tokens_output,
        )

    async def _load_media(
        self, message_id: uuid.UUID
    ) -> list[tuple[str, bytes]]:
        stmt = (
            select(Media)
            .join(MessageMedia, MessageMedia.media_id == Media.id)
            .where(MessageMedia.message_id == message_id)
        )
        rows = list((await self.session.execute(stmt)).scalars())
        images: list[tuple[str, bytes]] = []
        for media in rows:
            try:
                data = await self.storage.get_object(media.storage_key)
            except Exception as exc:  # noqa: BLE001 — não bloquear a mensagem
                logger.warning(
                    "media_download_failed",
                    extra={
                        "event": "message_processor",
                        "media_id": str(media.id),
                        "err": type(exc).__name__,
                    },
                )
                continue
            images.append((media.content_type, data))
        return images

    async def _record_success(
        self,
        user_message: Message,
        result: LLMCallResult,
        dispatch: DispatchResult,
    ) -> Message:
        raw = _pack_raw(result)
        return await self.messages.create(
            user_id=user_message.user_id,
            day_log_id=user_message.day_log_id,
            role="assistant",
            content=dispatch.content,
            llm_intent=dispatch.llm_intent,
            llm_model=result.model,
            llm_prompt_version=result.prompt_version,
            llm_confidence=dispatch.llm_confidence,
            raw_llm_response=raw,
            tokens_input=result.tokens_input,
            tokens_output=result.tokens_output,
        )

    async def _record_error(
        self, user_message: Message, result: LLMCallResult
    ) -> Message:
        raw = _pack_raw(result)
        return await self.messages.create(
            user_id=user_message.user_id,
            day_log_id=user_message.day_log_id,
            role="assistant",
            content=_FALLBACK_LLM_ERROR,
            llm_intent="unknown",
            llm_model=result.model,
            llm_prompt_version=result.prompt_version,
            raw_llm_response=raw,
            tokens_input=result.tokens_input,
            tokens_output=result.tokens_output,
        )

    async def _record_not_implemented(
        self, user_message: Message, result: LLMCallResult, intent: str
    ) -> Message:
        raw = _pack_raw(result)
        raw["dispatch"] = {"not_implemented": intent}
        return await self.messages.create(
            user_id=user_message.user_id,
            day_log_id=user_message.day_log_id,
            role="assistant",
            content=_FALLBACK_NOT_IMPLEMENTED,
            llm_intent=intent,
            llm_model=result.model,
            llm_prompt_version=result.prompt_version,
            llm_confidence=result.envelope.confidence if result.envelope else None,
            raw_llm_response=raw,
            tokens_input=result.tokens_input,
            tokens_output=result.tokens_output,
        )


_DISCLAIMER = (
    "As estimativas nutricionais são aproximações e não substituem "
    "acompanhamento médico ou nutricional."
)


def _compose_meal_summary(meal: MealResult, recompute: RecomputeResult) -> str:
    lines: list[str] = ["Registrei:"]
    for item in meal.items:
        amount = _amount_label(item.grams, item.ml, item.quantity, item.unit)
        marks: list[str] = []
        if item.is_estimate:
            marks.append("estimativa")
        if item.needs_confirmation:
            marks.append("confirmar")
        marks_str = f" ({', '.join(marks)})" if marks else ""
        lines.append(f"- {item.detected_name}{f' — {amount}' if amount else ''}{marks_str}")

    snap = recompute.snapshot
    totals = (
        f"Total do dia: {int(snap.kcal_in)} kcal · "
        f"P {int(snap.protein_g)}g · C {int(snap.carbs_g)}g · G {int(snap.fat_g)}g."
    )
    lines.append("")
    lines.append(totals)

    warnings = meal.warnings
    to_confirm = [w for w in warnings if w["code"] in ("low_confidence_item", "no_catalog_hit")]
    if to_confirm:
        names = ", ".join(
            {w.get("detected_name", w.get("item_id", "item")) for w in to_confirm}
        )
        lines.append(f"Confirma esses itens? {names}")

    lines.append(_DISCLAIMER)
    return "\n".join(lines)


def _amount_label(grams, ml, quantity, unit) -> str:
    if grams is not None and grams > 0:
        return f"{int(grams)}g"
    if ml is not None and ml > 0:
        return f"{int(ml)}ml"
    if quantity is not None and unit:
        return f"{quantity} {unit}"
    return ""


def _totals_line(snap) -> str:
    return (
        f"Total do dia: {int(snap.kcal_in)} kcal in · "
        f"{int(snap.kcal_out)} kcal out · saldo {int(snap.kcal_balance)} kcal · "
        f"água {int(snap.water_ml)} ml · outros líquidos {int(snap.other_liquids_ml)} ml."
    )


def _compose_water_summary(
    hydration: HydrationResult, recompute: RecomputeResult
) -> str:
    lines = [f"Registrei {hydration.record.volume_ml} ml de água.", ""]
    lines.append(_totals_line(recompute.snapshot))
    lines.append(_DISCLAIMER)
    return "\n".join(lines)


def _compose_beverage_summary(
    beverage: BeverageResult, recompute: RecomputeResult
) -> str:
    record = beverage.record
    lines = [
        f"Registrei {record.volume_ml} ml de {record.detected_name}"
        f" ({int(record.kcal or 0)} kcal).",
    ]
    to_confirm = [
        w for w in beverage.warnings
        if w["code"] in ("no_catalog_hit", "low_confidence_item")
    ]
    if to_confirm:
        names = ", ".join(
            {w.get("detected_name", record.detected_name) for w in to_confirm}
        )
        lines.append(f"Confirma esses itens? {names}")
    lines.append("")
    lines.append(_totals_line(recompute.snapshot))
    lines.append(_DISCLAIMER)
    return "\n".join(lines)


def _compose_activity_summary(
    activity: ActivityResult, recompute: RecomputeResult
) -> str:
    record = activity.record
    duration = int(record.duration_minutes)
    kcal = int(record.kcal_burned)
    intensity_label = {
        "light": "leve",
        "moderate": "moderada",
        "vigorous": "intensa",
        "unknown": "sem intensidade informada",
    }.get(record.intensity, record.intensity)
    lines = [
        f"Registrei {duration} min de {record.detected_name}"
        f" ({intensity_label}) — {kcal} kcal gastos.",
    ]
    if any(w["code"].startswith("missing_") for w in activity.warnings):
        lines.append(
            "Alguns dados ficaram estimados; confirma se está certo?"
        )
    lines.append("")
    lines.append(_totals_line(recompute.snapshot))
    lines.append(_DISCLAIMER)
    return "\n".join(lines)


_CLARIFY_TEMPLATES = {
    "water_intent_rejected": (
        "Isso soou como uma bebida com calorias, não água pura. "
        "Pode confirmar se foi café, leite, suco ou similar?"
    ),
    "weight_kg_required": (
        "Antes de calcular as calorias gastas, preciso do seu peso atual em kg."
    ),
    "profile_no_change": (
        "Recebi seus dados, mas eles já estão iguais aos que tenho. "
        "Se quiser mudar algo, me passe o valor novo."
    ),
}


def _clarify_from_validation(exc: ValidationAppError) -> str:
    return _CLARIFY_TEMPLATES.get(
        exc.code, "Pode reformular sua mensagem com mais detalhes?"
    )


_FIELD_LABELS = {
    "weight_kg": "peso",
    "height_cm": "altura",
    "birthdate": "data de nascimento",
    "sex": "sexo",
}


def _compose_profile_summary(profile: ProfileUpdateResult) -> str:
    parts: list[str] = []
    for field, (_before, after) in profile.changed_fields.items():
        label = _FIELD_LABELS.get(field, field)
        if field == "weight_kg":
            parts.append(f"{label} atualizado para {after} kg")
        elif field == "height_cm":
            parts.append(f"{label} atualizada para {after} cm")
        else:
            parts.append(f"{label} atualizado para {after}")
    joined = "; ".join(parts)
    if "weight_kg" in profile.changed_fields:
        follow_up = (
            " Agora posso calcular kcal gastos — reenvie a atividade "
            "que você tinha tentado registrar."
        )
    else:
        follow_up = ""
    return f"Perfil {joined}.{follow_up}"


def _pack_raw(result: LLMCallResult) -> dict[str, Any]:
    packed = asdict(result)
    # `envelope` é um BaseModel e não é JSON-serializable por asdict.
    packed["envelope"] = (
        result.envelope.model_dump(mode="json") if result.envelope else None
    )
    return packed


async def run_processor_in_background(
    message_id: uuid.UUID,
    *,
    session_factory: Callable[[], AsyncSession],
    anthropic_client: AnthropicClient,
    storage: MinioStorage,
) -> None:
    """Wrapper para FastAPI `BackgroundTasks`: sessão dedicada via factory.

    `session_factory` é injetada pela rota (dep FastAPI) para permitir que
    testes usem o mesmo engine da sessão de request (evita 'attached to a
    different loop' quando o event loop do teste difere do que criou o
    engine module-level).
    """
    async with session_factory() as session:
        processor = MessageProcessor(
            session=session, anthropic=anthropic_client, storage=storage
        )
        try:
            await processor.process(message_id)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception(
                "background_processor_failed",
                extra={"event": "message_processor", "message_id": str(message_id)},
            )
