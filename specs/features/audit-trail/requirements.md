# Requisitos — Trilha de auditoria

> **Rastreabilidade**: Const. Art. III §11 · Invariante INV-10.

## Visão geral

Toda mutação em registro de negócio grava uma linha em `audit_events` com `before`, `after`, `actor` e `message_id`. É uma feature *cross-cutting*: não tem endpoint próprio — é chamada por `AuditEventRepository.record(...)` ao final de cada operação de escrita nos services de food, water, beverage, activity, correção, deleção, confirmação, fechamento de dia, rótulo nutricional e perfil. O `before`/`after` são snapshots JSONB do estado imediato da entidade antes e depois da mutação.

## Requisitos funcionais

| ID | Requisito | Feature que chama | Prioridade |
|---|---|---|---|
| RF-001 | Criação de `food_record` + `food_items` → audit `action='create', entity_type='food_record', actor='llm'`. | [`food-logging`](../food-logging/) | Must Have |
| RF-002 | Criação de `water_record` → audit `action='create', entity_type='water_record', actor='llm'`. | [`water-tracking`](../water-tracking/) | Must Have |
| RF-003 | Criação de `beverage_record` → audit `action='create', entity_type='beverage_record', actor='llm'`. | [`caloric-beverages`](../caloric-beverages/) | Must Have |
| RF-004 | Criação de `activity_record` → audit `action='create', entity_type='activity_record', actor='llm'`. | [`activity-cardio-logging`](../activity-cardio-logging/) | Must Have |
| RF-005 | Correção via chat → audit `action='correct', actor='llm'`; via REST PATCH → `actor='user'`. | [`record-correction`](../record-correction/) | Must Have |
| RF-006 | Soft delete → audit `action='delete', actor='llm'|'user', before=<snapshot>, after=NULL`. | [`record-deletion`](../record-deletion/) | Must Have |
| RF-007 | Confirmação de item (`confirm_items`) → audit `action='confirm', actor='llm'`. | `confirmation.py` | Must Have |
| RF-008 | Fechamento de dia → audit `action='close', entity_type='day_log', actor='user'`. | [`day-close`](../day-close/) | Must Have |
| RF-009 | Cadastro de `nutrient_fact` via rótulo ou manual → audit `action='create', entity_type='nutrient_fact', actor='user'`. | [`nutrition-label-ocr`](../nutrition-label-ocr/), [`manual-catalog-recovery`](../manual-catalog-recovery/) | Must Have |
| RF-010 | Atualização de `nutrient_fact` (PATCH §33) → audit `action='update', entity_type='nutrient_fact', actor='user'`. | [`nutrition-label-ocr`](../nutrition-label-ocr/) | Must Have |
| RF-011 | Atualização de perfil do usuário (`set_profile`) → audit `action='update', entity_type='user', actor='llm'`. | `profile.py` | Should Have |
| RF-012 | `before` = snapshot do estado antes da mutação (ou `NULL` em `create`). `after` = snapshot pós-mutação (ou `NULL` em `delete`). | INV-10 | Must Have |
| RF-013 | `message_id` presente quando ação disparada via chat; `NULL` quando via REST. | INV-10 | Must Have |
| RF-014 | `actor` CHECK IN (`user`, `llm`) — enforçado em schema. | INV-10 | Must Have |
| RF-015 | `action` CHECK IN (`create`, `update`, `delete`, `correct`, `confirm`, `close`) — enforçado em schema. | INV-10 | Must Have |

## Requisitos não funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | Linha de audit gravada via `session.flush()` dentro da mesma transação da mutação — rollback anula ambos. | Atomicidade |
| RNF-002 | Sem endpoint HTTP público de leitura de `audit_events` no MVP — acesso via SQL direto. | Segurança |
| RNF-003 | Escalabilidade: `audit_events` cresce sem bound — sem purge no MVP. | Operacional |

## Restrições e premissas

- **Sem API de leitura no MVP**: `audit_events` é consultável apenas por SQL direto (acesso operacional ou debugging). Não existe `GET /audit-events`.
- **`before`/`after` são snapshots leves**: não duplicam todos os campos — cada service define o subconjunto relevante (ex.: food inclui macros; water só `volume_ml`; day_log inclui `status` e `closed_at`).
- **`entity_id` não tem FK constraint**: evita problema de ON DELETE CASCADE (se entidade for hard-deletada no futuro, audit permanece). Hoje todas as deleções são soft.
- **`AuditEventRepository` é instanciado em todos os services**: sem singleton — cada transação tem sua própria instância vinculada à sessão.
- **`action='confirm'` não está em `AUDIT_ACTIONS` no modelo** — verificar se o model já foi atualizado ou se é bug latente (grep mostra `action="confirm"` em `confirmation.py`).

## Dependências

**Requerido por (todos os services que mutam negócio):**
- [`food-logging`](../food-logging/) — `create` em `food_record`
- [`water-tracking`](../water-tracking/) — `create` em `water_record`
- [`caloric-beverages`](../caloric-beverages/) — `create` em `beverage_record`
- [`activity-cardio-logging`](../activity-cardio-logging/) — `create` em `activity_record`
- [`record-correction`](../record-correction/) — `correct` em food/water/beverage/activity
- [`record-deletion`](../record-deletion/) — `delete` em food/water/beverage/activity
- [`day-close`](../day-close/) — `close` em `day_log`
- [`nutrition-label-ocr`](../nutrition-label-ocr/) — `create`/`update` em `nutrient_fact`
- [`manual-catalog-recovery`](../manual-catalog-recovery/) — `create` em `nutrient_fact`, `correct` em `food_item`
- `confirmation.py` — `confirm` em `food_item`/`beverage_record`
- `profile.py` — `update` em `user`

**Depende de:**
- [`authentication-session`](../authentication-session/) — `user_id` propagado em toda mutação.
