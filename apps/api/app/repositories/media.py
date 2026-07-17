import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models import Media


class MediaRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        storage_key: str,
        content_type: str,
        size_bytes: int,
        width: int | None,
        height: int | None,
        checksum_sha256: str,
        status: str = "uploaded",
    ) -> Media:
        media = Media(
            user_id=user_id,
            storage_key=storage_key,
            content_type=content_type,
            size_bytes=size_bytes,
            width=width,
            height=height,
            checksum_sha256=checksum_sha256,
            status=status,
        )
        self.session.add(media)
        await self.session.flush()
        return media

    async def get_by_id(
        self, media_id: uuid.UUID, *, user_id: uuid.UUID
    ) -> Media | None:
        stmt = select(Media).where(Media.id == media_id, Media.user_id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_by_ids(
        self, media_ids: list[uuid.UUID], *, user_id: uuid.UUID
    ) -> list[Media]:
        if not media_ids:
            return []
        stmt = select(Media).where(
            Media.id.in_(media_ids), Media.user_id == user_id
        )
        return list((await self.session.execute(stmt)).scalars())
