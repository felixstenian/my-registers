# Critérios de Aceitação — Recuperação manual de itens sem catálogo

## AC-001 — Bloco de recovery aparece apenas quando há `no_catalog_hit` (SP-140)

**Dado que** o resultado de `MealService.create_from_llm` gerou warnings **sem** `no_catalog_hit`
**Quando** `message_formatter.compose_meal` roda
**Então** assistant message **não** contém "Sem catálogo para:".

**Dado que** o resultado tem 2 warnings `no_catalog_hit`
**Quando** compose roda
**Então** assistant message inclui bloco:
```
**Sem catálogo para:** {item1}, {item2}

- 📸 Enviar foto do rótulo — envie uma foto da tabela nutricional na próxima mensagem.
- ✏️ Cadastrar manualmente — clique para preencher os valores.
- ❌ Descartar item — responda `apaga {nome}`.
```
**E** aviso legal (Const. §26) permanece após o bloco.

**Notas**: T-B501 cobre isso com teste em `test_message_formatter.py`.

---

## AC-002 — Cadastro básico sem promoção (SP-141, RF-003, RF-005)

**Dado que** body:
```json
{"canonical_name": "pao_de_queijo_congelado", "display_name": "...", "basis": "per_100g", "kcal": 320, "protein_g": 8, "carbs_g": 40, "fat_g": 14}
```
**Quando** `POST /nutrient-facts/manual`
**Então** 201 com `{ id, canonical_name: "...", source: "user_manual", verified_by_user: true, promotion: null }`
**E** DB tem linha `nutrient_facts` com `source='user_manual'`, `verified_by_user=true`, `created_by=current_user.id`
**E** `audit_events` tem linha `entity_type='nutrient_fact', action='create', actor='user'`.

---

## AC-003 — Validação de payload (SP-141)

**Dado que** body com `canonical_name="pão-de-queijo"` (traço, não slug)
**Quando** POST
**Então** 422 com detalhe apontando canonical_name inválido.

**Dado que** body com `kcal=-10`
**Quando** POST
**Então** 422 (validação `≥ 0`).

**Dado que** body com `basis="per_serving"`
**Quando** POST
**Então** 422 (`Literal` só aceita `per_100g|per_100ml`).

---

## AC-004 — Promoção com item válido (SP-142, RF-009)

**Dado que** `food_item X` existe: pertence a `current_user`, `deleted_at IS NULL`, `catalog_ref_id IS NULL`, `kcal=0`, `grams=100`, dia aberto
**Quando** POST `/nutrient-facts/manual` com body inclui `promote_food_item_id=X.id`, `kcal=320`, `basis=per_100g`
**Então** 201 com `promotion.food_item_id = X.id`, sem warning
**E** DB:
- `nutrient_facts.novo_fact` criado com `source='user_manual'`
- `food_items.X.catalog_ref_id = novo_fact.id`
- `food_items.X.kcal = 320` (100g × 320/100)
- `food_items.X.needs_confirmation = false`
- `daily_snapshots.kcal_in` refletindo o valor novo
- 2 linhas em `audit_events`: uma `action='create'` no fact, uma `action='correct'` no food_item

---

## AC-005 — Promoção falha silenciosa: item de outro user (SP-142, RF-010)

**Dado que** `food_item Y` pertence a `other_user`
**Quando** `current_user` faz POST com `promote_food_item_id=Y.id`
**Então** 201 com `promotion.warning = 'promotion_failed'`
**E** fact criado normalmente (pertence a current_user)
**E** `food_items.Y` **inalterado**.

---

## AC-006 — Promoção falha silenciosa: item deletado (SP-142, RF-010)

**Dado que** `food_item Z` pertence a current_user mas `deleted_at != NULL`
**Quando** POST com `promote_food_item_id=Z.id`
**Então** 201 com `promotion.warning = 'promotion_failed'`
**E** fact criado; item continua deletado (não "revive").

---

## AC-007 — Sobrescrita de catalog_ref_id existente (SP-142, RF-011)

