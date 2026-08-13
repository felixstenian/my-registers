# Especificações Técnicas — Relatório semanal

> **Fontes**: `apps/api/app/services/weekly_report.py` (~318 linhas), `apps/api/app/api/routes/weekly.py`, `apps/api/app/models/weekly_report.py`, `apps/api/app/schemas/weekly.py`.

## Endpoint

### `GET /weekly`

- **Auth**: `access_token` válido.
- **Body**: vazio.
- **Sucesso** (`200`, `WeeklyReportOut`):
  ```json
  {
    "id": "uuid",
    "window_start": "2026-07-21",
    "window_end": "2026-07-27",
    "days_included": 7,
    "totals": { "kcal_in": 12250.5, "kcal_out": 2100.0, "water_ml": 14000, ... },
    "averages": { "kcal_in": 1750.07, "kcal_out": 300.0, "water_ml": 2000, ... },
    "per_day": [
      { "date": "2026-07-21", "closed_at": "...", "kcal_in": 1820.0, ..., "version": 5 },
      ...
    ],
    "warnings": [],
    "narrative": "Semana equilibrada com...\n\nAs estimativas nutricionais...",
    "generated_at": "2026-07-28T10:00:00Z",
    "version": 1
  }
  ```
- **Com `insufficient_history`** (< 7 dias):
  ```json
  {
    "days_included": 3,
    "warnings": [{"code": "insufficient_history", "days_available": 3}],
    ...
  }
  ```
- **Zero dias fechados**:
  ```json
  {
    "window_start": null,
    "window_end": null,
    "days_included": 0,
    "warnings": [{"code": "insufficient_history", "days_available": 0}],
    "narrative": "Semana consolidada...\n\nAs estimativas..."
  }
  ```

## Modelo de dados

### `weekly_reports`

Modelo: [`apps/api/app/models/weekly_report.py`](../../../apps/api/app/models/weekly_report.py)

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | UUID | PK |
| `user_id` | UUID FK users(id) ON DELETE CASCADE | Owner |
| `window_start` | date NULL | Menor `log_date` dos dias incluídos |
| `window_end` | date NULL | Maior `log_date` dos dias incluídos |
| `days_included` | integer NOT NULL | Count dos dias fechados na janela |
| `totals` | JSONB NOT NULL DEFAULT `{}` | Soma de todos os campos numéricos |
| `averages` | JSONB NOT NULL DEFAULT `{}` | Média (`totals/N`) de todos os campos |
| `per_day` | JSONB NOT NULL DEFAULT `[]` | Lista de `{date, closed_at, kcal_in, ..., version}` ASC |
| `warnings` | JSONB NOT NULL DEFAULT `[]` | `[{code:"insufficient_history", days_available:N}]` |
| `snapshot_versions` | JSONB NOT NULL DEFAULT `[]` | `[{day_log_id, version}]` ordenado — fingerprint de idempotência |
| `narrative` | text NULL | Texto + disclaimer |
| `generated_at` | timestamptz NOT NULL | Última geração |
| `version` | integer NOT NULL DEFAULT 1 | Incrementa a cada upsert com mudança |

**Constraint única**: `uq_weekly_reports_user_window(user_id, window_start, window_end)`.

### `_TOTAL_FIELDS` agregados

```python
("kcal_in", "kcal_out", "kcal_balance", "protein_g", "carbs_g", "fat_g",
 "fiber_g", "sodium_mg", "calcium_mg", "iron_mg", "potassium_mg",
 "water_ml", "other_liquids_ml")
```

`water_ml` e `other_liquids_ml` → `int`; demais → `float`.

## Fluxo de dados

### `WeeklyReportService.generate(user)`

