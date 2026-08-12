# Especificações Técnicas — Edição inline de registros na página `/day`

> **Rastreabilidade**: SP-160..SP-169, INV-14 · SDD: [`specs/002-edicao-inline-day/spec.md`](../../002-edicao-inline-day/spec.md), [`plan.md`](../../002-edicao-inline-day/plan.md), [`research.md`](../../002-edicao-inline-day/research.md) (ADR-013/014/015).

## Escopo técnico

Extende o componente `FoodItemRow` e o `AuxiliarySections` do Bloco 6 ([`daily-detail-view`](../daily-detail-view/specifications.md)) com **painéis de edição** dentro da expansão `<details>`. Estratégia: mantém o shell server component; injeta um **client component** (`EditFoodItemForm`/`EditWaterForm`/`EditBeverageForm`/`EditActivityForm`) só quando o `<details>` abre (`onToggle`), evitando hidratar N forms em uma página com 20+ itens.

Backend novas áreas: refatora `services/correction.py` extraindo funções puras para `services/correction_ops.py` (compartilhadas entre chat e REST — ADR-015). Adiciona `services/nutrient_fact_propagation.py` (INV-14 — ADR-013). Três novos handlers PATCH em `api/routes/records.py` (water/beverage/activity). Extensão do handler PATCH em `api/routes/nutrient_facts.py` para chamar `propagate`.

## Interface (arquivos)

### Backend — novos endpoints REST

```python
# apps/api/app/api/routes/records.py — extensão
class WaterPatch(BaseModel):
    volume_ml: int = Field(gt=0)

class BeveragePatch(BaseModel):
    volume_ml: int | None = Field(default=None, gt=0)

class ActivityPatch(BaseModel):
    duration_minutes: float | None = Field(default=None, gt=0)
    intensity: Literal["light","moderate","vigorous","unknown"] | None = None
    kcal_burned: float | None = Field(default=None, ge=0)
    # detected_name não aceito — 422 se presente

@router.patch("/water/{entity_id}", response_model=RecordSummary)
@router.patch("/beverage/{entity_id}", response_model=RecordSummary)
@router.patch("/activity/{entity_id}", response_model=RecordSummary)
```

- Todos: `current_user = Depends(get_current_user)`, `session = Depends(get_session)`.
- Filtro `user_id == current_user.id` no SELECT (Const. Art. V §21); 404 `not_found` se inexistente ou `deleted_at IS NOT NULL`; 409 `conflict_closed_day` (INV-5).
- Sucesso: chama `correction_ops.apply_*_change` (reusado da Fase 0 refactor), grava `audit_events(action='correct', actor='user')`, chama `DailyRecomputeService.recompute(day_log_id)`. Retorna `RecordSummary{id, kcal?, grams?, ml?, volume_ml?, duration_minutes?}`.
- `correction_ops.py` é consumido por `CorrectionService` (chat) e pelos handlers REST (SP-164/165/166).

### Backend — extensão `PATCH /nutrient-facts/{id}` (SP-163, INV-14)

```python
# apps/api/app/api/routes/nutrient_facts.py — fim do handler
from app.services.nutrient_fact_propagation import propagate

# resposta estendida (default [] para não quebrar clientes antigos)
class NutrientFactOut(BaseModel):  # estendido
    ...  # campos existentes
    propagated: list[PropagatedItem] = []
    propagation_skipped: list[SkippedItem] = []
```

- `propagate(session, fact, user)` em `services/nutrient_fact_propagation.py`:
  1. `SELECT` `food_items` vivos + JOIN `food_records` + JOIN `day_logs` `status='open'` com `catalog_ref_id = fact.id`.
  2. Para cada item: `NutritionCalculator.compute(hit=fact, grams, ml)` → sobrescreve macros; `source='user_corrected'`; audit `action='correct'` `actor='user'` `entity_type='food_item'` before/after.
  3. Idem `beverage_records`.
  4. `day_log_id`s distintos → `DailyRecomputeService.recompute` cada um.
  5. Itens em dia `closed` → `propagation_skipped` com `reason='day_closed'` (não mutam — INV-5).

### Frontend — componentes novos

```tsx
// apps/web/src/app/(app)/day/actions.ts — Server Actions
'use server';
export async function editFoodItem(itemId: string, payload): Promise<{ok, error?}> { ... }
export async function editNutrientFact(factId: string, payload): Promise<{ok, error?}> { ... }
export async function editWater(id: string, payload): Promise<{ok, error?}> { ... }
export async function editBeverage(id: string, payload): Promise<{ok, error?}> { ... }
export async function editActivity(id: string, payload): Promise<{ok, error?}> { ... }
// Cada uma: fetch PATCH via INTERNAL_API_URL + cookies(), revalidatePath('/day') + revalidatePath('/day/[date]')
```

