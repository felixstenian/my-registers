# Requisitos — Chat e mensagens (núcleo)

> **Rastreabilidade**: SP-10..SP-14 em [`spec.md §3.2`](../../001-mvp-registro-diario/spec.md#32-chat) + SP-92 (fuso do dia) · Invariantes INV-9 · UX do composer é feature separada ([`chat-composer-ux`](../chat-composer-ux/)) · Renderização estruturada da assistant message é [`assistant-message-rendering`](../assistant-message-rendering/).

## Visão geral

Único ponto de entrada de negócio do usuário: **chat com o assistente**. `POST /chat/messages` recebe texto + até 4 mídias já uploadadas (via [`media-storage`](../media-storage/)), persiste `messages(role='user')` e agenda `BackgroundTask` para o `MessageProcessor` (que invoca [`anthropic-integration`](../anthropic-integration/) + dispatchers). Endpoint retorna imediatamente 202. Cliente faz polling via `GET /chat/messages?after=<id>` para receber a assistant message. Histórico persiste para sempre; correção/deleção não apaga mensagens.

## Requisitos funcionais

| ID | Requisito | SP | Prioridade |
|---|---|---|---|
| RF-001 | `POST /chat/messages` com `{text}` retorna 202 com `{message_id, status: "processing"}`; assistant message fica disponível em até 30s via `GET /chat/messages?after=<id>`. | SP-10 | Must Have |
| RF-002 | `POST /chat/messages` aceita `{text?, media_ids: [1..4 UUID]}` linkando mídias (já uploadadas via `POST /media`) ao registro. | SP-11 | Must Have |
| RF-003 | Bloqueia mensagem completamente vazia (sem texto e sem mídia) → 422 `code=empty_message`. | SP-10 | Must Have |
| RF-004 | Bloqueia > 4 mídias por mensagem → 422 `code=too_many_media`. | SP-11 | Must Have |
| RF-005 | Bloqueia `media_id` que não pertence ao current user → 422 `code=unknown_media` (nunca "existe mas não é seu"). | SP-11, Const. §21 | Must Have |
| RF-006 | Persiste `messages` com `role='user'`, `day_log_id` do dia local (SP-92), `content` (texto trimmed) e associa mídias via `message_media`. | SP-10, SP-11 | Must Have |
| RF-007 | Cria `day_log` do dia local do user (fuso `users.timezone`) via `get_or_create` — mensagem 23:50 BRT em 12/jul entra em `day_log 2026-07-12` mesmo que UTC seja 13/jul. | SP-92 | Must Have |
| RF-008 | `GET /chat/messages` retorna lista paginada com cursor por `after=<id>` (mensagens novas) ou `before=<id>` (histórico); `limit ∈ [1..200]`, default 50. Ordem cronológica ascendente. | SP-12 | Must Have |
| RF-009 | Sem `after` nem `before` → retorna as **mais recentes** (não as mais antigas). | SP-12 | Must Have |
| RF-010 | Cada `MessageOut` inclui `id, role, content, llm_intent, llm_confidence, media[], created_at, nutrient_fact_id?`. Media traz URL pré-assinada MinIO expira em ~1h. | SP-12, SP-33 | Must Have |
| RF-011 | `Cache-Control: no-store` no header do `GET /chat/messages` — polling da mesma URL sem header pode ser cacheado por navegador (bug reportado em 2026-07-19). | Correção | Must Have |
| RF-012 | Mensagem ambígua ("hoje foi puxado", sem info registrável) → assistente devolve `intent=clarify` com pergunta; **nenhum** record de negócio é criado. | SP-13 | Must Have |
| RF-013 | Timeout LLM (>60s) ou erro após retries → assistente responde "Não consegui interpretar; pode reformular?" e grava `messages.raw_llm_response.error`; **nada** persistido em records. | SP-14 | Must Have |
| RF-014 | Histórico persiste para sempre — correção ou deleção de registros **NÃO** apaga mensagens. Mensagens contam a história; registros contam os fatos. | SP-12 | Must Have |
| RF-015 | Assistente grava metadados: `llm_intent`, `llm_confidence`, `llm_model`, `llm_prompt_version`, `tokens_input`, `tokens_output`, `raw_llm_response` (JSONB). | Auditabilidade | Must Have |
| RF-016 | `BackgroundTask` roda com `session_factory` novo, não a `session` do request (que já commitou). `AsyncSession` do worker é independente. | Correção | Must Have |
| RF-017 | Router faz `await session.commit()` explícito **antes** de agendar background task — evita race onde worker abre nova sessão antes do commit da request. | Correção | Must Have |

## Requisitos não funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | Latência de `POST /chat/messages` (só persist + agendar) P95 ≤ 300ms. | Performance |
| RNF-002 | Latência ponta-a-ponta (POST → assistant message chegar via polling) P50 ≤ 6s texto puro, ≤ 12s com foto. | Performance |
| RNF-003 | `GET /chat/messages` P95 ≤ 200ms. | Performance |
| RNF-004 | Isolamento por usuário — todas as queries filtram por `user_id`. | Segurança (Const. §21) |
| RNF-005 | `text` limitado a 8000 chars (Pydantic `max_length=8000`). | Correção |
| RNF-006 | Mídia validada por ownership antes de link (não apenas por existência). | Segurança |
| RNF-007 | Cobertura mínima do `ChatService` e `MessageProcessor`: 80%. | Qualidade |

## Restrições e premissas

- **Mídias já uploadadas** em `POST /media` antes; `POST /chat/messages` só liga IDs. Ver [`media-storage`](../media-storage/).
- **Sem streaming SSE**: cliente faz polling `GET /chat/messages?after=<last>` a intervalos.
- **BackgroundTask do FastAPI**: roda no mesmo processo Python, após response ser enviada. Não usa Celery/RQ (single-VPS single-user).
- **`day_log_id` na message é opcional (FK ON DELETE SET NULL)**: se dia for deletado por algum motivo (migração), mensagem sobrevive como histórico.
- **`role='system'`** permitido no modelo (CHECK), mas não usado hoje.
- **Anúncios sobre a mesma mensagem**: assistente sempre gera **uma** message por request do user. Sem streaming de "penso alto".

## Dependências

**Depende de:**
- [`authentication-session`](../authentication-session/) — `Depends(get_current_user)`.
- [`media-storage`](../media-storage/) — validação de ownership + URL pré-assinada MinIO.
- [`anthropic-integration`](../anthropic-integration/) — LLM.
- [`daily-snapshot`](../daily-snapshot/) — mensagem "abre" o dia via `get_or_create`.
- [`food-logging`](../food-logging/), [`water-tracking`](../water-tracking/), [`caloric-beverages`](../caloric-beverages/), [`activity-cardio-logging`](../activity-cardio-logging/), [`nutrition-label-ocr`](../nutrition-label-ocr/), [`record-correction`](../record-correction/), [`record-deletion`](../record-deletion/), [`day-close`](../day-close/) — dispatchers por intent.

**Requerido por:**
- [`chat-composer-ux`](../chat-composer-ux/) — melhoria de UX no lado cliente (Enter, drag-drop, camera).
- [`assistant-message-rendering`](../assistant-message-rendering/) — como o cliente renderiza a `content` da mensagem.
- [`daily-detail-view`](../daily-detail-view/) — chat continua sendo a única superfície de mutação; `/day` é read-only.
