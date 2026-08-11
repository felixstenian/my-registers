# Critérios de Aceitação — Registro de alimentos

## AC-001 — Texto com quantidades explícitas resolve pelo catálogo (SP-20)

**Dado que** o catálogo TBCA está semeado com `arroz_branco_cozido`, `feijao_carioca_cozido` e `peito_de_frango_grelhado`
**E** existe `day_log` aberto para o usuário no fuso local
**Quando** o usuário envia "150 g de arroz, 90 g de feijão, 180 g de frango"
**Então** o sistema cria 1 `food_records` com `meal_slot` derivado do envelope (ou `unspecified` se ausente)
**E** cria 3 `food_items` com `catalog_ref_id` preenchido para cada item
**E** `kcal` do item de arroz = `hit.kcal × 150 / 100` (arredondado 2 casas)
**E** o snapshot do dia é recomputado, `kcal_in` reflete a soma dos 3 itens.

**Notas de validação:**
- Ver `test_meal_service.py::test_sp20_explicit_quantities_resolve_from_catalog`.
- Ver `test_log_food_flow.py::test_log_food_end_to_end_persists_and_recomputes`.

---

## AC-002 — Unidade doméstica marca estimativa (SP-21)

**Dado que** o usuário envia "uma concha de feijão"
**Quando** a LLM extrai `FoodItemIn(detected_name="feijão", unit="concha", quantity=1, grams_estimate=~120, confidence=0.7, is_estimate=true)`
**Então** o item persiste com `unit='concha'`, `is_estimate=true`, `confidence=0.70`
**E** o cálculo usa `grams_estimate` normalmente (`hit × 120/100`)
**E** UI destaca o item como estimativa (badge distinto de `needs_confirmation`).

**Notas de validação:**
- Ver `test_meal_service.py::test_sp21_domestic_unit_marks_estimate_and_low_confidence`.
- `confidence=0.7 < LOW_CONFIDENCE_THRESHOLD (0.5)` é FALSO — só `is_estimate=true` sozinho não dispara `needs_confirmation`.

---

## AC-003 — Item sem catálogo persiste com macros zerados (SP-23)

**Dado que** a LLM emite `FoodItemIn(detected_name="sushi ninja rolls", grams_estimate=200, confidence=0.6)`
**E** `LocalTBCACatalog.lookup(...)` devolve `None`
**Quando** `MealService._create_item(...)` roda
**Então** item persiste com `catalog_ref_id=NULL`, `kcal=0`, `protein_g=0`, `carbs_g=0`, `fat_g=0`
**E** `needs_confirmation=true` (por `hit is None`)
**E** warning `{code:"no_catalog_hit", item_id, detected_name}` é emitido
**E** `NutritionCalculator.compute` devolve `ComputedNutrition.zeros("no_catalog_hit")`.

**Notas de validação:**
- Ver `test_meal_service.py::test_sp23_unknown_item_zeros_and_warning`.
- Ver `test_log_food_flow.py::test_unknown_food_creates_zero_kcal_with_warning`.
- Warning `no_catalog_hit` sobe até `daily_snapshots.warnings` (verificado em `test_daily_recompute.py`).

---

## AC-004 — Confiança < 0.5 marca item como pendente (SP-24)

**Dado que** a LLM emite `FoodItemIn(detected_name="arroz", grams_estimate=100, confidence=0.30)`
**E** o item **tem** hit no catálogo (`arroz_branco_cozido`)
**Quando** `MealService._create_item(...)` roda
**Então** item persiste com `catalog_ref_id` preenchido, `kcal` calculado normalmente
**E** `needs_confirmation=true` (porque `confidence < 0.5`)
**E** warning `{code:"low_confidence_item", item_id, confidence: 0.3}` é emitido.

**Notas de validação:**
- Ver `test_meal_service.py::test_sp24_low_confidence_flags_needs_confirmation`.

---

## AC-005 — `meal_slot` ausente → `unspecified` (SP-26)

