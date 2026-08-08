# Requisitos — Composer do chat — UX (Bloco 1)

> **Rastreabilidade**: SP-15..SP-19 em [`specs/001-mvp-registro-diario/spec.md`](../../001-mvp-registro-diario/spec.md#32-chat--mensagens) (Bloco 1) · Implementação: `apps/web/src/app/(app)/chat/page.tsx` · Dependências: SP-10/SP-11 (chat base, feature `chat-messaging`).

## Visão geral

Melhorias de UX no compositor do chat (`/chat`): envio por Enter (SP-15), captura direta pela câmera em mobile (SP-16), limite client-side de 4 imagens com feedback por nome de arquivo (SP-17), mensagens de erro amigáveis para rejeições de upload (SP-18) e drag-and-drop de arquivos (SP-19). Tudo no frontend (Next.js 16 + React 19); o backend (`POST /media`, `POST /chat/messages`) já valida as mesmas regras, mas a UI dá feedback imediato antes do round-trip.

## Requisitos funcionais

| ID | Requisito | SP | Prioridade |
|---|---|---|---|
| RF-001 | Enter sem Shift envia a mensagem; Shift+Enter insere quebra de linha; textarea vazia + sem mídia → tecla ignorada; envio em curso → tecla ignorada (anti-duplo-envio). | SP-15 | May Have |
| RF-002 | Em mobile, `<input type="file" capture="environment">` oferece "Tirar foto" além de "Escolher da galeria" (câmera traseira preferida). Em desktop, `capture` é ignorado. | SP-16 | May Have |
| RF-003 | Limite client-side de 4 imagens por mensagem: se N>4, aceita os 4 primeiros e lista nome de cada arquivo rejeitado com motivo. Contagem inclui arquivos já pré-anexados. | SP-17 | May Have |
| RF-004 | Mensagens de erro amigáveis em pt-BR para rejeições de upload: `file_too_large` (>8MB), `invalid_image`, `unsupported_media_type`, `empty_upload` — cada uma cita o nome do arquivo. Envio em lote não aborta por 1 falha; válidos são anexados. Compositor não fecha nem perde texto. | SP-18 | May Have |
| RF-005 | Drag-and-drop de arquivos sobre o compositor: adiciona ao anexo (modo append), aplica mesmas regras do input file (MIME, cap de 4, erros SP-18). Feedback visual enquanto arrasta (borda tracejada/fundo); removido ao sair ou soltar. | SP-19 | May Have |
| RF-006 | Composição IME (chinês/japonês/coreano): Enter durante `isComposing` não envia. | [Inferido do código] | Must Have |

## Requisitos não funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | Allowlist de MIME client-side reflete o backend: `image/jpeg`, `image/png`, `image/webp` (`ACCEPT_MIME`). | Confiabilidade |
| RNF-002 | Cap de 8 MB por arquivo client-side (`MAX_FILE_BYTES = 8 * 1024 * 1024`) idêntico ao backend — bloqueia antes do round-trip para feedback imediato. | UX |
| RNF-003 | `credentials: 'include'` em `fetch('/api/media')` para enviar cookie `access_token`. | Segurança |
| RNF-004 | `cache: 'no-store'` em upload de mídia. | Confiabilidade |
| RNF-005 | Polling de resposta do assistente: intervalo 1500ms, cap 60s (`POLL_INTERVAL_MS`, `POLL_CAP_MS`). | UX |
| RNF-006 | Drag-and-drop usa `dragCounterRef` para evitar flicker ao passar por elementos filhos. | UX |

## Restrições e premissas

- **SP-15..19 são `may`**: não bloqueiam MVP, mas já implementados em produção (v1.3.0).
- **Backend também valida**: `POST /media` rejeita >4 `media_ids`, >8MB, MIME inválido (SP-11). A UI replica para feedback imediato; se bypass programático passar, o backend ainda rejeita.
- **Sem envio em lote de mensagens**: uma mensagem por vez; `sending` state bloqueia duplo envio.
- **`capture="environment"`** é dica para o SO; não garante câmera traseira em todos os dispositivos.
- **Drag-and-drop em mobile**: comportamento touch do SO prevalece; drop é opcional (SP-19 aceita isso).

## Dependências

**Depende de:**
- [`chat-messaging`](../chat-messaging/requirements.md) — `POST /chat/messages` (SP-10/SP-11) é o destino do envio; `POST /media` (SP-11) para upload.
- [`media-storage`](../media-storage/requirements.md) — MinIO via `POST /media`; erros `file_too_large`/`invalid_image`/`unsupported_media_type` vêm daqui.
- [`authentication-session`](../authentication-session/requirements.md) — cookie `access_token` enviado via `credentials: 'include'`.

**Requerido por:**
- [`assistant-message-rendering`](../assistant-message-rendering/requirements.md) — composer envia a mensagem que dispara a resposta do assistente (SP-115..118).
- [`nutrition-label-ocr`](../nutrition-label-ocr/requirements.md) — foto do rótulo anexada via composer (SP-16/SP-19).
- [`food-logging`](../food-logging/requirements.md) — foto de prato anexada via composer (SP-22).
