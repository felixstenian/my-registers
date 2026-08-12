# Tasks — Edição inline de registros na página `/day`

**Feature ID:** 002-edicao-inline-day
**Depende de:** [`spec.md`](spec.md), [`plan.md`](plan.md), [`../../.specify/memory/constitution.md`](../../.specify/memory/constitution.md)

---

## Regras deste documento

- Cada tarefa tem ID `T-B2XXX` estável (B2 = Bloco 2 desta feature).
- Uma tarefa é **atômica**: entrega em ≤ 1 dia, em 1 PR pequeno.
- Cada tarefa referencia: os `SP-XX` que atende, arquivos-chave, dependências (`blocked_by`), critério de aceite.
- Status: `todo` · `in_progress` · `done` · `blocked` · `deferred`.
- Tamanho: **S** (≤ 2h) · **M** (½ dia) · **L** (1 dia).

---

## Fase 0 — Refactor: extrair `correction_ops` ⬜

Status: **todo**. Destrava a Fase 1 sem duplicar a lógica de correção já testada no fluxo de chat.

- [ ] **T-B200** — Extrair `correction_ops.py` a partir de `services/correction.py`. (S) — refactor; nenhum SP novo direto, mas habilita SP-164/165/166.
  - Arquivos: novo `apps/api/app/services/correction_ops.py`;修改 `apps/api/app/services/correction.py` para consumir as funções extraídas.
  - Funções puras por tipo: `apply_water_change(record, *, volume_ml)`, `apply_beverage_change(record, *, volume_ml, session)`, `apply_activity_change(record, *, duration_minutes?, intensity?, kcal_burned?, user)`. Cada uma devolve `dict[str, tuple[before, after]]` (mesmo shape que `CorrectionService` usa hoje) + `warnings`.
  - `blocked_by`: nenhum.
  - **Aceite:** `tests/test_correction.py` (do fluxo chat) continua 100% verde sem alteração de teste; `correction.py` sem lógica duplicada.

---

## Fase 1 — Backend: PATCH water/beverage/activity ⬜

Status: **todo**. Meta: três novos endpoints REST de edição, reusando `correction_ops`.

- [ ] **T-B210** — `PATCH /records/water/{id}`. (S) — SP-164.
  - Arquivos: `apps/api/app/api/routes/records.py`, schemas `WaterPatch`/`RecordSummary` (reusar `RecordSummary`).
  - Body: `{volume_ml: int > 0}`. Valida `user_id` (Art. V §21), 404 se deletado/inexistente, 409 `conflict_closed_day` (INV-5). `source='user_corrected'`, audit `action='correct'` `actor='user'`, `DailyRecomputeService.recompute`.
  - `blocked_by`: T-B200.
  - **Aceite:** integração `test_patch_water.py` — happy path, 404, 409 closed, cross-user isolation (404), recompute ocorre (snapshot `version` incrementa), audit gravado.

- [ ] **T-B211** — `PATCH /records/beverage/{id}`. (M) — SP-165.
  - Arquivos: `records.py`, `BeveragePatch`. Body: `{volume_ml?: int > 0}`. Reusa `correction_ops.apply_beverage_change` (recompute macros via `NutritionCalculator` a partir do fact referenciado). Resto igual a T-B210.
  - `blocked_by`: T-B200.
  - **Aceite:** `test_patch_beverage.py` — happy com recompute de macros (fact per-100ml), 404, 409, isolation, audit, snapshot. Inclui caso beverage sem `catalog_ref_id` (macros ficam como estavam — warning `no_catalog_hit`).

- [ ] **T-B212** — `PATCH /records/activity/{id}`. (M) — SP-166.
  - Arquivos: `records.py`, `ActivityPatch`. Body: `{duration_minutes?, intensity?, kcal_burned?}`. Reusa `correction_ops.apply_activity_change`. `kcal_burned` explícito → `calc_method='user_manual'`, `met_value=NULL`. Sem `kcal_burned` + sem `weight_kg` → warning `weight_kg_required_for_kcal`. `detected_name` não editável (400 se vier no body).
  - `blocked_by`: T-B200.
  - **Aceite:** `test_patch_activity.py` — happy (recompute por MET), `user_manual` path, sem peso (warning + mantém kcal), 404/409/isolation/audit/snapshot.

**Gate Fase 1 — cumprido:** SP-164/165/166 verdes em integração; checklist §4 verde; `correction.py` do chat intacto.

---

## Fase 2 — Backend: propagação do nutrient_fact ⬜

Status: **todo**. Núcleo da feature (INV-14).

- [ ] **T-B220** — `services/nutrient_fact_propagation.py`. (M) — SP-163, INV-14.
  - Arquivos: novo `apps/api/app/services/nutrient_fact_propagation.py`; extensão de `apps/api/app/api/routes/nutrient_facts.py` (chamar no fim do PATCH).
  - Função `propagate(session, fact, user) -> PropagationResult{propagated, skipped}`:
    1. `SELECT food_items WHERE catalog_ref_id = fact.id AND deleted_at IS NULL` + JOIN `food_records` + `day_logs` (status='open').
    2. Para cada item: `NutritionCalculator.compute(hit=fact, grams, ml)` → sobrescreve macros; `source='user_corrected'`; audit `action='correct'` `actor='user'` `entity_type='food_item'`.
    3. Idem `beverage_records`.
    4. `day_log_id`s distintos → `DailyRecomputeService.recompute` cada um.
    5. Itens em dias `closed` → `skipped` com `reason='day_closed'` (não mutam — INV-5).
  - Response do `PATCH /nutrient-facts/{id}` adiciona `propagated: []` e `propagation_skipped: []` (default `[]` — não quebra clientes antigos).
  - `blocked_by`: nenhum (independente da Fase 1).
  - **Aceite:** `test_nutrient_fact_propagation.py` — cenário INV-14: 2 days abertos (3 items) + 1 day fechado (1 item) referenciando o fact; após PATCH, 3 items recomputeados + 3 snapshots atualizados + 1 skipped; audit gravado por item; day fechado imutável. Cobertura ≥ 90% do módulo.

