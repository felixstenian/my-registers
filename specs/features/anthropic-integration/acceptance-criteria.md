# Critérios de Aceitação — Integração Anthropic

## AC-001 — `tool_use` obrigatório (INV-9)

**Dado que** Anthropic devolve resposta com blocos `text` mas sem `tool_use`
**Quando** `call_record_intent` processa
**Então** retorna `LLMCallResult(envelope=None, error='no_tool_use')`
**E** nenhum registro é persistido
**E** assistente responde fallback SP-14.

**Notas**: `test_llm_flow.py::test_no_tool_use_response_treated_as_error`.

---

## AC-002 — LLM não contamina cálculo (INV-1)

**Dado que** mock Anthropic devolve envelope com `FoodItemIn(kcal=99999, grams_estimate=150)`
**E** o item tem hit no catálogo (`kcal_100g=130`)
**Quando** pipeline processa
**Então** `food_items.kcal = 195.00` (calculado 130×150/100), **não** 99999
**E** `daily_snapshots.kcal_in` idem.

**Notas**: `test_log_food_flow.py::test_llm_kcal_lies_ignored_backend_calculates`.

---

## AC-003 — Envelope validado com `extra=forbid` no raiz

**Dado que** LLM devolve `tool_input` com campo `nova_chave` no nível raiz
**Quando** `LLMEnvelope.model_validate(tool_input)` roda
**Então** `ValidationError` → dispara retry semântico
**E** se persistir → `error='validation_exhausted'`.

---

## AC-004 — Sub-payloads toleram campos extras (`extra=ignore`)

**Dado que** `FoodItemIn` no envelope tem `sugars_g=15, pace=8.5, caloric_density=high`
**Quando** validate roda
**Então** validação passa
**E** campos extras são **descartados** silenciosamente
**E** `food_items` no DB não guarda esses campos.

**Motivação**: LLM inventa campos comuns; rejeitar levaria a `validation_exhausted` em massa.

---

## AC-005 — Roteamento Sonnet vs Haiku (RF-004)

**Dado que** `user_text=None` (só imagens)
**Então** `_pick_model` devolve `self.model` (Sonnet).

**Dado que** sem imagens, `user_text="200g arroz"` (< 500 chars)
**Então** devolve `self.fallback_model` (Haiku).

**Dado que** sem imagens, `user_text` > 500 chars
**Então** devolve `self.model` (Sonnet).

**Dado que** com imagens, texto qualquer
**Então** devolve `self.model` (Sonnet).

---

## AC-006 — Sem API key configurada → shortcut

**Dado que** `ANTHROPIC_API_KEY=""` (vazio)
**Quando** `call_record_intent(text)` é chamado
**Então** `is_configured=False`
**E** retorna `LLMCallResult(envelope=None, error='anthropic_not_configured')`
**E** **nenhuma** chamada HTTP é feita.

**Notas**: `test_llm_flow.py::test_login_alone_does_not_touch_anthropic`.

---

## AC-007 — Timeout (SP-14, RF-006)

**Dado que** SDK Anthropic levanta `anthropic.APITimeoutError`
**Quando** dentro do loop de attempts
**Então** função retorna `error='anthropic_timeout'` (não tenta retry)
**E** assistente responde SP-14 fallback.

---

## AC-008 — 4xx da API é logado com body (RF-007)

**Dado que** SDK levanta `APIStatusError(status_code=400)`
**Quando** dentro do loop
**Então** logger.warning com `event='anthropic_error', status_code=400, body=<msg>`
**E** retorna `error='anthropic_status_400'`.

---

## AC-009 — Retry semântico com payload limpo (RF-011)

**Dado que** 1ª tentativa: envelope validou fail (LLM devolveu `confidence=1.5`)
**Quando** entra em `attempt=1`
**Então** conversação inclui:
- `{role: assistant, content: <tool_use limpo, SEM 'caller' metadata>}`
- `{role: user, content: [{type: tool_result, tool_use_id, is_error: True, content: "JSON anterior falhou..."}]}`
**E** nova chamada dispara com essa conversação.

**Motivação técnica**: SDK inclui `caller` interno nos blocos `tool_use`; Haiku 4.5 rejeita com 400. `_clean_content_for_retry` remove.

---

## AC-010 — `validation_exhausted` após esgotar retries

