# Especificações Técnicas — Correção de registros

> **Fontes**: `apps/api/app/services/correction.py` (~410 linhas), `apps/api/app/services/correction_matcher.py` (~272 linhas — `TargetMatcher`, `TargetKind`), `apps/api/app/api/routes/records.py` (PATCH food-items, ~linhas 121-240), `apps/api/app/schemas/llm.py::CorrectionIn`, `apps/api/app/services/message_processor.py::_handle_correct_record`, `apps/api/tests/test_corrections_deletions.py`.

## Escopo técnico

Duas superfícies com semânticas ligeiramente diferentes:

1. **Chat** (`intent=correct_record`) → `CorrectionService.apply_from_llm`. Aceita 4 kinds; usa `TargetMatcher` para resolver `target_hint`.
2. **REST** (`PATCH /records/food-items/{id}`) → apenas food; UI passa ID exato (sem matcher).

## Interface

### Via chat — envelope

`LLMEnvelope.correction` ([`schemas/llm.py`](../../../apps/api/app/schemas/llm.py)):

```python
CorrectionIn(
    target_hint="frango do almoço" | "café da manhã" | "corrida",
    changes={"grams": 220, "unit": "g"} | {"volume_ml": 500} | {"duration_minutes": 40, "intensity": "moderate"},
    confidence=0.9,
)
```

- `target_hint`: string livre; `TargetMatcher` tokeniza + normaliza.
- `changes`: `dict[str, float|int|str|bool|None]` — extra="forbid" no schema, mas backend só consome campos conhecidos.

### Via REST — `PATCH /records/food-items/{entity_id}`

- **Auth**: `access_token`.
- **Body** (`FoodItemPatch`):
  ```json
  { "grams": 220, "ml": null, "quantity": 220, "unit": "g" }
  ```
- **Sucesso** (`200`):
  ```json
  { "id": "...", "kcal": 286.0, "grams": 220.0, "ml": null }
  ```
- **Erros**:
  - `404 not_found` — item não existe, não é do current user, ou já deletado (`deleted_at != NULL`).
  - `409 conflict_closed_day` — day_log fechado (INV-5).
  - `422` — payload inválido.

## Fluxo de dados

### Chat path — `CorrectionService.apply_from_llm`

```
IntentDispatcher.handle(envelope, ...)
  ├─ intent=correct_record
  └─ CorrectionService.apply_from_llm(user, day_log_id, message_id, envelope):
        ├─ if envelope.correction is None → ValidationAppError invalid_correction_envelope
        ├─ _ensure_day_open(session, day_log_id):
        │     ├─ day_log = session.get(DayLog, day_log_id)
        │     └─ if status=='closed' → raise DayClosedError()
        ├─ candidate = TargetMatcher.resolve(day_log_id, envelope.correction.target_hint):
        │     ├─ tokens = _tokenize(hint) — normaliza + split _
        │     ├─ kind_filter = _detect_kind(tokens) — via _KIND_HINTS (agua/cafe/corri/treino/...)
        │     ├─ meal_slot_filter = _detect_meal_slot(tokens) — via _MEAL_SLOT_HINTS
        │     ├─ name_tokens = tokens - meal_slot tokens (evita double-count)
        │     ├─ candidates = _search_food + _search_water + _search_beverage + _search_activity
        │     │     — cada busca filtra por kind_filter se presente
        │     │     — score = tokens ∩ normalized_name; +5 se meal_slot bate (food)
        │     ├─ sort by score desc
        │     ├─ if not candidates → raise NoTargetFound
        │     ├─ winners = candidates com top_score
        │     └─ if len(winners) > 1 → raise AmbiguousTarget(hint, winners)
        │        else → return winners[0]
        ├─ before = _snapshot(candidate.entity, kind)
        ├─ apply changes por kind:
        │     ├─ FOOD → _apply_food_changes: extract grams/ml/quantity/unit;
        │     │     if new_grams/new_ml → lookup catalog + NutritionCalculator.compute
        │     │     → atualiza kcal/protein_g/carbs_g/fat_g/fiber_g/sodium_mg/calcium_mg/iron_mg/potassium_mg
        │     │     → coleta warnings de `computed.reasons` (missing_grams/no_catalog_hit/etc)
        │     │     → if needs_confirmation && catalog_ref_id → needs_confirmation=False (SP-24 revalida)
        │     ├─ WATER → _apply_water_changes: só volume_ml
        │     ├─ BEVERAGE → _apply_beverage_changes: volume_ml + recompute similar a food
        │     └─ ACTIVITY → _apply_activity_changes:
        │           ├─ new_duration | new_intensity | reported_kcal
        │           ├─ if reported_kcal: kcal_burned=reported, calc_method='user_manual'
        │           ├─ else if changed && user.weight_kg is None → warning missing_weight_kg
        │           └─ else if changed && weight_kg: ActivityCalculator.compute(...)
        ├─ if not changed → ValidationAppError correction_no_effect
        ├─ if kind in (FOOD, BEVERAGE) → entity.source = 'user_corrected'
        ├─ session.flush()
        ├─ after = _snapshot(candidate.entity, kind)
        └─ AuditEventRepository.record(
              user_id, entity_type=_entity_type_for_audit(kind),
              entity_id, action='correct', actor='llm',
              message_id, before, after
           )

MessageProcessor então chama:
DailyRecomputeService.recompute(day_log_id)   # INV-4
```

### REST path — `PATCH /records/food-items/{id}`

