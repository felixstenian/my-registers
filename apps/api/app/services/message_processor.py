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
from app.repositories.day_log import DayLogRepository
from app.repositories.food import AuditEventRepository
from app.repositories.message import MessageRepository
from app.services import message_formatter
from app.services.activity import ActivityResult, ActivityService, WeightRequired
from app.services.beverage import BeverageResult, BeverageService
from app.services.chat import local_today
from app.services.correction import (
    CorrectionResult,
    CorrectionService,
    DayClosedError,
)
from app.services.correction_matcher import (
    AmbiguousTarget,
    NoTargetFound,
    TargetKind,
)
from app.services.daily_recompute import DailyRecomputeService, RecomputeResult
from app.services.day_close import DayCloseResult, DayCloseService
from app.services.day_query import DayPayload, DayQueryService
from app.services.deletion import DeletionResult, DeletionService
from app.services.hydration import HydrationResult, HydrationService
from app.services.intent_dispatcher import (
    DispatchResult,
    IntentDispatcher,
    IntentNotImplemented,
)
from app.services.label_catalog import LabelCatalogService, LabelResult
from app.services.meal import MealResult, MealService
from app.services.profile import ProfileService, ProfileUpdateResult
from app.services.promotion import try_promote_food_item
from app.services.weekly_report import WeeklyReportService

logger = logging.getLogger("app.message_processor")

