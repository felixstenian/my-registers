# Casos de Teste — Correção de registros

> Arquivo principal: `apps/api/tests/test_corrections_deletions.py`.
> Cobre: matcher (4 casos), correction service (4), PATCH endpoint (2+), interação com snapshot (1), chat integration (1).

---

## Testes de integração — TargetMatcher

### TC-I-001 — Match não ambíguo

- **Arquivo**: `test_matcher_unambiguous_food_hit`
- **Setup**: dia com 1 food_item "arroz branco"
- **Ação**: `TargetMatcher.resolve(day_log_id, "arroz")`
- **Verificar**: `Candidate(kind=FOOD, score>0)`

### TC-I-002 — Ambiguidade levanta

- **Arquivo**: `test_matcher_ambiguous_raises`
- **Setup**: 2 items empatados no top score
- **Ação**: resolve
- **Verificar**: `AmbiguousTarget(hint, candidates=[c1, c2])`

### TC-I-003 — Qualificado por meal_slot

- **Arquivo**: `test_matcher_qualified_by_meal_slot`
- **Setup**: 2 items "frango" em lunch e dinner
- **Ação**: `resolve(hint="frango almoço")`
- **Verificar**: item lunch vence (+5 bônus)

### TC-I-004 — Sem target

- **Arquivo**: `test_matcher_no_target_raises`
- **Setup**: dia sem "quinoa"
- **Ação**: `resolve("quinoa")`
- **Verificar**: `NoTargetFound(hint="quinoa")`

---

## Testes de integração — CorrectionService

### TC-I-010 — Atualiza grams + recomputa macros

- **Arquivo**: `test_correction_updates_grams_and_recomputes_macros`
- **Setup**: food_item grams=100, kcal=130
- **Ação**: correção grams=200
- **Verificar**:
  - `grams=200, kcal=260` (200×130/100)
  - `source='user_corrected'`
  - Snapshot recomputado

### TC-I-011 — Grava audit event

- **Arquivo**: `test_correction_grava_audit_event`
- **Verificar**: 1 linha em `audit_events` com `action='correct', actor='llm', before, after`

### TC-I-012 — Ambigua não persiste

- **Arquivo**: `test_correction_ambiguous_does_not_persist`
- **Setup**: 2 items empatados
- **Ação**: apply_from_llm
- **Verificar**: `AmbiguousTarget` levantada; DB inalterado

### TC-I-013 — Dia fechado bloqueia

- **Arquivo**: `test_correction_on_closed_day_blocks`
- **Setup**: day_log.status='closed'
- **Ação**: apply_from_llm
- **Verificar**: `DayClosedError` levantada; sem mutação

---

## Testes de integração — PATCH endpoint

### TC-I-020 — PATCH recomputa macros

- **Arquivo**: `test_patch_food_item_recomputes_macros`
- **Ação**: `PATCH /records/food-items/{id} { grams: 200 }`
- **Verificar**:
  - 200 OK
  - Macros recalculados via NutritionCalculator
  - `source='user_corrected'`
  - `needs_confirmation=False`

### TC-I-021 — PATCH em dia fechado → 409

- **Arquivo**: `test_delete_endpoint_closed_day_returns_409` (companion; deletion tem similar mas correction herda mesmo padrão)
- **Verificar**: 409 `conflict_closed_day`

### TC-I-022 — Snapshot recomputa após correção

- **Arquivo**: `test_snapshot_recomputes_after_correction`
- **Verificar**: `snapshot.version` incrementou; `kcal_in` reflete correção

---

## Testes de chat integration

### TC-I-030 — Ambigua via chat → clarify

- **Arquivo**: `test_ambiguous_correction_via_chat_returns_clarify`
- **Setup**: 2 items empatados
- **Ação**: user manda "corrija frango para 220g"
- **Verificar**:
  - LLM retorna `intent=correct_record`
  - `AmbiguousTarget` capturado
  - Assistant message pede desambiguação
  - Nenhum record mutado

---

## Testes unitários potenciais (gaps)

### TC-U-001 — `_extract_grams` de várias formas

- `{grams: 150}` → 150
- `{quantity: 150, unit: "g"}` → 150
- `{quantity: 150, unit: "gramas"}` → 150
- `{grams_estimate: 150}` → 150
- `{quantity: 150, unit: "ml"}` → None (é ml, não g)

### TC-U-002 — `_detect_kind` prioriza primeira keyword

- `["cafe"]` → BEVERAGE
- `["corri"]` → ACTIVITY
- `["agua"]` → WATER
- `[]` → None

### TC-U-003 — `_snapshot` por kind

- FOOD: retorna dict com detected_name/grams/ml/quantity/unit/kcal/macros/needs_confirmation/source
- WATER: retorna `{volume_ml}` apenas
- BEVERAGE: retorna dict com detected_name/volume_ml/kcal/source
- ACTIVITY: retorna dict com detected_name/activity_type/duration_minutes/intensity/kcal_burned/calc_method/met_value

### TC-U-004 — Activity com reported_kcal marca calc_method='user_manual'

- Input: `changes={kcal_burned:380}`
- Verificar: `record.calc_method='user_manual'`, `kcal_burned=380`

### TC-U-005 — `correction_no_effect`

- Item com `grams=150`; changes={grams:150}
- Verificar: `ValidationAppError code='correction_no_effect'`

---

## Testes E2E manuais

### TC-E-001 — Fluxo completo via chat

- **Persona**: Felix
- **Passos**:
  1. Registrar 2 items "frango" (lunch + dinner).
  2. Enviar "corrija o frango para 220g".
  3. Ver assistant pedir desambiguação.
  4. Enviar "corrija o frango do almoço para 220g".
  5. Ver assistant confirmar + `DayTotalsBar` atualizar.

### TC-E-002 — Correção via modal SP-117

- **Passos**:
  1. Item com `needs_confirmation=True` no card.
  2. Clicar "Confirmar" → modal abre com valores pré-preenchidos.
  3. Editar grams pra 200; submit.
  4. Modal fecha; `DayTotalsBar` atualiza; badge some.

### TC-E-003 — Correção retroativa em dia fechado (esperado bloqueio)

- **Passos**:
  1. Fechar dia D.
  2. Tentar "corrija o arroz do dia D para 200g".
  3. Assistant devolve "Dia já fechado; crie novo registro hoje".

---

## Testes de regressão críticos

- **`test_correction_ambiguous_does_not_persist`** — INV que impede corrupção silenciosa.
- **`test_correction_on_closed_day_blocks`** — INV-5.
- **`test_correction_grava_audit_event`** — INV-10.
- **`test_snapshot_recomputes_after_correction`** — INV-4.
- **`test_patch_food_item_recomputes_macros`** — regressão se NutritionCalculator não for chamado.

## Como rodar

```bash
cd apps/api

# suíte completa
uv run pytest tests/test_corrections_deletions.py -v

# só matcher
uv run pytest tests/test_corrections_deletions.py -v -k matcher

# só correction (não deletion)
uv run pytest tests/test_corrections_deletions.py -v -k correction

# coverage
uv run pytest tests/test_corrections_deletions.py \
  --cov=app/services/correction \
  --cov=app/services/correction_matcher \
  --cov-report=term-missing
```
