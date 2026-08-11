# Critérios de Aceitação — Snapshot diário

## AC-001 — `GET /days/today` cria day_log e retorna totals zerados (SP-90, RF-002)

**Dado que** usuário logado sem nenhum registro hoje
**Quando** `GET /days/today`
**Então** 200 com `{ status: "open", closed_at: null, totals: { kcal_in: 0.0, ..., water_ml: 0, other_liquids_ml: 0 }, records: {food:[], water:[], beverage:[], activity:[]}, warnings: [], narrative: null, snapshot_version: 1 }`
**E** existe `day_log` no DB com `log_date = local_today(user.timezone)`.

---

## AC-002 — `GET /days/{date}` 404 se day_log inexiste (SP-91)

**Dado que** nenhum `day_log` existe para `2026-07-01` do usuário
**Quando** `GET /days/2026-07-01`
**Então** 404 `{"code": "day_not_found", "detail": "no day_log for user on 2026-07-01"}`
**E** **nenhum** `day_log` é criado (contrasta com `today`).

---

## AC-003 — Fuso horário local define o dia (SP-92)

**Dado que** `users.timezone = 'America/Sao_Paulo'`
**E** hora UTC atual = `2026-07-13T02:30:00Z`
**Quando** `local_today(user.timezone)` é chamado
**Então** retorna `date(2026, 7, 12)`
**E** `GET /days/today` retorna snapshot do dia 12, não 13.

**Notas**:
- Implementado em `app/services/chat.py::local_today` via `zoneinfo`.

---

## AC-004 — Recompute soma food_items vivos (RF-005, RF-006)

**Dado que** existem 3 `food_items` vivos com kcals 200, 300, 150
**E** 1 `food_items` deletado (`deleted_at != NULL`) com kcal 500
**Quando** `DailyRecomputeService.recompute(day_log_id)` roda
**Então** `daily_snapshots.kcal_in = 650` (não 1150)
**E** `snapshot.protein_g = SUM dos vivos`
**E** todos os macros seguem a mesma regra.

**Notas**:
- `test_daily_recompute.py::test_snapshot_sums_food_items`.
- `test_daily_recompute.py::test_deleted_items_excluded_from_snapshot`.

---

## AC-005 — kcal_in inclui bebidas calóricas (RF-006, INV-3)

**Dado que** food_items somam `kcal=1000`
**E** beverage_records somam `kcal=200` (ex.: café com leite)
**Quando** recompute roda
**Então** `snapshot.kcal_in = 1200`
**E** `snapshot.protein_g` reflete food.protein + beverage.protein
**E** `snapshot.other_liquids_ml = SUM(beverage_records.volume_ml)`
**E** `snapshot.water_ml` **NÃO** inclui volume das bebidas.

---

## AC-006 — water_ml só de water_records (INV-2)

**Dado que** water_records somam 2000 ml
**E** beverage_records somam 300 ml (café)
**Quando** recompute roda
**Então** `snapshot.water_ml = 2000` (INV-2)
**E** `snapshot.other_liquids_ml = 300` (INV-3).

---

## AC-007 — Recompute é idempotente e incrementa version (RF-010)

**Dado que** snapshot v1 já existe
**Quando** `recompute(day_log_id)` roda 3× seguidas sem mudança de dados
**Então** valores finais são iguais aos iniciais
**E** `snapshot.version = 4` (1 inicial + 3 recomputes = ...wait, 1 + 3 = 4).

**Notas**:
- `test_daily_recompute.py::test_recompute_is_idempotent_and_increments_version`.
- `pg_insert.on_conflict_do_update(set_={..., version = version + 1})`.

---

## AC-008 — Novos items refletem imediatamente após recompute (INV-4)

**Dado que** snapshot atual reflete estado A
**Quando** novo `food_item` é criado (via `MealService.create_from_llm`) e recompute roda
**Então** próxima leitura do snapshot mostra kcal atualizado.

**Notas**:
- `test_daily_recompute.py::test_recompute_new_items_reflect_immediately`.

---

## AC-009 — Warnings agregam no_catalog_hit e needs_confirmation (RF-011)