**Dado que** o envelope tem `meal_slot=None`
**Quando** `MealService.create_from_llm(...)` roda
**Então** `food_records.meal_slot` é `'unspecified'` (default do schema no server_default)
**E** a barra e o card renderizam nome "Refeição" ou fallback pt-BR contextual.

**Notas de validação:**
- Ver `test_meal_service.py::test_sp26_unspecified_meal_slot_defaults`.

---

## AC-006 — Auditoria da criação (INV-10)

**Dado que** qualquer `MealService.create_from_llm(...)` terminou com sucesso
**Então** existe **exatamente uma** linha em `audit_events` com:
- `entity_type='food_record'`
- `entity_id = food_record.id`
- `action='create'`
- `actor='llm'`
- `message_id` = mensagem originadora
- `after = {meal_slot, occurred_at, item_ids: [str(uuid), ...]}`
- `before = NULL`

**Notas de validação:**
- Ver `test_meal_service.py::test_audit_event_recorded_on_create`.

---

## AC-007 — LLM não pode contaminar cálculo (INV-1)

**Dado que** o `AnthropicClient` é substituído por mock que devolve `FoodItemIn(...)` com campos extra `kcal=99999`, `protein_g=99999` (ignorados por `extra="ignore"`)
**E** o item tem hit no catálogo
**Quando** o pipeline processa a mensagem
**Então** `food_items.kcal` reflete apenas `hit.kcal × grams/100`, **nunca** `99999`
**E** `daily_snapshots.kcal_in` também.

**Notas de validação:**
- Ver `test_log_food_flow.py::test_llm_kcal_lies_ignored_backend_calculates`.
- Este é o teste que garante que uma regressão no prompt não vaza para persistência.

---

## AC-008 — Isolamento por usuário (Const. §21)

**Dado que** dois usuários `A` e `B` existem
**Quando** `A` cria refeição
**Então** repositórios só devolvem esses itens para `A` (via `user_id` obrigatório).

**Notas de validação:**
- Ver `test_meal_service.py::test_ownership_isolation`.

---

## Cenários de borda

| Cenário | Comportamento esperado |
|---|---|
| `envelope.food_items = []` | `MealService.create_from_llm` levanta `ValueError` (bug de caller — dispatcher deveria filtrar). |
| `grams=None, ml=None, hit.basis='per_100g'` | `ComputedNutrition.zeros("missing_grams")`; item persiste com kcal=0 + warning. |
| `grams=0` ou `grams<0` | Tratado como `missing_grams` (`amount <= 0`). |
| `hit.basis='per_100ml'` mas item tem `grams` | `missing_ml`; item persiste zerado. |
| Envelope com `intent=log_food` **sem** `food_items` | Não chega em `MealService`; dispatcher devolve clarify ("não identifiquei o que você comeu"). |
| `catalog_ref_id` aponta para nutrient_fact deletado depois | Sem impacto: valores já materializados em `food_items`. Recompute continua funcionando. |
| Múltiplas fotos (até 4, SP-25) | 1 `food_records`, N `food_items`, mesmo `meal_slot`. |
| Dia `status='closed'` (INV-5) | Envio de nova mensagem tentando `log_food` para hoje ainda cria em `day_log` novo; correção/deleção em dia fechado retorna 409 (feature separada). |

## Critérios de não-funcionalidade

| Critério | Threshold | Fonte |
|---|---|---|
| Cobertura de `NutritionCalculator` | ≥ 90% | `plan.md` §5.3, CLAUDE.md "Testes" |
| Cobertura de `MealService` | ≥ 90% | Idem |
| Latência (fim-a-fim, texto puro) | P50 ≤ 6s | `spec.md` §4.2 |
| Latência (com 1 foto) | P50 ≤ 12s | Idem |
| Determinismo | Mesma entrada → mesmos macros (Decimal `.quantize`) | RNF-003 |
| Assistente disclaimer | 100% das respostas | Const. §26 |