**Gate Fase 2 — cumprido:** SP-163 + INV-14 verdes; ADR-013 aceito em `research.md`.

---

## Fase 3 — UI: painel de edição food_item ⬜

Status: **todo**. Frontend da motivação principal.

- [ ] **T-B230** — Server Actions para edições. (S) — SP-169.
  - Arquivos: novo `apps/web/src/app/(app)/day/actions.ts` com server actions `editFoodItem`, `editNutrientFact`, `editWater`, `editBeverage`, `editActivity`. Cada uma faz fetch server-side para o PATCH via `INTERNAL_API_URL`, repassa cookies, e chama `revalidatePath('/day')` + `revalidatePath('/day/[date]')`. Retorna `{ok, error?}` tipado.
  - `blocked_by`: T-B210, T-B211, T-B212, T-B220 (todos os endpoints prontos).
  - **Aceite:** action `editFoodItem` executável a partir de um client component; revalida a rota (next.js cache invalidado); erro 409 bubbles como `{ok:false, error:'conflict_closed_day'}`.

- [ ] **T-B231** — `EditFoodItemForm` (client) dentro de `FoodItemRow`. (M) — SP-160, SP-161, SP-162, SP-167.
  - Arquivos: split `FoodItemRow.tsx` → mantém shell server + cria `EditFoodItemForm.tsx` (`'use client'`), montado só quando `<details>` `open` (via `onToggle`). Formulário com inputs `grams`/`ml` (ou `quantity`/`unit`) e, se `has_catalog && source ∈ {label_ocr, manual}`, inputs per-100g (`kcal`, `protein_g`, `carbs_g`, `fat_g`, `fiber_g`, micros, `serving_grams`). Se `source ∈ {TBCA_2023, USDA_FDC}` mostra "Catálogo canônico — não editável" (sem inputs per-100g).
  - Estado inicial dos inputs = valores atuais; botão "Salvar" desabilitado até diff raso. `useFormState`/`useActionState` chamando `editFoodItem`/`editNutrientFact`. Loading state, erro inline (`aria-live`), sucesso colapsa + revalida.
  - Dia `closed` (vindo do `DaySnapshot.status` via prop): inputs desabilitados + dica "Dia encerrado é imutável".
  - `blocked_by`: T-B230.
  - **Aceite manual:** (1) editar grams de um item → totais atualizam; (2) editar kcal do fact → item + totais atualizam e itens do mesmo rótulo em outro dia aberto também (testar com 2 days); (3) dia fechado → sem inputs; (4) fact TBCA → sem inputs per-100g; (5) a11y: foco no 1º input ao abrir, erro anunciado.

**Gate Fase 3 — cumprido:** SP-160/161/162/167/169 aceitos; `pnpm --filter web typecheck`/`lint`/`build --webpack`/`verify:sw` verdes.

---

## Fase 4 — UI: seções auxiliares ⬜

Status: **todo**.

- [ ] **T-B240** — `EditWaterForm`, `EditBeverageForm`, `EditActivityForm` (client) em `AuxiliarySections.tsx`. (M) — SP-168.
  - Arquivos: refatorar `AuxiliarySections.tsx` para expandir `<details>` em cada seção (igual `FoodItemRow`) e injetar os três forms. `EditWaterForm`: `volume_ml`. `EditBeverageForm`: `volume_ml`. `EditActivityForm`: `duration_minutes`, `intensity` (select), `kcal_burned`.
  - Mesmas garantias de SP-161 (dia fechado desabilita) e SP-167 (loading/erro/sucesso, a11y).
  - `blocked_by`: T-B230, T-B231.
  - **Aceite manual:** editar volume de água/bebida e duration/intensity/kcal de atividade; totais revalidam; dia fechado bloqueia.

**Gate Fase 4 — cumprido:** SP-168 aceito; build/lint/typecheck/verify:sw verdes.

---

## Fase 5 — Hardening + gates finais ⬜

Status: **todo**.

- [ ] **T-B250** — Testes de regressão + auditoria de gates. (S) — cobertura INV-1/4/5/10/14.
  - Re-roda `tests/` do backend; garante que `test_correction.py` (chat) e `test_deletion.py` continuam verdes (refactor T-B200 não regression).
  - Verifica INV-5 (PATCH em dia fechado → 409 em todos os 4 tipos) num único teste parametrizado.
  - Documenta steps de teste manual final (cenários do §2.2 da spec) num bloco no `CHANGELOG.md` ou `docs/fase-edicao-inline.md`.
  - `blocked_by`: T-B231, T-B240.
  - **Aceite:** CI verde (jobs `api` + `web`); cobertura ≥ 90% em `correction_ops.py` e `nutrient_fact_propagation.py`; checklist §4 do `plan.md` assinalado.

**Gate Fase 5 — feature entregue.**

---

## Resumo de dependências

```
T-B200 ─┬─> T-B210 ─┐
        ├─> T-B211 ─┤─> T-B230 ─┬─> T-B231 ─> T-B240 ─> T-B250
        └─> T-B212 ─┘           │
T-B220 ──────────────────────────┘
```