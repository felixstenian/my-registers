# Especificações Técnicas — Remoção de registros

> **Fontes**: `apps/api/app/services/deletion.py` (~185 linhas), `apps/api/app/api/routes/records.py` (DELETE routes, ~linhas 85-120 + `_delete_generic`), `apps/api/app/services/correction.py` (reutiliza `DayClosedError`, `_ensure_day_open`, `_snapshot`), `apps/api/app/services/correction_matcher.py` (reutiliza `TargetMatcher`).

## Escopo técnico

`DeletionService` é deliberadamente enxuto: delega resolução de target ao `TargetMatcher` (compartilhado com `CorrectionService`) e delega verificação de dia ao `_ensure_day_open` importado de `correction.py`. A lógica própria é: (1) check `already_deleted`, (2) `deleted_at=now()`, (3) audit com `after=None`, (4) recompute.

## Endpoints REST

### `DELETE /records/food-items/{entity_id}`
### `DELETE /records/water/{entity_id}`
### `DELETE /records/beverage/{entity_id}`
### `DELETE /records/activity/{entity_id}`

Todos passam por `_delete_generic(path, entity_id, current_user, session)`.

- **Auth**: `access_token` válido.
- **Sucesso** (`200`):
  ```json
  { "kind": "food", "entity_id": "...", "already_deleted": false }
  ```
- **Idempotente** (2ª chamada):
  ```json
  { "kind": "food", "entity_id": "...", "already_deleted": true }
  ```
- **Erros**:
  - `404 not_found` — não existe ou não pertence ao current user.
  - `409 conflict_closed_day` — dia fechado (INV-5).

## Fluxo de dados

### Chat path — `DeletionService.apply_from_llm`

```
IntentDispatcher._handle_delete_record(user, day_log_id, message_id, envelope)
  └─ DeletionService.apply_from_llm(user, day_log_id, message_id, envelope):
        ├─ if envelope.deletion is None → ValidationAppError invalid_deletion_envelope
        ├─ _ensure_day_open(session, day_log_id)       # importado de correction.py
        │     └─ if status='closed' → raise DayClosedError
        ├─ candidate = TargetMatcher.resolve(day_log_id, envelope.deletion.target_hint)
        │     — mesma lógica de correction (AmbiguousTarget, NoTargetFound)
        └─ _soft_delete(user, candidate, message_id):
              ├─ day_log_id = _resolve_day_log_id(entity, kind)
              ├─ if entity.deleted_at is not None → already_deleted=True (no-op)
              ├─ before = _snapshot(entity, kind)       # importado de correction.py
              ├─ entity.deleted_at = datetime.now(UTC)
              ├─ session.flush()
              └─ AuditEventRepository.record(action='delete', actor='llm', before, after=None)

MessageProcessor então chama:
DailyRecomputeService.recompute(day_log_id)     # se not already_deleted
```

### REST path — `DeletionService.delete_by_id`

```
DELETE /records/{path}/{entity_id}
  └─ _delete_generic(path, entity_id, current_user, session):
        ├─ kind = _kind_from_path(path)
        ├─ DeletionService(session).delete_by_id(user, kind, entity_id):
        │     ├─ entity = _load_by_id(session, kind, entity_id, user.id)
        │     │     ├─ FOOD: SELECT FoodItem JOIN FoodRecord WHERE user_id (ownership)
        │     │     │     └─ pré-popula entity.day_log_id via food_record
        │     │     └─ outros: SELECT model WHERE id AND user_id
        │     ├─ if entity is None → ValidationAppError target_not_found → 404
        │     ├─ _ensure_day_open(session, entity.day_log_id)  → 409 se closed
        │     └─ _soft_delete(user, Candidate(kind, entity_id, entity), message_id=None)
        ├─ if DayClosedError → 409 conflict_closed_day
        ├─ if not already_deleted: DailyRecomputeService.recompute(outcome.day_log_id)
        └─ 200 DeletionOut(kind, entity_id, already_deleted)
```

