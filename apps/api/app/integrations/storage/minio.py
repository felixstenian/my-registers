"""Cliente MinIO (S3-compatible) via boto3.

`put_object` e `presigned_get_url` são chamados em thread pool para não
bloquear o event loop (boto3 é síncrono). `make_storage_key` gera o path
canonical do MVP: `users/{uid}/media/{yyyy}/{mm}/{uuid}.{ext}`
(Const. Art. V §22 — nome sempre gerado pelo backend).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from functools import lru_cache

import boto3
from botocore.client import Config

from app.core.config import get_settings

MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


def make_storage_key(user_id: uuid.UUID, ext: str) -> str:
    now = datetime.now(UTC)
    return f"users/{user_id}/media/{now.year:04d}/{now.month:02d}/{uuid.uuid4().hex}.{ext}"


class MinioStorage:
    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        region: str,
        bucket: str,
        force_path_style: bool,
        public_base_url: str | None = None,
    ) -> None:
        self.bucket = bucket
        self._public_base_url = public_base_url or None
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path" if force_path_style else "auto"},
            ),
        )

    async def put_object(
        self,
        *,
        key: str,
        body: bytes,
        content_type: str,
    ) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )

    async def presigned_get_url(self, key: str, *, expires_in: int = 3600) -> str:
        url: str = await asyncio.to_thread(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        # Em produção, o MinIO fica em rede interna. `S3_PUBLIC_BASE_URL` permite
        # trocar o host interno pela URL pública (Nginx) sem regenerar a
        # assinatura.
        if self._public_base_url:
            from urllib.parse import urlsplit, urlunsplit

            parts = urlsplit(url)
            pub = urlsplit(self._public_base_url)
            url = urlunsplit(
                (pub.scheme, pub.netloc, parts.path, parts.query, parts.fragment)
            )
        return url


@lru_cache
def get_storage() -> MinioStorage:
    s = get_settings()
    return MinioStorage(
        endpoint=s.s3_endpoint,
        access_key=s.s3_access_key,
        secret_key=s.s3_secret_key,
        region=s.s3_region,
        bucket=s.s3_bucket,
        force_path_style=s.s3_force_path_style,
        public_base_url=s.s3_public_base_url or None,
    )
