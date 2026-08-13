# Especificações Técnicas — Leitura de rótulo nutricional (Fase 4.b)

> **Rastreabilidade**: SP-30..SP-35 · Implementação: `apps/api/app/services/label_catalog.py`, `apps/api/app/api/routes/nutrient_facts.py`, `apps/api/app/models/nutrient_fact.py`, `apps/api/app/schemas/llm.py` (NutritionLabelIn, NutritionLabelAlsoConsumed), `apps/api/app/services/message_processor.py:605` (`_handle_log_nutrition_label`).

## Escopo técnico

Dois fluxos: (1) **cadastro via chat** — foto do rótulo → `LabelCatalogService.upsert_from_label` → `nutrient_facts`; opcionalmente `register_consumption` se `also_consumed`. (2) **confirmação via REST** — `PATCH /nutrient-facts/{id}` ajusta valores e marca `verified_by_user=true`.

## Interface

### Entrada (LLMEnvelope via `tool_use`)

```python
class NutritionLabelIn(_StrictBase):          # extra="forbid"
    product_name: str
    brand: str | None = None
    barcode: str | None = None
    basis: Literal["per_100g","per_100ml","per_serving"]
    serving_size_g: float | None = None
    serving_size_ml: float | None = None
    servings_per_pack: float | None = None
    kcal, protein_g, carbs_g, sugars_g, added_sugars_g,
    fat_g, saturated_fat_g, trans_fat_g, fiber_g,
    sodium_mg, calcium_mg, iron_mg, potassium_mg: float | None
    confidence_per_field: dict[str, float] = {}
    also_consumed: NutritionLabelAlsoConsumed | None = None

    @model_validator(mode="after")
    def _serving_needs_size(self):
        if self.basis == "per_serving" and not (self.serving_size_g or self.serving_size_ml):
            raise ValueError("basis=per_serving requer serving_size_g ou serving_size_ml")

class NutritionLabelAlsoConsumed(_StrictBase):
    quantity: float
    unit: str
    grams: float | None = None
    ml: float | None = None
    servings: float | None = None
```

`LLMEnvelope.intent == "log_nutrition_label"` + `LLMEnvelope.nutrition_label` preenchido. `_StrictBase` (`extra="forbid"`) — LLM não pode inventar campos.

### Endpoint REST (SP-33)

```http
PATCH /nutrient-facts/{id}
Content-Type: application/json
Cookie: access_token=...

{
  "kcal": 180,
  "protein_g": 6.5,
  "serving_grams": 170
}
```

**Response 200** (`NutrientFactOut`): fato atualizado com `verified_by_user=true`.
**Errors**: `404 not_found` (id inexistente); `422 not_editable` (source `TBCA_2023`/`USDA_FDC`).

### Saída (snapshot do dia)

Se `also_consumed`: `food_items` com `catalog_ref_id` apontando para o fato; `daily_snapshots` recomputeado com kcal/macros do novo item.

### Erros de domínio

| Code | Quando | HTTP |
|---|---|---|
| `not_found` | `PATCH` em id inexistente | 404 |
| `not_editable` | `PATCH` em fact `source ∈ {TBCA_2023, USDA_FDC}` | 422 |
| `ValueError` (Pydantic) | `basis=per_serving` sem `serving_size_g/ml` (SP-32) | 422 → `validation_exhausted` |

## Modelo de dados

### `nutrient_facts`

| Coluna | Tipo | Constraints | Notas |
|---|---|---|---|
| `id` | UUID PK | `uuid_generate_v4()` | |
| `canonical_name` | `Text` | `NOT NULL` | `normalize_name(product_name)` |
| `aliases` | `ARRAY(Text)` | `NOT NULL`, default `{}` | `{canonical, normalize_name(product_name)}` |
| `brand` | `Text` | nullable | |
| `source` | `Text` | `NOT NULL`, `CHECK IN ('TBCA_2023','USDA_FDC','manual','label_ocr')` | |
| `serving_grams` | `Numeric(10,2)` | nullable | preservado para `also_consumed.servings` |
| `kcal`, `protein_g`, `carbs_g`, `fat_g`, `fiber_g` | `Numeric(10,2)` | nullable | macros por 100 |
| `sodium_mg`, `calcium_mg`, `iron_mg`, `potassium_mg` | `Numeric(10,2)` | nullable | micros por 100; Ca/Fe/K geralmente `null` (SP-34) |
| `basis` | `Text` | `NOT NULL`, `CHECK IN ('per_100g','per_100ml')` | `per_serving` normalizado antes de persistir |
| `barcode` | `Text` | nullable | chave de idempotência forte |
| `label_media_id` | UUID FK → `media.id` | nullable, `ON DELETE SET NULL` | foto do rótulo |
| `verified_by_user` | `Boolean` | `NOT NULL`, default `false` | SP-33 marca `true` |
| `created_at` | `DateTime(timezone=true)` | `NOT NULL` | sem `updated_at` — fatos são imutáveis exceto via PATCH |

**Sem `user_id`**: catálogo é compartilhado. `PATCH` exige auth mas não filtra por usuário. <!-- TODO: multi-tenant precisaria owner_user_id -->

### Migration

`nutrient_facts` criada na Fase 4 (food-logging); `label_media_id`, `barcode`, `verified_by_user` adicionados na Fase 4.b. <!-- TODO: confirmar migration exata -->

## Fluxo de dados

### Fluxo 1 — Cadastro sem consumo (SP-30)

