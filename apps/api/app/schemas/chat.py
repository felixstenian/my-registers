from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PostMessageRequest(BaseModel):
    text: str | None = Field(default=None, max_length=8000)
    media_ids: list[uuid.UUID] = Field(default_factory=list, max_length=4)
    # SP-143: quando o usuário envia foto de rótulo pelo card recovery
    # do Bloco 5, o frontend passa o ID do food_item que precisa ser
    # promovido depois de o backend criar o nutrient_fact. Ownership é
    # validado silenciosamente no ChatService — se falha, o campo é
    # descartado e a mensagem segue o fluxo normal (sem promoção).
    promote_food_item_id: uuid.UUID | None = None


class PostMessageResponse(BaseModel):
    message_id: uuid.UUID
    status: Literal["processing"]


class MediaRef(BaseModel):
    id: uuid.UUID
    content_type: str
    url: str


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str | None
    llm_intent: str | None = None
    llm_confidence: Decimal | None = None
    media: list[MediaRef] = Field(default_factory=list)
    created_at: datetime
    # SP-33: quando `llm_intent='log_nutrition_label'`, o cliente usa este
    # campo para renderizar o cartão de confirmação inline com botão que
    # chama `PATCH /nutrient-facts/{id}`.
    nutrient_fact_id: uuid.UUID | None = None


class MessagesListResponse(BaseModel):
    messages: list[MessageOut]
