# Especificações Técnicas — Recuperação manual de itens sem catálogo

> **Fontes autoritativas nesta árvore** (`docs/enhancement`): `specs/001-mvp-registro-diario/spec.md §3.14`, `tasks.md § Bloco 5`.
> **Fontes de implementação** (na branch `feat/bloco-5-catalog-recovery`, não aqui): `apps/api/app/api/routes/nutrient_facts.py` (POST /manual), `apps/api/app/schemas/nutrient_facts.py` (ManualNutrientFactIn), `apps/api/app/services/nutrient_facts.py` ou reuso de `label_catalog.py`, `apps/web/src/components/ManualCatalogForm.tsx`, `apps/web/src/components/AssistantContent.tsx`.
> **Modelo já existente nesta árvore**: `apps/api/app/models/nutrient_fact.py`.
>
> **Marcações**: `[Implementação em feat/bloco-5-catalog-recovery]` = a peça descrita já foi planejada; verifique a branch para confirmação. `[Ainda no spec, sem código]` = concebida mas não codificada em nenhuma branch conhecida.

## Escopo técnico

Duas mudanças distintas empacotadas juntas:

1. **UX (SP-140, T-B501)** — o composer `message_formatter.compose_meal` ganha um bloco extra quando o payload de recompute contém warnings `no_catalog_hit`.
2. **Backend + UI (SP-141/SP-142, T-B502..B507)** — nova rota, novo schema, nova migration, novo form no frontend.

## Endpoints / Interface

### `POST /nutrient-facts/manual` [Implementação em feat/bloco-5-catalog-recovery]

- **Auth**: `access_token` válido (via `Depends(get_current_user)`).
- **Content-Type**: `application/json`.
- **Body (`ManualNutrientFactIn`, planejado)**:
  ```json
  {
    "canonical_name": "pao_de_queijo_congelado",
    "display_name": "Pão de queijo congelado",
    "brand": "Forno de Minas",
    "basis": "per_100g",
    "kcal": 320,
    "protein_g": 8,
    "carbs_g": 40,
    "fat_g": 14,
    "fiber_g": 0.5,
    "sodium_mg": 380,
    "calcium_mg": null,
    "iron_mg": null,
    "potassium_mg": null,
    "aliases": ["pao de queijo", "pao_queijo"],
    "promote_food_item_id": "d3b07384-d9a4-4a52-9e9e-2c6f7d6e5c4a"
  }
  ```
- **Validação (Pydantic)**:
  - `canonical_name`: `^[a-z0-9_]+$`, `min_length=1`, `max_length=100`.
  - `display_name`: obrigatório, texto livre.
  - `basis`: enum `Literal["per_100g", "per_100ml"]`.
  - `kcal, protein_g, carbs_g, fat_g, fiber_g`: `float ≥ 0`.
  - `sodium_mg, calcium_mg, iron_mg, potassium_mg`: `float ≥ 0` ou `None`.
  - `aliases`: `list[str]`, opcional, default `[]`.
  - `promote_food_item_id`: `UUID` opcional.
- **Sucesso**:
  - `201 Created` — corpo:
    ```json
    {
      "id": "novo-uuid-do-fact",
      "canonical_name": "...",
      "source": "user_manual",
      "verified_by_user": true,
      "promotion": null | { "food_item_id": "...", "warning": "promotion_failed?" }
    }
    ```
- **Erros**:
  - `422` — payload inválido (kcal negativa, basis inválido, canonical_name malformado).
  - `401` — sem cookie.
  - `409` — apenas se promoção do item em dia fechado (INV-5); fact continua sendo criado, warning no body em vez de rollback (decisão SP-142).

### Bloco de recovery na assistant message [Ainda no spec, sem código; T-B501]

Quando `compose_meal` recebe `warnings` do recompute e detecta pelo menos um `code='no_catalog_hit'`, anexa:

```markdown
---

**Sem catálogo para:** pão de queijo congelado, sushi ninja rolls

- 📸 **Enviar foto do rótulo** — envie uma foto da tabela nutricional na próxima mensagem.
- ✏️ **Cadastrar manualmente** — clique para preencher os valores.
- ❌ **Descartar item** — responda `apaga pão de queijo` (ou outro nome).
```

