# Casos de Teste — Registro de alimentos

> Cobertura alvo (plan.md §5.3, CLAUDE.md "Testes"):
> - **Unitários** de `NutritionCalculator` e `MealService`: ≥ **90%**.
> - **Integração** end-to-end de `log_food`: ≥ **80%** de `app/services/`.
> - Suíte roda com `uv run pytest` em `apps/api/`.

---

## Testes unitários

### TC-U-001 — Cálculo com basis per_100g e quantidade em gramas

- **Módulo**: `app/services/nutrition_calculator.py::NutritionCalculator.compute`
- **Entrada**: `hit=CatalogHit(kcal=130, protein_g=2.7, basis="per_100g", ...)`, `grams=Decimal("150")`, `ml=None`
- **Saída esperada**: `ComputedNutrition(kcal=Decimal("195.00"), protein_g=Decimal("4.05"), reasons=[])`
- **Tipo**: Happy path
- **Arquivo**: `tests/test_nutrition_calculator.py`

### TC-U-002 — Sem hit devolve zeros com reason `no_catalog_hit`

- **Entrada**: `hit=None`, `grams=Decimal("100")`, `ml=None`
- **Saída esperada**: `ComputedNutrition.zeros("no_catalog_hit")`
- **Tipo**: Edge case

### TC-U-003 — Basis per_100g sem grams devolve zeros

- **Entrada**: `hit=CatalogHit(basis="per_100g", kcal=100, ...)`, `grams=None`, `ml=None`
- **Saída esperada**: `ComputedNutrition.zeros("missing_grams")`
- **Tipo**: Edge case

### TC-U-004 — Basis per_100ml sem ml devolve zeros

- **Entrada**: `hit=CatalogHit(basis="per_100ml", ...)`, `grams=None`, `ml=None`
- **Saída esperada**: `ComputedNutrition.zeros("missing_ml")`
- **Tipo**: Edge case

### TC-U-005 — Amount ≤ 0 é tratado como missing

- **Entrada**: `grams=Decimal("0")` ou `Decimal("-1")`, basis per_100g
- **Saída esperada**: `zeros("missing_grams")`
- **Tipo**: Edge case (invariante de validação; LLM não deveria emitir isso, mas defense-in-depth)

### TC-U-006 — Basis desconhecido devolve zeros com reason `unknown_basis`

- **Entrada**: `hit.basis="per_serving"` (não suportado por este service)
- **Saída esperada**: `zeros("unknown_basis")`
- **Tipo**: Defensivo (per_serving é fluxo de `nutrition-label-ocr`)

### TC-U-007 — Cálculo com `hit_value=None` em micro específico

- **Entrada**: `hit.calcium_mg=None`, restante preenchido, `grams=100`
- **Saída esperada**: `calcium_mg=Decimal("0")`, outros macros calculados normalmente
- **Tipo**: Rótulos brasileiros omitem cálcio/ferro/potássio (RDC 429/2020) — SP-34

---

## Testes de service (unit + repositório mocado ou DB real)

### TC-U-010 — `MealService` SP-20: quantidades explícitas resolvem pelo catálogo

- **Arquivo**: `tests/test_meal_service.py::test_sp20_explicit_quantities_resolve_from_catalog`
- **Setup**: catálogo TBCA semeado, `day_log` aberto
- **Ação**: envelope com 3 itens (arroz/feijão/frango) com `grams_estimate` preenchidos e `confidence=0.9`
- **Verificar**: 1 `food_records`, 3 `food_items` com `catalog_ref_id != NULL` e `kcal > 0`; snapshot recomputado

### TC-U-011 — SP-21: unidade doméstica marca estimativa

- **Arquivo**: `tests/test_meal_service.py::test_sp21_domestic_unit_marks_estimate_and_low_confidence`
- **Ação**: envelope com `unit='concha'`, `is_estimate=True`, `confidence=0.7`
- **Verificar**: `food_items.is_estimate=True`, `confidence=Decimal("0.70")`, `needs_confirmation=False` (0.7 ≥ 0.5)

### TC-U-012 — SP-23: item sem catálogo persiste zerado + warning

- **Arquivo**: `tests/test_meal_service.py::test_sp23_unknown_item_zeros_and_warning`
- **Ação**: envelope com `detected_name="sushi ninja"`, catálogo devolve None
- **Verificar**: `catalog_ref_id=NULL`, macros=0, `needs_confirmation=True`, warning `no_catalog_hit` em `MealResult.warnings`

### TC-U-013 — SP-24: confiança baixa marca `needs_confirmation`

- **Arquivo**: `tests/test_meal_service.py::test_sp24_low_confidence_flags_needs_confirmation`
- **Ação**: envelope com `confidence=0.30` e item com hit válido
- **Verificar**: `needs_confirmation=True`, `catalog_ref_id != NULL`, macros calculados normalmente, warning `low_confidence_item`

### TC-U-014 — SP-26: meal_slot ausente → unspecified

