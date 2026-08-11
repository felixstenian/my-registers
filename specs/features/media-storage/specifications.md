# Especificações Técnicas — Storage de mídia

> **Fontes**: `apps/api/app/services/media.py`, `apps/api/app/api/routes/media.py`, `apps/api/app/integrations/storage/minio.py`, `apps/api/app/models/media.py`, `apps/api/app/schemas/media.py`, `apps/api/app/repositories/media.py`.

## Endpoint

### `POST /media`

- **Auth**: `access_token`.
- **Content-Type**: `multipart/form-data`.
- **Field**: `file` (UploadFile).
- **Sucesso** (`201`):
  ```json
  {
    "id": "uuid",
    "content_type": "image/jpeg",
    "size_bytes": 153600,
    "width": 1024,
    "height": 768,
    "created_at": "2026-07-28T10:00:00Z"
  }
  ```
- **Erros**:
  - `422 unsupported_media_type` — MIME não está na allowlist ou `content_type=None`.
  - `422 empty_upload` — arquivo vazio.
  - `422 file_too_large` — > 8 MB.
  - `422 invalid_image` — bytes não passam no decode probe.
  - `401 unauthorized` — sem cookie.

## Modelo de dados

### `media`

Modelo: [`apps/api/app/models/media.py`](../../../apps/api/app/models/media.py)

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | UUID | PK |
| `user_id` | UUID FK users(id) ON DELETE CASCADE | Owner |
| `storage_key` | text UNIQUE NOT NULL | Path canônico no MinIO: `users/{uid}/media/{yyyy}/{mm}/{uuid}.{ext}` |
| `content_type` | text NOT NULL | `image/jpeg`, `image/png` ou `image/webp` |
| `size_bytes` | bigint NOT NULL | Tamanho original (pre-compressão) |
| `width`, `height` | integer NULL | Dimensões da imagem (do decode probe) |
| `checksum_sha256` | text NULL | SHA-256 hex do conteúdo original |
| `status` | text CHECK IN (`uploaded`, `failed`) DEFAULT `uploaded` | |
| `created_at` | timestamptz NOT NULL DEFAULT now() | |

## Fluxo de dados

### Upload

```
POST /media (multipart, field=file)
  ├─ if file.content_type is None → 422 unsupported_media_type
  ├─ data = await file.read()
  └─ MediaService.upload(user, data, content_type):
        ├─ if content_type not in MIME_TO_EXT → 422 unsupported_media_type
        ├─ if len(data) == 0 → 422 empty_upload
        ├─ if len(data) > 8 * 1024 * 1024 → 422 file_too_large
        ├─ decoded = _decode_probe(data):
        │     ├─ PIL.Image.open(BytesIO(data)).verify()     # autentica bytes
        │     ├─ PIL.Image.open(BytesIO(data)).size         # captura dims
        │     └─ except (UnidentifiedImageError, OSError, ValueError) → 422 invalid_image
        ├─ checksum = hashlib.sha256(data).hexdigest()
        ├─ ext = MIME_TO_EXT[content_type]                  # jpg | png | webp
        ├─ key = make_storage_key(user.id, ext)
        │     → "users/{uid}/media/{yyyy}/{mm}/{uuid4}.{ext}"
        ├─ await storage.put_object(key, body=data, content_type)
        │     → asyncio.to_thread(s3_client.put_object, ...)
        └─ await media_repo.create(user_id, storage_key=key, content_type,
                                   size_bytes, width, height, checksum_sha256)
           → 201 MediaOut
```

### Leitura — presigned URL (gerada em `GET /chat/messages`)

```
GET /chat/messages
  └─ para cada media:
        url = await storage.presigned_get_url(media.storage_key)
              → asyncio.to_thread(s3_client.generate_presigned_url,
                    "get_object", Params={Bucket, Key}, ExpiresIn=3600)
              → se S3_PUBLIC_BASE_URL configurado:
                    substitui scheme+netloc pela URL pública, mantém path+query
        MediaRef(id, content_type, url=presigned_url)
```

### Download — bytes para Anthropic

```
MessageProcessor.process(message_id)
  └─ para cada media vinculada à mensagem:
        data: bytes = await storage.get_object(media.storage_key)
              → asyncio.to_thread(s3_client.get_object, ...) + Body.read()
        AnthropicClient._compress_image(data, content_type)
              → JPEG 1024px q=75 (feature anthropic-integration)
        base64.b64encode(compressed_data)
```

## Constantes e mapeamentos

```python
MIME_TO_EXT = {
    "image/jpeg": "jpg",
    "image/png":  "png",
    "image/webp": "webp",
}

MAX_SIZE_BYTES = 8 * 1024 * 1024    # 8 MB

# storage_key canônico (Const. §22):
f"users/{user_id}/media/{year:04d}/{month:02d}/{uuid4().hex}.{ext}"
```

## `MinioStorage` — interface

| Método | Async | Descrição |
|---|---|---|
| `put_object(key, body, content_type)` | `asyncio.to_thread` | Upload de objeto |
| `get_object(key)` | `asyncio.to_thread` | Download de bytes |
| `presigned_get_url(key, expires_in=3600)` | `asyncio.to_thread` | URL assinada pré-gerada |

Singleton via `@lru_cache get_storage()`.

## Configurações e variáveis de ambiente

| Variável | Descrição | Dev default |
|---|---|---|
| `S3_ENDPOINT` | URL interna do MinIO | `http://localhost:9000` |
| `S3_ACCESS_KEY` | Access key MinIO | `minio_dev` |
| `S3_SECRET_KEY` | Secret key MinIO | `minio_dev_secret` |
| `S3_REGION` | Região S3 | `us-east-1` |
| `S3_BUCKET` | Nome do bucket | `my-registers` |
| `S3_FORCE_PATH_STYLE` | `true` para MinIO path-style | `true` |
| `S3_PUBLIC_BASE_URL` | URL pública do MinIO (Nginx em prod) | `None` |

Em produção, `S3_ENDPOINT` aponta para o MinIO interno (Docker network); `S3_PUBLIC_BASE_URL` aponta para `https://<domínio>/media` (ou similar) via Nginx. A reescrita de host em `presigned_get_url` preserva a assinatura S3 (path + query) enquanto troca scheme+netloc.

## Referências de implementação

- **Service**: [`app/services/media.py`](../../../apps/api/app/services/media.py) (`MediaService`, `_decode_probe`, `DecodedImage`).
- **Route**: [`app/api/routes/media.py`](../../../apps/api/app/api/routes/media.py).
- **Storage**: [`app/integrations/storage/minio.py`](../../../apps/api/app/integrations/storage/minio.py) (`MinioStorage`, `make_storage_key`, `MIME_TO_EXT`, `get_storage`).
- **Model**: [`app/models/media.py`](../../../apps/api/app/models/media.py).
- **Schema**: [`app/schemas/media.py`](../../../apps/api/app/schemas/media.py) (`MediaOut`, `MediaWithUrl`).
- **Repository**: [`app/repositories/media.py`](../../../apps/api/app/repositories/media.py) (`MediaRepository`).
- **Testes**: [`apps/api/tests/test_media.py`](../../../apps/api/tests/test_media.py) (6 casos).