**Dado que** 2 food_items têm `catalog_ref_id IS NULL`
**E** 1 food_item tem `needs_confirmation=True`
**E** 1 activity_record tem `calc_method='reported_by_device'` (não `mets_body_weight`)
**Quando** recompute roda
**Então** `snapshot.warnings` contém 4 entradas: 2 `no_catalog_hit`, 1 `needs_confirmation`, 1 `activity_estimated`
**E** cada uma tem `entity`, `item_id`/`record_id`, `detected_name`.

**Notas**:
- `test_daily_recompute.py::test_warnings_include_missing_catalog_and_needs_confirmation`.

---

## AC-010 — Dia fechado nunca recomputa on-read (INV-5, Const. §28)

**Dado que** `day_log.status = 'closed'` e `snapshot.narrative` já preenchida
**Quando** `GET /days/{data_fechada}`
**Então** snapshot é lido sem chamar `DailyRecomputeService.recompute`
**E** valores retornados são os congelados no fechamento
**E** `narrative` é a narrativa congelada.

**Nota implementação**: `should_recompute = day_log.status == 'open' AND snapshot is None`.

---

## AC-011 — Upsert atomicamente resolve concorrência

**Dado que** duas mensagens do mesmo user chegam simultaneamente e ambas disparam recompute
**Quando** os `pg_insert(...) ON CONFLICT DO UPDATE` executam
**Então** ambos completam sem erro (constraint UNIQUE não quebra)
**E** o snapshot final reflete o estado consolidado após a última mutação
**E** `version` incrementa 2× (não colide).

**Nota**: race de leitura entre computes é aceitável em MVP; para exatidão em multi-user seria necessário advisory lock por `day_log_id`.

---

## AC-012 — `populate_existing=True` evita snapshot cacheado

**Dado que** `session.execute(pg_insert(...).returning(DailySnapshot))` roda
**Quando** SQLAlchemy poderia retornar instância antiga do identity map
**Então** `execution_options(populate_existing=True)` força re-load
**E** valores refletem o novo `payload`, não o cacheado.

**Nota**: sem essa flag, testes na Fase 4 mostraram snapshot "stale" mesmo após update. Não remover.

---

## AC-013 — `records` payload agrupa food por `food_records` com items embutidos

**Dado que** existem 2 `food_records` no dia com 3 items no primeiro e 2 no segundo
**Quando** `_load_food` roda
**Então** `records.food` é lista de 2 objetos `{ id, meal_slot, occurred_at, items: [...] }`
**E** cada `items[i]` inclui macros + micros + `has_catalog: bool` + `is_estimate` + `needs_confirmation` + `source` + `confidence`
**E** ordenados por `FoodRecord.occurred_at ASC`, itens por `FoodItem.id`.

---

## Cenários de borda

| Cenário | Comportamento esperado |
|---|---|
| Sem `day_log` em `today` | `DayLogRepository.get_or_create` cria vazio; totals=0. |
| Snapshot NULL em dia fechado | `_snapshot_to_totals(None)` devolve zeros; cliente não explode. |
| Concorrência de recompute | UPSERT resolve; version pula 2 mas valor final consistente. |
| Todos os items deletados | Snapshot zerado; warnings vazia. |
| Warnings JSONB vazio | Retorna `[]` (não `null`). |
| `activity_records` sem `calc_method` | Warning `activity_estimated` emitido (proteção contra registros manuais mal-formados). |
| Mudança de timezone do user | Impacto só em próximas chamadas de `local_today`; dias já criados mantêm `log_date` original. |

## Critérios de não-funcionalidade

| Critério | Threshold | Fonte |
|---|---|---|
| Latência de `GET /days/today` P95 | ≤ 200ms | `spec.md §4.2` |
| SUM completo do dia | ~10ms (Postgres em Docker, N<30 registros) | Empírico |
| Atomicidade | `INSERT ... ON CONFLICT` numa transação | Const. §10 |
| Isolamento por usuário | 100% das queries filtram via `day_log.user_id` | Const. §21 |
| Cobertura de `DailyRecomputeService` | ≥ 90% | `plan.md §5.3` |
