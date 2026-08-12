# Requisitos — Edição inline de registros na página `/day`

> **Rastreabilidade**: SP-160..SP-169, INV-14 em [`specs/002-edicao-inline-day/spec.md`](../../002-edicao-inline-day/spec.md) (SDD rascunho) · Constituição Art. II §5, III §10-11, V §21, VII §26, VIII §28 · Estende [`daily-detail-view`](../daily-detail-view/requirements.md) (Bloco 6 — página `/day` read-only v1).
> **Status**: documented-only (spec escrita, implementação pendente).

## Visão geral

Edição inline dos registros na página `/day` (e `/day/[date]` em dia aberto): o usuário expande a linha de um item e ajusta, sem sair da página e sem usar o chat, (a) a **quantidade** consumida (grams/ml/quantity/unit para food; volume_ml para water/beverage; duration/intensity/kcal_burned para activity) e (b) os valores **per-100g/per-100ml** do `nutrient_fact` referenciado (quando `source ∈ {label_ocr, manual}`). O backend já oferece `PATCH /records/food-items/{id}` e `PATCH /nutrient-facts/{id}` (SP-33); faltam `PATCH` para water/beverage/activity, a **propagação** da edição do `nutrient_fact` aos `food_items`/`beverage_records` que o referenciam (bug emergente: hoje editar o rótulo não corrige o item já consumido), e a UI inline. Correções via chat (SP-70..SP-74) continuam válidas e unchanged.

Motivador: em produção, ao registrar iogurte por foto de rótulo, valores `kcal` per-100g lidos pela LLM vieram incorretos. O usuário vê o erro ao expandir o item no `/day`, mas hoje precisa voltar ao chat e redigir uma frase de correção — caminho incerto (SP-71, matching ambíguo). A edição inline existe para fechar esse loop de confiança.

## Requisitos funcionais

| ID | Requisito | SP | Prioridade |
|---|---|---|---|
| RF-001 | Editar quantidade do food_item inline. `PATCH /records/food-items/{id}` (backend já existe) com `grams`/`ml`/`quantity`/`unit`. Recalcula macros via `NutritionCalculator`, grava `audit_events(action='correct', actor='user')`, chama `DailyRecomputeService.recompute`. UI revalida a página. | SP-160 | Must Have |
| RF-002 | Dia `status='closed'` é imutável (INV-5): painel de edição **não** exibe inputs (render read-only + dica); backend retorna 409 `conflict_closed_day` se bypassado. | SP-161, INV-5 | Must Have |
| RF-003 | Editar per-100g do nutrient_fact inline. `PATCH /nutrient-facts/{id}` (SP-33, backend já existe). Marca `verified_by_user=true`, grava audit `action='update'`. Facts `source ∈ {TBCA_2023, USDA_FDC}` não são editáveis (422 `not_editable`); UI esconde inputs e mostra "Catálogo canônico — não editável". | SP-162 | Must Have |
| RF-004 | **Propagação (núcleo)** — após SP-162 commitar, backend recomputa todos os `food_items` e `beverage_records` vivos (`deleted_at IS NULL`) em dias abertos que referenciam o fact; `source='user_corrected'`; audit por item; `DailyRecomputeService.recompute` por `day_log_id` distinto. Itens em dia `closed` pulam (INV-5) e aparecem em `propagation_skipped` no response. | SP-163, INV-14 | Must Have |
| RF-005 | `PATCH /records/water/{id}` — body `{volume_ml: int > 0}`. `source='user_corrected'`, audit, recompute. 404 se inexistente/deletado, 409 se dia fechado, filtro por `user_id`. | SP-164 | Must Have |
| RF-006 | `PATCH /records/beverage/{id}` — body `{volume_ml?: int > 0}`. Recalcula macros via `NutritionCalculator` a partir do fact referenciado. Resto igual a RF-005. | SP-165 | Must Have |
| RF-007 | `PATCH /records/activity/{id}` — body `{duration_minutes?, intensity?, kcal_burned?}`. `kcal_burned` explícito → `calc_method='user_manual'`, `met_value=NULL`. Sem `kcal_burned` + sem `weight_kg` → warning `weight_kg_required_for_kcal`, mantém valor anterior. `detected_name` não editável. | SP-166 | Must Have |
| RF-008 | Painel de edição dentro da expansão do `FoodItemRow` (SP-152). Inputs `grams`/`ml` (ou `quantity`/`unit`) + (se `has_catalog && source ∈ {label_ocr, manual}`) inputs per-100g. Botão "Salvar" desabilitado até diff raso; "Cancelar" reverte. Estados loading/erro/sucesso com `aria-live`. Foco no primeiro input ao abrir. | SP-167 | Must Have |
| RF-009 | Painéis de edição nas seções auxiliares (`AuxiliarySections.tsx` — SP-153) para water (`volume_ml`), beverage (`volume_ml`), activity (`duration_minutes`, `intensity` select, `kcal_burned`). Mesmas garantias de RF-002 (dia fechado desabilita) e RF-008 (loading/erro/sucesso, a11y). | SP-168 | Should Have |
| RF-010 | Revalidação pós-edição: Server Actions chamam `revalidatePath('/day')` e `revalidatePath('/day/[date]')`; totais e snapshot atualizam sem refresh manual. Se dia corrente não está entre os afetados pela propagação (raro), toast informativo + link ao primeiro `day_log` afetado. | SP-169 | Should Have |

