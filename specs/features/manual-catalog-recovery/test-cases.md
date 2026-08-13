# Casos de Teste — Recuperação manual de itens sem catálogo

> **Estado**: nenhum dos testes abaixo existe nesta árvore (`docs/enhancement`). Todos estão previstos como gate T-B505 (12 casos de integração) + T-B501 (unit no formatter). Prováveis arquivos: `apps/api/tests/test_manual_nutrient_facts.py` e adição em `tests/test_message_formatter.py`.
> Convenção: adotar mesmo padrão dos testes existentes de `test_meal_service.py` e `test_daily_recompute.py`.

---

## Testes unitários — bloco de recovery no formatter

### TC-U-001 — Sem warning `no_catalog_hit` → sem bloco

- **Módulo**: `apps/api/app/services/message_formatter.py::compose_meal`
- **Setup**: `MealResult` com warnings `[low_confidence_item]` só
- **Ação**: compose
- **Verificar**: assistant message **não** contém "Sem catálogo para:"
- **SP**: SP-140

### TC-U-002 — Com 1 warning `no_catalog_hit` → bloco com 1 nome

- **Setup**: warnings `[{code:"no_catalog_hit", detected_name:"pão de queijo"}]`
- **Ação**: compose
- **Verificar**:
  - Bloco `**Sem catálogo para:** pão de queijo`
  - 3 CTAs presentes
  - Aviso legal permanece
- **SP**: SP-140

### TC-U-003 — Múltiplos warnings deduplicam por `detected_name`

- **Setup**: 2 warnings apontando pra mesmo item (por bug)
- **Ação**: compose
- **Verificar**: nome aparece 1 vez, não 2

---

## Testes de integração — `POST /nutrient-facts/manual` (gate T-B505)

### TC-I-001 — Happy path `per_100g` sem promoção

- **Body**: canonical_name, basis=per_100g, kcal, macros
- **Verificar**:
  - 201 `{id, source: "user_manual", verified_by_user: true, promotion: null}`
  - Linha em `nutrient_facts` com `created_by=user.id`
  - Audit `action='create'`

### TC-I-002 — Happy path `per_100ml`

- **Body**: `basis="per_100ml"`, campos numéricos
- **Verificar**: fact criado com `basis="per_100ml"`

### TC-I-003 — `canonical_name` inválido → 422

- **Body**: `canonical_name="pão-de-queijo"` ou `"PAO"`, `"pao de queijo"` (espaço)
- **Verificar**: 422 detalhe apontando canonical_name

### TC-I-004 — `kcal` negativo → 422

- **Body**: `kcal=-1`
- **Verificar**: 422

### TC-I-005 — Isolamento cross-user (leitura)

- **Setup**: user A cria fact `pao_de_queijo`
- **Ação**: user B envia mensagem que geraria lookup do mesmo nome
- **Verificar**: `LocalTBCACatalog.lookup` do B devolve `None` (não encontra A)

### TC-I-006 — Audit event gravado no create

- **Ação**: POST simples
- **Verificar**: 1 linha `audit_events` com `entity_type='nutrient_fact', action='create', actor='user', after` com o payload

### TC-I-007 — Promoção com item válido

- **Setup**: food_item X do user, `catalog_ref_id=NULL`, `kcal=0`, `grams=150`, dia aberto
- **Ação**: POST com `promote_food_item_id=X.id`, `kcal=200, basis=per_100g`
- **Verificar**:
  - 201 `promotion.food_item_id=X.id`, `warning=None`
  - `food_items.X.catalog_ref_id=novo_fact.id`
  - `food_items.X.kcal=300.00` (150g × 200/100)
  - `food_items.X.needs_confirmation=false`
  - `daily_snapshots.kcal_in` atualizado
  - 2 audit events (create fact + correct item)

### TC-I-008 — Promoção com item de outro user

- **Setup**: food_item Y do user_B
- **Ação**: user_A POST com `promote_food_item_id=Y.id`
- **Verificar**:
  - 201 `promotion.warning='promotion_failed'`
  - Fact criado (pertence a user_A)
  - `food_items.Y` **inalterado**

