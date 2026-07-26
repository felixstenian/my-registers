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

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationAppError
from app.models import Media, Message, User
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

        day_log = await self.day_logs.get_or_create(
            user_id=user.id, log_date=local_today(user.timezone)
        )
        message = await self.messages.create(
            user_id=user.id,
            day_log_id=day_log.id,
            role="user",
            content=text_stripped,
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
        after_id: uuid.UUID | None,
        before_id: uuid.UUID | None,
        limit: int,
    ) -> list[MessageWithMedia]:
        rows = await self.messages.list_messages(
            user_id=user.id,
            after_id=after_id,
            before_id=before_id,
            limit=limit,
        )
        media_map = await self.messages.load_media_map([m.id for m in rows])
        return [MessageWithMedia(message=m, media=media_map.get(m.id, [])) for m in rows]
