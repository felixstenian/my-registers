from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Media, Message, MessageMedia


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        day_log_id: uuid.UUID | None,
        role: str,
        content: str | None = None,
        llm_intent: str | None = None,
        llm_model: str | None = None,
        llm_prompt_version: str | None = None,
        llm_confidence: float | None = None,
        raw_llm_response: dict[str, Any] | None = None,
        tokens_input: int | None = None,
        tokens_output: int | None = None,
    ) -> Message:
        message = Message(
            user_id=user_id,
            day_log_id=day_log_id,
            role=role,
            content=content,
            llm_intent=llm_intent,
            llm_model=llm_model,
            llm_prompt_version=llm_prompt_version,
            llm_confidence=llm_confidence,
            raw_llm_response=raw_llm_response,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def link_media(self, *, message_id: uuid.UUID, media_ids: list[uuid.UUID]) -> None:
        for mid in media_ids:
            self.session.add(MessageMedia(message_id=message_id, media_id=mid))
        await self.session.flush()

    async def get_by_id(self, message_id: uuid.UUID, *, user_id: uuid.UUID) -> Message | None:
        stmt = select(Message).where(Message.id == message_id, Message.user_id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_messages(
        self,
        *,
        user_id: uuid.UUID,
        after_id: uuid.UUID | None = None,
        before_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[Message]:
        anchor_after = await self.get_by_id(after_id, user_id=user_id) if after_id else None
        anchor_before = await self.get_by_id(before_id, user_id=user_id) if before_id else None

        stmt = select(Message).where(Message.user_id == user_id)
        if anchor_after is not None:
            stmt = stmt.where(Message.created_at > anchor_after.created_at)
        if anchor_before is not None:
            stmt = stmt.where(Message.created_at < anchor_before.created_at)

        if anchor_before is not None:
            # pega os N MAIS RECENTES antes do anchor, depois reverte
            stmt = stmt.order_by(Message.created_at.desc()).limit(limit)
            rows = list((await self.session.execute(stmt)).scalars())
            rows.reverse()
            return rows

        stmt = stmt.order_by(Message.created_at).limit(limit)
        return list((await self.session.execute(stmt)).scalars())

    async def load_media_map(self, message_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Media]]:
        if not message_ids:
            return {}
        stmt = (
            select(MessageMedia.message_id, Media)
            .join(Media, Media.id == MessageMedia.media_id)
            .where(MessageMedia.message_id.in_(message_ids))
        )
        rows = (await self.session.execute(stmt)).all()
        out: dict[uuid.UUID, list[Media]] = {}
        for message_id, media in rows:
            out.setdefault(message_id, []).append(media)
        return out
