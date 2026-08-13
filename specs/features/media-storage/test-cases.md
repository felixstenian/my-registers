# Casos de Teste — Storage de mídia

> Arquivo: `apps/api/tests/test_media.py` (6 casos de integração).
> Fixture de MinIO: provavelmente stub/mock — verificar `conftest.py`.

---

## Testes de integração

### TC-I-001 — Upload PNG happy path

- **Arquivo**: `test_upload_png_happy_path`
- **Setup**: PNG válido em memória
- **Ação**: `POST /media` multipart
- **Verificar**:
  - 201 com `{id, content_type:"image/png", size_bytes, width, height}`
  - `media` row no DB com `user_id`, `storage_key` no formato canônico
  - `checksum_sha256` preenchido

### TC-I-002 — Upload JPEG happy path

- **Arquivo**: `test_upload_jpeg_happy_path`
- **Verificar**: 201 com `content_type:"image/jpeg"`

### TC-I-003 — MIME não suportado → 422

- **Arquivo**: `test_upload_rejects_unsupported_mime`
- **Setup**: arquivo com `content_type: image/gif`
- **Verificar**: 422 `{code: "unsupported_media_type"}`; sem row em `media`

### TC-I-004 — Imagem falsa (decode probe) → 422

- **Arquivo**: `test_upload_rejects_fake_image`
- **Setup**: bytes de texto com `content_type: image/jpeg`
- **Verificar**: 422 `{code: "invalid_image"}`; MinIO `put_object` não chamado

### TC-I-005 — Arquivo > 8MB → 422

- **Arquivo**: `test_upload_rejects_too_large`
- **Setup**: `b"x" * (8 * 1024 * 1024 + 1)`
- **Verificar**: 422 `{code: "file_too_large"}`

### TC-I-006 — Sem auth → 401

- **Arquivo**: `test_upload_requires_auth`
- **Verificar**: 401

---

## Testes unitários potenciais (gaps)

### TC-U-001 — `_decode_probe` com imagem válida

- **Setup**: bytes de PNG real (1×1 pixel)
- **Verificar**: `DecodedImage(width=1, height=1)` retornado
- **Nota**: dois `Image.open` necessários (`verify()` consome stream)

### TC-U-002 — `_decode_probe` com bytes inválidos

- **Setup**: `b"not an image"`
- **Verificar**: `ValidationAppError(code="invalid_image")` levantada

### TC-U-003 — `make_storage_key` formato canônico

- **Setup**: `user_id=uuid4()`, `ext="jpg"`
- **Verificar**: resultado bate com regex `^users/[^/]+/media/\d{4}/\d{2}/[a-f0-9]{32}\.jpg$`
- **Verificar**: dois calls produzem keys diferentes (UUID v4)

### TC-U-004 — `presigned_get_url` reescrita de host

- **Setup**: `MinioStorage(public_base_url="https://myregister.felix.dev.br")`
- **Mock**: boto3 retorna URL `http://minio:9000/my-registers/users/.../foto.jpg?X-Amz-Signature=...`
- **Verificar**: URL retornada tem `https://myregister.felix.dev.br/my-registers/users/.../foto.jpg?X-Amz-Signature=...` (path+query preservados)

### TC-U-005 — `MIME_TO_EXT` cobertura

- Verificar que apenas `image/jpeg`, `image/png`, `image/webp` estão no dict
- Verificar extensões corretas: `jpg`, `png`, `webp`

### TC-U-006 — Arquivo vazio → `empty_upload`

- `MediaService.upload(data=b"", content_type="image/jpeg")` → `ValidationAppError(code="empty_upload")`

---

## Testes E2E manuais

### TC-E-001 — Upload via chat (mobile)

- **Persona**: Felix (iPhone Safari)
- **Passos**: abrir `/chat`, clicar clipe, selecionar foto 3MB, enviar
- **Verificar**: foto aparece no balão da mensagem; assistant processa

### TC-E-002 — URL pública em produção

- **Passos**: upload em prod; verificar `media[].url` em `GET /chat/messages`
- **Verificar**: URL começa com `https://myregister.felix.dev.br/...`, não `http://minio:9000/...`

### TC-E-003 — PDF disfarçado de JPEG

- **Passos**: renomear PDF para `foto.jpg`; tentar upload
- **Verificar**: 422 `invalid_image`; frontend exibe "não parece ser uma imagem válida"

---

## Testes de regressão críticos

- **`test_upload_rejects_fake_image`** — Const. §22; sem decode probe, arquivos maliciosos chegam à Anthropic.
- **`test_upload_rejects_unsupported_mime`** — allowlist server-side; cliente não pode bypassar.
- **`test_upload_rejects_too_large`** — SP-11; upload grande pode bloquear o servidor.

## Como rodar

```bash
cd apps/api
# MinIO precisa estar up: pnpm infra:up

uv run pytest tests/test_media.py -v

# coverage
uv run pytest tests/test_media.py \
  --cov=app/services/media \
  --cov=app/integrations/storage/minio \
  --cov-report=term-missing
```
