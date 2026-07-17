import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MediaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    content_type: str
    size_bytes: int
    width: int | None
    height: int | None
    created_at: datetime


class MediaWithUrl(BaseModel):
    id: uuid.UUID
    content_type: str
    url: str
