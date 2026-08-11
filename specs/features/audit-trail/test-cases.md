# Casos de Teste — Trilha de auditoria

> Audit não tem arquivo de teste próprio — é verificado dentro dos testes de cada feature caller.
> Convenção: todo teste de service que grava audit deve ter ao menos 1 assert em `audit_events`.

---

## Testes existentes que cobrem audit

### TC-I-001 — Audit de criação de food_record

- **Arquivo**: `test_meal_service.py::test_audit_event_recorded_on_create`
- **Verificar**: 1 linha em `audit_events` com `action='create', actor='llm', entity_type='food_record', before=NULL, after≠NULL`

### TC-I-002 — Audit de correção via chat

- **Arquivo**: `test_corrections_deletions.py::test_correction_grava_audit_event`
- **Verificar**: `action='correct', actor='llm', before≠NULL, after≠NULL`

### TC-I-003 — Audit de soft delete

- **Arquivo**: `test_corrections_deletions.py::test_deletion_soft_deletes_and_audits`
- **Verificar**: `action='delete', before≠NULL, after=NULL`

### TC-I-004 — Audit de fechamento de dia

- **Arquivo**: `test_day_close_report.py::test_close_records_audit_event`
- **Verificar**: `entity_type='day_log', action='close', actor='user', before={status:"open"}, after={status:"closed",...}`

---

## Testes unitários de `AuditEventRepository`

### TC-U-001 — `record()` persiste todos os campos

- **Módulo**: `AuditEventRepository.record`
- **Setup**: `session` real (DB); `user_id`, `entity_type`, `entity_id`, `action`, `actor`, `message_id`, `before`, `after` definidos
- **Verificar**: `SELECT FROM audit_events WHERE id=event.id` tem todos os campos corretos

### TC-U-002 — `record()` com `before=None, after=None`

- **Verificar**: INSERT válido; campos JSONB ficam NULL

### TC-U-003 — CHECK constraint action

- **Setup**: tentar inserir `action='reopen'`
- **Verificar**: `IntegrityError` do Postgres (`ck_audit_events_action`)

### TC-U-004 — CHECK constraint actor

- **Setup**: tentar inserir `actor='system'`
- **Verificar**: `IntegrityError` do Postgres (`ck_audit_events_actor`)

### TC-U-005 — FK `message_id` ON DELETE SET NULL

- **Setup**: criar audit com `message_id=M`; deletar mensagem M (hard delete)
- **Verificar**: `audit_events.message_id = NULL` (não cascata deleta o audit)

---

## Testes gaps (não cobertos)

### TC-G-001 — Audit de criação de water_record

- Adicionar assert em `test_hydration_beverage_activity.py` verificando `audit_events` após criação de `water_record`.

### TC-G-002 — Audit de criação de beverage_record

- Idem para `beverage_record`.

### TC-G-003 — Audit de criação de activity_record

- Idem para `activity_record`.

### TC-G-004 — Audit de `confirm` em food_item

- `test_corrections_deletions.py::test_confirm_food_item_clears_needs_confirmation` deveria verificar `audit_events` com `action='confirm'`.

### TC-G-005 — Audit de correção via REST PATCH (`actor='user'`)

- `test_corrections_deletions.py::test_patch_food_item_recomputes_macros` deveria verificar `actor='user'` no audit.

### TC-G-006 — Audit de update de nutrient_fact

- `test_label_catalog.py` deveria verificar `audit_events` após PATCH `/nutrient-facts/{id}`.

### TC-G-007 — Rollback anula audit (atomicidade)

- Simular falha pós-flush no service; verificar que `audit_events` não persiste.

---

## Como verificar manualmente

```bash
cd apps/api

# Listar todos os audits de um usuário (SQL direto)
# pnpm infra:up necessário
psql -U postgres my_registers -c "
  SELECT entity_type, entity_id, action, actor, created_at
  FROM audit_events
  ORDER BY created_at DESC LIMIT 20;
"

# Audits de um entity_id específico
psql -U postgres my_registers -c "
  SELECT * FROM audit_events WHERE entity_id='<uuid>' ORDER BY created_at;
"
```

## Como rodar testes que cobrem audit

```bash
cd apps/api

# Coberturas indiretas existentes
uv run pytest tests/test_meal_service.py::test_audit_event_recorded_on_create -v
uv run pytest tests/test_corrections_deletions.py::test_correction_grava_audit_event -v
uv run pytest tests/test_corrections_deletions.py::test_deletion_soft_deletes_and_audits -v
uv run pytest tests/test_day_close_report.py::test_close_records_audit_event -v
```
