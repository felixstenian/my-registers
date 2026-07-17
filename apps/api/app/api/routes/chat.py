"""POST /chat/messages e GET /chat/messages (SP-10, SP-11, SP-12, SP-92)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_session, get_storage_dep
from app.integrations.storage.minio import MinioStorage
from app.models import User
from app.schemas.chat import (
    MediaRef,
    MessageOut,
    MessagesListResponse,
    PostMessageRequest,
    PostMessageResponse,
)
from app.services.chat import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post(
    "/messages",
    response_model=PostMessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_message(
    payload: PostMessageRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PostMessageResponse:
    service = ChatService(session)
    message = await service.post_user_message(
        user=current_user, text=payload.text, media_ids=payload.media_ids
    )
    return PostMessageResponse(message_id=message.id, status="processing")


@router.get("/messages", response_model=MessagesListResponse)
async def list_messages(
    after: uuid.UUID | None = Query(default=None),
    before: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: MinioStorage = Depends(get_storage_dep),
) -> MessagesListResponse:
    service = ChatService(session)
    items = await service.list_messages(
        user=current_user, after_id=after, before_id=before, limit=limit
    )
    out: list[MessageOut] = []
    for item in items:
        media_refs: list[MediaRef] = []
        for m in item.media:
            url = await storage.presigned_get_url(m.storage_key)
            media_refs.append(
                MediaRef(id=m.id, content_type=m.content_type, url=url)
            )
        out.append(
            MessageOut(
                id=item.message.id,
                role=item.message.role,
                content=item.message.content,
                llm_intent=item.message.llm_intent,
                llm_confidence=item.message.llm_confidence,
                media=media_refs,
                created_at=item.message.created_at,
            )
        )
    return MessagesListResponse(messages=out)
