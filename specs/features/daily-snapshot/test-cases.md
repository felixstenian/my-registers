# Casos de Teste — Snapshot diário

> Localização: `apps/api/tests/test_daily_recompute.py` (5 casos) + integração via `test_log_food_flow.py`, `test_day_close_report.py`, `test_hydration_beverage_activity.py`.
> Rodar: `uv run pytest tests/test_daily_recompute.py -v`

---

## Testes de integração (DB real)

### TC-I-001 — Snapshot soma food_items

- **Arquivo**: `test_daily_recompute.py::test_snapshot_sums_food_items`
- **Setup**: 3 food_items ativos com kcal={200,300,150}
- **Ação**: `DailyRecomputeService.recompute(day_log_id)`
- **Verificar**:
  - `snapshot.kcal_in == 650`
  - macros somados (protein, carbs, fat, fiber)
  - micros somados (sodium, calcium, iron, potassium)
  - `snapshot.version == 1` (primeiro compute)
- **RF**: RF-005, RF-006

### TC-I-002 — Recompute idempotente e incrementa version

- **Arquivo**: `test_recompute_is_idempotent_and_increments_version`
- **Setup**: snapshot já v1
- **Ação**: recompute 3× em seguida, sem mutação
- **Verificar**:
  - Valores kcal/macros idênticos entre chamadas
  - `version` incrementa a cada chamada (1 → 2 → 3 → 4)
  - `computed_at` sobe monotonicamente
- **RF**: RF-010, RNF-002

### TC-I-003 — Novos items refletem imediatamente

- **Arquivo**: `test_recompute_new_items_reflect_immediately`
- **Setup**: snapshot v1 estabelecido, novo food_item criado com kcal=100
- **Ação**: recompute
- **Verificar**: `snapshot.kcal_in += 100`, `version` incrementou
- **RF**: RF-005, INV-4

### TC-I-004 — Items deletados excluídos

- **Arquivo**: `test_deleted_items_excluded_from_snapshot`
- **Setup**: 2 items vivos + 1 item soft-deleted
- **Ação**: recompute
- **Verificar**:
  - Item deletado **não** contribui para kcal
  - `SUM` filtra `deleted_at IS NULL`
  - Deleção reversa (setar `deleted_at=NULL`) + recompute → item volta
- **RF**: RF-005

### TC-I-005 — Warnings agregam catalog + confirmation

- **Arquivo**: `test_warnings_include_missing_catalog_and_needs_confirmation`
- **Setup**:
  - 1 food_item com `catalog_ref_id IS NULL`
  - 1 food_item com `needs_confirmation = True`
  - 1 beverage_record com `catalog_ref_id IS NULL`
  - 1 activity_record com `calc_method='reported_by_device'`
- **Ação**: recompute
- **Verificar**: `snapshot.warnings` tem 4 entradas com `entity` + `item_id`/`record_id` + `detected_name`
- **RF**: RF-011

---

## Testes de integração indireta

### TC-I-010 — Snapshot atualiza após `log_food` end-to-end

- **Arquivo**: `test_log_food_flow.py::test_log_food_end_to_end_persists_and_recomputes`
- **Verificar**: após `POST /chat/messages` que dispara `log_food`, `GET /days/today.totals.kcal_in > 0`
- **INV**: INV-4

### TC-I-011 — Snapshot inclui água + bebida + atividade

- **Arquivo**: `test_hydration_beverage_activity.py::*`
- **Verificar**:
  - Adicionar `WaterRecord(500ml)` → `snapshot.water_ml=500`
  - Adicionar `BeverageRecord(volume_ml=200, kcal=50)` → `snapshot.other_liquids_ml=200`, `kcal_in+=50`
  - Adicionar `ActivityRecord(kcal_burned=300)` → `snapshot.kcal_out=300`, `kcal_balance=kcal_in-300`
- **INV**: INV-2, INV-3