```tsx
// apps/web/src/app/(app)/day/FoodItemRow.tsx (modificado)
// Shell server mantém; <details onToggle> injeta { open && <EditFoodItemForm .../> }
```

```tsx
// apps/web/src/app/(app)/day/EditFoodItemForm.tsx (novo, client)
'use client';
// inputs: grams/ml (ou quantity/unit) + optional per-100g
// useActionState hook -> editFoodItem / editNutrientFact
// loading/erro/sucesso; aria-live
// facilita diff raso: disabled se !dirty
```

```tsx
// apps/web/src/app/(app)/day/EditWaterForm.tsx, EditBeverageForm.tsx, EditActivityForm.tsx (novos, client)
// consumidos por AuxiliarySections.tsx modificado
```

### UI detalhes

- **`FoodItemRow` expandido**:
  - Se `day.status === 'closed'`: inputs `disabled` + dica "Dia encerrado é imutável; corrija via novo registro no dia atual" (SP-161).
  - Se `has_catalog && source ∈ {label_ocr, manual}`: inputs per-100g (`kcal`, `protein_g`, `carbs_g`, `fat_g`, `fiber_g`, micros, `serving_grams`).
  - Se `source ∈ {TBCA_2023, USDA_FDC}`: "Catálogo canônico — não editável" (sem inputs per-100g, mantém inputs de quantidade).
  - Estado inicial dos inputs = valores atuais; "Salvar" desabilitado até diff raso.
- **Server Action**: chama `editFoodItem` (se quantidade mudou) e/ou `editNutrientFact` (se per-100g mudou). Numa única chamada usa um payload combinado — decisão de implementação: dois PATCHs em sequência (mais simples, sem combinar).

## Modelo de dados

Sem mudança de schema — somente novas chamadas PATCH + lógica de propagação operando sobre tabelas existentes.

| Tabela | Colunas-chave mutadas | Quem muta |
|---|---|---|
| `food_items` | `grams`, `ml`, `quantity`, `unit`, `kcal`, `protein_g`, `carbs_g`, `fat_g`, `fiber_g`, micros, `source='user_corrected'`, `needs_confirmation=false`, `catalog_ref_id` | SP-160 (quantidade), SP-163 (propagação via fact) |
| `beverage_records` | `volume_ml`, macros materializados, `source='user_corrected'` | SP-165 (quantidade), SP-163 (propagação) |
| `water_records` | `volume_ml`, `source='user_corrected'` | SP-164 |
| `activity_records` | `duration_minutes`, `intensity`, `kcal_burned`, `met_value`, `calc_method` | SP-166 |
| `nutrient_facts` | `kcal`, `protein_g`, ..., `verified_by_user=true` | SP-162 |
| `audit_events` | nova linha por mutação (`action='correct'`/`'update'`, `actor='user'`) | SP-163, SP-164, SP-165, SP-166, SP-167 |
| `daily_snapshots` | `version = version + 1`, totais recompute | Via `DailyRecomputeService.recompute` |

## Fluxo de dados

### Editar quantidade de food_item (SP-160)
1. User expande linha em `/day` (ou `/day/[date]` aberto).
2. Altera `grams` no `EditFoodItemForm` → clica "Salvar".
3. Server Action `editFoodItem(itemId, {grams})` → `PATCH /records/food-items/{id}`.
4. Backend: `correction_ops.apply_food_change` recalcula `NutritionCalculator.compute(hit, grams, ml)`; `source='user_corrected'`; audit; `DailyRecomputeService.recompute(day_log_id)`.
5. Response 200 `{id, kcal, grams, ml}`.
6. Server Action: `revalidatePath('/day')` → server refetch → `DayView` re-render com novos totais.

### Editar per-100g do rótulo + propagação (SP-162 + SP-163)
1. User expande linha; altera `kcal` per-100g no `EditFoodItemForm`.
2. Server Action `editNutrientFact(factId, {kcal, protein_g, ...})` → `PATCH /nutrient-facts/{id}`.
3. Backend: atualiza `fact`, `verified_by_user=true`, audit `action='update'`.
4. `propagate(session, fact, user)`:
   - `SELECT` food_items vivos em dias abertos com `catalog_ref_id = fact.id`.
   - Para cada item: `NutritionCalculator.compute(hit=fact_atualizado, grams, ml)` → sobrescreve macros; `source='user_corrected'`; audit `action='correct'`.
   - `beverage_records` idem.
   - `day_log_id`s distintos → recompute.
   - Itens em dia fechado → `propagation_skipped`.
