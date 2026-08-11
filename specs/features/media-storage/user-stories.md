# Histórias de Usuário — Storage de mídia

## Personas

- **Felix (P1)** — faz upload de fotos de prato ou rótulo para registrar via chat.
- **Sistema (não-persona)** — garante segurança e validade das imagens antes de expô-las à LLM.

---

### US-001 — Fazer upload de foto de prato

**Como** Felix,
**Quero** selecionar uma foto do meu prato no celular e anexar à mensagem do chat,
**Para que** o assistente identifique os alimentos por visão.

**Critérios de aceitação:**
- [ ] `POST /media` com JPEG válido → 201 com `{id, content_type, width, height, ...}`.
- [ ] `media.storage_key` no formato `users/{uid}/media/...` (gerado pelo backend).
- [ ] `media_id` retornado pode ser passado em `POST /chat/messages { media_ids: [id] }`.

**Cobertura**: SP-11, RF-001.

---

### US-002 — Ver a foto que enviei no chat

**Como** Felix,
**Quero** que a minha foto apareça no balão da mensagem no chat,
**Para que** eu confirme visualmente o que foi enviado.

**Critérios de aceitação:**
- [ ] `GET /chat/messages` gera presigned URL (~1h) para cada media da mensagem.
- [ ] URL assinada por S3v4 acessível diretamente pelo browser.
- [ ] Em produção: host reescrito para `S3_PUBLIC_BASE_URL` (Nginx público), não IP interno.

**Cobertura**: RF-009, integração com [`chat-messaging`](../chat-messaging/).

---

### US-003 — Ser avisado quando arquivo não é imagem válida

**Como** Felix,
**Quero** receber erro claro ao tentar enviar um PDF renomeado como `.jpg`,
**Para que** eu saiba exatamente o que está errado.

**Critérios de aceitação:**
- [ ] Bytes que falham no decode probe → 422 `invalid_image`.
- [ ] Frontend exibe "arquivo.jpg não parece ser uma imagem válida" (SP-18).
- [ ] Nenhum objeto enviado ao MinIO.

**Cobertura**: Const. §22, RF-005.

---

### US-004 — Ser avisado quando arquivo é grande demais

**Como** Felix,
**Quero** ver mensagem clara ao tentar enviar foto de 12MB,
**Para que** eu tire foto menor ou comprima antes.

**Critérios de aceitação:**
- [ ] `len(data) > 8MB` → 422 `file_too_large`.
- [ ] Frontend exibe "selfie_grande.jpg é maior que 8 MB" (SP-18).

**Cobertura**: SP-11, RF-003.

---

### US-005 — Ter foto enviada à Anthropic com privacidade

**Como** Felix,
**Quero** garantia de que minhas fotos vão para a Anthropic em base64, sem URL pública,
**Para que** a imagem não fique exposta na internet.

**Critérios de aceitação:**
- [ ] `MessageProcessor` baixa bytes via `storage.get_object(key)`.
- [ ] `AnthropicClient._build_user_content` codifica em base64.
- [ ] Nenhuma URL de foto aparece no payload enviado à API Anthropic.

**Cobertura**: Const. §26, RF-010, RF-011.

---

### US-006 — Formato não suportado rejeitado

**Como** Felix,
**Quero** ver erro ao enviar GIF ou MP4,
**Para que** o app rejeite arquivos que não sabe processar.

**Critérios de aceitação:**
- [ ] `content_type` não em `{image/jpeg, image/png, image/webp}` → 422 `unsupported_media_type`.
- [ ] Frontend exibe "formato de arquivo.gif não suportado. Envie JPEG, PNG ou WEBP" (SP-18).

**Cobertura**: RF-002.
