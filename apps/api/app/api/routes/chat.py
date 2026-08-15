"""POST /chat/messages e GET /chat/messages (SP-10, SP-11, SP-12, SP-13, SP-14, SP-92)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_anthropic_client_dep,
    get_current_user,
    get_session,
    get_session_factory_dep,
    get_storage_dep,
)
from app.integrations.anthropic.client import AnthropicClient
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
from app.services.message_processor import run_processor_in_background

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post(
    "/messages",
    response_model=PostMessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_message(
    payload: PostMessageRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    anthropic_client: AnthropicClient = Depends(get_anthropic_client_dep),
    storage: MinioStorage = Depends(get_storage_dep),
    session_factory=Depends(get_session_factory_dep),
) -> PostMessageResponse:
    service = ChatService(session)
    message = await service.post_user_message(
        user=current_user,
        text=payload.text,
        media_ids=payload.media_ids,
        via=payload.via,
        promote_food_item_id=payload.promote_food_item_id,
    )
    # BackgroundTasks rodam ANTES do cleanup da dep `get_session`; comitamos
    # explicitamente aqui para que o worker (com sua própria sessão) enxergue
    # a mensagem.
    await session.commit()
    background_tasks.add_task(
        run_processor_in_background,
        message.id,
        session_factory=session_factory,
        anthropic_client=anthropic_client,
        storage=storage,
    )
    return PostMessageResponse(message_id=message.id, status="processing")


@router.get("/messages", response_model=MessagesListResponse)
async def list_messages(
    response: Response,
    via: str = Query(default="food", pattern="^(food|workout)$"),
    after: uuid.UUID | None = Query(default=None),
    before: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: MinioStorage = Depends(get_storage_dep),
) -> MessagesListResponse:
    # Chat depende de poll da mesma URL; sem `Cache-Control` explícito, alguns
    # browsers aplicam heurística de freshness e servem a resposta vazia do
    # cache até o cap do poll expirar (bug reportado em 2026-07-19).
    response.headers["Cache-Control"] = "no-store"
    service = ChatService(session)
    items = await service.list_messages(
        user=current_user, via=via, after_id=after, before_id=before, limit=limit
    )
    out: list[MessageOut] = []
    for item in items:
        media_refs: list[MediaRef] = []
        for m in item.media:
            url = await storage.presigned_get_url(m.storage_key)
            media_refs.append(MediaRef(id=m.id, content_type=m.content_type, url=url))
        # SP-33: expõe `nutrient_fact_id` ao cliente quando o assistant
        # cadastrou um rótulo, para o botão de confirmação inline.
        nutrient_fact_id = None
        raw = item.message.raw_llm_response
        if item.message.llm_intent == "log_nutrition_label" and isinstance(raw, dict):
            dispatch = raw.get("dispatch") or {}
            fid = dispatch.get("nutrient_fact_id")
            if isinstance(fid, str):
                nutrient_fact_id = uuid.UUID(fid)
        out.append(
            MessageOut(
                id=item.message.id,
                role=item.message.role,
                content=item.message.content,
                llm_intent=item.message.llm_intent,
                llm_confidence=item.message.llm_confidence,
                media=media_refs,
                created_at=item.message.created_at,
                nutrient_fact_id=nutrient_fact_id,
            )
        )
    return MessagesListResponse(messages=out)