### TC-I-009 — Promoção com item deletado

- **Setup**: food_item Z do user, `deleted_at != NULL`
- **Ação**: POST com `promote_food_item_id=Z.id`
- **Verificar**: 201 `promotion.warning='promotion_failed'`. Fact criado. Z inalterado.

### TC-I-010 — Sobrescrita de `catalog_ref_id` existente

- **Setup**: food_item W já tem `catalog_ref_id=fact_antigo.id`
- **Ação**: POST com `promote_food_item_id=W.id` para novo fact
- **Verificar**:
  - 201 sucesso
  - `food_items.W.catalog_ref_id=novo_fact.id` (mudou)
  - Audit `action='correct'` com `before.catalog_ref_id=fact_antigo.id`

### TC-I-011 — Recompute snapshot após promoção

- **Setup**: dia com food_items zerados + snapshot v1
- **Ação**: POST com promoção
- **Verificar**: `snapshot.version` incrementou; `snapshot.kcal_in` refletindo novo valor; warning `no_catalog_hit` sumiu do snapshot.warnings (porque `catalog_ref_id` agora existe)

### TC-I-012 — Dia fechado bloqueia promoção

- **Setup**: food_item V em `day_log.status='closed'`
- **Ação**: POST com `promote_food_item_id=V.id`
- **Verificar**:
  - Fact ainda criado (source=user_manual)
  - `food_items.V` **inalterado** (INV-5)
  - Warning `promotion.warning` presente com código adequado (SP-142 diz "cadastro prossegue com warning")
  - **Comportamento exato** (200 vs 201 vs 409 no body) depende da decisão do T-B505 — este teste solidifica.

---

## Testes E2E manuais

### TC-E-001 — Fluxo completo pelo chat

- **Persona**: Felix (browser)
- **Passos**:
  1. Enviar "comi 100g de pão de queijo congelado" (fora do TBCA seed).
  2. Ver assistant message com bloco "Sem catálogo para: pão de queijo congelado" + 3 CTAs.
  3. Clicar em "Cadastrar manualmente".
  4. Preencher form: display_name, kcal=320, P=8, C=40, G=14. Submit.
  5. Ver form fechar; `DayTotalsBar` atualizar; item no `/day` sem mais o badge "sem catálogo".
- **Resultado esperado**: total do dia bate; user não precisou sair do chat.

### TC-E-002 — Fluxo por foto (alternativa)

- Deveria ir pelo caminho SP-30..35 ([`nutrition-label-ocr`](../nutrition-label-ocr/)), não por este endpoint. Documentar que o form manual é para quando **não** há rótulo/foto.

### TC-E-003 — Descartar item

- Clicar em "Descartar" → composer pré-preenchido com `apaga pão de queijo` → Enter → item soma do dia.

---

## Testes de regressão críticos

- **Gate T-B505 completo (12 casos)** — se qualquer um regride, feature está quebrada.
- **Isolamento cross-user (TC-I-005, TC-I-008)** — segurança fundamental.
- **INV-5 em promoção (TC-I-012)** — se regredir, dia fechado deixa de ser imutável.
- **Recompute snapshot após promoção (TC-I-011)** — sem isso, UX degrada (user precisa refresh manual).
- **Regressão no formatter (TC-U-002)** — se `compose_meal` deixar de detectar warnings, bloco some.

## Como rodar

Após checkout de `feat/bloco-5-catalog-recovery` e merge da migration:

```bash
cd apps/api

# migrations
uv run alembic -c alembic.ini upgrade head

# suite específica
uv run pytest tests/test_manual_nutrient_facts.py -v

# regressão do formatter
uv run pytest tests/test_message_formatter.py -v -k recovery

# gate completo Bloco 5
uv run pytest tests/test_manual_nutrient_facts.py tests/test_message_formatter.py --cov=app/services --cov=app/api/routes
```
