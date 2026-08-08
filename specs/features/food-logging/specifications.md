# Especificações Técnicas — Registro de alimentos

> **Fontes**: `apps/api/app/services/meal.py`, `apps/api/app/services/nutrition_calculator.py`, `apps/api/app/services/message_processor.py`, `apps/api/app/services/intent_dispatcher.py`, `apps/api/app/schemas/llm.py`, `apps/api/app/models/food_record.py`, `apps/api/app/models/food_item.py`, `apps/api/app/integrations/nutrition/catalog.py`.

## Escopo técnico

Feature entra em ação **exclusivamente** pelo intent `log_food` no pipeline de chat. Nenhum endpoint HTTP público cria `food_records` diretamente — a única entrada externa é `POST /chat/messages` (owned pela feature `chat-messaging`). Este documento descreve o que acontece **dentro** desse pipeline quando `intent=log_food`.

## Interface — trigger e resposta

### Entrada (contrato interno via `LLMEnvelope`)

O `MessageProcessor` recebe do `AnthropicClient` um `LLMEnvelope` (schemas em [`apps/api/app/schemas/llm.py`](../../../apps/api/app/schemas/llm.py)) validado por Pydantic v2 com `extra="forbid"` no nível raiz. Campos relevantes:

```python
LLMEnvelope(
    intent="log_food",
    confidence=0.85,              # 0..1
    user_text_summary="...",
    meal_slot="lunch" | None,     # breakfast|lunch|snack|dinner|other|unspecified|None
    occurred_at_hint=datetime | None,
    food_items=[
        FoodItemIn(
            detected_name="arroz branco",
            normalized_name="arroz_branco_cozido",   # opcional; MealService normaliza se ausente
            brand=None | "Camil",
            quantity=1.0 | None,
            unit="concha" | "g" | None,
            grams_estimate=150.0 | None,
            ml_estimate=None,
            confidence=0.9,       # 0..1
            is_estimate=False,
        ),
        # ... 1..N itens
    ],
)
```

`FoodItemIn` usa `extra="ignore"` propositalmente: a LLM tende a inventar campos comuns (`pace`, `heart_rate_avg`, `calories`, `sugars_g`). Rejeitar levaria a `validation_exhausted`. Campos conhecidos ainda são validados; extras são silenciosamente descartados.

### Saída

A camada de service devolve `MealResult(food_record, items, warnings)`. O `MessageProcessor` compõe a `assistant_message` via `message_formatter.compose_meal(...)` (padronização SP-118: tabela markdown de totais da refeição + totais acumulados do dia). O snapshot do dia é **recomputado from-scratch** (INV-4) antes da resposta.

## Modelo de dados

### `food_records` — a refeição/registro agrupador

Modelo: [`apps/api/app/models/food_record.py`](../../../apps/api/app/models/food_record.py)

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | UUID | PK |
| `user_id` | UUID FK users(id) | Owner; obrigatório (Const. §21) |
| `day_log_id` | UUID FK day_logs(id) | O dia local do usuário (fuso; SP-92) |
| `message_id` | UUID FK messages(id) NULL | Mensagem que originou o registro |
| `meal_slot` | text (check) | Enum: `breakfast \| lunch \| snack \| dinner \| other \| unspecified` |
| `occurred_at` | timestamptz | Vem de `occurred_at_hint` ou `now(UTC)` |
| `notes` | text NULL | Livre |
| `deleted_at` | timestamptz NULL | Soft delete |
| `created_at`, `updated_at` | timestamptz | Timestamps padrão |

### `food_items` — o item consumido