**Formato**: markdown padrão do `MessageFormatter`; nada de JSON estruturado — o frontend detecta o padrão de texto para renderizar botões (T-B507 estende `AssistantContent.tsx` com regex que casa `**Sem catálogo para:**`).

## Modelo de dados

### `nutrient_facts` (extensão)

Modelo atual em [`apps/api/app/models/nutrient_fact.py`](../../../apps/api/app/models/nutrient_fact.py):

| Campo | Tipo atual | Mudança planejada |
|---|---|---|
| `source` | CHECK IN (`TBCA_2023, USDA_FDC, manual, label_ocr`) | **T-B502**: adiciona `user_manual` ao CHECK. |
| `verified_by_user` | bool NOT NULL DEFAULT false | Manter; setar `true` no POST /manual. |
| `created_by` | ❓ Ainda **não** existe no modelo desta árvore | **A adicionar** em T-B502 ou T-B503 se a implementação precisar (spec §141 diz "`created_by=user_id`"). |

**Ambiguidade a resolver na branch**: o spec pede `source='user_manual'` mas o modelo atual já tem `'manual'` no CHECK. Ou a migration adiciona `user_manual` (o que o T-B502 sugere) ou reaproveita `'manual'`. Assumir: **adiciona `user_manual`** para diferenciar de rótulos antigos manualmente cadastrados (sem contexto claro no spec).

### `food_items` (afetada por SP-142)

Sem mudança de schema. Ao promover:
- `catalog_ref_id` = `novo_fact.id`
- macros recalculados via `NutritionCalculator.compute(hit=novo_fact, grams, ml)`
- `needs_confirmation` = `false`

## Fluxo de dados

### SP-141 puro (sem promoção)

```
POST /nutrient-facts/manual
  Body: { canonical_name, ..., promote_food_item_id: null }
  ├─ Auth: current_user
  ├─ Pydantic validation → ManualNutrientFactIn
  ├─ Service (novo — inspirado em LabelCatalogService.upsert_from_label):
  │     ├─ INSERT nutrient_facts (
  │     │     source='user_manual',
  │     │     verified_by_user=true,
  │     │     created_by=user.id,
  │     │     canonical_name, brand, basis, kcal, macros, micros, aliases
  │     │  )
  │     ├─ AuditEventRepository.record(
  │     │     entity_type='nutrient_fact',
  │     │     entity_id=fact.id,
  │     │     action='create',
  │     │     actor='user',
  │     │     after=<payload>
  │     │  )
  │     └─ return fact
  └─ 201 { id, canonical_name, source, verified_by_user, promotion: null }
```

### SP-142 (com promoção) — transação única

```
POST /nutrient-facts/manual
  Body: { ..., promote_food_item_id: "uuid" }
  ├─ Auth: current_user
  ├─ Begin transaction:
  │     ├─ INSERT nutrient_facts (source='user_manual', ...)      ← SP-141
  │     ├─ AuditEventRepository.record(action='create')
  │     ├─ item = SELECT FROM food_items WHERE id = promote_food_item_id
  │     ├─ if item is None OR item.food_record.user_id != current_user.id
  │     │      OR item.deleted_at != NULL:
  │     │     └─ promotion.warning = 'promotion_failed'
  │     │     └─ SKIP promotion (mas não faz rollback)
  │     ├─ elif item.food_record.day_log.status == 'closed':      ← INV-5
  │     │     └─ raise ConflictError('conflict_closed_day') — reverte tudo? ou só warning?
  │     │     └─ Decisão: spec §142 diz "cadastro prossegue com warning";
  │     │                 gate T-B505 valida cenário. Comportamento provável:
  │     │                 warning + fact criado, sem raise (INV-5 não bloqueia fact).
  │     ├─ else:
  │     │     ├─ before = { catalog_ref_id, kcal, protein_g, ..., needs_confirmation }
  │     │     ├─ hit = CatalogHit.from_nutrient_fact(novo_fact)
  │     │     ├─ computed = NutritionCalculator.compute(hit, item.grams, item.ml)
  │     │     ├─ UPDATE food_items SET
  │     │     │     catalog_ref_id=novo_fact.id,
  │     │     │     kcal=computed.kcal,
  │     │     │     ...,
  │     │     │     needs_confirmation=false
  │     │     ├─ audit action='correct', actor='user', before, after
  │     │     └─ DailyRecomputeService.recompute(item.food_record.day_log_id)
  │     └─ commit
  └─ 201 { id, ..., promotion: { food_item_id, warning?: 'promotion_failed' } }
```

