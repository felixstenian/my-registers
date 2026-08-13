# Implementation Plan — Edição inline de registros na página `/day`

**Feature ID:** 002-edicao-inline-day
**Owner:** Felix
**Depende de:** [`spec.md`](spec.md) v1.0, [`../../.specify/memory/constitution.md`](../../.specify/memory/constitution.md) v1.0.0
**Referencia:** [`../001-mvp-registro-diario/plan.md`](../001-mvp-registro-diario/plan.md) — fases 4/4.b/7 entregaram os PATCH food-items e nutrient-facts aqui reutilizados.

---

## Regras deste documento

- Descreve **como** implementar o que está em `spec.md`, sem duplicar decisões da spec.
- Não duplica `app_plan.md` (fonte canônica de arquitetura) — apenas mapeia SP-XX → arquivos/ordem/gates.
- Alterações neste arquivo requerem PR próprio (`plan:`).

---

## 1. Mapa SP-XX → arquivos

| SP | Área | Arquivos-chave | Status backend |
|----|------|----------------|----------------|
| SP-160 | Editar qtd food_item | `apps/api/app/api/routes/records.py:121` (PATCH food-items, **já existe**), `apps/api/app/services/nutrition_calculator.py` | ✅ backend; ❌ UI |
| SP-161 | Dia fechado imutável (UI + 409) | `apps/web/src/app/(app)/day/FoodItemRow.tsx`, `records.py:155` | ✅ backend; ❌ UI |
| SP-162 | Editar per-100g do fact (UI) | `apps/api/app/api/routes/nutrient_facts.py:48` (PATCH, **já existe** SP-33) | ✅ backend; ❌ UI |
| SP-163 | Propagação fact → registros vivos | `nutrient_facts.py` (extensão), novo `apps/api/app/services/nutrient_fact_propagation.py` | ❌ novo |
| SP-164 | PATCH /records/water/{id} | `records.py`, reusa lógica de `correction.py::_apply_water_changes` | ❌ novo |
| SP-165 | PATCH /records/beverage/{id} | `records.py`, reusa `correction.py::_apply_beverage_changes` | ❌ novo |
| SP-166 | PATCH /records/activity/{id} | `records.py`, reusa `correction.py::_apply_activity_changes` | ❌ novo |
| SP-167 | UI edit na expansão food_item | `FoodItemRow.tsx` → split client/server, novo `EditFoodItemForm.tsx` (client) | ❌ novo |
| SP-168 | UI edit seções auxiliares | `AuxiliarySections.tsx`, novos `EditWaterForm`/`EditBeverageForm`/`EditActivityForm` | ❌ novo |
| SP-169 | Revalidação pós-edição | Server Actions em `apps/web/src/app/(app)/day/actions.ts` | ❌ novo |

### Refatoração necessária (DRY backend)

A lógica de correção hoje está acoplada ao fluxo de chat em `services/correction.py` (`_apply_water_changes`, `_apply_beverage_changes`, `_apply_activity_changes` recebem um `changes dict`no formato LLM). Os novos PATCH REST reusansem a essência mas recebem payloads Pydantic tipados. **Decisão:** extrair funções puras por tipo em `app/services/correction_ops.py` (sem dependência de `LLMEnvelope`), consumidas tanto por `CorrectionService` (chat) quanto pelos novos handlers REST. Evita duplicação e mantém o chat intacto. (Ver ADR-013 em `research.md` para a propagação.)

---

## 2. Ordem de execução (Fases)

| Fase | Nome | Estim. | Entrega os SPs |
|------|------|--------|----------------|
| 0 | Backend: extração de `correction_ops` | ½d | (refactor — não cobre SP novo diretamente; destrava Fase 1) |
| 1 | Backend: PATCH water/beverage/activity | 1d | SP-164, SP-165, SP-166 |
| 2 | Backend: propagação do nutrient_fact | 1d | SP-163, INV-14 |
| 3 | UI: painel de edição food_item | 1d | SP-160, SP-161, SP-162, SP-167, SP-169 |
| 4 | UI: seções auxiliares | 1d | SP-168 |
| 5 | Testes ponta-a-ponta + gates | ½d | cobertura INV-1/4/5/10/14 |