Modelo: [`apps/api/app/models/food_item.py`](../../../apps/api/app/models/food_item.py)

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | UUID | PK |
| `food_record_id` | UUID FK food_records(id) ON DELETE CASCADE | Agrupador |
| `detected_name` | text | Como a LLM viu ("arroz branco") |
| `normalized_name` | text | Slug para lookup (`arroz_branco_cozido`) |
| `brand` | text NULL | Marca (`Camil`), opcional |
| `quantity` | numeric(10,3) NULL | Quantidade em unidade doméstica (1 concha, 2 colheres) |
| `unit` | text NULL | Unidade doméstica |
| `grams`, `ml` | numeric(10,3) NULL | Um dos dois **precisa** ter valor para o cálculo |
| `source` | text (check) | `manual`, `llm`, `user_corrected`, `catalog` |
| `confidence` | numeric(3,2) NULL | 0.00..1.00; da LLM |
| `is_estimate` | bool | LLM decide (não default) |
| `needs_confirmation` | bool | `true` se `confidence < 0.5` OU sem hit no catálogo |
| `catalog_ref_id` | UUID FK nutrient_facts(id) NULL | Hit do catálogo, ou NULL (SP-23) |
| `kcal`, `protein_g`, `carbs_g`, `fat_g`, `fiber_g` | numeric(10,2) NULL | Macros materializados (cache) |
| `sodium_mg`, `calcium_mg`, `iron_mg`, `potassium_mg` | numeric(10,2) NULL | Micros materializados |
| `deleted_at` | timestamptz NULL | Soft delete |

Materializar as colunas nutricionais é decisão consciente (`app_plan.md` §7): permite `DailyRecomputeService` fazer uma única query agregada sem N+1 e sobrevive a mudança no catálogo (histórico não muda ao alterar TBCA).

### `audit_events`

Toda criação grava linha via `AuditEventRepository.record(...)` com `entity_type='food_record'`, `action='create'`, `actor='llm'`, `after={meal_slot, occurred_at, item_ids}`. Sem `before` (é create).

## Fluxo de dados

```
POST /chat/messages (routes/chat.py)
  ├─ persiste user message + media
  ├─ agenda BackgroundTask
  └─ 202 { message_id, status: "processing" }
        ▼
MessageProcessor.process(message_id)          [services/message_processor.py]
  ├─ carrega histórico
  ├─ chama AnthropicClient.classify(...)      [integrations/anthropic]
  │     tool_use forçado + retry semântico
  ├─ recebe LLMEnvelope validado
  └─ dispatch:
        IntentDispatcher.handle(envelope, user, day_log, message)
              ├─ intent="log_food"
              └─ MealService.create_from_llm(...)     [services/meal.py]
                    ├─ FoodRecordRepository.create(...)
                    ├─ loop sobre envelope.food_items:
                    │     normalize_name(detected_name)
                    │     LocalTBCACatalog.lookup(name, brand)   → CatalogHit | None
                    │     NutritionCalculator.compute(hit, grams, ml)  → ComputedNutrition
                    │     FoodItemRepository.create(...)
                    │     coletar warnings
                    ├─ AuditEventRepository.record(...)
                    └─ retorna MealResult
        ▼
DailyRecomputeService.recompute(day_log_id)   [services/daily_recompute.py]
  → SELECT SUM sobre food_items + water + beverages + activities (deleted_at IS NULL)
  → UPSERT daily_snapshots
        ▼
message_formatter.compose_meal(result, snapshot, warnings)
  → tabela SP-118 + narrativa curta + aviso legal
        ▼
persiste assistant message em `messages`
```

## Regras de negócio

