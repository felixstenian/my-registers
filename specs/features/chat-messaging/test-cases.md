# Casos de Teste — Chat e mensagens

> Arquivo principal: `apps/api/tests/test_chat.py` (13 casos).
> Integração ampla: `tests/test_llm_flow.py` (11 casos) cobre pipeline com fake Anthropic.
> Rodar: `uv run pytest tests/test_chat.py tests/test_llm_flow.py -v`.

---

## Testes de integração — POST

### TC-I-001 — POST só texto retorna 202

- **Arquivo**: `test_post_text_only_returns_202`
- **Verificar**: 202 + `message_id`, message no DB com `role='user'`
- **SP**: SP-10

### TC-I-002 — POST sem auth → 401

- **Arquivo**: `test_post_requires_auth`

### TC-I-003 — Empty message rejeitada

- **Arquivo**: `test_post_rejects_empty_message`
- **Casos**: `text=""`, `text=" "`, `text=null`, todos sem media → 422 `empty_message`

### TC-I-004 — POST com media linka corretamente

- **Arquivo**: `test_post_with_media_links_them`
- **Setup**: 2 mídias uploadadas antes via `/media`
- **Verificar**: `message_media` tem 2 entradas; `GET` mostra mídias

### TC-I-005 — Bloqueia > 4 mídias

- **Arquivo**: `test_post_rejects_more_than_four_media`
- **Verificar**: 422 `too_many_media`

### TC-I-006 — Bloqueia mídia de outro user

- **Arquivo**: `test_post_rejects_media_from_other_user`
- **Setup**: user_A cria media; user_B tenta linkar
- **Verificar**: 422 `unknown_media`
- **SP**: Const. §21

---

## Testes de integração — GET

### TC-I-010 — Listagem cronológica

- **Arquivo**: `test_list_returns_chronological`
- **Verificar**: ordem ASC por `created_at`

### TC-I-011 — `after` devolve novos

- **Arquivo**: `test_list_after_returns_newer`
- **Verificar**: só messages com id > cursor

### TC-I-012 — Sem cursor devolve MAIS RECENTES

- **Arquivo**: `test_list_no_anchor_returns_most_recent_not_oldest`
- **Regressão explícita**: se alguém mudar pra "primeiras 50", este teste quebra

### TC-I-013 — `before` devolve antigas

- **Arquivo**: `test_list_before_returns_older`

### TC-I-014 — Media URLs presigned

- **Arquivo**: `test_list_media_urls_returned`
- **Verificar**: `media[].url` é URL MinIO com signature

---

## Testes de integração — day_log

### TC-I-020 — POST cria day_log respeitando fuso

- **Arquivo**: `test_post_creates_day_log_for_user_timezone`
- **Setup**: user com `timezone='America/Sao_Paulo'`
- **Verificar**: `day_log.log_date` respeita fuso local, não UTC
- **SP**: SP-92

### TC-I-021 — POST reusa day_log

- **Arquivo**: `test_post_reuses_existing_day_log`
- **Setup**: day_log já existe
- **Verificar**: nenhum novo day_log criado; message.day_log_id aponta pro existente

---

## Testes indiretos — LLM flow (test_llm_flow.py)

Cobrem o pipeline pós-202:

- `test_clarify_intent_creates_assistant_message` (SP-13)
- `test_clarify_does_not_create_business_records` (SP-13)
- `test_unknown_intent_uses_fallback_not_summary`
- `test_llm_error_creates_fallback_assistant_message` (SP-14)
- `test_no_tool_use_response_treated_as_error` (INV-9)
- `test_validation_exhausted_treated_as_error`
- `test_media_is_downloaded_and_forwarded_to_llm`
- `test_login_alone_does_not_touch_anthropic`
- `test_full_flow_visible_via_get_messages`

Ver [`anthropic-integration/test-cases.md`](../anthropic-integration/test-cases.md) para detalhes.

---

## Testes unitários potenciais (gaps)

### TC-U-001 — `local_today` em `services/chat.py`

- Já sugerido em [`daily-snapshot/test-cases.md`](../daily-snapshot/test-cases.md#tc-u-001).

### TC-U-002 — Deduplicação de media_ids

- **Módulo**: `ChatService.post_user_message`
- **Setup**: `media_ids=[u1, u2, u1]`
- **Verificar**: `link_media` chamado com `[u1, u2]` (dedup preservando ordem)

### TC-U-003 — `Cache-Control: no-store` obrigatório

- **Módulo**: `GET /chat/messages` route
- **Verificar**: header sempre presente na response, mesmo com lista vazia

---

## E2E manuais

### TC-E-001 — Jornada completa: registro por chat

- **Persona**: Felix (browser)
- **Passos**:
  1. Login → `/chat`.
  2. Digitar "150g arroz, 90g feijão" + Enter.
  3. Ver mensagem própria imediatamente.
  4. ~4s depois, ver assistant response.
  5. `DayTotalsBar` atualiza kcal_in.

### TC-E-002 — Foto + descrição

- **Passos**: anexar 2 fotos, texto "meu almoço", enviar
- **Resultado**: assistant response com items estimados; badges de `is_estimate`

### TC-E-003 — Timeout LLM (simular)

- **Passos**: mockar Anthropic pra dormir 61s; enviar mensagem
- **Resultado**: após ~65s, assistant SP-14 fallback

### TC-E-004 — Foco após envio

- **Passos**: enviar msg; verificar composer volta pro foco pra próxima
- (Feature UX está em [`chat-composer-ux`](../chat-composer-ux/))

---

## Testes de regressão críticos

- **`test_list_no_anchor_returns_most_recent_not_oldest`** — semântica de "sem cursor". Regressão silenciosa quebra UX.
- **`test_post_rejects_media_from_other_user`** — segurança. Se regredir, cross-user leak.
- **`test_post_creates_day_log_for_user_timezone`** — SP-92. Regressão UTC-based joga registros no dia errado.
- **`test_media_is_downloaded_and_forwarded_to_llm`** (test_llm_flow.py) — se pipeline de media quebrar, foto vira sem foto sem alerta.

## Como rodar

```bash
cd apps/api
# Postgres + MinIO precisam estar rodando: pnpm infra:up

# suite completa
uv run pytest tests/test_chat.py tests/test_llm_flow.py -v

# só teste específico
uv run pytest tests/test_chat.py::test_list_no_anchor_returns_most_recent_not_oldest -v

# coverage
uv run pytest tests/test_chat.py --cov=app/services/chat --cov=app/api/routes/chat --cov-report=term-missing
```
