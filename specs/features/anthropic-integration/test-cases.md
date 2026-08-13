# Casos de Teste — Integração Anthropic

> Localização primária: `apps/api/tests/test_llm_flow.py` (11 casos, integração de pipeline com fake Anthropic).
> Convenção CLAUDE.md: **LLM sempre mockada em testes**; fixtures em `tests/fixtures/anthropic/*.json`.

---

## Testes de integração — `test_llm_flow.py`

### TC-I-001 — Intent `clarify` cria assistant message

- **Arquivo**: `test_clarify_intent_creates_assistant_message`
- **Setup**: fake Anthropic devolve envelope com `intent="clarify", clarification_question="qual foi a refeição?"`
- **Verificar**:
  - Assistant message persistida em `messages` com `role=assistant`
  - `content` = texto da clarification_question (com disclaimer)
  - Nenhum `food_records`, `water_records`, etc. criado

### TC-I-002 — `clarify` não cria records de negócio

- **Arquivo**: `test_clarify_does_not_create_business_records`
- **Verificar**: `SELECT COUNT(*) FROM food_records` = 0 após pipeline

### TC-I-003 — `clarify` sem `clarification_question` usa fallback

- **Arquivo**: `test_clarify_without_question_uses_fallback_not_summary`
- **Setup**: envelope `intent=clarify, clarification_question=None`
- **Verificar**: assistant message tem texto fallback ("Pode reformular?"), NÃO usa `user_text_summary`

### TC-I-004 — `unknown` usa fallback

- **Arquivo**: `test_unknown_intent_uses_fallback_not_summary`
- **Verificar**: mesma semântica do clarify (fallback textual)

### TC-I-005 — LLM error (`anthropic_error`) → fallback

- **Arquivo**: `test_llm_error_creates_fallback_assistant_message`
- **Setup**: fake levanta `anthropic.APIError`
- **Verificar**:
  - `LLMCallResult.error='anthropic_error'`
  - Assistant message persistida com texto SP-14
  - Nenhum record de negócio

### TC-I-006 — `no_tool_use` (INV-9) → fallback

- **Arquivo**: `test_no_tool_use_response_treated_as_error`
- **Setup**: fake devolve `response.content = [text_block]` sem tool_use
- **Verificar**: `error='no_tool_use'`, assistant message fallback

### TC-I-007 — `validation_exhausted` → fallback

- **Arquivo**: `test_validation_exhausted_treated_as_error`
- **Setup**: fake devolve tool_use com JSON malformado (`confidence=1.5`)
- **Verificar**:
  - `LLMEnvelope.model_validate` falha em ambos attempts
  - `error='validation_exhausted'`, `raw_tool_input` preservado
  - Assistant message fallback

### TC-I-008 — Intents não implementados fallham gracefully

- **Arquivo**: `test_not_implemented_intents_fall_back_to_reformulation` (marcado `# pragma: no cover`)
- **Verificar**: intent futuro (não em dispatcher) → fallback

### TC-I-009 — Media é baixada e enviada à LLM

- **Arquivo**: `test_media_is_downloaded_and_forwarded_to_llm`
- **Setup**: mensagem com `media_ids`
- **Verificar**: fake recebe blocos `type=image` no content; bytes base64 presentes

### TC-I-010 — Login não toca Anthropic

- **Arquivo**: `test_login_alone_does_not_touch_anthropic`
- **Setup**: cliente fake configurado, mas rota chamada é `POST /auth/login`
- **Verificar**: fake não recebeu nenhuma chamada

### TC-I-011 — Fluxo completo visível via GET messages

- **Arquivo**: `test_full_flow_visible_via_get_messages`
- **Verificar**: user message + assistant message aparecem em `GET /chat/messages?after=`

---

## Testes de otimização de tokens (potencial em `test_token_optimizations.py`)

### TC-U-001 — Roteamento por complexidade