_FALLBACK_LLM_ERROR = "Não consegui interpretar sua mensagem agora. Pode reformular?"
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

        # SP-70..74 correções, SP-80..82 remoções.
        if result.envelope.intent in {"correct_record", "delete_record"}:
            return await self._handle_correction_or_deletion(user_message, result)

        # SP-100..104 encerramento do dia por chat.
        if result.envelope.intent == "close_day":
            return await self._handle_close_day(user_message, result)

        # SP-90..92 consulta do dia por chat.
        if result.envelope.intent == "query_day":
            return await self._handle_query_day(user_message, result)

        # SP-110..113 resumo semanal por chat.
        if result.envelope.intent == "weekly_summary":
            return await self._handle_weekly_summary(user_message, result)

        # SP-30..35 cadastro de produto por foto de rótulo.
        if result.envelope.intent == "log_nutrition_label":
            return await self._handle_nutrition_label(user_message, result)

        try:
            dispatch = self.dispatcher.dispatch(result.envelope)
        except IntentNotImplemented as exc:
            logger.info(
                "intent_not_implemented",
                extra={"event": "intent_dispatch", "intent": exc.intent},
            )
            return await self._record_not_implemented(user_message, result, exc.intent)

        return await self._record_success(user_message, result, dispatch)

    async def _handle_registration(self, user_message: Message, result: LLMCallResult) -> Message:
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

        try:
            day_log_id = await self._resolve_registration_day_log(
                user=user, envelope=envelope, default_day_log_id=user_message.day_log_id
            )
        except ValidationAppError as exc:
            return await self._record_clarify(
                user_message, result, _clarify_from_validation(exc), code=exc.code
            )

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
                    day_log_id=day_log_id,
                    message_id=user_message.id,
                    envelope=envelope,
                )
                recompute = await recompute_service.recompute(day_log_id)
                dispatch_meta["meal"] = {
                    "food_record_id": str(meal.food_record.id),
                    "item_ids": [str(i.id) for i in meal.items],
                    "warnings": meal.warnings,
                }
                content = message_formatter.compose_meal(
                    meal, recompute, local_today(user.timezone)
                )
            elif envelope.intent == "log_water":
                if envelope.water is None:
                    return await self._record_error(user_message, result)
                hydration = await HydrationService(self.session).create_from_llm(
                    user=user,
                    day_log_id=day_log_id,
                    message_id=user_message.id,
                    envelope=envelope,
                )
                recompute = await recompute_service.recompute(day_log_id)
                dispatch_meta["water"] = {"record_id": str(hydration.record.id)}
                content = message_formatter.compose_water(
                    hydration, recompute, local_today(user.timezone)
                )
            elif envelope.intent == "log_beverage":
                if envelope.beverage is None:
                    return await self._record_error(user_message, result)
                beverage = await BeverageService(self.session, catalog).create_from_llm(
                    user=user,
                    day_log_id=day_log_id,
                    message_id=user_message.id,
                    envelope=envelope,
                )
                recompute = await recompute_service.recompute(day_log_id)
                dispatch_meta["beverage"] = {
                    "record_id": str(beverage.record.id),
                    "warnings": beverage.warnings,
                }
                content = message_formatter.compose_beverage(
                    beverage, recompute, local_today(user.timezone)
                )
            elif envelope.intent == "log_activity":
                if envelope.activity is None:
                    return await self._record_error(user_message, result)
                try:
                    activity = await ActivityService(self.session).create_from_llm(
                        user=user,
                        day_log_id=day_log_id,
                        message_id=user_message.id,
                        envelope=envelope,
                    )
                except WeightRequired:
                    # SP-61: sem weight_kg → não persiste; clarify amigável.
                    return await self._record_clarify(
                        user_message,
                        result,
                        "Antes de calcular as calorias gastas, me diga seu peso "
                        'atual em kg. Você pode dizer, por exemplo, "peso 78 kg".',
                        code="weight_kg_required",
                    )
                recompute = await recompute_service.recompute(day_log_id)
                dispatch_meta["activity"] = {
                    "record_id": str(activity.record.id),
                    "warnings": activity.warnings,
                }
                content = message_formatter.compose_activity(
                    activity, recompute, local_today(user.timezone)
                )
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

    async def _resolve_registration_day_log(
        self,
        *,
        user: User,
        envelope: Any,
        default_day_log_id: uuid.UUID,
    ) -> uuid.UUID:
        """Resolve o `day_log` alvo do registro (SP-184, INV-25).

        Sem `target_date`, mantém o dia corrente (day_log da user message).
        Com `target_date`, resolve/cria o `day_log` daquela data — rejeitando
        data futura e dia fechado com `ValidationAppError` (virará clarify).
        """
        if envelope.target_date is None:
            return default_day_log_id

        today = local_today(user.timezone)
        if envelope.target_date > today:
            raise ValidationAppError("registro em data futura não é permitido", code="future_date")

        day_log = await DayLogRepository(self.session).get_or_create(
            user_id=user.id, log_date=envelope.target_date
        )
        if day_log.status == "closed":
            raise ValidationAppError(
                "esse dia já foi encerrado e não pode receber registros",
                code="retroactive_day_closed",
            )
        return day_log.id

    async def _handle_set_profile(self, user_message: Message, result: LLMCallResult) -> Message:
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
                    k: {"before": v[0], "after": v[1]} for k, v in profile.changed_fields.items()
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

    async def _handle_correction_or_deletion(
        self, user_message: Message, result: LLMCallResult
    ) -> Message:
        envelope = result.envelope
        if envelope is None:
            return await self._record_error(user_message, result)
        if user_message.day_log_id is None:
            return await self._record_error(user_message, result)

        user = await self.session.get(User, user_message.user_id)
        if user is None:
            return await self._record_error(user_message, result)

        is_correction = envelope.intent == "correct_record"
        service_call = (
            CorrectionService(self.session).apply_from_llm
            if is_correction
            else DeletionService(self.session).apply_from_llm
        )

        try:
            outcome = await service_call(
                user=user,
                day_log_id=user_message.day_log_id,
                message_id=user_message.id,
                envelope=envelope,
            )
        except DayClosedError:
            return await self._record_clarify(
                user_message,
                result,
                "Esse dia já foi encerrado — não é possível alterar registros nele.",
                code="conflict_closed_day",
            )
        except NoTargetFound as exc:
            return await self._record_clarify(
                user_message,
                result,
                (
                    f'Não achei nenhum registro que casse com "{exc.hint}" '
                    "no dia de hoje. Pode me dizer qual foi?"
                ),
                code="target_not_found",
            )
        except AmbiguousTarget as exc:
            return await self._record_clarify(
                user_message,
                result,
                _compose_ambiguity_prompt(exc),
                code="ambiguous_correction_target",
            )
        except ValidationAppError as exc:
            return await self._record_clarify(
                user_message,
                result,
                _clarify_from_validation(exc),
                code=exc.code,
            )

        # Sucesso → recompute do dia.
        recompute = await DailyRecomputeService(self.session).recompute(user_message.day_log_id)

        raw = _pack_raw(result)
        raw["dispatch"] = {
            "action": "correct" if is_correction else "delete",
            "kind": outcome.kind.value,
            "entity_id": str(outcome.entity_id),
            "snapshot_version": recompute.snapshot.version,
        }
        if is_correction:
            assert isinstance(outcome, CorrectionResult)
            raw["dispatch"]["changed"] = {
                k: {"before": v[0], "after": v[1]} for k, v in outcome.changed_fields.items()
            }
            content = _compose_correction_summary(outcome, recompute)
        else:
            assert isinstance(outcome, DeletionResult)
            raw["dispatch"]["already_deleted"] = outcome.already_deleted
            content = _compose_deletion_summary(outcome, recompute)

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

    async def _handle_close_day(self, user_message: Message, result: LLMCallResult) -> Message:
        envelope = result.envelope
        if envelope is None:
            return await self._record_error(user_message, result)

        user = await self.session.get(User, user_message.user_id)
        if user is None:
            return await self._record_error(user_message, result)

        close_result = await DayCloseService(self.session, anthropic=self.anthropic).close_today(
            user=user, message_id=user_message.id
        )

        raw = _pack_raw(result)
        raw["dispatch"] = {
            "action": "close_day",
            "day_log_id": str(close_result.day_log.id),
            "log_date": close_result.day_log.log_date.isoformat(),
            "was_already_closed": close_result.was_already_closed,
            "snapshot_version": close_result.snapshot.version,
        }
        content = _compose_close_summary(close_result)
        return await self.messages.create(
            user_id=user_message.user_id,
            day_log_id=close_result.day_log.id,
            role="assistant",
            content=content,
            llm_intent="close_day",
            llm_model=result.model,
            llm_prompt_version=result.prompt_version,
            llm_confidence=envelope.confidence,
            raw_llm_response=raw,
            tokens_input=result.tokens_input,
            tokens_output=result.tokens_output,
        )

    async def _handle_query_day(self, user_message: Message, result: LLMCallResult) -> Message:
        envelope = result.envelope
        if envelope is None:
            return await self._record_error(user_message, result)

        user = await self.session.get(User, user_message.user_id)
        if user is None:
            return await self._record_error(user_message, result)

        from app.core.exceptions import NotFoundError

        try:
            payload = await DayQueryService(self.session).get_today(user=user)
        except NotFoundError:
            # Usuário novo, sem day_log ainda. Ao chegar até `query_day` a
            # `ChatService.post_user_message` já deveria ter criado, mas caso
            # algo tenha impedido, respondemos amigável em vez de estourar.
            return await self._record_clarify(
                user_message,
                result,
                (
                    "Ainda não há registros no dia de hoje pra resumir. "
                    "Me conta o que você comeu, bebeu ou treinou."
                ),
                code="day_not_found",
            )

        raw = _pack_raw(result)
        raw["dispatch"] = {
            "action": "query_day",
            "log_date": payload.date.isoformat(),
            "snapshot_version": payload.snapshot_version,
        }
        content = _compose_query_day_summary(payload)
        return await self.messages.create(
            user_id=user_message.user_id,
            day_log_id=user_message.day_log_id,
            role="assistant",
            content=content,
            llm_intent="query_day",
            llm_model=result.model,
            llm_prompt_version=result.prompt_version,
            llm_confidence=envelope.confidence,
            raw_llm_response=raw,
            tokens_input=result.tokens_input,
            tokens_output=result.tokens_output,
        )

    async def _handle_nutrition_label(
        self, user_message: Message, result: LLMCallResult
    ) -> Message:
        envelope = result.envelope
        if envelope is None or envelope.nutrition_label is None:
            return await self._record_error(user_message, result)

        user = await self.session.get(User, user_message.user_id)
        if user is None:
            return await self._record_error(user_message, result)

        # SP-30: `label_media_id` = a primeira mídia da user message, se houver.
        label_media_id = await self._first_media_id(user_message.id)

        service = LabelCatalogService(self.session)
        label_result = await service.upsert_from_label(
            user=user,
            label=envelope.nutrition_label,
            label_media_id=label_media_id,
            message_id=user_message.id,
        )

        # SP-31: se `also_consumed`, cria food_record + food_item + recompute.
        recompute = None
        consumed_item = None
        if envelope.nutrition_label.also_consumed is not None:
            if user_message.day_log_id is None:
                # Sem day_log não dá para registrar consumo — retorna só o cadastro.
                pass
            else:
                _, item = await service.register_consumption(
                    user=user,
                    day_log_id=user_message.day_log_id,
                    message_id=user_message.id,
                    fact=label_result.fact,
                    consumed=envelope.nutrition_label.also_consumed,
                    meal_slot=envelope.meal_slot or "unspecified",
                )
                consumed_item = item
                recompute = await DailyRecomputeService(self.session).recompute(
                    user_message.day_log_id
                )

        # SP-143 / T-B521: se a user message veio do card recovery do Bloco 5
        # (frontend adicionou `promote_food_item_id` ao POST /chat/messages,
        # armazenado em raw_llm_response.metadata pelo ChatService), promove
        # o item legado usando o fact recém-criado. Falha silenciosa grava
        # audit `action='promotion_failed'` sem afetar a resposta.
        promotion_warning: str | None = None
        promoted_item_id: uuid.UUID | None = None
        promote_id = _extract_promote_id(user_message.raw_llm_response)
        if promote_id is not None:
            promotion_warning, promoted_item_id = await try_promote_food_item(
                session=self.session,
                user=user,
                item_id=promote_id,
                fact=label_result.fact,
                message_id=user_message.id,
                promoted_from="label_ocr",
            )
            if promotion_warning is not None:
                await AuditEventRepository(self.session).record(
                    user_id=user.id,
                    entity_type="food_item",
                    entity_id=promote_id,
                    action="promotion_failed",
                    actor="user",
                    message_id=user_message.id,
                    before=None,
                    after={
                        "nutrient_fact_id": str(label_result.fact.id),
                        "reason": promotion_warning,
                        "promoted_from": "label_ocr",
                    },
                )

        raw = _pack_raw(result)
        raw["dispatch"] = {
            "action": "log_nutrition_label",
            "nutrient_fact_id": str(label_result.fact.id),
            "verified_by_user": label_result.fact.verified_by_user,
            "warnings": label_result.warnings,
        }
        if consumed_item is not None:
            raw["dispatch"]["consumed_item_id"] = str(consumed_item.id)
        if recompute is not None:
            raw["dispatch"]["snapshot_version"] = recompute.snapshot.version
        if promoted_item_id is not None:
            raw["dispatch"]["promoted_item_id"] = str(promoted_item_id)
        if promotion_warning is not None:
            raw["dispatch"]["promotion_warning"] = promotion_warning

        content = _compose_label_summary(
            envelope.nutrition_label, label_result, consumed_item, recompute
        )
        return await self.messages.create(
            user_id=user_message.user_id,
            day_log_id=user_message.day_log_id,
            role="assistant",
            content=content,
            llm_intent="log_nutrition_label",
            llm_model=result.model,
            llm_prompt_version=result.prompt_version,
            llm_confidence=envelope.confidence,
            raw_llm_response=raw,
            tokens_input=result.tokens_input,
            tokens_output=result.tokens_output,
        )

    async def _first_media_id(self, message_id: uuid.UUID) -> uuid.UUID | None:
        stmt = (
            select(MessageMedia.media_id)
            .where(MessageMedia.message_id == message_id)
            .order_by(MessageMedia.media_id)
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _handle_weekly_summary(self, user_message: Message, result: LLMCallResult) -> Message:
        envelope = result.envelope
        if envelope is None:
            return await self._record_error(user_message, result)

        user = await self.session.get(User, user_message.user_id)
        if user is None:
            return await self._record_error(user_message, result)

        outcome = await WeeklyReportService(self.session, anthropic=self.anthropic).generate(
            user=user, message_id=user_message.id
        )
        report = outcome.report

        raw = _pack_raw(result)
        raw["dispatch"] = {
            "action": "weekly_summary",
            "report_id": str(report.id),
            "window_start": (report.window_start.isoformat() if report.window_start else None),
            "window_end": (report.window_end.isoformat() if report.window_end else None),
            "days_included": report.days_included,
            "reused": outcome.reused,
            "version": report.version,
        }
        content = _compose_weekly_summary(report)
        return await self.messages.create(
            user_id=user_message.user_id,
            day_log_id=user_message.day_log_id,
            role="assistant",
            content=content,
            llm_intent="weekly_summary",
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

    async def _load_media(self, message_id: uuid.UUID) -> list[tuple[str, bytes]]:
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

    async def _record_error(self, user_message: Message, result: LLMCallResult) -> Message:
        # Log estruturado — facilita diagnóstico quando o assistant cai
        # no fallback genérico. Inclui o erro do cliente Anthropic e, se
        # foi validation_exhausted, os erros específicos do Pydantic +
        # o último payload que a LLM tentou emitir.
        logger.warning(
            "llm_error_recorded",
            extra={
                "event": "message_processor",
                "message_id": str(user_message.id),
                "user_id": str(user_message.user_id),
                "error": result.error,
                "model": result.model,
                "prompt_version": result.prompt_version,
                "validation_errors": result.validation_errors,
                "raw_tool_input": result.raw_tool_input,
            },
        )
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
        names = ", ".join({w.get("detected_name", w.get("item_id", "item")) for w in to_confirm})
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


def _compose_water_summary(hydration: HydrationResult, recompute: RecomputeResult) -> str:
    lines = [f"Registrei {hydration.record.volume_ml} ml de água.", ""]
    lines.append(_totals_line(recompute.snapshot))
    lines.append(_DISCLAIMER)
    return "\n".join(lines)


_KIND_LABELS = {
    TargetKind.FOOD: "alimento",
    TargetKind.WATER: "água",
    TargetKind.BEVERAGE: "bebida",
    TargetKind.ACTIVITY: "atividade",
}


def _compose_correction_summary(outcome: CorrectionResult, recompute: RecomputeResult) -> str:
    label = _KIND_LABELS[outcome.kind]
    changes_parts = [
        f"{field}: {v[0]} → {v[1]}"
        for field, v in outcome.changed_fields.items()
        if field
        not in {
            "kcal",
            "protein_g",
            "carbs_g",
            "fat_g",
            "fiber_g",
            "sodium_mg",
            "calcium_mg",
            "iron_mg",
            "potassium_mg",
            "met_value",
            "calc_method",
            "needs_confirmation",
            "source",
        }
    ]
    lines = [
        f"Ajustei o registro de {label}. Alterações: {'; '.join(changes_parts)}."
        if changes_parts
        else f"Ajustei o registro de {label}.",
    ]
    lines.append("")
    lines.append(_totals_line(recompute.snapshot))
    lines.append(_DISCLAIMER)
    return "\n".join(lines)


def _compose_deletion_summary(outcome: DeletionResult, recompute: RecomputeResult) -> str:
    label = _KIND_LABELS[outcome.kind]
    if outcome.already_deleted:
        first_line = f"O registro de {label} já estava removido — nada a fazer."
    else:
        first_line = f"Removi o registro de {label}."
    lines = [first_line, ""]
    lines.append(_totals_line(recompute.snapshot))
    lines.append(_DISCLAIMER)
    return "\n".join(lines)


def _compose_ambiguity_prompt(exc: AmbiguousTarget) -> str:
    candidates_desc: list[str] = []
    for cand in exc.candidates[:4]:
        entity = cand.entity
        label = _KIND_LABELS[cand.kind]
        name = getattr(entity, "detected_name", None) or "água"
        detail = _entity_short_desc(cand.kind, entity)
        candidates_desc.append(f"- {label}: {name} ({detail})")
    listing = "\n".join(candidates_desc)
    return (
        f'Encontrei mais de um registro que casa com "{exc.hint}". '
        "Pode me dizer qual desses?\n" + listing
    )


def _entity_short_desc(kind: TargetKind, entity) -> str:
    if kind == TargetKind.FOOD:
        if entity.grams:
            return f"{int(entity.grams)}g"
        if entity.ml:
            return f"{int(entity.ml)}ml"
        return f"{entity.quantity} {entity.unit or ''}".strip()
    if kind == TargetKind.WATER:
        return f"{entity.volume_ml}ml"
    if kind == TargetKind.BEVERAGE:
        return f"{entity.volume_ml}ml"
    if kind == TargetKind.ACTIVITY:
        return f"{int(entity.duration_minutes)}min"
    return ""


def _compose_beverage_summary(beverage: BeverageResult, recompute: RecomputeResult) -> str:
    record = beverage.record
    lines = [
        f"Registrei {record.volume_ml} ml de {record.detected_name}"
        f" ({int(record.kcal or 0)} kcal).",
    ]
    to_confirm = [
        w for w in beverage.warnings if w["code"] in ("no_catalog_hit", "low_confidence_item")
    ]
    if to_confirm:
        names = ", ".join({w.get("detected_name", record.detected_name) for w in to_confirm})
        lines.append(f"Confirma esses itens? {names}")
    lines.append("")
    lines.append(_totals_line(recompute.snapshot))
    lines.append(_DISCLAIMER)
    return "\n".join(lines)


def _compose_activity_summary(activity: ActivityResult, recompute: RecomputeResult) -> str:
    record = activity.record
    duration = int(record.duration_minutes)
    kcal = int(record.kcal_burned)
    intensity_label = {
        "light": "leve",
        "moderate": "moderada",
        "vigorous": "intensa",
        "unknown": "sem intensidade informada",
    }.get(record.intensity, record.intensity)
    source_hint = " (informado pelo dispositivo)" if record.calc_method == "user_manual" else ""
    lines = [
        f"Registrei {duration} min de {record.detected_name}"
        f" ({intensity_label}) — {kcal} kcal gastos{source_hint}.",
    ]
    if any(w["code"].startswith("missing_") for w in activity.warnings):
        lines.append("Alguns dados ficaram estimados; confirma se está certo?")
    lines.append("")
    lines.append(_totals_line(recompute.snapshot))
    lines.append(_DISCLAIMER)
    return "\n".join(lines)


def _compose_label_summary(
    label,
    label_result: LabelResult,
    consumed_item,
    recompute,
) -> str:
    """SP-30/31: cabeçalho do cadastro + consumo opcional + disclaimer."""
    fact = label_result.fact
    brand = f" ({label.brand})" if label.brand else ""
    lines: list[str] = [
        f"Cadastrei o produto {label.product_name}{brand} com base no rótulo.",
    ]
    if fact.kcal is not None:
        lines.append(
            f"Valores por 100{'g' if fact.basis == 'per_100g' else 'ml'}: "
            f"{int(fact.kcal)} kcal · P {_maybe_int(fact.protein_g)}g · "
            f"C {_maybe_int(fact.carbs_g)}g · G {_maybe_int(fact.fat_g)}g."
        )
    if label_result.warnings:
        micros = next(
            (w for w in label_result.warnings if w["code"] == "micros_missing_for_product"),
            None,
        )
        if micros:
            lines.append(
                "Cálcio, ferro e potássio não vieram no rótulo — aparecerão como "
                "zerados nos totais até você preencher no cartão."
            )
    lines.append(
        "Confirme os valores no cartão abaixo (ou peça para eu ajustar) — "
        "isso melhora a precedência do catálogo quando o mesmo produto for lido de novo."
    )
    if consumed_item is not None and recompute is not None:
        lines.append("")
        amount = _amount_label(
            consumed_item.grams,
            consumed_item.ml,
            consumed_item.quantity,
            consumed_item.unit,
        )
        lines.append(f"Consumo registrado: {consumed_item.detected_name} — {amount}.")
        lines.append(_totals_line(recompute.snapshot))
    lines.append(_DISCLAIMER)
    return "\n".join(lines)


def _maybe_int(value) -> str:
    if value is None:
        return "0"
    return str(int(value))


def _compose_weekly_summary(report) -> str:
    """SP-110/113: cabeçalho curto + narrative (que já traz o disclaimer)."""
    if report.days_included == 0:
        head = (
            "Ainda não há dias encerrados para gerar um resumo semanal. "
            'Encerre um dia primeiro ("encerrar dia") e tente de novo.'
        )
    else:
        start = report.window_start.strftime("%d/%m") if report.window_start else "?"
        end = report.window_end.strftime("%d/%m") if report.window_end else "?"
        head = (
            f"Resumo semanal ({start} → {end}) com {report.days_included} "
            f"{'dia' if report.days_included == 1 else 'dias'} encerrados."
        )
    body = report.narrative or ""
    return f"{head}\n\n{body}".strip()


def _compose_close_summary(close_result: DayCloseResult) -> str:
    """SP-103: `narrative` já vem com disclaimer concatenado pelo service.

    Prefixamos uma linha curta explicando o fechamento (ou reafirmação
    idempotente), e depois a narrative in-full. Não repetimos o disclaimer.
    """
    log_date = close_result.day_log.log_date.strftime("%d/%m/%Y")
    if close_result.was_already_closed:
        prefix = f"O dia {log_date} já estava encerrado. Segue o resumo:"
    else:
        prefix = f"Dia {log_date} encerrado."
    return f"{prefix}\n\n{close_result.narrative}"


def _compose_query_day_summary(payload: DayPayload) -> str:
    """SP-90/SP-91: resumo do dia em formato tabular (padrão SP-118).

    Usa `message_formatter._daily_totals_table` para produzir a mesma
    tabela `Total acumulado — DD/MM/YYYY` que aparece após qualquer
    registro, com formatação pt-BR + `≈` quando houver itens pendentes.
    """
    from types import SimpleNamespace

    # `_daily_totals_table` lê o snapshot por atributos — o payload aqui
    # devolve totals como dict, então adaptamos para SimpleNamespace.
    snap = SimpleNamespace(**payload.totals)
    # `approx=True` quando existem warnings de itens que ainda podem mudar
    # os totais (needs_confirmation/no_catalog_hit/low_confidence_item).
    approx = any(
        w.get("code") in ("needs_confirmation", "no_catalog_hit", "low_confidence_item")
        for w in payload.warnings
    )

    log_date_str = payload.date.strftime("%d/%m/%Y")
    status_label = "encerrado" if payload.status == "closed" else "em aberto"

    header = f"Resumo de {log_date_str} ({status_label})."
    totals_table = message_formatter._daily_totals_table(snap, payload.date, approx)

    parts = [header, "", totals_table, "", _DISCLAIMER]
    if payload.warnings:
        n = len(payload.warnings)
        parts.append("")
        pending_label = (
            "item ainda pode ser confirmado" if n == 1 else "itens ainda podem ser confirmados"
        )
        parts.append(f"**Confirma estes itens?** — {n} {pending_label}.")
    return "\n".join(parts)


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
    "future_date": (
        "Não consigo registrar em uma data futura. Você pode me dizer o que "
        "quer registrar para hoje ou para um dia anterior?"
    ),
    "retroactive_day_closed": (
        "Esse dia já foi encerrado, então não consigo adicionar registros nele."
    ),
}


def _clarify_from_validation(exc: ValidationAppError) -> str:
    return _CLARIFY_TEMPLATES.get(exc.code, "Pode reformular sua mensagem com mais detalhes?")


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
    packed["envelope"] = result.envelope.model_dump(mode="json") if result.envelope else None
    return packed


def _extract_promote_id(raw: Any) -> uuid.UUID | None:
    """SP-143: lê `promote_food_item_id` da metadata gravada pelo ChatService
    quando o usuário enviou pelo card recovery do Bloco 5.

    Retorna None se qualquer coisa faltar/estiver malformada — o handler
    fallback é "não promover" (comportamento pré-Bloco 5).
    """
    if not isinstance(raw, dict):
        return None
    metadata = raw.get("metadata")
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("promote_food_item_id")
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError):
        return None


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

    Contrato de segurança: **o usuário sempre recebe uma assistant message**.
    Se `processor.process()` erguer qualquer exceção inesperada, a
    transação primária é revertida e abrimos uma NOVA sessão para gravar
    uma mensagem de fallback. Sem isso, o usuário fica preso ao "digitando"
    e nem o refresh resolve — apenas outra mensagem (que dispara novo
    background task) mostraria alguma resposta.
    """
    async with session_factory() as session:
        processor = MessageProcessor(session=session, anthropic=anthropic_client, storage=storage)
        try:
            await processor.process(message_id)
            await session.commit()
            return
        except Exception:
            await session.rollback()
            logger.exception(
                "background_processor_failed",
                extra={"event": "message_processor", "message_id": str(message_id)},
            )

    # Fallback: nova sessão, tenta persistir um assistant message amigável.
    # Falha silenciosa aqui é aceitável — melhor não mascarar o problema
    # original nos logs.
    try:
        async with session_factory() as fallback_session:
            stmt = select(Message).where(Message.id == message_id)
            user_message = (await fallback_session.execute(stmt)).scalar_one_or_none()
            if user_message is None:
                return
            await MessageRepository(fallback_session).create(
                user_id=user_message.user_id,
                day_log_id=user_message.day_log_id,
                role="assistant",
                content=_FALLBACK_LLM_ERROR,
                llm_intent="unknown",
                raw_llm_response={"error": "background_processor_failed"},
            )
            await fallback_session.commit()
    except Exception:
        logger.exception(
            "background_fallback_failed",
            extra={"event": "message_processor", "message_id": str(message_id)},
        )
