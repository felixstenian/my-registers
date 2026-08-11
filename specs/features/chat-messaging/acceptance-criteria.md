# Critérios de Aceitação — Chat e mensagens

## AC-001 — POST só com texto retorna 202 (SP-10, RF-001)

**Dado que** user logado
**Quando** `POST /chat/messages { text: "150g arroz" }`
**Então** 202 com `{message_id: <uuid>, status: "processing"}`
**E** `messages` tem linha `role='user', content='150g arroz', day_log_id=<hoje>`.

**Notas**: `test_chat.py::test_post_text_only_returns_202`.

---

## AC-002 — Sem cookie → 401 (RF-004)

**Dado que** POST sem `access_token`
**Então** 401.

**Notas**: `test_post_requires_auth`.

---

## AC-003 — Empty message rejeitada (RF-003)

**Dado que** `text=""` ou `text=null` e `media_ids=[]`
**Quando** POST
**Então** 422 `code=empty_message`.
**E** whitespace-only text é tratado como vazio (`text.strip() or None`).

**Notas**: `test_post_rejects_empty_message`.

---

## AC-004 — POST com media linka corretamente (SP-11, RF-002)

**Dado que** 2 mídias uploadadas em `POST /media`
**Quando** POST `{text, media_ids: [u1, u2]}`
**Então** 202
**E** `message_media` tem 2 linhas para o message
**E** `GET /chat/messages?after=<pre>` mostra a message com `media[]` de 2 items.

**Notas**: `test_post_with_media_links_them`.

---

## AC-005 — > 4 mídias rejeitadas (RF-004)

**Dado que** `media_ids` com 5 UUIDs válidos
**Quando** POST
**Então** 422 `code=too_many_media`
**E** Pydantic `max_length=4` no schema também barra (defense-in-depth).

**Notas**: `test_post_rejects_more_than_four_media`.

---

## AC-006 — Mídia de outro user rejeitada (RF-005, Const. §21)

**Dado que** media_id existe mas pertence a `other_user`
**Quando** `current_user` faz POST com esse ID
**Então** 422 `code=unknown_media`
**E** DB não é modificado
**E** resposta não indica se ID existe para outro user.

**Notas**: `test_post_rejects_media_from_other_user`.

---

## AC-007 — Listagem cronológica ASC (SP-12, RF-008)

**Dado que** 5 mensagens em ordens variadas
**Quando** `GET /chat/messages?limit=10`
**Então** ordenadas por `created_at ASC`.

**Notas**: `test_list_returns_chronological`.

---

## AC-008 — `after` devolve novas mensagens

**Dado que** cliente tem última message `id=A`
**Quando** `GET /chat/messages?after=A`
**Então** retorna mensagens com `id > A` em ordem ASC.

**Notas**: `test_list_after_returns_newer`.

---

## AC-009 — Sem cursor devolve MAIS RECENTES (RF-009)

**Dado que** 100 messages no DB, limite default 50
**Quando** `GET /chat/messages` sem `after` nem `before`
**Então** retorna as 50 **mais recentes** (não as 50 mais antigas).

**Motivação**: UX de "abri app e vejo o mais recente". Regressão comum: alguém acha que "sem cursor = do início".

**Notas**: `test_list_no_anchor_returns_most_recent_not_oldest`.

---

## AC-010 — `before` devolve mais antigas

**Dado que** cliente tem `id=B` como topo da lista
**Quando** `GET /chat/messages?before=B&limit=50`
**Então** retorna 50 mensagens anteriores a B.

**Notas**: `test_list_before_returns_older`.

---

## AC-011 — Media URLs pré-assinadas (RF-010)

**Dado que** message com media
**Quando** GET
**Então** `media[].url` é URL MinIO com assinatura
**E** URL é válida por ~1h
**E** cliente consegue GET direto no MinIO.

**Notas**: `test_list_media_urls_returned`.

---

## AC-012 — POST cria day_log respeitando fuso (SP-92, RF-007)

**Dado que** `user.timezone='America/Sao_Paulo'`, UTC = 12/jul 04:00Z (= 11/jul 23:00 BRT)
**Quando** POST
**Então** `day_log.log_date = 2026-07-11` (data local, não UTC).

**Notas**: `test_post_creates_day_log_for_user_timezone`.

---

## AC-013 — POST reusa day_log existente

**Dado que** `day_log` de hoje já existe
**Quando** POST subsequente
**Então** message tem `day_log_id = day_log_existente.id`
**E** DB não tem duplicata (UNIQUE `(user_id, log_date)`).

**Notas**: `test_post_reuses_existing_day_log`.

---

## AC-014 — Cache-Control: no-store no GET

**Dado que** cliente faz polling repetido de `GET /chat/messages?after=X`
**Quando** response chega
**Então** header `Cache-Control: no-store` presente
**E** browser NÃO cacheia (bug do 2026-07-19 pré-fix).

---

## AC-015 — Timeout LLM gera fallback SP-14

**Dado que** processor recebe `LLMCallResult(error='anthropic_timeout')`
**Quando** message_processor termina
**Então** cria `messages(role='assistant', content="Não consegui interpretar; pode reformular?")`
**E** `raw_llm_response.error='anthropic_timeout'`
**E** **nenhum** food/water/beverage/activity record criado.

---

## AC-016 — Clarify não cria records (SP-13)

**Dado que** LLM devolve `intent='clarify', clarification_question='qual refeição?'`
**Então** assistant message tem a pergunta
**E** `food_records = 0`, `water_records = 0`, etc.

---

## AC-017 — Ambiguidade completa vs. genérica

**Dado que** LLM devolve `intent='unknown'`
**Então** assistant fallback (sem `user_text_summary` como resposta — sempre texto de reformulação).

**Notas**: `test_llm_flow.py::test_unknown_intent_uses_fallback_not_summary`.

---

## AC-018 — Commit antes de background task (RF-017)

**Dado que** router chama `session.commit()` antes de `add_task`
**Quando** worker abre nova sessão via `session_factory`
**Então** worker enxerga `message` recém-criado (sem race).

**Regressão**: se remover `await session.commit()` explícito, alguns cenários de dep exception podem fazer worker abrir sessão antes do commit implícito da dep.

---

## Cenários de borda

| Cenário | Comportamento esperado |
|---|---|
| Text = " " (só espaço) | `strip()` → None → 422 se sem media |
| Text = 8001 chars | 422 Pydantic (max_length=8000) |
| media_ids com duplicatas | Deduplicado em `link_media` via `list(dict.fromkeys(...))` |
| media_ids com UUID inexistente | 422 unknown_media |
| Concorrência: 2 POST simultâneos do mesmo user | 2 messages, 2 background tasks; sem conflito |
| Server restart durante processing | Message user persiste; assistant não chega; próximo polling não vê. User precisa reenviar. **Sem retry automático no MVP.** |
| Anthropic devolve resposta em > 30s mas < 60s | Assistant chega tardio; sem timeout |
| Cliente sem polling | Assistant persiste no DB; ao reabrir chat, aparece |
| `nutrient_fact_id` só em `log_nutrition_label` | Demais intents: sempre `null` |

## Critérios de não-funcionalidade

| Critério | Threshold | Fonte |
|---|---|---|
| POST P95 | ≤ 300ms | RNF-001 |
| Fim-a-fim P50 texto | ≤ 6s | RNF-002 |
| Fim-a-fim P50 foto | ≤ 12s | RNF-002 |
| GET P95 | ≤ 200ms | RNF-003 |
| Text max_length | 8000 chars | RNF-005 |
| media_ids max | 4 | SP-11 |
| Limit query | 1..200, default 50 | SP-12 |
