# Requisitos — Storage de mídia (MinIO S3)

> **Rastreabilidade**: SP-11 em [`spec.md §3.2`](../../001-mvp-registro-diario/spec.md#32-chat) · Const. Art. V §22 · Const. Art. VII §26 (privacidade — fotos via base64, não URL).

## Visão geral

Upload de imagens (JPEG, PNG, WEBP) para MinIO (S3-compatible) antes de linkarem a uma mensagem de chat. `POST /media` valida MIME server-side, tamanho (≤ 8MB), faz *decode probe* via Pillow (garante que os bytes são uma imagem válida — Const. §22), gera `storage_key` canônico pelo backend e persiste metadados em `media`. A URL pré-assinada (~1h) é gerada por demanda na listagem de mensagens (`GET /chat/messages`). Fotos enviadas à Anthropic vão em base64, nunca via URL (Const. §26).

## Requisitos funcionais

| ID | Requisito | SP / Const. | Prioridade |
|---|---|---|---|
| RF-001 | `POST /media` multipart aceita arquivos JPEG, PNG, WEBP ≤ 8 MB. Retorna 201 com `{id, content_type, size_bytes, width, height, created_at}`. | SP-11 | Must Have |
| RF-002 | MIME validado server-side contra allowlist `{image/jpeg, image/png, image/webp}` — não confia no header do cliente. | Const. §22 | Must Have |
| RF-003 | Tamanho validado (`len(data) > 8 * 1024 * 1024` → 422 `file_too_large`). | SP-11 | Must Have |
| RF-004 | Arquivo vazio → 422 `empty_upload`. | Const. §22 | Must Have |
| RF-005 | *Decode probe* via `PIL.Image.verify()` — bytes que não são imagem real → 422 `invalid_image`, mesmo que MIME seja `image/jpeg`. | Const. §22 | Must Have |
| RF-006 | `storage_key` gerado pelo backend no formato `users/{uid}/media/{yyyy}/{mm}/{uuid}.{ext}` — nunca nome do arquivo do cliente. | Const. §22 | Must Have |
| RF-007 | SHA-256 do conteúdo calculado e gravado em `media.checksum_sha256`. | Auditabilidade | Should Have |
| RF-008 | `MinioStorage.put_object` e `presigned_get_url` rodam em `asyncio.to_thread` (boto3 é síncrono). | Não bloquear event loop | Must Have |
| RF-009 | `MinioStorage.presigned_get_url` reescreve host interno para `S3_PUBLIC_BASE_URL` quando configurado (produção: MinIO fica em rede interna, Nginx é o público). | Deploy | Must Have |
| RF-010 | `MinioStorage.get_object(key)` baixa bytes do objeto — usado pelo `MessageProcessor` para enviar imagens à Anthropic em base64. | SP-11, Const. §26 | Must Have |
| RF-011 | Fotos enviadas à Anthropic via base64, nunca via URL pública. | Const. §26 | Must Have |
| RF-012 | Ownership: `media.user_id = current_user.id`. `ChatService` rejeita `media_id` que não pertence ao user antes de linkar à mensagem. | Const. §21 | Must Have |
| RF-013 | `media.status` CHECK IN (`uploaded`, `failed`) — default `uploaded`. | Auditabilidade | Should Have |

## Requisitos não funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | Decode probe (Pillow `verify()`) bloqueia em thread separada — não via `asyncio.to_thread` (executado síncrono no request, antes do upload). | Correção |
| RNF-002 | `put_object` e `get_object` em `asyncio.to_thread` — boto3 síncrono não pode bloquear o loop FastAPI. | Performance |
| RNF-003 | Latência de upload P95 ≤ 2s para imagem comprimida (~200KB pós-Pillow). | Performance |
| RNF-004 | MinIO configurado com `force_path_style=True` em dev local e produção (compatibilidade com S3 path-style). | Deploy |
| RNF-005 | Isolamento: `storage_key` inclui `user_id` no path — objetos de users diferentes nunca colidem. | Segurança |

## Restrições e premissas

- **Allowlist de MIME**: apenas `image/jpeg`, `image/png`, `image/webp`. GIF, SVG, MP4 etc. são rejeitados.
- **Decode probe é síncrono**: `PIL.Image.verify()` roda no request thread. Custo baixo (~1ms para imagem < 8MB).
- **Dois `Image.open` separados**: `verify()` consome o stream; segundo `open` relê para capturar `width`/`height`.
- **Compressão é feita na integração Anthropic** (não aqui): `AnthropicClient._compress_image` (Pillow, 1024px, JPEG q=75) roda ao enviar pra Anthropic — feature [`anthropic-integration`](../anthropic-integration/). MediaService não comprime.
- **Presigned URL expira em 1h** (`expires_in=3600`): hardcoded, não configurável. Cliente não deve cachear além disso.
- **MinIO bucket**: configurado por `S3_BUCKET`. Não criamos o bucket na API — deploy runbook (docs/deploy.md) inicializa.

## Dependências

**Depende de:**
- `Pillow` para decode probe.
- `boto3` para MinIO (S3-compatible).
- [`authentication-session`](../authentication-session/) — `Depends(get_current_user)`.
- Config `S3_*` de `app/core/config.py`.

**Requerido por:**
- [`chat-messaging`](../chat-messaging/) — `ChatService.post_user_message` valida ownership e linka `media_ids` à mensagem; `GET /chat/messages` gera presigned URL por demanda.
- [`anthropic-integration`](../anthropic-integration/) — `MessageProcessor` chama `storage.get_object(key)` para baixar bytes e enviar à Anthropic.
- [`nutrition-label-ocr`](../nutrition-label-ocr/) — foto do rótulo passa pelo mesmo fluxo de upload.
