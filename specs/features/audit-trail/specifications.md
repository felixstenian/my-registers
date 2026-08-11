# Especificações Técnicas — Trilha de auditoria

> **Fontes**: `apps/api/app/models/audit_event.py`, `apps/api/app/repositories/food.py::AuditEventRepository`.

## Escopo técnico

Feature cross-cutting sem rota HTTP própria. Implementada como `AuditEventRepository` (em `repositories/food.py`, por razões históricas) e `AuditEvent` model. Cada service que muta dados de negócio instancia `AuditEventRepository(session)` e chama `.record(...)` dentro da mesma transação.

## Interface

### `AuditEventRepository.record(...)`

```python
await AuditEventRepository(session).record(
    user_id=user.id,           # UUID — dono do registro
    entity_type="food_record", # str livre — ver tabela abaixo
    entity_id=record.id,       # UUID — PK da entidade mutada
    action="create",           # CHECK IN ('create','update','delete','correct','confirm','close')
    actor="llm",               # CHECK IN ('user','llm')
    message_id=message_id,     # UUID | None — mensagem do chat, se aplicável
    before=None,               # dict | None — estado antes
    after={...},               # dict | None — estado depois
)
```

Retorna `AuditEvent` com `id` e `created_at`.

## Modelo de dados

### `audit_events`

Modelo: [`apps/api/app/models/audit_event.py`](../../../apps/api/app/models/audit_event.py)

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | UUID | PK |
| `user_id` | UUID FK users(id) ON DELETE CASCADE | Dono — quem sofreu a mutação |
| `entity_type` | text NOT NULL | Tipo da entidade (ver tabela abaixo) |
| `entity_id` | UUID NOT NULL | PK da entidade (sem FK — ver restrições) |
| `action` | text CHECK IN (`create`, `update`, `delete`, `correct`, `confirm`, `close`) | Operação realizada |
| `actor` | text CHECK IN (`user`, `llm`) | Quem originou |
| `before` | JSONB NULL | Snapshot antes (NULL em `create`) |
| `after` | JSONB NULL | Snapshot depois (NULL em `delete`) |
| `message_id` | UUID FK messages(id) ON DELETE SET NULL NULL | Mensagem do chat origem |
| `created_at` | timestamptz NOT NULL DEFAULT now() | Timestamp da mutação |

## Tabela de uso por feature

| `entity_type` | `action` | `actor` | Feature | `before` shape | `after` shape |
|---|---|---|---|---|---|
| `food_record` | `create` | `llm` | food-logging | NULL | `{meal_slot, occurred_at, item_ids:[...]}` |
| `food_item` | `correct` | `llm` | record-correction (chat) | `{detected_name, grams, ml, kcal, macros, needs_confirmation, source}` | idem pós-mudança |
| `food_item` | `correct` | `user` | record-correction (REST PATCH) | `{grams, ml, quantity, unit, kcal}` | idem pós |
| `food_item` | `delete` | `llm`\|`user` | record-deletion | `{detected_name, grams, ml, kcal, macros, ...}` | NULL |
| `food_item` | `confirm` | `llm` | confirmation | `{needs_confirmation: true, ...}` | `{needs_confirmation: false}` |
| `water_record` | `create` | `llm` | water-tracking | NULL | `{volume_ml, occurred_at}` |
| `water_record` | `correct` | `llm`\|`user` | record-correction | `{volume_ml}` | `{volume_ml}` novo |
| `water_record` | `delete` | `llm`\|`user` | record-deletion | `{volume_ml}` | NULL |
| `beverage_record` | `create` | `llm` | caloric-beverages | NULL | `{detected_name, volume_ml, kcal, occurred_at}` |
| `beverage_record` | `correct` | `llm`\|`user` | record-correction | `{detected_name, volume_ml, kcal, source}` | idem pós |
| `beverage_record` | `delete` | `llm`\|`user` | record-deletion | `{detected_name, volume_ml, kcal, source}` | NULL |
| `activity_record` | `create` | `llm` | activity-cardio-logging | NULL | `{detected_name, activity_type, duration_minutes, intensity, kcal_burned, met_value, calc_method}` |
| `activity_record` | `correct` | `llm`\|`user` | record-correction | idem (antes) | idem (depois) |
| `activity_record` | `delete` | `llm`\|`user` | record-deletion | idem | NULL |
| `day_log` | `close` | `user` | day-close | `{status: "open"}` | `{status: "closed", closed_at, snapshot_version}` |
| `nutrient_fact` | `create` | `user` | nutrition-label-ocr / manual-catalog-recovery | NULL | `{canonical_name, source, verified_by_user, kcal, ...}` |
| `nutrient_fact` | `update` | `user` | nutrition-label-ocr (PATCH §33) | `{verified_by_user, kcal, macros, ...}` | idem pós |
| `user` | `update` | `llm` | profile (set_profile) | `{weight_kg, height_cm, ...}` antes | idem pós |

## Convenções de `before`/`after`

1. **`create`**: `before=NULL`, `after=<estado inicial>`.
2. **`delete`**: `before=<estado final antes de deletar>`, `after=NULL`.
3. **`correct`/`update`**: `before=<estado antes>`, `after=<estado depois>`. Incluem apenas campos que podem mudar — não o snapshot completo.
4. **`confirm`**: `before={needs_confirmation: true}`, `after={needs_confirmation: false}` — snapshot mínimo (apenas a mudança semântica).
5. **`close`**: `before={status: "open"}`, `after={status: "closed", closed_at, snapshot_version}`.

## Referências de implementação

- **Repository**: [`app/repositories/food.py::AuditEventRepository`](../../../apps/api/app/repositories/food.py) (linhas 110–138).
- **Model**: [`app/models/audit_event.py`](../../../apps/api/app/models/audit_event.py) (`AuditEvent`, `AUDIT_ACTIONS`, `AUDIT_ACTORS`).
- **Callers** (todos os services listados na tabela acima):
  - [`app/services/meal.py`](../../../apps/api/app/services/meal.py) — `create` food_record
  - [`app/services/hydration.py`](../../../apps/api/app/services/hydration.py) — `create` water_record
  - [`app/services/beverage.py`](../../../apps/api/app/services/beverage.py) — `create` beverage_record
  - [`app/services/activity.py`](../../../apps/api/app/services/activity.py) — `create` activity_record
  - [`app/services/correction.py`](../../../apps/api/app/services/correction.py) — `correct`
  - [`app/services/deletion.py`](../../../apps/api/app/services/deletion.py) — `delete`
  - [`app/services/confirmation.py`](../../../apps/api/app/services/confirmation.py) — `confirm`
  - [`app/services/day_close.py`](../../../apps/api/app/services/day_close.py) — `close`
  - [`app/services/label_catalog.py`](../../../apps/api/app/services/label_catalog.py) — `create`/`update` nutrient_fact
  - [`app/api/routes/records.py`](../../../apps/api/app/api/routes/records.py) — `correct` via REST
  - [`app/api/routes/nutrient_facts.py`](../../../apps/api/app/api/routes/nutrient_facts.py) — `update` nutrient_fact
  - [`app/services/profile.py`](../../../apps/api/app/services/profile.py) — `update` user