## Modelo de dados

Nenhuma mudança de schema. Feature usa colunas `deleted_at` já existentes:

- `food_items.deleted_at`
- `water_records.deleted_at`
- `beverage_records.deleted_at`
- `activity_records.deleted_at`

### Nova entrada em `audit_events`

```python
AuditEventRepository.record(
    user_id=user.id,
    entity_type="food_item"|"water_record"|"beverage_record"|"activity_record",
    entity_id=entity_id,
    action="delete",
    actor="llm",    # se message_id presente (chat)
    actor="user",   # se message_id=None (REST)
    message_id=message_id | None,
    before=_snapshot(entity, kind),   # estado antes
    after=None,                       # entidade "deixa de existir"
)
```

`_snapshot(entity, kind)` importado de `correction.py`:
- FOOD: `{detected_name, grams, ml, quantity, unit, kcal, protein_g, carbs_g, fat_g, needs_confirmation, source}`
- WATER: `{volume_ml}`
- BEVERAGE: `{detected_name, volume_ml, kcal, source}`
- ACTIVITY: `{detected_name, activity_type, duration_minutes, intensity, kcal_burned, calc_method, met_value}`

## Regras de negócio

1. **Dia fechado bloqueia (INV-5)**: `_ensure_day_open` é chamado antes da decisão de delete — mesmo se item estiver em `already_deleted`, o check de dia aberto roda (mas `already_deleted` já é no-op).
2. **2ª chamada é no-op**: `if entity.deleted_at is not None → return DeletionResult(already_deleted=True)`. **Sem** audit event, **sem** recompute.
3. **Recompute somente em delete efetivo**: `if not outcome.already_deleted: recompute(day_log_id)`.
4. **`after=None` no audit**: semanticamente "entidade deixou de existir". `before` preserva o estado final.
5. **`actor` inferido de `message_id`**: elegante — service não precisa saber de onde vem a chamada; `message_id != None → 'llm'`.
6. **FOOD ownership via JOIN**: `FoodItem` não tem `user_id`; `_load_by_id` faz `SELECT FoodItem JOIN FoodRecord WHERE FoodRecord.user_id = user_id`.
7. **`day_log_id` de FOOD pré-populado no REST**: `_load_by_id` acessa `food_record` e copia `day_log_id` para `entity.day_log_id` para que `_ensure_day_open` e `recompute` funcionem sem query extra.
8. **TargetMatcher compartilhado**: comportamento idêntico ao de `record-correction` — ambiguidade nunca deleta, `NoTargetFound` → assistant informa.
9. **Sem cascade delete**: soft delete em `food_items` não afeta `food_records` (pai). O pai permanece — poderiam existir outros itens no mesmo `food_records`.

## Referências de implementação

- **Service**: [`app/services/deletion.py`](../../../apps/api/app/services/deletion.py) (`DeletionService`, `DeletionResult`, `_soft_delete`, `_load_by_id`, `_resolve_day_log_id`, `_entity_type_for_audit`).
- **Routes**: [`app/api/routes/records.py`](../../../apps/api/app/api/routes/records.py) — `_delete_generic`, `delete_food_item`, `delete_water`, `delete_beverage`, `delete_activity`.
- **Reutilizações de correction**: `DayClosedError`, `_ensure_day_open`, `_snapshot`, `TargetMatcher`, `Candidate`, `TargetKind`.
- **Schemas**: `DeletionIn` em [`app/schemas/llm.py`](../../../apps/api/app/schemas/llm.py) (`target_hint, confidence`), `DeletionOut` em `routes/records.py`.
- **Testes**: [`apps/api/tests/test_corrections_deletions.py`](../../../apps/api/tests/test_corrections_deletions.py) — `test_deletion_soft_deletes_and_audits`, `test_deletion_closed_day_blocks`, `test_delete_food_item_endpoint`, `test_delete_endpoint_idempotent`, `test_delete_endpoint_closed_day_returns_409`, `test_snapshot_recomputes_after_deletion`.