**Dado que** attempts 0 e 1 ambos falharam em `LLMEnvelope.model_validate`
**Quando** loop termina
**Então** retorna `LLMCallResult(envelope=None, raw_tool_input=<último>, error='validation_exhausted', validation_errors=<lista>)`
**E** service consumer usa `raw_tool_input` para debug.

**Notas**: `test_llm_flow.py::test_validation_exhausted_treated_as_error`.

---

## AC-011 — Compressão de imagem (RF-008)

**Dado que** foto PNG 3024×4032 (12MB)
**Quando** `_compress_image` roda
**Então** resultado é JPEG ≤ 1024×1024 (redimensionado por thumbnail)
**E** quality=75, optimize=True
**E** log estruturado se falhar (não trava).

**Dado que** foto JPEG 800×600 (já ≤ 1024, já JPEG)
**Então** retorna bytes originais sem re-encode.

---

## AC-012 — Cache ephemeral em system + tools (RF-009)

**Dado que** chamada N=1 do dia para o user
**Quando** log de usage aparece
**Então** `cache_creation_input_tokens > 0, cache_read_input_tokens = 0`.

**Dado que** chamada N=2 nos próximos ~5 min (TTL do cache)
**Então** `cache_read_input_tokens > 0, cache_creation_input_tokens = 0`.

---

## AC-013 — Narrativa: prompt versionado, temperature=0.3 (RF-012)

**Dado que** `call_narrative(totals_payload={kcal_in: 1750, ...})`
**Quando** chama Anthropic
**Então** payload da API tem:
- `model = self.model` (Sonnet)
- `max_tokens = 400`
- `temperature = 0.3`
- `system = [{text: <narrative_v1.md carregado>, cache_control: ephemeral}]`
- `messages = [{role: user, content: [{type: text, text: "Totais do dia (calculados pelo backend, use exatos):\n<json>"}]}]`
- **Sem** `tools`, **sem** `tool_choice`.

**E** retorna `NarrativeResult(text=<texto>, prompt_version='narrative_v1')`.

---

## AC-014 — Narrativa vazia detecta com `empty_narrative`

**Dado que** LLM devolve resposta só com `text=""` ou sem blocos text
**Então** `NarrativeResult(text=None, error='empty_narrative')`
**E** `DayCloseService` faz fallback textual.

---

## AC-015 — Fake client em testes

**Dado que** teste sobrescreve `get_anthropic_client_dep` com fake
**Quando** roda pipeline
**Então** cliente real nunca é instanciado
**E** fixtures em `tests/fixtures/anthropic/*.json` alimentam o fake.

**Convenção CLAUDE.md** "Testes": LLM sempre mockada.

---

## Cenários de borda

| Cenário | Comportamento esperado |
|---|---|
| Content vazio (sem text nem imagens) | Adiciona `"(mensagem vazia)"` — Anthropic exige ≥ 1 bloco. LLM provavelmente devolve `intent=clarify`. |
| Imagem corrompida | Pillow lança `UnidentifiedImageError`; envia bytes originais. |
| PNG com transparência | Convertido para RGB antes de JPEG. |
| `user_text` UTF-8 quebrado | Anthropic lida; nossa camada só passa. |
| Modelo devolve `tool_use` com nome ≠ `record_intent` | `_extract_tool_input` ignora; retorna `no_tool_use`. |
| Multiple `tool_use` blocks na resposta | Só o primeiro com `name=record_intent` é usado. |
| Cache expira entre calls | Próxima chamada re-cria (custo mais alto naquela chamada). |
| Retry semântico e Anthropic retorna erro HTTP na 2ª chamada | Erro propagado; loop termina; `error='anthropic_timeout|error|status_XXX'`. |

## Critérios de não-funcionalidade

| Critério | Threshold | Fonte |
|---|---|---|
| Latência P50 texto puro (fim-a-fim) | ≤ 6s | SP §4.2 |
| Latência P50 texto + 1 foto | ≤ 12s | SP §4.2 |
| Latência P99 | ≤ 20s → fallback SP-14 | SP §4.2 |
| SDK HTTP retries | `max_retries=2` (backoff exponencial em 5xx/429) | RF-006 |
| SDK timeout | 60s | RF-006 |
| Retries semânticos | 1 | RF-011 |
| Cache TTL | ~5 min (ephemeral do Anthropic) | RF-009 |
| Compressão target | ≤ 1024 longest side, JPEG q=75 | RF-008 |
