# Critérios de Aceitação — Trilha de auditoria

## AC-001 — Criação de food_record grava audit (RF-001)

**Dado que** `MealService.create_from_llm` roda com sucesso
**Então** 1 linha em `audit_events`:
- `entity_type='food_record'`
- `entity_id=food_record.id`
- `action='create'`
- `actor='llm'`
- `before=NULL`
- `after={meal_slot, occurred_at, item_ids:[...]}`
- `message_id=<mensagem origem>`

**Verificado por**: `test_meal_service.py::test_audit_event_recorded_on_create`.

---

## AC-002 — Correção via chat grava audit `actor='llm'` (RF-005)

**Dado que** `CorrectionService.apply_from_llm` aplica mudança em food_item
**Então** 1 linha:
- `entity_type='food_item'`
- `action='correct'`
- `actor='llm'`
- `before` com estado anterior dos campos
- `after` com estado posterior

**Verificado por**: `test_corrections_deletions.py::test_correction_grava_audit_event`.

---

## AC-003 — Correção via REST PATCH grava audit `actor='user'` (RF-005)

**Dado que** `PATCH /records/food-items/{id}` bem-sucedido
**Então** 1 linha com `actor='user'`, `message_id=NULL`.

---

## AC-004 — Soft delete grava `before`, `after=NULL` (RF-006, RF-012)

**Dado que** `DeletionService._soft_delete` roda
**Então**:
- `action='delete'`
- `before=_snapshot(entity, kind)` — contém campos do estado pré-delete
- `after=NULL`

**Verificado por**: `test_corrections_deletions.py::test_deletion_soft_deletes_and_audits`.

---

## AC-005 — `actor` inferido corretamente (RF-013, RF-014)

**Dado que** `message_id != None` (chat) → `actor='llm'`
**E** `message_id = None` (REST) → `actor='user'`
**Então** CHECK constraint `actor IN ('user','llm')` nunca viola.

---

## AC-006 — Fechamento de dia grava audit (RF-008)

**Dado que** `DayCloseService.close_date` executa
**Então** 1 linha:
- `entity_type='day_log'`
- `action='close'`
- `actor='user'`
- `before={status:"open"}`
- `after={status:"closed", closed_at:"...", snapshot_version:N}`

**Verificado por**: `test_day_close_report.py::test_close_records_audit_event`.

---

## AC-007 — `action` CHECK constraint (RF-015)

**Dado que** service tenta gravar `action='reopen'` (inexistente)
**Quando** `session.flush()`
**Então** Postgres levanta `IntegrityError` (`ck_audit_events_action`)
**E** transação é desfeita.

---

## AC-008 — Atomicidade: rollback anula audit (RNF-001)

**Dado que** service grava audit + falha depois (ex.: recompute lança exception)
**Quando** transação faz rollback
**Então** linha de audit não persiste.

---

## AC-009 — `message_id` SET NULL em delete de mensagem

**Dado que** audit_event tem `message_id=M`
**E** mensagem M é deletada (hard delete — evento de manutenção)
**Então** `audit_events.message_id` vira `NULL` (FK ON DELETE SET NULL)
**E** audit permanece; só o link com a mensagem é perdido.

---

## AC-010 — `create` tem `before=NULL`

**Dado que** qualquer operação de criação
**Então** `before=NULL` — não há "estado anterior" em entidade nova.

---

## AC-011 — Isolamento por `user_id`

**Dado que** user_A e user_B fazem operações
**Então** `audit_events.user_id` reflete o dono correto de cada entidade.

---

## Cenários de borda

| Cenário | Comportamento esperado |
|---|---|
| `AuditEventRepository.record` chamado com `before=None` e `after=None` | INSERT válido — `before` e `after` são nullable |
| `entity_id` de entidade hard-deletada no futuro | Audit permanece sem FK orphan (sem FK constraint em `entity_id`) |
| `confirm` não estava em `AUDIT_ACTIONS` no model | Verificar se migration adicionou; se não, INSERT falhará em CHECK. Bug latente — ver RF-015 |
| Duas correções no mesmo item | 2 linhas de audit com `created_at` diferentes; histórico completo |
| `after` inclui campos que mudaram e não mudaram | Convenção varia por service — ver tabela em specifications.md |

## Critérios de não-funcionalidade

| Critério | Threshold | Fonte |
|---|---|---|
| Atomicidade | 100% (rollback anula audit) | RNF-001 |
| Cobertura via testes dos callers | Todo service que muta tem teste de audit | INV-10 |
| Sem endpoint HTTP público | 0 rotas expostas | RNF-002 |