5. Response `{fact_out, propagated: [...], propagation_skipped: [...]}`.
6. Server Action: `revalidatePath('/day')` + se `propagated` inclui dia corrente, toast de confirmação; se só `skipped` em dia corrente, toast informativo.

### Editar água/bebida/atividade (SP-164/165/166)
1. User expande seção auxiliar; altera input no form apropriado.
2. Server Action → PATCH correspondente.
3. Backend: `correction_ops.apply_*_change`; audit; recompute.
4. Response → revalidate.

## Regras de negócio

1. **Dia fechado imutável** (INV-5): handler valida `day_log.status === 'open'` antes de mutar; UI desabilita inputs.
2. **LLM não calcula** (Const. Art. II §5): `NutritionCalculator`/`ActivityCalculator` determinísticos em todo PATCH.
3. **Recompute from-scratch** (INV-4, Const. Art. III §10): `DailyRecomputeService.recompute` ao fim de cada PATCH.
4. **Audit total** (INV-10, Const. Art. III §11): audit gravado antes do commit; por item propagado; por PATCH.
5. **Isolamento** (Const. Art. V §21): filtro `user_id == current_user.id` em todo SELECT de PATCH.
6. **Água ≠ bebida** (Const. Art. IV): PATCH water só `volume_ml`; PATCH beverage não toca `water_ml` (continua contribuindo para `other_liquids_ml` + `kcal_in`).
7. **Activity `kcal_burned` explícito** sobrescreve cálculo MET → `calc_method='user_manual'` (precedence SP-64). Sem peso → warning `weight_kg_required_for_kcal`, mantém valor.
8. **Fact canônico não editável** (SP-35): `source ∈ {TBCA_2023, USDA_FDC}` retorna 422 `not_editable`.
9. **Fact só descoberto no PATCH food-items**: o PATCH food-items atual (records.py:179) já tenta lookup TBCA e promove `catalog_ref_id` em item legado — esse comportamento é preservado, não duplicado.
10. **Aviso legal** (Const. Art. VII §26): não removido da UI ao editar; `<Disclaimer/>` permanece.

## Configurações e variáveis de ambiente

| Variável | Descrição | Padrão | Obrigatória |
|---|---|---|---|
| `INTERNAL_API_URL` | URL interna para Server Actions chamar backend (DNS interno do compose) | — | Sim (server) |

Sem novas variáveis — reusa infra existente.

## Referências de implementação

- **Endpoints PATCH existentes**: `apps/api/app/api/routes/records.py:121` (food-items), `apps/api/app/api/routes/nutrient_facts.py:48` (nutrient-facts, SP-33).
- **Lógica de correção (extraída em refactor)**: `apps/api/app/services/correction.py` → será reduzido a consumer de `correction_ops.py` (novo).
- **Recompute determinístico**: `apps/api/app/services/daily_recompute.py`, `nutrition_calculator.py`, `activity_calculator.py`.
- **Audit**: `apps/api/app/repositories/food.py::AuditEventRepository`.
- **UI Bloco 6 (a estender)**: `apps/web/src/app/(app)/day/FoodItemRow.tsx:1`, `MealSection.tsx`, `AuxiliarySections.tsx`, `DayView.tsx`, `types.ts`.
- **Front patterns (proxy/auth)**: `apps/web/src/proxy.ts:8` (`/day` em `PROTECTED_PREFIXES`).
- **Server Actions folder (padrão a definir)**: `apps/web/src/app/(app)/day/actions.ts` (novo — referência futura).
- **Spec contratual SDD**: `specs/002-edicao-inline-day/spec.md` (SP-160..169), `plan.md` (fases 0-5), `tasks.md` (T-B200..T-B250), `research.md` (ADR-013/014/015).
- **Tests backend existentes a manter verdes**: `tests/test_correction.py`, `tests/test_deletion.py`, `tests/test_label_catalog.py` (PATCH nutrient-facts).
- **Tests backend novos (alvo)**: `tests/test_patch_water.py`, `test_patch_beverage.py`, `test_patch_activity.py`, `test_nutrient_fact_propagation.py`.