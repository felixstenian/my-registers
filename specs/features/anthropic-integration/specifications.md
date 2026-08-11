# Especificações Técnicas — Integração Anthropic

> **Fontes**: `apps/api/app/integrations/anthropic/client.py` (~666 linhas), `apps/api/app/integrations/anthropic/tool_schema.py`, `apps/api/app/integrations/anthropic/prompts/system_v2.md`, `narrative_v1.md`, `weekly_narrative_v1.md`, `apps/api/app/schemas/llm.py` (LLMEnvelope), `docs/token-optimization-plan.md`.

## Interface — 3 métodos públicos

### `call_record_intent(user_text, images=None, max_semantic_retries=1)`

- **Entrada**: `user_text: str | None`, `images: list[tuple[str, bytes]] | None` (mime, raw bytes).
- **Retorno**: `LLMCallResult(envelope, raw_tool_input, tokens_input, tokens_output, model, prompt_version, error, validation_errors)`.
- **Semântica**: classifica o intent, extrai payload estruturado. Usado por [`chat-messaging`](../chat-messaging/) via `MessageProcessor`.
- **Erros possíveis** (`LLMCallResult.error`):
  - `anthropic_not_configured` — sem API key.
  - `anthropic_timeout` — SDK levantou `APITimeoutError`.
  - `anthropic_status_<code>` — 4xx da API.
  - `anthropic_error` — outros erros SDK.
  - `no_tool_use` — resposta sem bloco `tool_use` (viola INV-9).
  - `validation_exhausted` — Pydantic falhou em todas as tentativas.

### `call_narrative(totals_payload)`

- **Entrada**: `totals_payload: dict` — totais já calculados pelo `DayCloseService`.
- **Retorno**: `NarrativeResult(text, tokens_input, tokens_output, model, prompt_version, error)`.
- **Semântica**: gera narrativa curta (~150 palavras) para o dia. Prompt em `narrative_v1.md`.
- **Config**: sempre Sonnet, `max_tokens=400`, `temperature=0.3`.
- **Disclaimer**: `text` NÃO inclui aviso legal — caller (`DayCloseService`) concatena depois para garantir presença (Const. §26).

### `call_weekly_narrative(totals_payload)`

- **Entrada**: `totals_payload: dict` — window_start/end + totals + averages + warning_codes agregados.
- **Retorno**: `NarrativeResult`.
- **Semântica**: análoga; prompt em `weekly_narrative_v1.md`. `max_tokens=500`.

## Contrato do `tool_use`

### Tool schema

Registrado em `tool_schema.py::RECORD_INTENT_TOOL`:

```python
RECORD_INTENT_TOOL = {
    "name": "record_intent",
    "description": "...",
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": [...11 valores...]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "user_text_summary": {"type": "string"},
            "meal_slot": {"type": "string", "enum": [...]},
            "occurred_at_hint": {"type": "string", "format": "date-time"},
            "food_items": {...},
            "water": {...},
            "beverage": {...},
            "activity": {...},
            "correction": {...},
            "deletion": {...},
            "confirmation": {...},
            "nutrition_label": {...},
            "profile_update": {...},
            "clarification_question": {"type": "string"},
        },
        "required": ["intent", "confidence", "user_text_summary"]
    }
}
```

### Envelope Pydantic

`LLMEnvelope` em [`apps/api/app/schemas/llm.py`](../../../apps/api/app/schemas/llm.py):

- **Raiz**: `extra="forbid"` — garante shape estrito.
- **Sub-payloads** (`FoodItemIn`, `BeverageIn`, `ActivityIn`): `extra="ignore"` — LLM inventa campos comuns (`pace`, `heart_rate_avg`, `sugars_g`); rejeitar levaria a `validation_exhausted` em massa.
- **Intents suportados** (11):
  ```
  log_food | log_nutrition_label | log_water | log_beverage | log_activity |
  correct_record | delete_record | confirm_items | query_day | close_day |
  weekly_summary | set_profile | clarify | unknown
  ```

## Fluxo de dados — `call_record_intent`

```
call_record_intent(user_text, images=[])
  ├─ if not is_configured → return error='anthropic_not_configured'
  ├─ chosen_model = _pick_model(has_images=bool(images), user_text)
  │   ├─ has_images → self.model                   (Sonnet 4.6)
  │   ├─ text None ou vazio → self.fallback_model  (Haiku)
  │   ├─ len(text) > 500 → self.model              (Sonnet)
  │   └─ else → self.fallback_model                (Haiku)
  ├─ content = _build_user_content(user_text, images):
  │   ├─ for each image: _compress_image(data, ct) → JPEG base64
  │   │   ├─ Pillow abre; longest-side thumbnail(1024,1024); JPEG q=75
  │   │   └─ if fail → data original (não trava)
  │   ├─ text bloco se user_text
  │   └─ if content vazio → "(mensagem vazia)" (Anthropic exige ≥ 1 bloco)
  ├─ conversation = [{"role": "user", "content": content}]
  ├─ for attempt in range(max_semantic_retries + 1):    # loop de 2× por default
  │   ├─ try:
  │   │   response = await self._client.messages.create(
  │   │       model=chosen_model,
  │   │       max_tokens=1024,
  │   │       temperature=0.1,
  │   │       system=[{type:text, text=system_v2.md, cache_control:ephemeral}],
  │   │       tools=[{**RECORD_INTENT_TOOL, cache_control:ephemeral}],
  │   │       tool_choice={type:tool, name:record_intent},
  │   │       messages=conversation
  │   │   )
  │   ├─ except APITimeoutError → error='anthropic_timeout'
  │   ├─ except APIStatusError → log(status, body); error='anthropic_status_<code>'
  │   ├─ except APIError → log; error='anthropic_error'
  │   ├─ log_usage(input_tokens, output_tokens, cache_creation, cache_read)
  │   ├─ tool_input = _extract_tool_input(response):
  │   │   ├─ percorre response.content
  │   │   └─ retorna dict de bloco type=tool_use, name=record_intent
  │   ├─ if tool_input is None → error='no_tool_use'    # INV-9 falhou
  │   ├─ try envelope = LLMEnvelope.model_validate(tool_input)
  │   ├─ except ValidationError:
  │   │   ├─ if attempt >= max_retries → error='validation_exhausted'
  │   │   ├─ conversation.append(assistant tool_use LIMPO)      # _clean_content_for_retry
  │   │   └─ conversation.append(user tool_result is_error=True + msg com erros)
  │   ├─ return LLMCallResult(envelope=envelope, ...)
  └─ loop terminou → error='validation_exhausted'
```

