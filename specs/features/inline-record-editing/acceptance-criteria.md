# Critérios de Aceitação — Edição inline de registros na página `/day`

> **Rastreabilidade**: SP-160..SP-169, INV-14, INV-5 · Contratos: [`requirements.md`](./requirements.md), [`specifications.md`](./specifications.md).

## AC-001 — Editar quantidade de food_item inline (SP-160)

**Dado que** o usuário autenticado está em `/day` (dia `open`) e expande uma linha de `food_item`,
**Quando** altera `grams` (ou `ml`, ou `quantity`+`unit`) e clica "Salvar",
**Então** `PATCH /records/food-items/{id}` é chamado; backend recalcula macros via `NutritionCalculator`; grava `audit_events(action='correct', actor='user')`; chama `DailyRecomputeService.recompute`; UI revalida e mostra novos valores + totais.

**Dado que** o payload vem sem mudança real (mesmo valor),
**Quando** o PATCH é submetido,
**Então** retorna 200 sem recompute extra (idempotente — já implementado).

**Dado que** o item tem `catalog_ref_id=NULL`,
**Quando** PATCH com novo `grams`,
**Então** backend tenta lookup TBCA (records.py:179); se achar, promove `catalog_ref_id` e desmarca `needs_confirmation`; macros recomputados.

**Notas de validação:**
- Backend `records.py:121` já existe; esta AC valida UI + integração.

---

## AC-002 — Dia encerrado bloqueia edição (SP-161, INV-5)

**Dado que** o dia do item está `status='closed'`,
**Quando** o usuário expande a linha,
**Então** inputs renderizam `disabled` + dica "Dia encerrado é imutável; corrija via novo registro no dia atual".

**Dado que** bypass via API direta,
**Quando** `PATCH /records/food-items/{id}` com item em dia `closed`,
**Então** 409 `conflict_closed_day`; nada é mutado; snapshot version não incrementa.

**Notas de validação:**
- Mesmo AC reaplicado para PATCH water/beverage/activity (AC-007/008/009).

---

## AC-003 — Editar per-100g do nutrient_fact inline (SP-162)

**Dado que** o `food_item` expandido referencia um `nutrient_fact` com `source ∈ {label_ocr, manual}`,
**Quando** o usuário edita `kcal` (ou `protein_g`/`carbs_g`/`fat_g`/`fiber_g`/micros/`serving_grams`) e salva,
**Então** `PATCH /nutrient-facts/{id}` é chamado; `verified_by_user=true`; audit `action='update', actor='user'`.

**Dado que** o fact tem `source='TBCA_2023'` ou `'USDA_FDC'`,
**Quando** a UI renderiza o painel de edição,
**Então** exibe "Catálogo canônico — não editável" e **NÃO** renderiza inputs per-100g (apenas inputs de quantidade permanecem, pois food-item é editável).

**Dado que** bypass via API tentando PATCH fact TBCA,
**Quando** o PATCH chega,
**Então** 422 `not_editable` (já implementado em `nutrient_facts.py:62`).

---

## AC-004 — Propagação recalcula itens vivos (SP-163, INV-14)

**Dado que** um `nutrient_fact` foi atualizado via SP-162,
**Quando** o PATCH commita,
**Então** backend, na mesma transação:
1. `SELECT` todos `food_items` vivos (`deleted_at IS NULL`) com `catalog_ref_id = fact.id` em dias `status='open'`.
2. Para cada um: `NutritionCalculator.compute(hit=fact, grams, ml)` sobrescreve macros; `source='user_corrected'`; audit `action='correct'` `actor='user'` `entity_type='food_item'` before/after.
3. Idem para `beverage_records` vivos referenciando o fact.
4. `day_log_id`s distintos → `DailyRecomputeService.recompute(day_log_id)` cada um.

**Dado que** um item em dia `closed` referencia o fact,
**Quando** o PATCH commita,
**Então** o item **não** é mutado (INV-5); aparece em `propagation_skipped` com `reason='day_closed'`.

**Dado que** dois dias abertos têm itens referenciando o fact,
**Quando** a propagação roda,
**Então** os dois snapshots são recomputados; o response inclui ambos em `propagated`.

**Notas de validação:**
- Teste de integração com Postgres real (INV-14 — não mockar DB).
- Response shape: `NutrientFactOut` estendido com `propagated: []` e `propagation_skipped: []` (default `[]`).

---

