# Critérios de Aceitação — Remoção de registros

## AC-001 — Soft delete seta `deleted_at` e audita (SP-80, INV-10)

**Dado que** dia aberto com `food_item` vivo
**Quando** `DeletionService._soft_delete` roda
**Então**:
- `entity.deleted_at = datetime.now(UTC)` (não NULL)
- `audit_events` ganha linha `action='delete', before=<snapshot>, after=None`
- `entity.deleted_at` persistido após `session.flush()`

**Notas**: `test_deletion_soft_deletes_and_audits`.

---

## AC-002 — Snapshot recomputa excluindo item deletado (INV-4)

**Dado que** food_item com `kcal=200` é deletado
**Quando** `DailyRecomputeService.recompute` roda
**Então** `SELECT SUM(kcal) ... WHERE deleted_at IS NULL` exclui o item
**E** `daily_snapshots.kcal_in` decrementou 200.

**Notas**: `test_snapshot_recomputes_after_deletion`.

---

## AC-003 — DELETE endpoint idempotente (SP-81)

**Dado que** `food_item.deleted_at != NULL` (já deletado)
**Quando** `DELETE /records/food-items/{id}` de novo
**Então** 200 com `{already_deleted: true}`
**E** `deleted_at` inalterado
**E** sem novo `audit_events`
**E** sem recompute (desnecessário).

**Notas**: `test_delete_endpoint_idempotent`.

---

## AC-004 — Dia fechado bloqueia via REST (SP-82, INV-5)

**Dado que** dia `status='closed'`
**Quando** `DELETE /records/food-items/{id}`
**Então** 409 `{code: conflict_closed_day}`
**E** `entity.deleted_at` inalterado
**E** sem audit.

**Notas**: `test_delete_endpoint_closed_day_returns_409`.

---

## AC-005 — Dia fechado bloqueia via chat

**Dado que** dia `status='closed'`
**Quando** `DeletionService.apply_from_llm` roda
**Então** `_ensure_day_open` levanta `DayClosedError`
**E** assistant informa usuário
**E** sem mutação.

**Notas**: `test_deletion_closed_day_blocks`.

---

## AC-006 — DELETE endpoint happy path (SP-81)

**Dado que** food_item vivo em dia aberto
**Quando** `DELETE /records/food-items/{id}`
**Então** 200 com `{kind: "food", entity_id: ..., already_deleted: false}`
**E** `entity.deleted_at != NULL`
**E** `audit_events` gravado
**E** snapshot recomputado.

**Notas**: `test_delete_food_item_endpoint`.

---

## AC-007 — Entidade de outro user → 404

**Dado que** `food_item` pertence a `other_user`
**Quando** `current_user` faz DELETE
**Então** 404 `not_found` (sem vazar existência).

---

## AC-008 — `actor` inferido de `message_id`

**Dado que** chat: `message_id=<uuid>` → `actor='llm'`
**E** REST: `message_id=None` → `actor='user'`
**Quando** audit gravado
**Então** `actor` correto em cada path.

---

## AC-009 — Mensagens de chat inalteradas após delete

**Dado que** mensagem M originou criação do food_item
**Quando** food_item deletado
**Então** `GET /chat/messages` ainda retorna M com `role='user', content='150g arroz'`
**E** nenhum campo de M muda.

---

## AC-010 — `after=None` no audit

**Dado que** delete executado
**Então** `audit_events.after IS NULL`
**E** `audit_events.before` tem snapshot do estado final (antes do delete).

---

## AC-011 — Recompute não roda em `already_deleted`

**Dado que** 2ª chamada REST em item já deletado
**Então** `_delete_generic` detecta `already_deleted=True`
**E** `DailyRecomputeService.recompute` **não** é chamado
**E** snapshot.version não incrementa.

---

## AC-012 — Water/beverage/activity deletáveis

**Dado que** `water_record` / `beverage_record` / `activity_record` vivos
**Quando** DELETE nos respectivos endpoints
**Então** 200 `{already_deleted: false}`
**E** `deleted_at` setado
**E** recompute exclui contribuição do kind removido.

---

## AC-013 — Ambiguidade via chat → nada deletado

**Dado que** 2 items "refrigerante" no dia
**Quando** chat `target_hint="refrigerante"`
**Então** `AmbiguousTarget` → assistant pede desambiguação
**E** ambos os items com `deleted_at IS NULL`.

---

## Cenários de borda

| Cenário | Comportamento esperado |
|---|---|
| Delete de `food_record` (o agrupador) | Não existe endpoint — soft delete só em `food_items`. `food_records` permanece (pode ter outros items vivos). |
| `target_hint` sem match | `NoTargetFound` → assistant informa "não achei X no seu dia". |
| Item com `deleted_at` future (edge case de clock skew) | `deleted_at is not None` → `already_deleted=True` (não importa valor). |
| Delete via chat em dia fechado mas item já deletado | `_ensure_day_open` roda antes de `_soft_delete` → 409 ou `DayClosedError` mesmo assim. |
| Delete seguido imediatamente de `GET /days/today` | Recompute já foi; snapshot reflete. |

## Critérios de não-funcionalidade

| Critério | Threshold | Fonte |
|---|---|---|
| REST DELETE P95 | ≤ 200ms | RNF-003 |
| INV-5 enforce | 100% | RF-004 |
| Idempotência REST | 100% (sem exceção na 2ª chamada) | RF-003 |
| Audit em toda exclusão efetiva | 100% | RF-006 |
| Recompute somente em exclusão nova | 100% (não se `already_deleted`) | RF-005 |