## Regras de negócio

1. **`source='user_manual'` distingue de `label_ocr`** — mesmo shape geral, origem diferente. Precedência do `LocalTBCACatalog` empata com TBCA_2023; mais recente vence (spec §141).
2. **`verified_by_user=true` no create** — usuário digitou; não precisa passar por confirmação depois.
3. **Isolamento por usuário via `created_by`** — cada user tem seu fact; queries de `LocalTBCACatalog` filtram por `created_by` (ou aceitam globais TBCA_2023 sem filtro).
4. **`canonical_name` slug + `aliases`** — busca por normalized_name (`normalize_name(detected_name)` em [`food-logging`](../food-logging/)) tenta match em `canonical_name` OU em qualquer `aliases[i]`.
5. **Promoção falha silenciosa** — se item não pertence ao user, foi deletado, ou é de outro user, NÃO rollback do fact. Warning no body do 201. O fact fica disponível para futuros registros do próprio user.
6. **Sobrescrita de `catalog_ref_id` anterior** — se item já tem catalog_ref_id (edge case: user promoveu 2× o mesmo item), sobrescreve + audit da mudança.
7. **Dia fechado bloqueia promoção (INV-5)** — mas cadastro do fact prossegue (spec §142). Comportamento exato do 409 vs warning precisa ser confirmado em T-B505.
8. **Recompute snapshot só na promoção com sucesso** — se promoção pulou (item de outro user, dia fechado), sem recompute.

## Configurações e variáveis de ambiente

Nenhuma nova. Reusa infra existente (Postgres, JWT).

## Referências de implementação

### Nesta árvore (`docs/enhancement`)

- **Modelo já existente**: [`apps/api/app/models/nutrient_fact.py`](../../../apps/api/app/models/nutrient_fact.py) — precisa adicionar `user_manual` ao CHECK constraint (T-B502) e possivelmente coluna `created_by`.
- **Rota atual** (só PATCH da SP-33): [`apps/api/app/api/routes/nutrient_facts.py`](../../../apps/api/app/api/routes/nutrient_facts.py).
- **Schema atual** (só `NutrientFactPatch` + `NutrientFactOut`): [`apps/api/app/schemas/nutrient_facts.py`](../../../apps/api/app/schemas/nutrient_facts.py).
- **Referência de shape** para SP-141: [`apps/api/app/services/label_catalog.py`](../../../apps/api/app/services/label_catalog.py) — `LabelCatalogService.upsert_from_label` e `_resolve_basis_and_scale`.
- **Referência de audit de correção**: [`apps/api/app/api/routes/records.py`](../../../apps/api/app/api/routes/records.py) (PATCH `food-items/{id}`) — semântica de `before/after`.
- **Referência de recompute pós-promoção**: [`apps/api/app/services/daily_recompute.py`](../../../apps/api/app/services/daily_recompute.py).
- **Spec canônica**: [`specs/001-mvp-registro-diario/spec.md`](../../001-mvp-registro-diario/spec.md) §3.14 (SP-140..142).
- **Tasks canônicas**: [`specs/001-mvp-registro-diario/tasks.md`](../../001-mvp-registro-diario/tasks.md) § Bloco 5 (T-B501..T-B508).

### Na branch `feat/bloco-5-catalog-recovery` (verificar antes de assumir)

- `POST /nutrient-facts/manual` (rota nova em `routes/nutrient_facts.py`).
- Schema `ManualNutrientFactIn` (em `schemas/nutrient_facts.py`).
- Migration `0008_nutrient_facts_source_user_manual.py`.
- Testes em `tests/test_manual_nutrient_facts.py` (12 casos planejados em T-B505).
- Componentes frontend `ManualCatalogForm.tsx` e extensão de `AssistantContent.tsx`.
- Bloco de recovery em `services/message_formatter.py::compose_meal`.
