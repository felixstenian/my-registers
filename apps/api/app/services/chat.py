"""ChatService — persistência de mensagens do usuário e listagem paginada.

Cobre SP-10, SP-11 (parte de link com media), SP-12, SP-92 (day_log usa
timezone IANA do usuário). A resposta do assistant (LLM) entra na Fase 3;
aqui só criamos `messages(role='user')`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationAppError
from app.models import FoodItem, FoodRecord, Media, Message, User
from app.repositories.day_log import DayLogRepository
from app.repositories.media import MediaRepository
from app.repositories.message import MessageRepository

MAX_MEDIA_PER_MESSAGE = 4


def local_today(tz_name: str) -> date:
    return datetime.now(ZoneInfo(tz_name)).date()


@dataclass(slots=True)
class MessageWithMedia:
    message: Message
    media: list[Media]


class ChatService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.messages = MessageRepository(session)
        self.day_logs = DayLogRepository(session)
        self.media = MediaRepository(session)

    async def post_user_message(
        self,
        *,
        user: User,
        text: str | None,
        media_ids: list[uuid.UUID],
        via: str = "food",
        promote_food_item_id: uuid.UUID | None = None,
    ) -> Message:
        text_stripped = (text or "").strip() or None
        if text_stripped is None and not media_ids:
            raise ValidationAppError("message needs text or media", code="empty_message")
        if len(media_ids) > MAX_MEDIA_PER_MESSAGE:
            raise ValidationAppError(
                f"max {MAX_MEDIA_PER_MESSAGE} media per message",
                code="too_many_media",
            )
        if media_ids:
            # SP-11 / Const. §21: media precisa pertencer ao próprio user.
            resolved = await self.media.list_by_ids(media_ids, user_id=user.id)
            if len(resolved) != len(set(media_ids)):
                raise ValidationAppError("unknown media_id for this user", code="unknown_media")

        # SP-143: valida ownership silenciosamente. Se falha, dropa o
        # promote_food_item_id — mensagem segue o fluxo normal sem
        # promoção. Motivação: não bloquear envio por erro em ID inválido
        # que veio do frontend (race entre delete + upload). Bloco 5 §3.14.
        validated_promote_id: uuid.UUID | None = None
        if promote_food_item_id is not None:
            stmt = (
                select(FoodItem.id)
                .join(FoodRecord, FoodRecord.id == FoodItem.food_record_id)
                .where(
                    FoodItem.id == promote_food_item_id,
                    FoodRecord.user_id == user.id,
                    FoodItem.deleted_at.is_(None),
                )
            )
            row = (await self.session.execute(stmt)).scalar_one_or_none()
            if row is not None:
                validated_promote_id = promote_food_item_id

        day_log = await self.day_logs.get_or_create(
            user_id=user.id, log_date=local_today(user.timezone)
        )
        # SP-143: promote_food_item_id armazenado em raw_llm_response.metadata
        # (evita migration destrutiva). MessageProcessor lê daí quando o
        # intent detectado for `log_nutrition_label` pra acoplar a promoção.
        raw: dict | None = None
        if validated_promote_id is not None:
            raw = {"metadata": {"promote_food_item_id": str(validated_promote_id)}}
        message = await self.messages.create(
            user_id=user.id,
            day_log_id=day_log.id,
            role="user",
            content=text_stripped,
            via=via,
            raw_llm_response=raw,
        )
        if media_ids:
            await self.messages.link_media(
                message_id=message.id, media_ids=list(dict.fromkeys(media_ids))
            )
        return message

    async def list_messages(
        self,
        *,
        user: User,
        via: str = "food",
        after_id: uuid.UUID | None,
        before_id: uuid.UUID | None,
        limit: int,
    ) -> list[MessageWithMedia]:
        rows = await self.messages.list_messages(
            user_id=user.id,
            via=via,
            after_id=after_id,
            before_id=before_id,
            limit=limit,
        )
        media_map = await self.messages.load_media_map([m.id for m in rows])
        return [MessageWithMedia(message=m, media=media_map.get(m.id, [])) for m in rows]