## Requisitos não funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | Latência P95 do PATCH (qualquer tipo) ≤ 300ms, incluindo recompute. | Performance |
| RNF-002 | Toda mutação grava `audit_events` antes do commit (INV-10, Const. Art. III §11). | Auditoria |
| RNF-003 | `user_id` no `WHERE` de toda query de mutação (Const. Art. V §21). | Segurança |
| RNF-004 | Dia `closed` retorna 409 (INV-5) — validado antes de mutar. | Segurança |
| RNF-005 | Aviso legal (Const. Art. VII §26) permanece visível no `/day` após edição. | Conformidade |
| RNF-006 | Nenhuma soma nutricional via LLM — só `NutritionCalculator`/`ActivityCalculator` (Const. Art. II §5). | Determinismo |
| RNF-007 | Snapshot recomputa from-scratch, não delta (Const. Art. III §10, INV-4). | Determinismo |
| RNF-008 | Edição inline usa Server Actions via `INTERNAL_API_URL` — não expõe `NEXT_PUBLIC_API_URL` para mutação (padrão do repo). | Segurança/Infra |
| RNF-009 | `EditFoodItemForm` (client) só monta quando `<details>` está aberto (lazy mount) — preserva benefício zero-JS do SP-152 quando recolhido. | Performance |
| RNF-010 | A11y: `<label>`s associadas, foco no 1º input, `aria-live` para erros, `disabled` em dia fechado. | Acessibilidade |

## Restrições e premissas

- **Estende Bloco 6** (`daily-detail-view`) — a decisão 9 do trade-offs daquele bloco ("read-only v1, exceção: confirm/close") é **suplantada** por esta feature. A suplementação é explícita: mutações de valor (quantidade/per-100g) agora são inline; remoção continua via chat (SP-80..SP-82) ou futura feature.
- **Especificado em SDD** em [`specs/002-edicao-inline-day/`](../../002-edicao-inline-day/spec.md) (`spec.md`, `plan.md`, `tasks.md`, `research.md` com ADR-013/014/015). Esta pasta é a visão por-feature; a SDD é fonte contratual.
- **Só dias abertos** são mutáveis (INV-5). `/day/[date]` em dia `closed` renderiza painel read-only.
- **Backend já existe** para SP-160 (PATCH food-items, records.py:121) e SP-162 (PATCH nutrient-facts, nutrient_facts.py:48). SP-163 (propagação — INV-14) e SP-164/165/166 são novos.
- **Fora do escopo** (por design, especificado em spec 002 §7): editar `detected_name`/`normalized_name` inline (continua via chat — SP-70..72 faz matching por nome); editar per-100g de bebidas inline (só `volume_ml`); edição em lote; undo; histórico de versões navegável na UI.
- Água ≠ outros líquidos (Const. Art. IV): PATCH water só `volume_ml`; PATCH beverage nunca toca `water_ml`.
- **Timezone**: a regra do SP-92 ("dia" = `users.timezone`) continua — não há mudança de "data efetiva" da mutação porque só dias abertos são mutáveis.

## Dependências

**Depende de:**
- [`daily-detail-view`](../daily-detail-view/requirements.md) — `FoodItemRow`/`MealSection`/`AuxiliarySections`/`DayView`/`DayNavigator` (esta feature estende esses componentes com painéis de edição).
- [`daily-snapshot`](../daily-snapshot/requirements.md) — `GET /days/today` e `GET /days/{date}`; `DaySnapshot` shape consumido pela UI.
- [`record-correction`](../record-correction/requirements.md) — lógica de recompute em `correction.py`; extraída para `correction_ops.py` (ADR-015) consumida pelos novos PATCH REST.
- [`food-logging`](../food-logging/requirements.md) — `food_items` shape (`catalog_ref_id`, `source`, `needs_confirmation`/`has_catalog`).
- [`nutrition-label-ocr`](../nutrition-label-ocr/requirements.md) — `PATCH /nutrient-facts/{id}` base (SP-33); esta feature adiciona a propagação.
- [`audit-trail`](../audit-trail/requirements.md) — `audit_events(action='correct'/'update', actor='user')`.
- Fase 1 (`authentication-session`) — `proxy.ts` protege `/day`.

**Requerido por:**
- Sem dependentes diretos — é camada de mutação/UI.
- Pode habilitar futuro "undo inline" e "excluir inline" — não mapeados ainda.