1. **Quem calcula é o backend.** LLM entrega `grams_estimate`/`ml_estimate` + `is_estimate`; `NutritionCalculator.compute(hit, grams, ml)` produz `kcal`/macros/micros. Se `hit is None` → zeros + reason `no_catalog_hit`. Se `hit.basis='per_100g'` e `grams is None or <= 0` → zeros + reason `missing_grams`. Idem para `per_100ml`.
2. **Precisão decimal.** Todos os valores em `Decimal`, arredondados via `.quantize(Decimal("0.01"))` para 2 casas.
3. **`needs_confirmation` combina duas fontes.** `confidence < 0.5` (`LOW_CONFIDENCE_THRESHOLD`) **OU** sem catálogo (`hit is None`). UI trata os dois como "confirmar".
4. **Warnings agregam.** `no_catalog_hit`, `low_confidence_item`, `missing_grams`, `missing_ml` são emitidos por item e agregados no snapshot.
5. **`meal_slot` padrão.** Se `envelope.meal_slot is None` → `"unspecified"`.
6. **`occurred_at` fallback.** Ordem: `occurred_at` explícito → `envelope.occurred_at_hint` → `datetime.now(UTC)`.
7. **Auditoria só grava criação.** Correção/deleção têm entradas próprias em suas features.
8. **Envelope vazio de itens é bug de caller.** `create_from_llm` levanta `ValueError("envelope has no food_items")` se `food_items=[]` — nunca deve chegar aqui (dispatcher já filtra).
9. **Isolamento**: `user_id` obrigatório em `create()` e em todos os repositórios; RLS não é usado (validação em application-layer).

## Configurações e variáveis de ambiente

| Variável | Descrição | Padrão | Obrigatória |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Chave do modelo que classifica o intent. | — | Sim |
| `ANTHROPIC_MODEL` | Modelo primário (extração do envelope). | `claude-sonnet-4-6` | Sim |
| `ANTHROPIC_FALLBACK_MODEL` | Fallback ao esgotar retries. | `claude-haiku-4-5-20251001` | Não |
| `DATABASE_URL` | Postgres 16 (SQLAlchemy async). | — | Sim |
| Seed TBCA | Rodado por `pnpm db:bootstrap` (idempotente). | — | Sim (na 1ª subida) |

## Referências de implementação

- **Services**: [`app/services/meal.py`](../../../apps/api/app/services/meal.py), [`app/services/nutrition_calculator.py`](../../../apps/api/app/services/nutrition_calculator.py), [`app/services/intent_dispatcher.py`](../../../apps/api/app/services/intent_dispatcher.py), [`app/services/message_processor.py`](../../../apps/api/app/services/message_processor.py), [`app/services/message_formatter.py`](../../../apps/api/app/services/message_formatter.py), [`app/services/daily_recompute.py`](../../../apps/api/app/services/daily_recompute.py).
- **Repositórios**: [`app/repositories/food.py`](../../../apps/api/app/repositories/food.py) (`FoodRecordRepository`, `FoodItemRepository`, `AuditEventRepository`).
- **Modelos**: [`app/models/food_record.py`](../../../apps/api/app/models/food_record.py), [`app/models/food_item.py`](../../../apps/api/app/models/food_item.py), [`app/models/nutrient_fact.py`](../../../apps/api/app/models/nutrient_fact.py), [`app/models/audit_event.py`](../../../apps/api/app/models/audit_event.py).
- **Schemas**: [`app/schemas/llm.py`](../../../apps/api/app/schemas/llm.py) (`FoodItemIn`, `LLMEnvelope`), [`app/schemas/chat.py`](../../../apps/api/app/schemas/chat.py).
- **Integrações**: [`app/integrations/nutrition/catalog.py`](../../../apps/api/app/integrations/nutrition/catalog.py) (`LocalTBCACatalog`, `CatalogHit`, `LookupQuery`), [`app/integrations/nutrition/normalize.py`](../../../apps/api/app/integrations/nutrition/normalize.py) (`normalize_name`), [`app/integrations/nutrition/tbca_seed.py`](../../../apps/api/app/integrations/nutrition/tbca_seed.py).
- **Testes**: [`apps/api/tests/test_meal_service.py`](../../../apps/api/tests/test_meal_service.py), [`apps/api/tests/test_log_food_flow.py`](../../../apps/api/tests/test_log_food_flow.py), [`apps/api/tests/test_nutrition_calculator.py`](../../../apps/api/tests/test_nutrition_calculator.py), [`apps/api/tests/test_label_catalog.py`](../../../apps/api/tests/test_label_catalog.py).
- **Frontend renderizador**: `apps/web/src/app/(app)/chat/` (renderização SP-115..118 é [`assistant-message-rendering`](../assistant-message-rendering/)).
