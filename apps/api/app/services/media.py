"""MediaService — valida upload, faz decode probe, sobe pro MinIO e persiste.

Cobre SP-11 e Const. Art. V §22 (MIME server-side, ≤ 8MB, decode probe,
nome gerado pelo backend).
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationAppError
from app.integrations.storage.minio import (
    MIME_TO_EXT,
    MinioStorage,
    make_storage_key,
)
from app.models import Media, User
from app.repositories.media import MediaRepository

MAX_SIZE_BYTES = 8 * 1024 * 1024  # 8 MB


@dataclass(slots=True)
class DecodedImage:
    width: int
    height: int


def _decode_probe(data: bytes) -> DecodedImage:
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValidationAppError(
            "invalid image", code="invalid_image"
        ) from exc
    return DecodedImage(width=width, height=height)


class MediaService:
    def __init__(self, session: AsyncSession, storage: MinioStorage) -> None:
        self.session = session
        self.storage = storage
        self.media = MediaRepository(session)

    async def upload(
        self,
        *,
        user: User,
        data: bytes,
        content_type: str,
    ) -> Media:
        if content_type not in MIME_TO_EXT:
            raise ValidationAppError(
                f"unsupported content type: {content_type}",
                code="unsupported_media_type",
            )
        if len(data) == 0:
            raise ValidationAppError("empty upload", code="empty_upload")
        if len(data) > MAX_SIZE_BYTES:
            raise ValidationAppError(
                "file too large (max 8MB)", code="file_too_large"
            )

        decoded = _decode_probe(data)
        checksum = hashlib.sha256(data).hexdigest()
        ext = MIME_TO_EXT[content_type]
        key = make_storage_key(user.id, ext)

        await self.storage.put_object(
            key=key, body=data, content_type=content_type
        )

        return await self.media.create(
            user_id=user.id,
            storage_key=key,
            content_type=content_type,
            size_bytes=len(data),
            width=decoded.width,
            height=decoded.height,
            checksum_sha256=checksum,
        )
