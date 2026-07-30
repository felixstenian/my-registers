# Casos de Teste — Relatório semanal

> Arquivo: `apps/api/tests/test_weekly_report.py` (14 casos).
> Todos usam `fake_anthropic` (fixture que mocka `call_weekly_narrative`).

---

## Testes de integração

### TC-I-001 — Zero dias fechados → relatório transiente

- **Arquivo**: `test_generate_empty_when_no_closed_days`
- **Verificar**:
  - `days_included=0`, `window_start=None`, `window_end=None`
  - `warnings=[{code:"insufficient_history", days_available:0}]`
  - `id` não existe em `weekly_reports` DB

### TC-I-002 — Usa os 7 mais recentes

- **Arquivo**: `test_generate_uses_up_to_seven_most_recent_closed`
- **Setup**: 10 dias fechados
- **Verificar**: relatório inclui apenas os 7 com `log_date` mais recente

### TC-I-003 — Menos de 7 → warning

- **Arquivo**: `test_generate_less_than_seven_days_still_returns`
- **Setup**: 3 dias fechados
- **Verificar**: `days_included=3`, `warnings=[{code:"insufficient_history",...}]`

### TC-I-004 — Totais e médias determinísticos

- **Arquivo**: `test_totals_and_averages_are_deterministic`
- **Setup**: snapshots com valores conhecidos
- **Verificar**: `totals.kcal_in == SUM`, `averages.kcal_in == SUM/N`

### TC-I-005 — LLM não afeta totais (INV-1)

- **Arquivo**: `test_llm_lies_do_not_affect_stored_totals`
- **Setup**: fake LLM retorna narrativa com números inventados
- **Verificar**: `report.totals` inalterado; só `narrative` tem texto LLM

### TC-I-006 — Idempotência: reuse sem mudança

- **Arquivo**: `test_repeated_generate_reuses_same_row`
- **Ação**: `generate()` 2x sem fechar novo dia
- **Verificar**: mesmo `report.id`; `call_weekly_narrative` chamado só 1x; `version` inalterado

### TC-I-007 — Regenera ao mudar snapshot_version

- **Arquivo**: `test_regenerate_when_snapshot_version_changes`
- **Setup**: gerar relatório; forçar recompute em snapshot (version++)
- **Verificar**: `report.version` incrementou; nova narrativa gerada

### TC-I-008 — `per_day` ordenado ASC

- **Arquivo**: `test_per_day_ordered_from_oldest_to_newest`
- **Verificar**: `per_day[0].date` < `per_day[-1].date`

### TC-I-009 — Dias abertos ignorados

- **Arquivo**: `test_open_days_are_ignored`
- **Setup**: 5 fechados + 3 abertos
- **Verificar**: `days_included=5`; dias abertos ausentes de `per_day`

### TC-I-010 — Disclaimer presente

- **Arquivo**: `test_narrative_always_ends_with_disclaimer`
- **Verificar**: `narrative.endswith("...acompanhamento médico ou nutricional.")`

### TC-I-011 — Endpoint HTTP

- **Arquivo**: `test_get_weekly_endpoint`
- **Ação**: `GET /weekly`
- **Verificar**: 200 + shape `WeeklyReportOut` correto

### TC-I-012 — Chat `weekly_summary`

- **Arquivo**: `test_weekly_summary_via_chat`
- **Setup**: LLM retorna `intent=weekly_summary`
- **Verificar**: assistant message com narrativa; `WeeklyReportService.generate` chamado

### TC-I-013 — Chat sem histórico

- **Arquivo**: `test_weekly_summary_via_chat_when_no_closed_days`
- **Verificar**: assistant message com menção a histórico insuficiente

### TC-I-014 — Isolamento por usuário

- **Arquivo**: `test_reports_are_isolated_per_user`
- **Setup**: user_A e user_B com dias fechados próprios
- **Verificar**: `GET /weekly` de A não inclui dias de B

---

## Testes unitários potenciais (gaps)

### TC-U-001 — `_aggregate` com snapshots vazios

- `_aggregate([])` → `{kcal_in: 0.0, water_ml: 0, ...}`

### TC-U-002 — `_aggregate` water_ml é int, demais float

- `totals["water_ml"]` é `int`
- `totals["kcal_in"]` é `float`

### TC-U-003 — `_window_bounds` de lista de 1 elemento

- `closed = [day_D]` → `window_start=D`, `window_end=D`

### TC-U-004 — `_reduce_snapshot` com snapshot faltante

- `_reduce_snapshot(day, None)` → todos campos = 0, `version=0`

### TC-U-005 — `snapshot_versions` é determinístico

- Mesma lista de snapshots → mesma `snapshot_versions` em ordens diferentes de `snapshots`

### TC-U-006 — `_with_disclaimer` não duplica

- Texto que já tem o disclaimer → retorna sem duplicar

---

## E2E manuais

### TC-E-001 — Fluxo completo: fechar 7 dias → ver semanal

- **Passos**: fechar 7 dias consecutivos; abrir `/weekly`; ver tabela + narrativa
- **Resultado**: `days_included=7`, valores corretos

### TC-E-002 — Coluna "Dia" linka para `/day/[date]` (SP-155)

- **Passos**: ver `/weekly`; clicar em data na tabela `per_day`
- **Resultado**: navega para `/day/2026-07-21` com detalhe do dia

### TC-E-003 — Chamar `/weekly` 3x rápido (reuse)

- **Passos**: F5 3x em `/weekly` sem fechar novo dia
- **Resultado**: mesma narrativa; sem delay de LLM nas chamadas 2 e 3

---

## Testes de regressão críticos

- **`test_llm_lies_do_not_affect_stored_totals`** — INV-1 estrutural do weekly.
- **`test_open_days_are_ignored`** — INV-8.
- **`test_repeated_generate_reuses_same_row`** — SP-112; se fingerprint quebrar, LLM chamada toda vez.
- **`test_reports_are_isolated_per_user`** — Const. §21.

## Como rodar

```bash
cd apps/api

uv run pytest tests/test_weekly_report.py -v

# um caso específico
uv run pytest tests/test_weekly_report.py::test_llm_lies_do_not_affect_stored_totals -v

# coverage
uv run pytest tests/test_weekly_report.py \
  --cov=app/services/weekly_report \
  --cov-report=term-missing
```
