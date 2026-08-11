# Critérios de Aceitação — Storage de mídia

## AC-001 — Upload PNG happy path (RF-001)

**Dado que** PNG válido de 50KB
**Quando** `POST /media` multipart
**Então** 201 com `{id, content_type:"image/png", size_bytes:51200, width, height, created_at}`
**E** objeto existe em MinIO em `users/{uid}/media/{yyyy}/{mm}/{uuid}.png`
**E** `media` row no DB com `user_id`, `storage_key`, `checksum_sha256`.

**Notas**: `test_upload_png_happy_path`.

---

## AC-002 — Upload JPEG happy path

**Dado que** JPEG válido
**Quando** `POST /media`
**Então** 201 com `content_type:"image/jpeg"`.

**Notas**: `test_upload_jpeg_happy_path`.

---

## AC-003 — MIME não suportado → 422

**Dado que** arquivo com `content_type: image/gif`
**Quando** `POST /media`
**Então** 422 `{code: "unsupported_media_type"}`
**E** nenhum objeto enviado ao MinIO
**E** nenhum registro em `media`.

**Notas**: `test_upload_rejects_unsupported_mime`.

---

## AC-004 — Decode probe rejeita arquivo falso (Const. §22)

**Dado que** bytes de um PDF com `content_type: image/jpeg` (bytes não são JPEG)
**Quando** `_decode_probe(data)` roda
**Então** `PIL.Image.verify()` lança `UnidentifiedImageError`
**E** service levanta `ValidationAppError(code="invalid_image")`
**E** 422 `{code: "invalid_image"}`
**E** `put_object` nunca chamado.

**Notas**: `test_upload_rejects_fake_image`.

---

## AC-005 — Arquivo > 8MB → 422

**Dado que** arquivo de 9MB
**Quando** `POST /media`
**Então** 422 `{code: "file_too_large"}`
**E** decode probe não roda (size check é anterior).

**Notas**: `test_upload_rejects_too_large`.

---

## AC-006 — Sem auth → 401

**Quando** `POST /media` sem `access_token`
**Então** 401 `unauthorized`.

**Notas**: `test_upload_requires_auth`.

---

## AC-007 — `storage_key` gerado pelo backend (Const. §22, RF-006)

**Dado que** upload bem-sucedido
**Então** `media.storage_key` tem formato `users/{uid}/media/{yyyy}/{mm}/{hex}.{ext}`
**E** **não** contém nome original do arquivo do cliente
**E** é único (UUID v4 hex no path).

---

## AC-008 — SHA-256 gravado (RF-007)

**Dado que** upload bem-sucedido
**Então** `media.checksum_sha256 = hashlib.sha256(data).hexdigest()`
**E** valor é hex de 64 caracteres.

---

## AC-009 — Presigned URL gerada por demanda (RF-009)

**Dado que** media linkada a mensagem
**Quando** `GET /chat/messages`
**Então** `media[].url` é URL S3 assinada com parâmetros `X-Amz-Signature` etc.
**E** válida por ~3600s
**E** em produção (`S3_PUBLIC_BASE_URL` configurado): scheme+netloc reescrito para URL pública; path+query (incluindo assinatura) preservados.

---

## AC-010 — `get_object` baixa bytes para Anthropic (RF-010, Const. §26)

**Dado que** message com foto
**Quando** `MessageProcessor` processa
**Então** `storage.get_object(media.storage_key)` retorna bytes originais
**E** bytes são encodados em base64 para o payload Anthropic
**E** nenhuma URL de foto aparece no payload.

---

## AC-011 — boto3 não bloqueia event loop (RF-008, RNF-002)

**Dado que** `put_object` e `presigned_get_url` e `get_object` são síncrono no boto3
**Então** todos rodam via `asyncio.to_thread(...)`
**E** FastAPI não fica bloqueado durante I/O de objeto.

---

## AC-012 — Arquivo vazio → 422

**Dado que** upload com `data = b""`
**Quando** `MediaService.upload`
**Então** 422 `{code: "empty_upload"}` (check antes do decode probe).

---

## Cenários de borda

| Cenário | Comportamento esperado |
|---|---|
| `content_type=None` no header (cliente não manda) | Route retorna 422 `unsupported_media_type` antes de chegar no service |
| PNG com transparência (RGBA) | `verify()` aceita; `width`/`height` capturados corretamente |
| Imagem exatamente 8MB (= limite) | Aceita (`len(data) > MAX` é estrito; 8MB = limite) |
| Imagem de 8MB + 1 byte | Rejeita `file_too_large` |
| WEBP animado | `verify()` pode falhar em algumas versões do Pillow → `invalid_image`. Aceito |
| Upload de mesmo arquivo duas vezes | 2 rows em `media` com `storage_key` diferentes (UUID v4 garante unicidade) |
| MinIO indisponível durante `put_object` | boto3 lança exception → 500; `media` row não criada (transação) |

## Critérios de não-funcionalidade

| Critério | Threshold | Fonte |
|---|---|---|
| Upload P95 (imagem comprimida ~200KB) | ≤ 2s | RNF-003 |
| Isolamento de paths | `storage_key` inclui `user_id` | RNF-005 |
| MIME allowlist | `image/jpeg`, `image/png`, `image/webp` apenas | RF-002 |
| Tamanho máximo | 8 MB | RF-003 |
| TTL presigned URL | 3600s (1h) | RF-009 |