Total: ~5 dias úteis.

---

## 3. Gates de fase

Cada fase éconsiderada **entregue** quando:

1. Todos os SPs `must` da fase têm teste automatizado verde (unit de service + integração ponta-a-ponta route → service → DB).
2. Nenhum artigo da Constituição violado (checklist §4 abaixo).
3. Nenhuma alteração de spec sem PR próprio.
4. `git log` do PR referencia os SPs cobertos (ex.: `feat(fase-1): SP-164 SP-165 SP-166 - PATCH water/beverage/activity`).
5. Lint + typecheck + (backend) mypy/ruff + (frontend) `verify:sw` verdes no CI.

---

## 4. Checklist de conformidade constitucional

Aplicado em todo PR que toca código de negócio:

- [ ] Nenhuma soma nutricional passou pela LLM (Art. II §5) — PATCHs usam `NutritionCalculator`/`ActivityCalculator`.
- [ ] Snapshot recomputa from-scratch, não delta (Art. III §10) — `DailyRecomputeService.recompute` em todo PATCH.
- [ ] `audit_events` gravado em toda mutação, **antes** do commit (Art. III §11, INV-10).
- [ ] Água e outros líquidos separados (Art. IV) — PATCH water só `volume_ml`; PATCH beverage não toca `water_ml`.
- [ ] `user_id` no filtro de toda query de mutação (Art. V §21).
- [ ] Nenhum segredo em código/logs/response (Art. V §19).
- [ ] Aviso legal permanece no `/day` (Art. VII §26) — edição não remove o `<Disclaimer/>`.
- [ ] Dia fechado é imutável no path testado (Art. VIII §28, INV-5).
- [ ] Edição de `nutrient_fact` propaga a registros vivos em dias abertos (INV-14) — nunca a dias fechados.

---

## 5. Decisões técnicas SDD-específicas

### 5.1 Estrutura de branches

- `feat/bloco-edicao-inline-fase-N` por fase (mesma convenção do MVP).
- Merge para `dev`/`main` requer gates §3 + checklist §4.

### 5.2 Convenção de commits

Conventional Commits + SPs no primeiro parágrafo:

```
feat(fase-1): SP-164 SP-165 SP-166 - PATCH water/beverage/activity

Extrai correction_ops e adiciona endpoints REST de edição para
água, bebida e atividade. Reusa NutritionCalculator/ActivityCalculator.
Refs: spec 002 §3.3, constitution Art. II/V/III
```

### 5.3 Testes obrigatórios por camada

- **INV-14** → integração com Postgres real (cria fact, 2 food_items em 2 dias abertos + 1 em dia fechado, PATCH fact, verifica propagação completa + skip do fechado + snapshots atualizados).
- **SP-160..SP-166 `must`** → unit de service (`correction_ops`/`nutrient_fact_propagation`) + integração route → DB (201路径 do PATCH).
- **SP-167..SP-169** → teste manual (UI) — sem suite E2E automatizada no MVP; documentar steps de verificação em `tasks.md`.
- Cobertura alvo: ≥ 90% em `correction_ops.py` e `nutrient_fact_propagation.py` (paridade com `nutrition_calculator.py`).

### 5.4 PWA / Service Worker

O SW já aplica `NetworkOnly` em `/api/*` (INV-11 — nunca cachear resposta de negócio). Esta feature não introduz novas rotas estáticas; `verify:sw` continua verde. Nenhuma mudança em `sw.ts`.

### 5.5 Server Components vs Client

`FoodItemRow` hoje é server component (zero JS). O painel de edição **exige interatividade**. Decisão: manter `FoodItemRow` como server (render da expansão read-only) e injetar um **client component** `EditFoodItemForm` dentro do `<details>` —_ONLY-MOUNTED quando o `<details>` abre (via `onToggle`) para evitar hidratação de todos os forms da página. Ver ADR-014alternativa discutida em `research.md`.