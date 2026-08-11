# Especificações Técnicas — Snapshot diário

> **Fontes**: `apps/api/app/services/daily_recompute.py`, `apps/api/app/services/day_query.py`, `apps/api/app/api/routes/days.py`, `apps/api/app/models/daily_snapshot.py`, `apps/api/app/models/day_log.py`, `apps/api/app/services/chat.py` (`local_today`), `apps/api/app/repositories/day_log.py`.

## Endpoints / Interface

### `GET /days/today`

- **Auth**: `access_token` válido.
- **Efeito colateral**: cria `day_log` (`status='open'`) para hoje se não existir (`DayLogRepository.get_or_create`).
- **Sucesso** (200):
  ```json
  {
    "date": "2026-07-28",
    "status": "open",
    "closed_at": null,
    "totals": {
      "kcal_in": 1750.30, "kcal_out": 320.00, "kcal_balance": 1430.30,
      "protein_g": 95.2, "carbs_g": 210.5, "fat_g": 55.0, "fiber_g": 22.1,
      "sodium_mg": 1800.0, "calcium_mg": 480.0, "iron_mg": 8.5, "potassium_mg": 2100.0,
      "water_ml": 2000, "other_liquids_ml": 350
    },
    "records": {
      "food": [ { "id": "...", "meal_slot": "lunch", "occurred_at": "...", "items": [ ... ] } ],
      "water": [ { "id": "...", "volume_ml": 500, "occurred_at": "..." } ],
      "beverage": [ ... ],
      "activity": [ ... ]
    },
    "warnings": [ { "code": "needs_confirmation", "entity": "food_item", ... } ],
    "narrative": null,
    "snapshot_version": 12
  }
  ```

### `GET /days/{yyyy-mm-dd}`

- **Auth**: mesma.
- **Erro** (404): `{"code": "day_not_found", "detail": "no day_log for user on 2026-07-15"}` quando `day_log` não existe.
- **Sucesso**: mesmo shape acima. Se dia estiver `status='closed'`, `narrative` estará preenchida e `closed_at != null`.

### `POST /days/{yyyy-mm-dd}/close`

Dono da feature [`day-close`](../day-close/); listado aqui só por completude (retorna o mesmo shape via `DayQueryService.get_by_date(allow_recompute=False)` após fechar).

## Modelo de dados

### `day_logs`

Modelo: [`apps/api/app/models/day_log.py`](../../../apps/api/app/models/day_log.py)

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | UUID | PK |
| `user_id` | UUID FK users(id) ON DELETE CASCADE | |
| `log_date` | date NOT NULL | Data local (`local_today(user.timezone)`) |
| `status` | text CHECK IN (`open`, `closed`) DEFAULT `open` | Ciclo de vida |
| `closed_at` | timestamptz NULL | Setado por [`day-close`](../day-close/) |
| `notes` | text NULL | Livre |

**Constraint única**: `uq_day_logs_user_date(user_id, log_date)`. Um `day_log` por dia por usuário.

### `daily_snapshots`

Modelo: [`apps/api/app/models/daily_snapshot.py`](../../../apps/api/app/models/daily_snapshot.py)

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | UUID | PK |
| `user_id` | UUID FK users(id) | Redundante com `day_log.user_id` mas útil para índices |
| `day_log_id` | UUID FK day_logs(id) **UNIQUE** | 1:1 com `day_log` |
| `kcal_in` | numeric(10,2) NOT NULL DEFAULT 0 | `SUM(food_items.kcal) + SUM(beverage_records.kcal)` |
| `kcal_out` | numeric(10,2) NOT NULL DEFAULT 0 | `SUM(activity_records.kcal_burned)` |
| `kcal_balance` | numeric(10,2) NOT NULL DEFAULT 0 | `kcal_in - kcal_out` |
| `protein_g`, `carbs_g`, `fat_g`, `fiber_g` | numeric(10,2) NOT NULL DEFAULT 0 | Somam food + beverage |
| `sodium_mg`, `calcium_mg`, `iron_mg`, `potassium_mg` | numeric(10,2) NOT NULL DEFAULT 0 | Idem |
| `water_ml` | integer NOT NULL DEFAULT 0 | **Somente** `water_records` (INV-2) |
| `other_liquids_ml` | integer NOT NULL DEFAULT 0 | **Somente** `beverage_records.volume_ml` (INV-3) |
| `computed_at` | timestamptz NOT NULL DEFAULT now() | Última recomputação |
| `warnings` | JSONB NOT NULL DEFAULT `[]` | Array de warnings agregados |
| `version` | integer NOT NULL DEFAULT 1 | Incrementado a cada upsert |
| `narrative` | text NULL | Preenchido só por [`day-close`](../day-close/) (SP-103) |

