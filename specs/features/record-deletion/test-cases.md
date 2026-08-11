# Casos de Teste — Remoção de registros

> Arquivo principal: `apps/api/tests/test_corrections_deletions.py`.
> Casos de deletion: `test_deletion_soft_deletes_and_audits`, `test_deletion_closed_day_blocks`, `test_delete_food_item_endpoint`, `test_delete_endpoint_idempotent`, `test_delete_endpoint_closed_day_returns_409`, `test_snapshot_recomputes_after_deletion`.

---

## Testes de integração — DeletionService

### TC-I-001 — Soft delete seta `deleted_at` e grava audit

- **Arquivo**: `test_deletion_soft_deletes_and_audits`
- **Setup**: food_item vivo em dia aberto
- **Ação**: `DeletionService._soft_delete(user, candidate, message_id)`
- **Verificar**:
  - `entity.deleted_at != NULL`
  - `audit_events`: `action='delete'`, `before=_snapshot(entity)`, `after=NULL`
  - `actor='llm'` (message_id presente)

### TC-I-002 — Dia fechado bloqueia via chat

- **Arquivo**: `test_deletion_closed_day_blocks`
- **Setup**: `day_log.status='closed'`
- **Ação**: `apply_from_llm`
- **Verificar**: `DayClosedError` levantada; `entity.deleted_at IS NULL`

### TC-I-003 — Snapshot exclui item deletado

- **Arquivo**: `test_snapshot_recomputes_after_deletion`
- **Setup**: food_item `kcal=200` vivo; delete via service; `DailyRecomputeService.recompute`
- **Verificar**: `snapshot.kcal_in` não inclui 200

---

## Testes de integração — DELETE endpoints

### TC-I-010 — DELETE food-items endpoint happy path

- **Arquivo**: `test_delete_food_item_endpoint`
- **Ação**: `DELETE /records/food-items/{id}`
- **Verificar**:
  - 200 `{kind: "food", entity_id: ..., already_deleted: false}`
  - `entity.deleted_at != NULL`
  - Snapshot recomputado

### TC-I-011 — DELETE idempotente (2ª chamada)

- **Arquivo**: `test_delete_endpoint_idempotent`
- **Setup**: item já deletado (`deleted_at != NULL`)
- **Ação**: DELETE de novo
- **Verificar**:
  - 200 `{already_deleted: true}`
  - `deleted_at` não mudou
  - Nenhum audit_event novo
  - Snapshot não recomputado (version inalterado)

### TC-I-012 — DELETE em dia fechado → 409

- **Arquivo**: `test_delete_endpoint_closed_day_returns_409`
- **Setup**: `day_log.status='closed'`
- **Ação**: DELETE endpoint
- **Verificar**: 409 `{code: conflict_closed_day}`

---

## Testes unitários potenciais (gaps)

### TC-U-001 — `_entity_type_for_audit` por kind

- FOOD → `"food_item"`
- WATER → `"water_record"`
- BEVERAGE → `"beverage_record"`
- ACTIVITY → `"activity_record"`

### TC-U-002 — `actor` inferido de `message_id`

- `message_id != None` → `actor='llm'`
- `message_id = None` → `actor='user'`

### TC-U-003 — `_load_by_id` ownership cross-user

- FOOD: item de `other_user` → `None`
- WATER: record de `other_user` → `None`

### TC-U-004 — No-op em `already_deleted`

- `entity.deleted_at = T`; `_soft_delete` roda
- Verificar: `deleted_at` ainda T; nenhum `session.flush`; nenhum audit

---

## Testes E2E manuais

### TC-E-001 — Remover via chat

- **Persona**: Felix
- **Passos**:
  1. Registrar "500 ml de coca-cola".
  2. Enviar "remova o refrigerante".
  3. Ver assistant confirmar; `DayTotalsBar` com kcal reduzida.
  4. Navegar pra `/day`; item não aparece.

### TC-E-002 — Botão "Descartar" no modal (SP-117)

- **Passos**:
  1. Item `needs_confirmation=true` no card.
  2. Clicar "Confirmar" → modal abre.
  3. Clicar "Descartar" → `DELETE /records/food-items/{id}`.
  4. Modal fecha; badge some; totais atualizam.

### TC-E-003 — Tentar remover em dia fechado

- **Passos**:
  1. Fechar dia via "Encerrar dia".
  2. Enviar "remova o arroz".
  3. Assistant: "Dia já fechado; não é possível remover registros."

---

## Testes de regressão críticos

- **`test_deletion_soft_deletes_and_audits`** — INV-10 (audit obrigatório).
- **`test_delete_endpoint_idempotent`** — SP-81 (sem duplo audit, sem duplo recompute).
- **`test_delete_endpoint_closed_day_returns_409`** — INV-5.
- **`test_snapshot_recomputes_after_deletion`** — INV-4 (deleted_at IS NULL filtra).

## Como rodar

```bash
cd apps/api

# apenas casos de deletion
uv run pytest tests/test_corrections_deletions.py -v -k deletion or delete

# suíte completa (inclui correction)
uv run pytest tests/test_corrections_deletions.py -v

# coverage
uv run pytest tests/test_corrections_deletions.py \
  --cov=app/services/deletion \
  --cov=app/api/routes/records \
  --cov-report=term-missing
```
