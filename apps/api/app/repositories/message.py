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
        via: str = "food",
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
            via=via,
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
        via: str = "food",
        after_id: uuid.UUID | None = None,
        before_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[Message]:
        """Pagina cronologicamente. Regras:

        - `after_id`: pega TUDO desde o anchor (exclusivo) em ASC, cap no
          `limit`. Uso principal: polling incremental do chat.
        - `before_id`: pega os N mais recentes ANTES do anchor e devolve em
          ASC. Uso: scroll para cima no histórico.
        - **Sem anchor** (chamada inicial): pega os `limit` MAIS RECENTES
          (`ORDER BY created_at DESC LIMIT N`), depois reverte para ASC.
          Antes fazíamos `ASC LIMIT N` que devolvia as mais ANTIGAS — em
          contas com muito histórico isso escondia a conversa recente e
          o refresh não trazia o que o usuário acabou de escrever
          (bug reportado em 2026-07-19).
        """
        # SP-173: anchor só é válido dentro da mesma `via`; um after_id do
        # chat de alimentação não deve pular a página no chat de treino.
        anchor_after = await self.get_by_id(after_id, user_id=user_id) if after_id else None
        anchor_before = await self.get_by_id(before_id, user_id=user_id) if before_id else None
        if anchor_after is not None and anchor_after.via != via:
            anchor_after = None
        if anchor_before is not None and anchor_before.via != via:
            anchor_before = None

        stmt = select(Message).where(Message.user_id == user_id, Message.via == via)
        if anchor_after is not None:
            stmt = stmt.where(Message.created_at > anchor_after.created_at)
        if anchor_before is not None:
            stmt = stmt.where(Message.created_at < anchor_before.created_at)

        if anchor_after is not None:
            # Polling incremental: ordem cronológica ASC direto.
            stmt = stmt.order_by(Message.created_at).limit(limit)
            return list((await self.session.execute(stmt)).scalars())

        # Sem `after` (initial load ou scroll com `before`): pega os N MAIS
        # RECENTES, depois reverte para devolver em ASC.
        stmt = stmt.order_by(Message.created_at.desc()).limit(limit)
        rows = list((await self.session.execute(stmt)).scalars())
        rows.reverse()
        return rows

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
