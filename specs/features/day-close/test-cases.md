# Casos de Teste — Encerramento de dia

> Arquivo principal: `apps/api/tests/test_day_close_report.py` (~700 linhas, 13+ casos).
> Suite cobre: fechamento normal, idempotência, recompute forçado, narrativa, disclaimer, bloqueio de mutação, audit, query_day.

---

## Testes de integração — encerramento

### TC-I-001 — Fechar dia via chat intent

- **Arquivo**: `test_close_day_via_chat_intent`
- **Setup**: LLM fake devolve `intent=close_day`
- **Verificar**:
  - `day_log.status='closed'`
  - `day_log.closed_at` timestamp UTC
  - Assistant message com narrativa + disclaimer
  - `raw_llm_response.dispatch.action='close_day'`

### TC-I-002 — Idempotência: 2ª chamada não muda estado

- **Arquivo**: `test_close_day_idempotent_second_call_does_not_change_state`
- **Setup**: dia já `closed` (`closed_at=T`, narrative=N)
- **Ação**: `POST /days/{date}/close` novamente
- **Verificar**:
  - `closed_at` == T (inalterado)
  - narrative == N (LLM não foi chamada)
  - `was_already_closed=true`
  - Sem novo audit event
- **SP**: SP-101

### TC-I-003 — Recompute forçado antes de congelar

- **Arquivo**: `test_close_forces_recompute_before_freezing`
- **Setup**: manipular DB para deixar snapshot stale
- **Ação**: close
- **Verificar**: snapshot reflete estado real dos records vivos
- **SP**: SP-102, INV-4

---

## Testes de integração — narrativa e disclaimer

### TC-I-010 — Narrativa recebe totais pré-calculados

- **Arquivo**: `test_narrative_receives_precomputed_totals`
- **Verificar**: `call_narrative` mock recebe `totals_payload` com `kcal_in`, `water_ml`, `warning_codes[]` etc.
- **SP**: SP-103, INV-1

### TC-I-011 — Disclaimer sempre presente

- **Arquivo**: `test_narrative_always_ends_with_disclaimer`
- **Verificar**: `snapshot.narrative` termina com `"As estimativas nutricionais são aproximações..."`
- **SP**: SP-104

### TC-I-012 — Disclaimer preservado mesmo com LLM erro

- **Arquivo**: `test_narrative_disclaimer_present_even_on_llm_error`
- **Setup**: `call_narrative` retorna `error='anthropic_error', text=None`
- **Verificar**: fallback textual + disclaimer

### TC-I-013 — Disclaimer não duplica

- **Arquivo**: `test_disclaimer_not_duplicated_if_llm_returns_it`
- **Setup**: LLM devolve texto que já contém disclaimer
- **Verificar**: string final tem disclaimer apenas uma vez

---

## Testes de integração — INV-5 (bloqueio pós-close)

### TC-I-020 — Correção bloqueada em dia fechado

- **Arquivo**: `test_closed_day_blocks_new_food_correction`
- **Setup**: dia fechado; user tenta correct via chat
- **Verificar**: correção não aplica; assistant devolve mensagem informativa

### TC-I-021 — Deleção bloqueada

- **Arquivo**: `test_closed_day_blocks_deletion`
- **Verificar**: idem para delete

### TC-I-022 — Snapshot congelado em leituras

- **Arquivo**: `test_closed_day_snapshot_reads_are_frozen`
- **Setup**: dia fechado; UPDATE direto em nutrient_facts
- **Ação**: `GET /days/{date_fechado}`
- **Verificar**: snapshot NÃO reflete mudança; totals originais preservados

---

## Testes de integração — audit + query

### TC-I-030 — Audit event no fechamento

- **Arquivo**: `test_close_records_audit_event`
- **Verificar**: 1 linha `audit_events` com `action='close'`, `before/after` corretos
- **INV**: INV-10

### TC-I-031 — Query day via chat

- **Arquivo**: `test_query_day_intent_returns_totals_via_chat`
- **Setup**: LLM `intent=query_day`
- **Verificar**: assistant devolve tabela SP-118 com totais atuais

### TC-I-032 — Aproximação com items pendentes

- **Arquivo**: `test_query_day_shows_approx_when_pending_items`
- **Verificar**: prefixo `≈` presente na resposta se `needs_confirmation=true` em algum item

---

## Testes indiretos — `get_today` / `get_by_date`

Cobrem cenários relacionados de leitura:

- `test_get_today_returns_empty_snapshot_when_no_records`
- `test_get_today_reflects_registered_food`
- `test_get_by_date_not_found_returns_404` (SP-91)
- `test_get_by_date_open_day_returns_status_open`
- `test_get_today_uses_user_timezone_not_utc` (SP-92)

---

## Testes E2E manuais

### TC-E-001 — Fluxo completo pelo chat

- **Persona**: Felix (browser)
- **Passos**:
  1. Registrar refeições ao longo do dia.
  2. Clicar "Encerrar dia" no header do chat.
  3. Modal mostra resumo.
  4. Confirmar → ver narrativa como assistant message.
  5. Tentar corrigir item → assistant devolve mensagem informativa (dia fechado).

### TC-E-002 — Encerramento retroativo (SP-155 v1.11)

- **Passos**:
  1. Navegar pra `/day/2026-07-27` (ontem, ainda `open`).
  2. Ver botão "Encerrar dia".
  3. Clicar → confirmar → dia 27 fica `closed`.

### TC-E-003 — Sem narrativa em erro grave

- **Setup**: Anthropic API key inválida
- **Ação**: encerrar dia
- **Resultado**: narrativa fallback textual; disclaimer presente

---

## Testes de regressão críticos

- **`test_close_day_idempotent_second_call_does_not_change_state`** — Const. §29 estrutural.
- **`test_disclaimer_not_duplicated_if_llm_returns_it`** — regressão sutil se `_with_disclaimer` mudar; user pode ver disclaimer 2×.
- **`test_narrative_disclaimer_present_even_on_llm_error`** — compliance; NUNCA pode ser regredido.
- **`test_closed_day_snapshot_reads_are_frozen`** — INV-5 lado de leitura.
- **`test_closed_day_blocks_new_food_correction` + `test_closed_day_blocks_deletion`** — INV-5 lado de escrita.
- **`test_close_forces_recompute_before_freezing`** — INV-4 no momento crítico.

## Como rodar

```bash
cd apps/api

# suíte completa de day close + report
uv run pytest tests/test_day_close_report.py -v

# um teste específico
uv run pytest tests/test_day_close_report.py::test_close_day_idempotent_second_call_does_not_change_state -v

# coverage do service
uv run pytest tests/test_day_close_report.py --cov=app/services/day_close --cov-report=term-missing
```