- **Arquivo**: `tests/test_meal_service.py::test_sp26_unspecified_meal_slot_defaults`
- **Ação**: envelope sem `meal_slot`
- **Verificar**: `food_records.meal_slot='unspecified'`

### TC-U-015 — Auditoria da criação

- **Arquivo**: `tests/test_meal_service.py::test_audit_event_recorded_on_create`
- **Verificar**: 1 linha em `audit_events` com `action='create'`, `actor='llm'`, `after` contém `meal_slot`, `occurred_at`, `item_ids`

### TC-U-016 — Ownership isolation (Const. §21)

- **Arquivo**: `tests/test_meal_service.py::test_ownership_isolation`
- **Setup**: dois users; A cria refeição
- **Verificar**: queries do B não retornam nada de A

---

## Testes de integração (route → service → repo → DB real)

### TC-I-001 — End-to-end de `log_food` persiste e recomputa (INV-4)

- **Arquivo**: `tests/test_log_food_flow.py::test_log_food_end_to_end_persists_and_recomputes`
- **Fluxo**: `POST /chat/messages` com texto → mock Anthropic devolve `log_food` envelope → BackgroundTask processa → `daily_snapshots.kcal_in` atualiza
- **Pré-condições**: user logado, day_log aberto, TBCA semeado, mock Anthropic em `tests/fixtures/anthropic/`
- **Verificar**: assistant message aparece via `GET /chat/messages?after=...`, snapshot atualizado

### TC-I-002 — LLM mentindo em kcal não afeta persistência (INV-1)

- **Arquivo**: `tests/test_log_food_flow.py::test_llm_kcal_lies_ignored_backend_calculates`
- **Ação**: mock Anthropic devolve envelope com `FoodItemIn(kcal=99999)` (extra ignorado)
- **Verificar**: `food_items.kcal` = `hit × grams / 100`, nunca 99999. `snapshot.kcal_in` idem.

### TC-I-003 — Item sem catálogo com kcal=0 em snapshot

- **Arquivo**: `tests/test_log_food_flow.py::test_unknown_food_creates_zero_kcal_with_warning`
- **Verificar**: `daily_snapshots.warnings` contém `no_catalog_hit`, item persistido

### TC-I-004 — Fixtures de mock Anthropic

- **Diretório**: `tests/fixtures/anthropic/`
- **Verificar**: presença de fixtures nomeadas por cenário (`log_food_150g_arroz.json`, `log_food_uma_concha.json`, etc.)
- Convenção CLAUDE.md: **LLM sempre mockada** em testes.

---

## Testes E2E (não implementados no MVP; manuais)

### TC-E-001 — Jornada completa: registro → correção → dia fechado

- **Persona**: Felix
- **Passos**:
  1. Login em `/chat`.
  2. Enviar "150 g arroz, 90 g feijão" → esperar assistant message com tabela SP-118.
  3. Confirmar totais em `DayTotalsBar`.
  4. Corrigir "o arroz era 200g" → verificar snapshot recomputado.
  5. Encerrar dia via botão.
- **Resultado esperado**: `daily_snapshots.closed_at != NULL`, narrativa presente, semanal considera o dia.

### TC-E-002 — Registro por foto (mobile)

- **Persona**: Felix (iPhone)
- **Passos**: `/chat`, capturar foto do prato, enviar sem texto, esperar resposta listando itens com badges de estimativa, confirmar pelo modal SP-117.

### TC-E-003 — Anúncio SP-115 + SP-116 renderizam pt-BR corretamente

- **Verificar**: separador decimal vírgula, `≈` só quando há item estimado/pendente, aviso legal.

---

## Testes de regressão críticos

Manter no radar em cada release:

- **`test_llm_kcal_lies_ignored_backend_calculates`** — INV-1; regressão silenciosa no prompt (novo modelo) pode não ser pega sem esse teste.
- **`test_sp23_unknown_item_zeros_and_warning`** — bug do catálogo vazio em prod (v1.3.0 mencionou dessincronia seed × testes; ver CHANGELOG).
- **`test_daily_recompute`** com múltiplos food_records — INV-4; garantir soma from-scratch e não delta.
- **Testes de catálogo TBCA hardcoded** — 15 asserts em 8 arquivos que quebraram no PR #34 quando o seed foi enriquecido (`arroz_branco_cozido`: 124 → 130 kcal). Se o seed mudar, atualizar asserts junto na mesma PR.

## Como rodar

```bash
# tudo:
cd apps/api && uv run pytest

# um caso específico:
uv run pytest tests/test_meal_service.py::test_sp20_explicit_quantities_resolve_from_catalog -v

# só o calculator (rápido):
uv run pytest tests/test_nutrition_calculator.py -v

# integração ponta-a-ponta:
uv run pytest tests/test_log_food_flow.py -v

# com coverage:
uv run pytest tests/test_meal_service.py tests/test_nutrition_calculator.py --cov=app/services/meal --cov=app/services/nutrition_calculator --cov-report=term-missing
```
