# Requisitos — Remoção de registros

> **Rastreabilidade**: SP-80..SP-82 em [`spec.md §3.9`](../../001-mvp-registro-diario/spec.md#39-remoção-de-registros) · Const. Art. III §11, Art. VIII §28 · Invariantes INV-4, INV-5, INV-10.

## Visão geral

Soft delete de registros (food_items, water_records, beverage_records, activity_records) via duas superfícies: **chat** (intent `delete_record` → `TargetMatcher` + `DeletionService.apply_from_llm`) e **REST** (`DELETE /records/{tipo}/{id}` — idempotente por SP-81). Toda remoção seta `deleted_at=now()`, grava `audit_events(action='delete', before, after=NULL)` e re-executa `DailyRecomputeService.recompute` (INV-4 — snapshot exclui `deleted_at IS NOT NULL`). 2ª chamada no mesmo registro é no-op silencioso (`already_deleted=True`, sem audit, sem recompute). Dia `status='closed'` bloqueia (INV-5) com 409 via REST ou `DayClosedError` via chat.

## Requisitos funcionais

| ID | Requisito | SP | Prioridade |
|---|---|---|---|
| RF-001 | Remoção via chat: "remova o refrigerante do almoço" → `intent=delete_record`, `TargetMatcher` resolve `target_hint`, seta `deleted_at=now()`, snapshot recomputa. | SP-80 | Must Have |
| RF-002 | Remoção via REST: `DELETE /records/food-items/{id}`, `/records/water/{id}`, `/records/beverage/{id}`, `/records/activity/{id}` — 4 endpoints, mesma lógica. | SP-81 | Must Have |
| RF-003 | Idempotência: 2ª chamada ao mesmo registro retorna 200 com `already_deleted=true` sem regravar `deleted_at`, sem novo `audit_events`, sem recompute. | SP-81 | Must Have |
| RF-004 | Dia `status='closed'` bloqueia: REST → 409 `code=conflict_closed_day`; chat → `DayClosedError` → assistant informa. Nada muda. | SP-82, INV-5 | Must Have |
| RF-005 | Snapshot recomputa após soft delete bem-sucedido (INV-4). `SELECT SUM ... WHERE deleted_at IS NULL` exclui naturalmente o item. Não recomputa se `already_deleted=True`. | INV-4 | Must Have |
| RF-006 | Gravar `audit_events(action='delete', before=<snapshot>, after=NULL, actor='llm'|'user', message_id)`. | INV-10, SP-74 lateral | Must Have |
| RF-007 | `actor='llm'` quando `message_id` presente (chat); `actor='user'` quando `message_id=None` (REST). | INV-10 | Must Have |
| RF-008 | Mesmo `TargetMatcher` de [`record-correction`](../record-correction/) — resolve ambiguidade; `AmbiguousTarget` e `NoTargetFound` propagam normalmente. | SP-71 | Must Have |
| RF-009 | `DeletionService.delete_by_id` para path REST: carrega entidade filtrando por `user_id` (ownership); valida dia aberto; soft delete. | SP-81, Const. §21 | Must Have |
| RF-010 | Ownership enforçada: FOOD via JOIN `food_records.user_id`; demais via `model.user_id`. Entidade de outro user → 404 genérico. | Const. §21 | Must Have |

## Requisitos não funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | Operação atômica: `deleted_at` + audit em transação; recompute após flush. | Confiabilidade |
| RNF-002 | Isolamento por user em todos os paths. | Segurança (Const. §21) |
| RNF-003 | REST P95 ≤ 200ms (soft delete + recompute). | Performance |

## Restrições e premissas

- **Soft delete, nunca hard**: `deleted_at` é setado; o registro permanece no DB para auditoria e `messages` ainda referenciam via contexto histórico.
- **Mensagens não são apagadas** (SP-12): remoção de records não apaga mensagens de chat. Histórico da conversa é imutável.
- **`FoodItem` não tem `user_id` direto**: JOIN por `food_record_id → food_records.user_id` (mesma convenção de [`food-logging`](../food-logging/)).
- **`day_log_id` de FoodItem resolvido via `_resolve_day_log_id`**: pode estar em `entity.day_log_id` (pré-populado no path REST) ou requer `session.get(FoodRecord)`.
- **Sem "undelete"**: operação é irreversível via UI/chat. Auditoria via `audit_events` registra o estado antes.
- **Recompute só em exclusão efetiva**: `already_deleted=True` → recompute não roda (já exclui o registro das somas).

## Dependências

**Depende de:**
- [`record-correction`](../record-correction/) — reutiliza `TargetMatcher`, `DayClosedError`, `_ensure_day_open`, `_snapshot` (importação direta).
- [`chat-messaging`](../chat-messaging/) — routing via `IntentDispatcher._handle_delete_record`.
- [`daily-snapshot`](../daily-snapshot/) — `DailyRecomputeService.recompute` pós-delete.
- [`day-close`](../day-close/) — produz `status='closed'` que bloqueia.
- [`audit-trail`](../audit-trail/) — `AuditEventRepository.record`.
- [`anthropic-integration`](../anthropic-integration/) — extrai `intent=delete_record` com `deletion: {target_hint, confidence}`.
- [`authentication-session`](../authentication-session/) — `Depends(get_current_user)`.

**Requerido por:**
- [`assistant-message-rendering`](../assistant-message-rendering/) — SP-117 botão "Descartar" chama `DELETE` endpoint.
- [`manual-catalog-recovery`](../manual-catalog-recovery/) — CTA "Descartar item" do prompt SP-140.