## AC-005 — `PATCH /records/water/{id}` (SP-164)

**Dado que** o usuário edita `volume_ml` na seção Hidratação,
**Quando** envia o PATCH,
**Então** `water_records.volume_ml` atualiza; `source='user_corrected'`; audit `action='correct'` `actor='user'` `entity_type='water_record'`; `DailyRecomputeService.recompute(day_log_id)` roda.

**Dado que** a water_record não existe ou está `deleted_at IS NOT NULL`,
**Quando** o PATCH chama,
**Então** 404 `not_found`.

**Dado que** a water_record pertence a outro usuário,
**Quando** o PATCH chama,
**Então** 404 `not_found` (filtro `user_id` — Art. V §21; não revela existência).

**Dado que** o dia está `closed`,
**Quando** o PATCH chama,
**Então** 409 `conflict_closed_day`.

**Dado que** `volume_ml ≤ 0`,
**Quando** validação Pydantic,
**Então** 422 `validation_error`.

**Notas de validação:**
- Body Pydantic: `WaterPatch {volume_ml: int > 0}`.

---

## AC-006 — `PATCH /records/beverage/{id}` (SP-165)

**Dado que** o usuário edita `volume_ml` na seção Bebidas,
**Quando** envia o PATCH,
**Então** `beverage_records.volume_ml` atualiza; macros recomputados via `NutritionCalculator` a partir do `catalog_ref_id`; `source='user_corrected'`; audit; recompute.

**Dado que** a bebida tem `catalog_ref_id=NULL`,
**Quando** o PATCH com novo `volume_ml`,
**Então** macros ficam como estavam (sem fact para recalcular); warning `no_catalog_hit` no response.

**Dado que** drink é água pura (via bug),
**Quando** tentar PATCH em beverage_records,
**Então** deve falhar — invariant Art. IV: água vai em `water_records`, não `beverage_records` (prevenção no modelo).

**Notas de validação:**
- Body Pydantic: `BeveragePatch {volume_ml?: int > 0}`. Apenas `volume_ml` editável (per-100g do fact da bebida via SP-162 separado, fora desta UI na v1).

---

## AC-007 — `PATCH /records/activity/{id}` (SP-166)

**Dado que** o usuário edita `duration_minutes` e/ou `intensity` (sem `kcal_burned`),
**Quando** envia o PATCH,
**Então** se `user.weight_kg` está presente: `ActivityCalculator.compute` recalcula `kcal_burned` + `met_value`; `source`/audit/recompute.
**E** se `user.weight_kg === null`: warning `weight_kg_required_for_kcal` no response; `kcal_burned` mantém valor anterior; demais campos atualizam.

**Dado que** o usuário informa `kcal_burned` explicitamente,
**Quando** o PATCH commita,
**Então** `kcal_burned` sobrescreve o cálculo MET; `calc_method='user_manual'`; `met_value=NULL` (precedence SP-64).

**Dado que** o payload inclui `detected_name`,
**Quando** validação Pydantic,
**Então** 422 (campo não aceito).

**Dado que** `intensity` não é enum canônico,
**Quando** validação,
**Então** 422.

**Notas de validação:**
- Body Pydantic: `ActivityPatch {duration_minutes?, intensity?, kcal_burned?}`. `intensity: Literal['light','moderate','vigorous','unknown']`.

---

## AC-008 — Painel de edição no `FoodItemRow` (SP-167)

**Dado que** o usuário expande a linha de um food_item,
**Quando** o `<details>` abre (`onToggle`),
**Então** o `EditFoodItemForm` (client component) monta sem hidratar os outros 19 itens da página.

**Dado que** o form com estado inicial = valores atuais,
**Quando** nada foi alterado,
**Então** "Salvar" `disabled`.

**Dado que** o usuário altera `grams`,
**Quando** digita,
**Então** "Salvar" habilita.

**Dado que** o usuário clica "Salvar",
**Quando** o PATCH está em curso,
**Então** spinner no botão; inputs `disabled`.

**Dado que** o PATCH retorna 200,
**Quando** o server action finaliza,
**Então** `revalidatePath('/day')` dispara; o `<details>` recolhe; totais re-renderizados.

**Dado que** o PATCH retorna erro (ex.: 409),
**Quando** o server action finaliza,
**Então** erro inline `aria-live="polite"` com código estável mapeado para mensagem pt-BR.

