# Requisitos — Relatório semanal

> **Rastreabilidade**: SP-110..SP-113 em [`spec.md §3.12`](../../001-mvp-registro-diario/spec.md#312-relatório-semanal) · Const. §30 · Invariantes INV-1, INV-8.

## Visão geral

`GET /weekly` agrega os últimos 7 `day_logs` com `status='closed'` do usuário, calcula totais e médias determinísticos via SQL (INV-1 — LLM não recalcula), gera narrativa via `AnthropicClient.call_weekly_narrative` sobre esses números e persiste em `weekly_reports` via upsert atômico por `UNIQUE(user_id, window_start, window_end)`. Idempotente (SP-112): se as versões dos snapshots participantes não mudaram, devolve o mesmo relatório sem regenerar narrativa. Disparado também via chat (intent `weekly_summary`).

## Requisitos funcionais

| ID | Requisito | SP | Prioridade |
|---|---|---|---|
| RF-001 | `GET /weekly` retorna os últimos 7 `day_logs` com `status='closed'`, ignorando dias abertos. | SP-110, INV-8 | Must Have |
| RF-002 | Menos de 7 dias fechados → retorna os disponíveis + `warnings: [{code:"insufficient_history", days_available:N}]`. | SP-110 | Must Have |
| RF-003 | Zero dias fechados → retorna relatório transiente (não persistido) com `days_included=0` e `insufficient_history`. | SP-110 | Must Have |
| RF-004 | Totais e médias calculados via soma sobre `daily_snapshots` — nunca pela LLM (SP-111, INV-1). | SP-111, INV-1 | Must Have |
| RF-005 | `per_day` ordenado do mais antigo ao mais recente (SP-113). | SP-113 | Should Have |
| RF-006 | Idempotência por `snapshot_versions`: se os snapshots participantes têm as mesmas `version` desde a última geração, devolve o mesmo `weekly_reports.id` sem chamar LLM nem regerar narrativa. | SP-112 | Should Have |
| RF-007 | Se os snapshots mudaram (versão incrementou por recompute), regenera narrativa e faz upsert com `version+1`. | SP-112 | Should Have |
| RF-008 | Narrativa gerada via `AnthropicClient.call_weekly_narrative(payload)` com `totals`, `averages`, `window_start/end`, `warning_codes`. LLM recebe só dados calculados — nunca listas de registros brutos. | SP-111 | Must Have |
| RF-009 | Se LLM falhar, usar `_FALLBACK_NARRATIVE` textual; disclaimer (`_with_disclaimer`) sempre presente. | SP-14, Const. §26 | Must Have |
| RF-010 | Upsert atômico via `pg_insert ... ON CONFLICT(user_id, window_start, window_end) DO UPDATE ... version+1 ... RETURNING` com `populate_existing=True`. | SP-112 | Must Have |
| RF-011 | Relatório via chat (intent `weekly_summary`) dispara `WeeklyReportService.generate` e retorna narrativa como assistant message. | SP-110 | Should Have |
| RF-012 | Relatórios isolados por usuário — `user_id` em todas as queries. | Const. §21 | Must Have |

## Requisitos não funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | Totais e médias determinísticos — mesmos snapshots → mesmos valores, bit-a-bit. | Correção (INV-1) |
| RNF-002 | LLM não afeta `totals`/`averages`/`per_day` armazenados — mesmo se LLM retornar lixo. | INV-1 |
| RNF-003 | Latência P95 (com narrativa nova): ≤ 5s (narrativa ~2-3s + agregação ~50ms). | Performance |
| RNF-004 | Latência P95 (reuse): ≤ 200ms (sem LLM). | Performance |
| RNF-005 | Cobertura mínima `WeeklyReportService`: 80% (segue padrão geral de services). | Qualidade |

## Restrições e premissas

- **INV-8 é literal**: `status='closed'` — dias abertos não entram, mesmo que tenham registros.
- **`per_day` lida com snapshot faltante**: dia fechado sem snapshot (anomalia) → campos zerados + `version=0` — sem crash.
- **Zero dias fechados → relatório transiente**: não persiste porque `UNIQUE(user_id, NULL, NULL)` não funciona em Postgres (NULL != NULL). Retorna `WeeklyReport` em memória.
- **Idempotência por `snapshot_versions`**: lista de `{day_log_id, version}` ordenada por `day_log_id.bytes`. Se idêntica ao último relatório → reuse.
- **`water_ml` e `other_liquids_ml` são `int`** (ml); demais campos `float` — `_is_float_field` controla o tipo de saída.
- **Reabertura de dia não existe no MVP** (Const. §28) → window é praticamente estável; `snapshot_versions` só muda se um recompute externo rodar após o fechamento (impossível em MVP).

## Dependências

**Depende de:**
- [`day-close`](../day-close/) — produz `status='closed'`; sem dias fechados, `weekly_report` é vazio.
- [`daily-snapshot`](../daily-snapshot/) — `daily_snapshots` são a fonte de totais.
- [`anthropic-integration`](../anthropic-integration/) — `call_weekly_narrative(payload)`.
- [`authentication-session`](../authentication-session/) — `Depends(get_current_user)`.
- [`chat-messaging`](../chat-messaging/) — intent `weekly_summary` via `MessageProcessor`.

**Requerido por:**
- [`daily-detail-view`](../daily-detail-view/) — `/weekly` tem coluna "Dia" linkando para `/day/[date]` (SP-155).
