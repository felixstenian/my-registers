# Critérios de Aceitação — Relatório semanal

## AC-001 — Usa até 7 dias mais recentes fechados (SP-110, INV-8)

**Dado que** 10 dias fechados e 2 dias abertos
**Quando** `GET /weekly`
**Então** `days_included=7` (os 7 mais recentes por `log_date DESC`)
**E** dias abertos **não** aparecem em `per_day`
**E** `warnings=[]`.

**Notas**: `test_generate_uses_up_to_seven_most_recent_closed`.

---

## AC-002 — Menos de 7 dias → `insufficient_history` (SP-110)

**Dado que** 3 dias fechados
**Quando** `GET /weekly`
**Então** `days_included=3`
**E** `warnings=[{code:"insufficient_history", days_available:3}]`.

**Notas**: `test_generate_less_than_seven_days_still_returns`.

---

## AC-003 — Zero dias fechados → relatório transiente

**Dado que** nenhum dia fechado
**Quando** `GET /weekly`
**Então** `days_included=0`, `window_start=null`, `window_end=null`
**E** `warnings=[{code:"insufficient_history", days_available:0}]`
**E** Resposta 200 (não 404)
**E** `id` gerado com `uuid4` mas **não** persistido em `weekly_reports`.

**Notas**: `test_generate_empty_when_no_closed_days`.

---

## AC-004 — Totais e médias determinísticos (SP-111, INV-1)

**Dado que** 3 dias fechados com snapshots `kcal_in=[1000, 1500, 2000]`
**Quando** `_aggregate(snapshots)` roda
**Então**:
- `totals.kcal_in = 4500.0`
- `averages.kcal_in = 1500.0`
**E** `water_ml` e `other_liquids_ml` saem como `int`, demais como `float`.

**Notas**: `test_totals_and_averages_are_deterministic`.

---

## AC-005 — LLM não afeta totais armazenados (INV-1)

**Dado que** mock LLM retorna lixo na narrativa
**Quando** `generate()` roda
**Então** `report.totals.kcal_in` = soma real dos snapshots (não afetado pela LLM)
**E** apenas `report.narrative` contém output da LLM.

**Notas**: `test_llm_lies_do_not_affect_stored_totals`.

---

## AC-006 — `per_day` ordenado ASC (SP-113)

**Dado que** dias fechados em ordem decrescente de `log_date` [D7, D6, ..., D1]
**Quando** `_per_day(closed, snapshots)` roda
**Então** resultado é `[D1, D2, ..., D7]` (mais antigo primeiro).

**Notas**: `test_per_day_ordered_from_oldest_to_newest`.

---

## AC-007 — Dias abertos ignorados (INV-8)

**Dado que** mix de 5 dias fechados e 3 abertos
**Quando** `_fetch_last_closed_days(user_id, limit=7)`
**Então** query filtra `status='closed'` — dias abertos ausentes do resultado.

**Notas**: `test_open_days_are_ignored`.

---

## AC-008 — Idempotência: reusa relatório se snapshot_versions idêntico (SP-112)

**Dado que** relatório gerado na 1ª chamada com `snapshot_versions=[{d1, v3}, {d2, v5}]`
**E** nenhum snapshot mudou entre chamadas
**Quando** 2ª `GET /weekly`
**Então** `result.reused=True`
**E** mesmo `report.id`
**E** `call_weekly_narrative` **não** foi chamado
**E** `report.version` inalterado.

**Notas**: `test_repeated_generate_reuses_same_row`.

---

## AC-009 — Regenera ao mudar versão de snapshot (SP-112)

**Dado que** relatório v1 existe com `snapshot_versions=[{d1, v3}]`
**E** snapshot de d1 foi recomputado → `version=4`
**Quando** `GET /weekly`
**Então** `existing.snapshot_versions != current` → narrativa regenerada
**E** upsert incrementa `report.version` para 2
**E** `generated_at` atualizado.

**Notas**: `test_regenerate_when_snapshot_version_changes`.

---

## AC-010 — Disclaimer sempre presente (Const. §26)

**Dado que** LLM devolve texto sem disclaimer
**Quando** `_with_disclaimer(text)` roda
**Então** `narrative` termina com `"As estimativas nutricionais são aproximações e não substituem acompanhamento médico ou nutricional."`
**E** não duplica se LLM já incluiu.

**Notas**: `test_narrative_always_ends_with_disclaimer`.

---

## AC-011 — `GET /weekly` endpoint integrado

**Dado que** usuário com dias fechados
**Quando** `GET /weekly` via HTTP
**Então** 200 com `WeeklyReportOut` serializado corretamente.

**Notas**: `test_get_weekly_endpoint`.

---

## AC-012 — Relatório via chat (`weekly_summary`)

**Dado que** LLM retorna `intent=weekly_summary`
**Quando** `MessageProcessor._handle_weekly_summary` roda
**Então** assistant message com narrativa + disclaimer
**E** `WeeklyReportService.generate` chamado.

**Notas**: `test_weekly_summary_via_chat`.

---

## AC-013 — Relato via chat sem dias fechados

**Dado que** zero dias fechados, `intent=weekly_summary`
**Quando** roda
**Então** assistant message com `insufficient_history` no conteúdo.

**Notas**: `test_weekly_summary_via_chat_when_no_closed_days`.

---

## AC-014 — Isolamento por usuário (Const. §21)

**Dado que** user_A e user_B ambos com dias fechados
**Quando** `GET /weekly` de user_A
**Então** somente dias e snapshots de user_A são incluídos.

**Notas**: `test_reports_are_isolated_per_user`.

---

## Cenários de borda

| Cenário | Comportamento esperado |
|---|---|
| Dia fechado sem snapshot (anomalia) | `_reduce_snapshot(day, None)` → campos zerados + `version=0`; sem crash |
| `window_start == window_end` (apenas 1 dia fechado) | Válido; `days_included=1` |
| Todos os N campos `null` em snapshot | `_coerce(None)` → `Decimal(0)`; somado como 0 |
| `snapshot_versions` compara dicts; Python `==` em listas de dicts | Deve ser determinístico — sorted por `day_log_id.bytes` antes de montar |
| Narrativa LLM retorna apenas whitespace | Tratado como `text=None` → fallback |
| Novo dia fechado entra na janela mas o mais antigo sai | Nova `window_start`, novo `window_end` → upsert falha na UNIQUE antiga → INSERT nova linha |

## Critérios de não-funcionalidade

| Critério | Threshold | Fonte |
|---|---|---|
| P95 com narrativa nova | ≤ 5s | RNF-003 |
| P95 reuse (sem LLM) | ≤ 200ms | RNF-004 |
| Cobertura `WeeklyReportService` | ≥ 80% | RNF-005 |
| INV-1 (LLM não afeta totais) | 100% | RNF-002 |
| Isolamento por user | 100% | RF-012 |