**Dado que** o usuário clica "Cancelar",
**Quando** reverter,
**Então** inputs voltam ao estado inicial e `<details>` permanece aberto.

**Dado que** o foco está fora do painel e o usuário abre o `<details>`,
**Quando** expande,
**Então** foco automaticamente no primeiro input.

**Notas de validação:**
- A11y: `<label htmlFor>` associadas; `aria-live` em região de erro.

---

## AC-009 — Painéis nas seções auxiliares (SP-168)

**Dado que** o usuário expande um item em Hidratação,
**Quando** renderiza,
**Então** `EditWaterForm` com input `volume_ml`.

**Dado que** o usuário expande um item em Bebidas,
**Quando** renderiza,
**Então** `EditBeverageForm` com input `volume_ml`.

**Dado que** o usuário expande um item em Atividade,
**Quando** renderiza,
**Então** `EditActivityForm` com inputs `duration_minutes`, `intensity` (select pt-BR), `kcal_burned`.

**Dado que** o dia está `closed`,
**Quando** qualquer seção auxiliar expande,
**Então** inputs `disabled` + dica "Dia encerrado é imutável" (mesmo AC-002).

**Notas de validação:**
- `should` — pode ser adiado para v2 se pressão de entrega.

---

## AC-010 — Revalidação e toast informativo (SP-169)

**Dado que** o usuário edita no `/day` (dia atual),
**Quando** a server action finaliza,
**Então** `revalidatePath('/day')` re-renderiza e totais atualizam.

**Dado que** a edição afetou apenas o dia atual,
**Quando** finaliza,
**Então** nenhum toast extra (default).

**Dado que** a propagação afetou um dia diferente do corrente (SP-163 cross-day),
**Quando** finaliza,
**Então** toast "Itens de outros dias também foram atualizados" + link ao primeiro `day_log` afetado.

**Notas de validação:**
- `should` — pode simplificar para só refresh sem toast na v1.

---

## AC-011 — Aviso legal mantido (Const. Art. VII §26)

**Dado que** qualquer edição foi aplicada,
**Quando** a página re-renderiza,
**Então** `<Disclaimer/>` continua visível no rodapé.

---

## Cenários de Borda

| Cenário | Comportamento Esperado |
|---|---|
| PATCH food-item com `grams=0` | 422 — `Field(gt=0)` |
| PATCH nutrient-fact com `kcal=null` | 422 — `Field(ge=0)` requer número |
| PATCH water com `volume_ml=0` | 422 — `Field(gt=0)` |
| PATCH activity com `kcal_burned=-5` | 422 — `Field(ge=0)` |
| PATCH beverage sem `volume_ml` (vazio) | 200 sem efeito (não muta) — ou 422 se design escolher exigir |
| PATCH food-item com `unit='concha'` | 200 — qualquer string aceita |
| PATCH nutrient-fact com `source='manual'` e `verified_by_user=false` prévio | Após PATCH, `verified_by_user=true` |
| Propagação com 50+ itens | Ainda ≤ 300ms P95 (RNF-001); EVITAR timeout na transação |
| Edição de fact compartilhado por 2 dias abertos | Ambos snapshots recomputados; ambos em `propagated` |
| Edição de fact só referenciado em dia fechado | `propagated=[]`, `propagation_skipped=[...]` |
| `<details>` aberto do item afetado pela propagação | Após revalidate, valores do item atualizam sozinhos |
| Usuário edita `grams` + `kcal` per-100g no mesmo save | Dois PATCHs em sequência: `editFoodItem` + `editNutrientFact` (decisão de implementação) |
| Server Action retorna 401 (cookie expirado) | Erro `unauthorized` mapeado para "Sessão expirada, recarregue" |

## Critérios de Não-Funcionalidade

| Critério | Threshold |
|---|---|
| PATCH P95 (any kind) | ≤ 300ms incl. recompute |
| Audit sempre gravado antes do commit | INV-10 |
| `user_id` no WHERE | Obrigatório (Art. V §21) |
| Nenhum cálculo via LLM | INV-1, Art. II §5 |
| Snapshot recompute from-scratch | INV-4, Art. III §10 |
| Dia `closed` → 409 antes de mutar | INV-5 |
| Lazy mount do form (só no `<details>` aberto) | RNF-009 |
| `aria-live` para erros | RNF-010 |
| Disclaimer permanece | Const. Art. VII §26 |
| Server Actions usam `INTERNAL_API_URL` | RNF-008 |