## Roteamento de modelo

`_pick_model(has_images, user_text)` (linhas 142-156 de `client.py`):

| Cenário | Modelo | Justificativa |
|---|---|---|
| Qualquer foto | `self.model` (Sonnet 4.6) | Visão de qualidade |
| Sem foto, texto None | `self.fallback_model` (Haiku 4.5) | Extração trivial |
| Sem foto, `len(text) ≤ 500` | `self.fallback_model` (Haiku) | Barato, suficiente |
| Sem foto, `len(text) > 500` | `self.model` (Sonnet) | Robustez em extração longa |

## Configurações e variáveis de ambiente

| Variável | Descrição | Padrão | Obrigatória |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Chave (secreta). | — | Sim em prod |
| `ANTHROPIC_MODEL` | Modelo primário. | `claude-sonnet-4-6` | Sim |
| `ANTHROPIC_FALLBACK_MODEL` | Modelo fallback (Haiku). | `claude-haiku-4-5-20251001` | Não |
| `ANTHROPIC_MAX_TOKENS` | max_tokens do intent call. | `1024` | Não |
| `ANTHROPIC_TEMPERATURE` | temperature do intent call. | `0.1` | Não |

Config carregada por `get_settings()` (`app/core/config.py`, pydantic-settings). Cliente via `@lru_cache get_anthropic_client()` → singleton por processo.

## Regras de negócio

1. **LLM só interpreta e narrativa**. Nenhum valor nutricional calculado por ela chega ao DB (Const. Art. II §5, INV-1).
2. **`tool_use` obrigatório**. Se resposta não tem, é `no_tool_use` — assistente responde fallback.
3. **Retry semântico só 1×**. Fase 5 mostrou que 2º retry raramente resolve; prompt já é estrito.
4. **Payload de retry limpo**. Metadata `caller` do SDK derruba Haiku com HTTP 400 — remover em `_clean_content_for_retry`.
5. **`tool_result` obrigatório após `tool_use`**. Haiku 4.5 é estrito; enviar texto solto após tool_use quebra.
6. **Cache ephemeral em system + tool schema**. Cache TTL curto (~5min); ganho quando o mesmo usuário manda várias mensagens seguidas.
7. **Compressão best-effort**. Se Pillow falhar, envia bytes originais.
8. **Narrativa é sobre totais já calculados**. Prompt inclui explicitamente "use exatos"; LLM não recalcula.
9. **Disclaimer obrigatório** (Const. §26) mas concatenado pelo caller do narrative, não pela LLM — garantia estrutural.
10. **Sem streaming**. Assistant message só é persistida quando LLM completa; cliente vê via polling.

## Referências de implementação

- **Cliente**: [`app/integrations/anthropic/client.py`](../../../apps/api/app/integrations/anthropic/client.py) — `AnthropicClient`, `LLMCallResult`, `NarrativeResult`.
- **Tool schema**: [`app/integrations/anthropic/tool_schema.py`](../../../apps/api/app/integrations/anthropic/tool_schema.py) — `RECORD_INTENT_TOOL`.
- **Prompts**: [`app/integrations/anthropic/prompts/system_v2.md`](../../../apps/api/app/integrations/anthropic/prompts/system_v2.md), [`narrative_v1.md`](../../../apps/api/app/integrations/anthropic/prompts/narrative_v1.md), [`weekly_narrative_v1.md`](../../../apps/api/app/integrations/anthropic/prompts/weekly_narrative_v1.md).
- **Envelope Pydantic**: [`app/schemas/llm.py`](../../../apps/api/app/schemas/llm.py).
- **Config**: [`app/core/config.py`](../../../apps/api/app/core/config.py) (`anthropic_*` fields), fábrica em [`app/api/deps.py`](../../../apps/api/app/api/deps.py) (`get_anthropic_client_dep`).
- **Otimizações**: [`docs/token-optimization-plan.md`](../../../docs/token-optimization-plan.md).
- **ADR**: [`specs/001-mvp-registro-diario/research.md`](../../001-mvp-registro-diario/research.md) — ADR-002 (Anthropic escolha + tool_use).
- **Testes**: [`apps/api/tests/test_llm_flow.py`](../../../apps/api/tests/test_llm_flow.py) (11 casos + fixtures em `tests/fixtures/anthropic/*.json`).
