from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PostMessageRequest(BaseModel):
    text: str | None = Field(default=None, max_length=8000)
    media_ids: list[uuid.UUID] = Field(default_factory=list, max_length=4)


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


class MessagesListResponse(BaseModel):
    messages: list[MessageOut]