### TC-I-012 — Snapshot congelado em dia fechado (INV-5)

- **Arquivo**: `test_day_close_report.py::*`
- **Ação**: fechar dia; alterar registro (bug? deveria ser 409 — ver `record-correction`); recompute NÃO roda em read subsequente
- **Verificar**: `GET /days/{data_fechada}` retorna valores congelados no fechamento; `narrative` presente
- **INV**: INV-5

---

## Testes unitários potenciais (gaps)

### TC-U-001 — `local_today` com timezone

- **Módulo**: `app/services/chat.py::local_today`
- **Casos**:
  - `local_today('America/Sao_Paulo')` em UTC=`2026-07-13T02:00Z` → `date(2026, 7, 12)`
  - `local_today('UTC')` mesmo instante → `date(2026, 7, 13)`
  - `local_today('Pacific/Auckland')` mesmo instante → data diferente

### TC-U-002 — `_snapshot_to_totals(None)` devolve zeros

- **Módulo**: `app/services/day_query.py::_snapshot_to_totals`
- **Entrada**: `None`
- **Verificar**: shape completo com valores 0.0 / 0 (nunca `NULL`)

### TC-U-003 — `_dec(None)` → None, `_dec(Decimal(...))` → float

- **Módulo**: `app/services/day_query.py::_dec`
- **Verificar**: sem tipo mixin no serialization

### TC-U-004 — `DayQueryService._build` com `allow_recompute=False`

- **Módulo**: `DayQueryService`
- **Setup**: dia aberto SEM snapshot
- **Ação**: `get_by_date(allow_recompute=False)`
- **Verificar**: snapshot fica `None`, retorna totals zerados via `_snapshot_to_totals(None)` (não recomputa)

---

## E2E manuais

### TC-E-001 — Registro em UTC-diferente-de-BR e ver no dia certo

- **Persona**: Felix (VPN pra outra timezone)
- **Passos**: mudar timezone do device pra `America/New_York` (UTC-4), mas manter `users.timezone='America/Sao_Paulo'`
- **Resultado esperado**: mesmo assim, `GET /days/today` retorna dia local Brasil, não NY

### TC-E-002 — Deletar item pelo chat, ver total cair

- **Passos**: registrar "café" (kcal 50), ver total kcal, mandar "remova o café", ver total kcal cair
- **Resultado esperado**: snapshot atualizado sem F5

### TC-E-003 — Fechar dia, alterar catálogo, dia fechado permanece

- **Passos**: registrar refeição em dia D, fechar D, atualizar `nutrient_facts` do arroz (kcal 130 → 200), recompute manual via CLI de dia D
- **Resultado esperado**: `GET /days/{D}` continua mostrando snapshot congelado (INV-5); recompute em dia fechado é no-op ou erro

---

## Testes de regressão críticos

- **`test_deleted_items_excluded_from_snapshot`** — se algum `.where()` esquecer `deleted_at IS NULL`, snapshot infla; usuário perde confiança.
- **`test_recompute_is_idempotent_and_increments_version`** — se `on_conflict_do_update` regredir para `do_nothing` ou perder `version + 1`, cliente perde signal de refresh.
- **INV-2 / INV-3 em `test_hydration_beverage_activity`** — se alguém confundir `water_ml` com `other_liquids_ml`, quebra premissa da Const. Art. IV.
- **`populate_existing=True`** — regressão vista na Fase 4; se removida, cache do SQLAlchemy vaza para respostas subsequentes.

## Como rodar

```bash
cd apps/api

# 5 casos principais
uv run pytest tests/test_daily_recompute.py -v

# um caso específico
uv run pytest tests/test_daily_recompute.py::test_warnings_include_missing_catalog_and_needs_confirmation -v

# coverage do recompute + query
uv run pytest tests/test_daily_recompute.py tests/test_day_close_report.py \
  --cov=app/services/daily_recompute --cov=app/services/day_query \
  --cov-report=term-missing
```