## Fluxo de dados

### Read path — `GET /days/today`

```
GET /days/today (routes/days.py)
  ├─ Depends(get_current_user) → User com timezone
  ├─ log_date = local_today(user.timezone)          # via zoneinfo
  ├─ DayLogRepository.get_or_create(user_id, log_date)  # cria vazio se hoje
  ├─ DayQueryService.get_today(user):
  │     └─ _build(user_id, log_date, allow_recompute=True):
  │           ├─ day_log = SELECT WHERE user_id, log_date
  │           ├─ snapshot = SELECT WHERE day_log_id
  │           ├─ should_recompute = day_log.status='open' AND snapshot IS NULL
  │           ├─ if should_recompute:
  │           │     └─ DailyRecomputeService.recompute(day_log.id)
  │           ├─ totals = _snapshot_to_totals(snapshot)
  │           ├─ warnings = snapshot.warnings if snapshot else []
  │           └─ records = _load_records(day_log_id):
  │                 ├─ _load_food(...): joins FoodRecord + FoodItem, agrupa
  │                 ├─ _load_water(...): WaterRecord ordenado
  │                 ├─ _load_beverage(...): BeverageRecord ordenado
  │                 └─ _load_activity(...): ActivityRecord ordenado
  └─ retorna DaySnapshotOut serializado
```

### Recompute path — `DailyRecomputeService.recompute(day_log_id)`

```
DailyRecomputeService.recompute(day_log_id):
  ├─ day_log = session.get(DayLog, day_log_id)
  ├─ if day_log is None → raise ValueError
  ├─ food_totals, food_warnings = _aggregate_food(day_log_id):
  │     ├─ SELECT SUM(kcal), SUM(protein_g), ... FROM food_items
  │     │   JOIN food_records ON food_records.id = food_items.food_record_id
  │     │   WHERE food_records.day_log_id = ?
  │     │     AND food_records.deleted_at IS NULL
  │     │     AND food_items.deleted_at IS NULL
  │     └─ SELECT id, detected_name, catalog_ref_id, needs_confirmation
  │        FROM food_items JOIN food_records ...
  │        → emite `no_catalog_hit` para itens com catalog_ref_id NULL
  │        → emite `needs_confirmation` para itens flagados
  ├─ bev_totals, bev_warnings = _aggregate_beverage(day_log_id):
  │     ├─ SELECT SUM(kcal), ..., SUM(volume_ml) FROM beverage_records
  │     │   WHERE day_log_id = ? AND deleted_at IS NULL
  │     └─ Warnings análogos aos de food
  ├─ water_ml = _aggregate_water(day_log_id):
  │     └─ SELECT SUM(volume_ml) FROM water_records
  │        WHERE day_log_id = ? AND deleted_at IS NULL
  ├─ kcal_out, act_warnings = _aggregate_activity(day_log_id):
  │     ├─ SELECT SUM(kcal_burned) FROM activity_records
  │     │   WHERE day_log_id = ? AND deleted_at IS NULL
  │     └─ Emite `activity_estimated` se calc_method != 'mets_body_weight' ou met_value IS NULL
  ├─ kcal_in = food_totals[kcal] + bev_totals[kcal]                # INV-3
  ├─ combined = { field: food_totals[f] + bev_totals[f] } exceto kcal e water/volume
  ├─ warnings = [*food_warnings, *bev_warnings, *act_warnings]
  ├─ payload = { user_id, day_log_id, kcal_in, kcal_out, kcal_balance,
  │              macros, micros, water_ml, other_liquids_ml=bev_totals[volume_ml],
  │              computed_at=now, warnings }
  ├─ stmt = pg_insert(DailySnapshot).values(**payload)
  │           .on_conflict_do_update(
  │             index_elements=[day_log_id],
  │             set_={ **payload_sem_day_log_id, version = version + 1 }
  │           ).returning(DailySnapshot)
  │           .execution_options(populate_existing=True)   # bug-fix Fase 4
  └─ snapshot = execute(stmt).scalar_one()
```