**Dado que** `food_item W` já tem `catalog_ref_id = fact_antigo.id` (ex.: promovido antes)
**Quando** POST com `promote_food_item_id=W.id` (novo fact)
**Então** 201 com `promotion.food_item_id=W.id`, sem warning
**E** `food_items.W.catalog_ref_id = novo_fact.id` (sobrescreveu)
**E** audit `action='correct'` grava `before.catalog_ref_id=fact_antigo.id, after.catalog_ref_id=novo_fact.id`
**E** macros recalculados via novo hit.

---

## AC-008 — Dia fechado bloqueia promoção mas fact é criado (SP-142, RF-012, INV-5)

**Dado que** `food_item V` pertence a current_user, `deleted_at IS NULL`, mas `day_log.status='closed'`
**Quando** POST com `promote_food_item_id=V.id`
**Então** fact criado (source='user_manual'), 201
**E** `food_items.V` inalterado
**E** `promotion.warning` presente (código exato: a confirmar; provável `conflict_closed_day` ou `promotion_failed` com sub-código).

**Notas**: T-B505 fecha o comportamento exato.

---

## AC-009 — Isolamento cross-user do catálogo (Const. §21, RNF-004)

**Dado que** user A cria fact `pao_de_queijo_congelado`
**Quando** user B envia mensagem "comi pão de queijo congelado"
**Então** `LocalTBCACatalog.lookup(...)` do B **não** encontra o fact de A
**E** cai em `no_catalog_hit` para B
**E** B pode cadastrar o próprio fact independentemente.

---

## AC-010 — Recompute automático após promoção bem-sucedida

**Dado que** promoção de `food_item X` foi feita com sucesso
**Quando** transação commita
**Então** `daily_snapshots.version` do dia do item incrementou
**E** `daily_snapshots.kcal_in` reflete novo kcal do item
**E** warnings do snapshot **removem** o `no_catalog_hit` daquele item (porque `catalog_ref_id` agora != NULL).

---

## AC-011 — Auditoria de create e correct

**Dado que** POST com promoção bem-sucedida
**Então** exatamente 2 linhas em `audit_events`:
1. `{entity_type: 'nutrient_fact', entity_id: novo_fact.id, action: 'create', actor: 'user'}`
2. `{entity_type: 'food_item', entity_id: item.id, action: 'correct', actor: 'user', before, after}`.

**Dado que** POST sem promoção
**Então** 1 linha em `audit_events` (só o `create` do fact).

---

## Cenários de borda

| Cenário | Comportamento esperado |
|---|---|
| Body sem `promote_food_item_id` (null / ausente) | Sucesso; só cria fact; `promotion: null` no body. |
| `promote_food_item_id` é UUID mas não existe | Warning `promotion_failed`. Fact criado. |
| `promote_food_item_id` = item que não é do user | Warning `promotion_failed`. Fact criado. |
| Fact com `canonical_name` já existente para o mesmo user | Decisão via ADR (spec §141): merge ou nova linha. Provável: idempotência por `canonical_name + created_by`. Confirmar em T-B505. |
| `aliases` com nomes já presentes em outro fact do mesmo user | Sem constraint; conflito de resolução resolvido por precedência (mais recente vence). |
| CHECK constraint bloqueia `source='user_manual'` (migration 0008 não aplicada) | 500 ou 422 dependendo do handler. Deploy tem que rodar migration antes do release. |
| Cliente frontend não passa `promote_food_item_id` para item recém-criado | Fact criado mas item legado permanece zerado. UX degradada. Frontend precisa passar SEMPRE quando disparado pelo prompt SP-140. |

## Critérios de não-funcionalidade

| Critério | Threshold | Fonte |
|---|---|---|
| Latência POST sem promoção P95 | ≤ 200ms | RNF-002 |
| Latência POST com promoção P95 | ≤ 400ms | RNF-002 |
| Cobertura de `test_manual_nutrient_facts.py` | 12 casos (gate T-B505) | RNF-003 |
| Atomicidade | 1 transação Postgres; rollback se erro fatal | RNF-001 |
| Isolamento | 100% queries filtram por `user_id`/`created_by` | RNF-004 |