1. Felix envia foto do rótulo via `POST /chat/messages` (sem texto de consumo).
2. `chat.router` insere `messages(role=user)` + valida/vincula mídia.
3. `MessageProcessor.process`:
   a. `AnthropicClient.classify` → `LLMEnvelope(intent="log_nutrition_label", nutrition_label={product_name, brand, basis, kcal, ...})`.
   b. `_handle_log_nutrition_label`:
      - `label_media_id = _first_media_id(user_message.id)`.
      - `LabelCatalogService.upsert_from_label(user, label, label_media_id, message_id)`:
        - `_resolve_basis_and_scale(label)` → se `per_serving`, escala para `per_100g|per_100ml`.
        - `_find_existing_label_fact(canonical, brand, barcode)` → se existe, **atualiza** (preserva `verified_by_user=true`); senão, **cria**.
        - `AuditEventRepository.record(action='create'|'update', entity_type='nutrient_fact', actor='llm')`.
        - Coleta `warnings`: `micros_missing_for_product` se Ca/Fe/K `null`.
      - Sem `also_consumed` → **não** cria `food_records`, **não** recomputa.
      - `_compose_label_summary` → "Cadastrei o produto X. Valores por 100g: ...".
4. Polling retorna mensagem assistant com `nutrient_fact_id` no `dispatch`.

### Fluxo 2 — Cadastro + consumo (SP-31)

Igual ao Fluxo 1, mas `also_consumed` presente:
- Após `upsert_from_label`, `service.register_consumption(user, day_log_id, message_id, fact, consumed, meal_slot)`:
  - `_resolve_consumed_amount(fact, consumed)` → `(grams, ml)` (prioridade: `grams`/`ml` explícito > `servings × serving_grams` > `quantity` interpretado por basis).
  - `FoodRecordRepository.create(...)` + `FoodItemRepository.create(catalog_ref_id=fact.id, kcal=NutritionCalculator.compute(...))`.
  - `AuditEventRepository.record(action='create', entity_type='food_record', after={..., from_label: True})`.
- `DailyRecomputeService.recompute(day_log_id)`.

### Fluxo 3 — Confirmação via PATCH (SP-33)

1. Felix (ou UI) chama `PATCH /nutrient-facts/{id}` com valores ajustados.
2. Rota carrega fato; se `source ∉ {label_ocr, manual}` → `not_editable`.
3. Atualiza campos, seta `verified_by_user=true`.
4. `AuditEventRepository.record(action='update', entity_type='nutrient_fact', actor='user', before, after)`.
5. Retorna `NutrientFactOut`.

## Regras de negócio

1. **`per_serving` é normalizado**: `_resolve_basis_and_scale` escala valores para `per_100g|per_100ml` antes de persistir. Catálogo só armazena basis canônico.
2. **Idempotência por `barcode` ou `(canonical_name, brand)`**: reupload atualiza, não duplica. `barcode` é chave forte; sem barcode, usa par canônico.
3. **`verified_by_user` nunca rebaixado**: se fato existente tinha `true`, reupload mantém `true` (não volta para `false`).
4. **SP-32 — `per_serving` sem tamanho**: `NutritionLabelIn._serving_needs_size` (model_validator) rejeita antes de chegar no service.
5. **SP-34 — micros ausentes**: `_MICRO_FIELDS = (calcium_mg, iron_mg, potassium_mg)`. Se `null` após upsert, warning `micros_missing_for_product` com lista de faltantes.
6. **SP-35 — precedência**: garantida pelo `LocalTBCACatalog.lookup` (feature `food-logging`). `label_ocr` perde para `TBCA_2023` na mesma marca; `verified_by_user=true` vence sobre `false`.
7. **SP-33 — `PATCH` só edita `label_ocr`/`manual`**: facts canônicos (`TBCA_2023`, `USDA_FDC`) não são editáveis.
8. **`also_consumed` sem `day_log`**: se `user_message.day_log_id is None`, só cadastra o fato (não registra consumo). [Inferido do código] linha 624-626.
9. **`register_consumption` usa `confidence=0.95`**: item de rótulo tem alta confiança (valores lidos do rótulo, não estimados).

## Configurações e variáveis de ambiente

| Variável | Descrição | Padrão | Obrigatória |
|---|---|---|---|
| `ANTHROPIC_MODEL` | Modelo que lê rótulo via foto | `claude-sonnet-4-6` | Sim |
| `ANTHROPIC_FALLBACK_MODEL` | Fallback | `claude-haiku-4-5-20251001` | Não |

Sem variáveis específicas de label-ocr.

## Referências de implementação

- **Service**: `apps/api/app/services/label_catalog.py` — `LabelCatalogService.upsert_from_label`, `register_consumption`, `_find_existing_label_fact`, `_resolve_basis_and_scale`, `_scale_or_none`, `_resolve_consumed_amount`.
- **Route (SP-33)**: `apps/api/app/api/routes/nutrient_facts.py` — `PATCH /nutrient-facts/{id}`, `_EDITABLE_FIELDS`.
- **Model**: `apps/api/app/models/nutrient_fact.py` — `NutrientFact`, `CATALOG_SOURCES`.
- **Schema LLM**: `apps/api/app/schemas/llm.py:188` — `NutritionLabelIn(_StrictBase)`, `_serving_needs_size` validator; linha 180 — `NutritionLabelAlsoConsumed`.
- **Integração no pipeline**: `apps/api/app/services/message_processor.py:605` — `_handle_log_nutrition_label`.
- **Summary**: `apps/api/app/services/message_processor.py` — `_compose_label_summary`.
- **Recompute**: só roda se `also_consumed` (linha 637).
- **Tests**: `apps/api/tests/test_label_catalog.py` — 17 testes cobrindo SP-30..35, upsert, idempotência, micros, also_consumed, PATCH, precedência.