## Regras de negócio

1. **Fuso horário do usuário define o dia.** `local_today(user.timezone)` retorna `date` no fuso `America/Sao_Paulo` (default). SP-92 exige que uma mensagem enviada 23:30 local em 12/jul pertença a `log_date=2026-07-12`, mesmo que UTC seja 13/jul.
2. **Um `day_log` por (user, log_date).** UNIQUE constraint garante idempotência do `get_or_create`.
3. **Snapshot 1:1 com day_log.** `UNIQUE(day_log_id)` + `INSERT ... ON CONFLICT` → upsert atômico.
4. **Recompute sempre from-scratch (INV-4).** Nunca `snapshot.kcal_in += novo_item.kcal`. Sempre SUM.
5. **Água ≠ bebida (INV-2, INV-3).** `water_ml` só de `water_records`, `other_liquids_ml` só de `beverage_records.volume_ml`. Impossível dupla contagem por engano (tabelas separadas).
6. **Deleted items excluídos.** Todos os `SUM` filtram `deleted_at IS NULL`. Soft delete recompõe naturalmente sem tocar snapshot antigo — só rodar recompute de novo.
7. **`kcal_in` combina food + beverage** (Const. Art. IV §13). Bebida calórica contribui pra kcal e pros macros; água pura não.
8. **Version incrementa.** `set_={..., version = version + 1}` — cada mutação bump. Útil pra clientes checarem "meu snapshot está stale?".
9. **`populate_existing=True` é obrigatório.** Sem essa flag, o `.returning(DailySnapshot)` pode devolver instância cacheada no identity map da sessão SQLAlchemy — regressão vista na Fase 4. Não remova.
10. **Dia fechado nunca recomputa (INV-5).** `should_recompute = day_log.status == 'open' AND snapshot is None`. `get_by_date(allow_recompute=None)` decide pelo status — se `closed`, snapshot congelado é retornado como está.
11. **Snapshot missing em dia fechado = anomalia.** `_snapshot_to_totals(None)` devolve zeros ao invés de explodir; cliente vê "0 kcal" (situação anômala documentada no comment do service).
12. **`Records` são ordenados por `occurred_at`.** UI depende disso pra timeline.

## Configurações e variáveis de ambiente

| Variável | Descrição | Padrão | Obrigatória |
|---|---|---|---|
| `users.timezone` | Coluna do DB, não env. Default `America/Sao_Paulo`. | | Sim (server_default) |
| `DATABASE_URL` | Postgres 16. | — | Sim |

## Referências de implementação

- **Rotas**: [`app/api/routes/days.py`](../../../apps/api/app/api/routes/days.py).
- **Services**: [`app/services/day_query.py`](../../../apps/api/app/services/day_query.py) (`DayQueryService`, `DayPayload`), [`app/services/daily_recompute.py`](../../../apps/api/app/services/daily_recompute.py) (`DailyRecomputeService`, `RecomputeResult`).
- **Helpers de fuso**: [`app/services/chat.py`](../../../apps/api/app/services/chat.py) (`local_today`).
- **Modelos**: [`app/models/day_log.py`](../../../apps/api/app/models/day_log.py), [`app/models/daily_snapshot.py`](../../../apps/api/app/models/daily_snapshot.py).
- **Repositório**: [`app/repositories/day_log.py`](../../../apps/api/app/repositories/day_log.py) (`DayLogRepository.get_or_create`).
- **Schemas**: [`app/schemas/days.py`](../../../apps/api/app/schemas/days.py) (`DaySnapshotOut`, `DayTotalsOut`, `DayRecordsOut`).
- **Testes**: [`apps/api/tests/test_daily_recompute.py`](../../../apps/api/tests/test_daily_recompute.py) (5 casos cobrindo SUM, idempotência, version, deleted excluídos, warnings).