- **Módulo**: `AnthropicClient._pick_model`
- **Casos**:
  - `has_images=True, text=None` → `self.model`
  - `has_images=True, text="curto"` → `self.model`
  - `has_images=False, text=None` → `self.fallback_model`
  - `has_images=False, text="curto"` → `self.fallback_model`
  - `has_images=False, text="X"*501` → `self.model`

### TC-U-002 — Compressão de imagem

- **Módulo**: `_compress_image`
- **Casos**:
  - PNG 2048×2048 → JPEG ≤ 1024×1024, quality=75
  - JPEG 800×600 (não precisa resize) → bytes originais
  - Bytes corrompidos → bytes originais + log warning
  - PNG com transparência → RGB antes de JPEG

### TC-U-003 — Cache ephemeral está sendo enviado

- **Módulo**: mock da SDK
- **Verificar**: `_client.messages.create` recebe `system=[{cache_control: ephemeral}]` e `tools=[{cache_control: ephemeral}]`

### TC-U-004 — Payload de retry limpa metadata `caller`

- **Módulo**: `_clean_content_for_retry`
- **Setup**: `content = [MockBlock(type='tool_use', id='x', name='record_intent', input={...}, caller='SDK')]`
- **Verificar**: retorno é `[{type:tool_use, id, name, input}]` **sem** `caller`

---

## Testes de contrato de envelope

### TC-U-010 — `extra=forbid` no LLMEnvelope raiz

- **Módulo**: `LLMEnvelope.model_validate({..., 'unknown_field': 'x'})`
- **Verificar**: `ValidationError`

### TC-U-011 — `extra=ignore` em FoodItemIn

- **Módulo**: `FoodItemIn.model_validate({'detected_name': 'x', 'grams_estimate': 100, 'sugars_g': 15, 'pace': 8})`
- **Verificar**: sucesso; `sugars_g` e `pace` descartados

### TC-U-012 — Aliases pt-BR de intensity

- **Módulo**: `ActivityIn._accept_ptbr_intensity`
- **Casos**: `"moderada" → "moderate"`, `"leve" → "light"`, `"vigorosa" → "vigorous"`, `"unknown"`

---

## Testes end-to-end (mocked)

### TC-E-001 — Full log_food com todas as otimizações ativas

- **Passos**:
  1. Configurar client com API key mocada.
  2. Enviar POST `/chat/messages` com foto + texto curto.
  3. Verificar que fake foi chamado com Sonnet (por foto) + cache_control.
  4. Envelope válido processado, food_items persistidos.

### TC-E-002 — Chamada de narrativa em close day

- **Passos**:
  1. Fechar dia via `POST /days/{date}/close`.
  2. Verificar `call_narrative` foi chamado com Sonnet, temperature=0.3.
  3. `daily_snapshots.narrative` populada.
  4. Texto termina com disclaimer (concatenado pelo `DayCloseService`).

---

## Testes de regressão críticos

- **`test_llm_kcal_lies_ignored_backend_calculates`** ([`food-logging`](../food-logging/)) — INV-1 estrutural.
- **`test_no_tool_use_response_treated_as_error`** — INV-9.
- **`test_validation_exhausted_treated_as_error`** — retry limits.
- **`test_media_is_downloaded_and_forwarded_to_llm`** — pipeline de mídia.
- **`_clean_content_for_retry` sem regressão** — se alguém remover, Haiku 4.5 volta a rejeitar payload de retry (bug histórico, `c4fa31e` no CHANGELOG).

## Como rodar

```bash
cd apps/api

# suíte de LLM flow
uv run pytest tests/test_llm_flow.py -v

# um teste específico
uv run pytest tests/test_llm_flow.py::test_no_tool_use_response_treated_as_error -v

# fixtures usadas
ls tests/fixtures/anthropic/

# roteamento + otimizações (se implementados)
uv run pytest tests/test_token_optimizations.py -v

# coverage do cliente
uv run pytest tests/test_llm_flow.py --cov=app/integrations/anthropic --cov-report=term-missing
```
