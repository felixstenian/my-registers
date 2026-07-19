"""POST /media — upload de imagem para MinIO.

SP-11. Const. Art. V §22 (MIME server-side, ≤ 8MB, decode probe,
storage_key gerado pelo backend).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_session, get_storage_dep
from app.core.exceptions import ValidationAppError
from app.integrations.storage.minio import MinioStorage
from app.models import User
from app.schemas.media import MediaOut
from app.services.media import MediaService

router = APIRouter(prefix="/media", tags=["media"])


@router.post("", response_model=MediaOut, status_code=status.HTTP_201_CREATED)
async def upload_media(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: MinioStorage = Depends(get_storage_dep),
) -> MediaOut:
    if file.content_type is None:
        raise ValidationAppError("missing content type", code="unsupported_media_type")
    data = await file.read()
    service = MediaService(session, storage)
    media = await service.upload(
        user=current_user,
        data=data,
        content_type=file.content_type,
    )
    return MediaOut.model_validate(media)