```
GET /weekly
  ├─ Depends(get_current_user, get_session, get_anthropic_client_dep)
  └─ WeeklyReportService.generate(user):
        ├─ closed = _fetch_last_closed_days(user_id, limit=7):
        │     SELECT day_logs WHERE user_id AND status='closed'
        │     ORDER BY log_date DESC LIMIT 7
        ├─ window_start, window_end = _window_bounds(closed)  → min/max(log_date)
        ├─ snapshots = _fetch_snapshots([d.id for d in closed])
        ├─ if len(closed) < 7 → warnings.append({code:"insufficient_history",...})
        ├─ totals, averages = _aggregate(snapshots):
        │     SUM e AVG de cada campo via Decimal; output float ou int por campo
        ├─ per_day = _per_day(closed, snapshots):
        │     sort closed ASC por log_date → [_reduce_snapshot(d, snap|None)]
        ├─ snapshot_versions = [{day_log_id, version} sorted by day_log_id.bytes]
        ├─ if not closed:
        │     return WeeklyReportResult(transient WeeklyReport em memória, reused=False)
        ├─ existing = _find_existing(user_id, window_start, window_end)
        ├─ if existing and existing.snapshot_versions == snapshot_versions:
        │     return WeeklyReportResult(existing, reused=True)    # SP-112
        ├─ narrative = _generate_narrative(payload):
        │     if not anthropic.is_configured → _FALLBACK_NARRATIVE
        │     else: call_weekly_narrative({window_start, window_end, totals, averages, warning_codes})
        ├─ narrative_full = _with_disclaimer(narrative)
        ├─ pg_insert(WeeklyReport).values(**payload)
        │     .on_conflict_do_update(
        │         index_elements=["user_id","window_start","window_end"],
        │         set_={...campos exceto user_id..., version = version + 1}
        │     ).returning(WeeklyReport).execution_options(populate_existing=True)
        └─ return WeeklyReportResult(report, reused=False)
```

### Via chat (intent `weekly_summary`)

```
POST /chat/messages "resumo semanal"
  ├─ LLM → intent=weekly_summary
  └─ MessageProcessor._handle_weekly_summary(user, message_id):
        ├─ WeeklyReportService.generate(user)
        └─ assistant message = result.report.narrative (+ totals tabela SP-118)
```

## Regras de negócio

1. **INV-8**: `status='closed'` é condição sine qua non. Dias abertos são invisíveis para o semanal.
2. **Determinismo dos cálculos (INV-1)**: `_aggregate` usa `Decimal` para somas exatas; `_out_type` converte pra `float`/`int` apenas na serialização. LLM só recebe o payload já calculado.
3. **Idempotência por fingerprint**: `snapshot_versions` é lista de `{day_log_id:str, version:int}` ordenada por `day_log_id.bytes` (consistente entre chamadas). Comparação por igualdade direta (`==`).
4. **Relatório transiente em zero dias**: sem persistência — `UNIQUE(user_id, NULL, NULL)` é inválido em Postgres. ID é gerado com `uuid.uuid4()` na memória; cliente recebe mas não pode referenciar depois.
5. **Upsert com `populate_existing=True`**: mesma necessidade do `DailyRecomputeService` — evita snapshot cacheado no identity map do SQLAlchemy.
6. **`_window_bounds`**: `min(dates)` = `window_start`, `max(dates)` = `window_end`.
7. **`_per_day` defende snapshot faltante**: `_reduce_snapshot(day_log, None)` → campos zerados + `version=0`. Dia fechado sem snapshot é anomalia mas não crashamos.
8. **`warning_codes` na payload da narrativa**: apenas códigos, sem IDs internos. LLM não precisa de referências.
9. **Payload LLM**: `{window_start, window_end, totals, averages, warning_codes}`. **Não** inclui `per_day` bruto (reduz tokens, LLM nao precisa de detalhe diário para narrativa semanal).
10. **`version` do relatório incrementa em cada regeneração** (`version = version + 1` no ON CONFLICT). Reuso não incrementa.

## Configurações e variáveis de ambiente

| Variável | Descrição | Padrão |
|---|---|---|
| `ANTHROPIC_API_KEY` | Para `call_weekly_narrative`. | — |
| `ANTHROPIC_MODEL` | Sonnet 4.6 (modelo principal; narrativa semanal sempre usa primary). | `claude-sonnet-4-6` |

## Referências de implementação

- **Service**: [`app/services/weekly_report.py`](../../../apps/api/app/services/weekly_report.py) (`WeeklyReportService`, `WeeklyReportResult`, `_aggregate`, `_per_day`, `_window_bounds`, `_with_disclaimer`, `_TOTAL_FIELDS`).
- **Route**: [`app/api/routes/weekly.py`](../../../apps/api/app/api/routes/weekly.py).
- **Model**: [`app/models/weekly_report.py`](../../../apps/api/app/models/weekly_report.py).
- **Schema**: [`app/schemas/weekly.py`](../../../apps/api/app/schemas/weekly.py) (`WeeklyReportOut`).
- **Anthropic**: `AnthropicClient.call_weekly_narrative(payload)` — usa `weekly_narrative_v1.md`.
- **Testes**: [`apps/api/tests/test_weekly_report.py`](../../../apps/api/tests/test_weekly_report.py) (14 casos — todos os SPs + INV-1 + INV-8 + reuse + chat + isolamento).