```
PATCH /records/food-items/{entity_id} { grams?, ml?, quantity?, unit? }
  ├─ Depends(get_current_user, get_session)
  ├─ SELECT FoodItem JOIN FoodRecord WHERE item.id AND record.user_id (ownership)
  ├─ if row None → 404 not_found
  ├─ if item.deleted_at != NULL → 404 not_found
  ├─ SELECT day_log; if closed → 409 conflict_closed_day
  ├─ before = snapshot
  ├─ apply payload fields presentes
  ├─ if changed && (grams OR ml presentes):
  │     ├─ catalog = LocalTBCACatalog(session)
  │     ├─ hit = lookup(normalized_name, brand)
  │     ├─ if hit && catalog_ref_id is NULL:
  │     │     item.catalog_ref_id = hit.fact_id       # promoção retroativa
  │     ├─ computed = NutritionCalculator.compute(hit, grams, ml)
  │     ├─ set macros/micros from computed
  │     └─ item.needs_confirmation = False
  ├─ if not changed → 200 sem audit
  ├─ item.source = 'user_corrected'
  ├─ session.flush()
  ├─ AuditEventRepository.record(entity_type='food_item', action='correct',
  │                              actor='user', message_id=None, before, after)
  ├─ DailyRecomputeService.recompute(day_log_id)
  └─ 200 RecordSummary(id, kcal, grams, ml)
```

## Modelo de dados

Nenhuma mudança de schema. Feature muta colunas existentes:

- `food_items`: `grams, ml, quantity, unit, kcal, protein_g, carbs_g, fat_g, fiber_g, sodium_mg, calcium_mg, iron_mg, potassium_mg, source, needs_confirmation, catalog_ref_id (via PATCH promoção retroativa)`.
- `water_records`: `volume_ml`.
- `beverage_records`: `volume_ml, kcal, macros, source`.
- `activity_records`: `duration_minutes, intensity, kcal_burned, met_value, calc_method`.
- Nova linha em `audit_events` por correção.
- Novo version em `daily_snapshots`.

## Regras de negócio

1. **Dia fechado bloqueia (INV-5)**: checado por `_ensure_day_open` no chat e por `if day_log.status == "closed"` no PATCH.
2. **Ambiguidade não muta**: `AmbiguousTarget` levantado **antes** de qualquer mutação. Backend não persiste nada; assistant devolve clarify.
3. **Score do matcher**:
   - Cada token do hint em comum com `normalized_name` do candidato = +1 ponto.
   - Match de `meal_slot` (só food) = +5 pontos (dominante).
   - Empate no top score → `AmbiguousTarget`.
4. **Water sem `detected_name`**: matcher usa `"agua"` implícito para scorear.
5. **Activity extended**: além de `normalized_name`, matcher também scoreia `activity_type` (ex.: user diz "corrida", record tem `activity_type='cardio_run'`).
6. **`_KIND_HINTS`**: presença de palavra-chave no hint filtra a busca por kind (agua → WATER only; cafe → BEVERAGE only). Sem hint → busca todos os kinds.
7. **`_MEAL_SLOT_HINTS`**: normaliza vocabulário pt-BR (almoco→lunch, tarde→snack, ceia→other, etc.).
8. **`_apply_food_changes` também detecta grams/ml a partir de `quantity+unit`**: "220g" → `grams=220`; "500ml" → `ml=500`.
9. **`source='user_corrected'`** só em FOOD e BEVERAGE. Water e activity não têm essa distinção estrutural.
10. **SP-24 revalidação**: `needs_confirmation` volta a `False` quando food tem catalog_ref_id após correção (chat) ou sempre no PATCH (UI pressupõe user confirmou ao digitar).
11. **PATCH promoção retroativa**: se `catalog_ref_id IS NULL` mas o `LocalTBCACatalog` agora encontra hit (seed foi enriquecido depois), o PATCH liga o item ao catálogo. Bug histórico documentado em `scripts/bootstrap.sh`.
12. **Activity com weight_kg ausente**: recompute só emite warning; `kcal_burned` fica como estava.
13. **Sem mudança efetiva → erro** no chat (`correction_no_effect`); no REST → 200 sem audit.

## Configurações e variáveis de ambiente

Nenhuma; reutiliza infra existente.

## Referências de implementação

- **Service**: [`app/services/correction.py`](../../../apps/api/app/services/correction.py) (`CorrectionService`, `DayClosedError`, helpers `_apply_*_changes`, `_snapshot`).
- **Matcher**: [`app/services/correction_matcher.py`](../../../apps/api/app/services/correction_matcher.py) (`TargetMatcher`, `TargetKind`, `AmbiguousTarget`, `NoTargetFound`, `_KIND_HINTS`, `_MEAL_SLOT_HINTS`).
- **Route PATCH**: [`app/api/routes/records.py`](../../../apps/api/app/api/routes/records.py) (`patch_food_item`, ~linhas 121-240).
- **Chat dispatch**: [`app/services/message_processor.py`](../../../apps/api/app/services/message_processor.py) `_handle_correct_record`.
- **Schemas**: [`app/schemas/llm.py::CorrectionIn`](../../../apps/api/app/schemas/llm.py), `FoodItemPatch` em `schemas/records.py`.
- **Testes**: [`apps/api/tests/test_corrections_deletions.py`](../../../apps/api/tests/test_corrections_deletions.py) — 4 casos de matcher + 4 de correction + 5 de PATCH endpoint (5+).
- **ActivityCalculator**: [`app/services/activity_calculator.py`](../../../apps/api/app/services/activity_calculator.py) — reusado no recompute pós-correção de duration/intensity.
