# Critérios de Aceitação — Leitura de rótulo nutricional (Fase 4.b)

> **Rastreabilidade**: SP-30..SP-35, INV-1, INV-4, INV-10 · Tests em `apps/api/tests/test_label_catalog.py` (17 testes).

## AC-001 — Cadastro sem consumo (SP-30)
**Dado que** Felix envia foto do rótulo sem texto de consumo,
**Quando** a LLM retorna `intent=log_nutrition_label, nutrition_label={product_name, basis:"per_100g", kcal:180, ...}`,
**Então** `nutrient_facts` é criado com `source='label_ocr'`, `label_media_id` preenchido, `verified_by_user=false`,
**E** **nenhum** `food_records` é criado,
**E** `audit_events(action='create', entity_type='nutrient_fact', actor='llm')` gravado.

**Notas de validação:**
- Teste: `test_upsert_creates_fact_with_source_label_ocr` (linha 79 em `test_label_catalog.py`).

---

## AC-002 — Cadastro + consumo (SP-31)
**Dado que** Felix envia foto + "comi um pote (170g)" com `also_consumed={quantity:170, unit:"g"}`,
**Quando** `_handle_log_nutrition_label` executa,
**Então** `nutrient_facts` criado **e** `food_records`+`food_items` com `catalog_ref_id` apontando para o fato,
**E** `kcal`/macros calculados via `NutritionCalculator`,
**E** snapshot recomputado.

**Notas de validação:**
- Teste: `test_also_consumed_creates_food_record` (linha 195 em `test_label_catalog.py`).

---

## AC-003 — `per_serving` sem tamanho rejeitado (SP-32)
**Dado que** a LLM retorna `basis='per_serving'` sem `serving_size_g` nem `serving_size_ml`,
**Quando** `NutritionLabelIn` valida,
**Então** `ValueError("basis=per_serving requer serving_size_g ou serving_size_ml")` é levantada,
**E** nenhum `nutrient_facts` persistido.

**Notas de validação:**
- Teste: `test_per_serving_without_size_rejected_by_schema` (linha 150 em `test_label_catalog.py`).

---

## AC-004 — `per_serving` com tamanho é normalizado
**Dado que** `basis='per_serving'`, `serving_size_g=30`, `kcal=60` (por porção),
**Quando** `upsert_from_label` executa,
**Então** fato persistido com `basis='per_100g'`, `kcal=200.00` (60 × 100/30).

**Notas de validação:**
- Teste: `test_upsert_normalizes_per_serving_to_per_100g` (linha 129 em `test_label_catalog.py`).

---

## AC-005 — PATCH confirma valores (SP-33)
**Dado que** um fato `label_ocr` existe com `verified_by_user=false`,
**Quando** `PATCH /nutrient-facts/{id}` com `{kcal: 190}`,
**Então** `kcal=190.00`, `verified_by_user=true`,
**E** `audit_events(action='update', entity_type='nutrient_fact', actor='user')` gravado.

**Notas de validação:**
- Teste: `test_patch_nutrient_fact_sets_verified` (linha 241 em `test_label_catalog.py`).

---

## AC-006 — PATCH recusa fact canônico
**Dado que** um fato `source='TBCA_2023'` existe,
**Quando** `PATCH /nutrient-facts/{id}`,
**Então** `ValidationAppError(code='not_editable')` (422).

**Notas de validação:**
- Teste: `test_patch_nutrient_fact_refuses_tbca_source` (linha 270 em `test_label_catalog.py`).

---

## AC-007 — Micros ausentes geram warning (SP-34)
**Dado que** um rótulo não informa cálcio, ferro e potássio,
**Quando** `upsert_from_label` executa,
**Então** `warnings` contém `{code:"micros_missing_for_product", missing:["calcium_mg","iron_mg","potassium_mg"]}`.

**Notas de validação:**
- Teste: `test_missing_micros_produces_warning` (linha 169 em `test_label_catalog.py`).

---

## AC-008 — Micros completos não geram warning
**Dado que** um rótulo informa todos os micros,
**Quando** `upsert_from_label` executa,
**Então** `warnings` não contém `micros_missing_for_product`.

**Notas de validação:**
- Teste: `test_complete_micros_no_warning` (linha 180 em `test_label_catalog.py`).

---

## AC-009 — Idempotência por barcode
**Dado que** um fato `label_ocr` com `barcode="789123"` existe,
**Quando** Felix refotografa o mesmo produto (mesmo barcode),
**Então** fato existente é **atualizado** (não duplicado),
**E** `action='update'` no audit.

**Notas de validação:**
- Teste: `test_upsert_updates_existing_on_repeat_barcode` (linha 89 em `test_label_catalog.py`).

---

## AC-010 — `verified_by_user` preservado no reupload
**Dado que** um fato existe com `verified_by_user=true`,
**Quando** Felix refotografa o mesmo produto,
**Então** `verified_by_user` permanece `true` (não é rebaixado).

**Notas de validação:**
- Teste: `test_upsert_preserves_verified_flag_on_reupload` (linha 108 em `test_label_catalog.py`).

---

## AC-011 — Precedência TBCA > label_ocr (SP-35)
**Dado que** existe fato `TBCA_2023` e fato `label_ocr` para mesmo produto,
**Quando** `LocalTBCACatalog.lookup` executa,
**Então** retorna o fato `TBCA_2023` (maior precedência).

**Notas de validação:**
- Teste: `test_catalog_prefers_tbca_over_label_ocr` (linha 301 em `test_label_catalog.py`).

---

## AC-012 — Precedência label_ocr verified > não-verified
**Dado que** existe fato `label_ocr` com `verified_by_user=true` e outro com `false`,
**Quando** `lookup` executa,
**Então** retorna o `verified_by_user=true`.

**Notas de validação:**
- Teste: `test_catalog_prefers_label_ocr_when_verified` (linha 323 em `test_label_catalog.py`).

---

## AC-013 — Cadastro via chat expõe nutrient_fact_id
**Dado que** uma mensagem `log_nutrition_label` é processada,
**Quando** a mensagem assistant é persistida,
**Então** `raw_llm_response.dispatch.nutrient_fact_id` contém o UUID do fato.

**Notas de validação:**
- Teste: `test_message_out_exposes_nutrient_fact_id` (linha 383 em `test_label_catalog.py`).

---

## Cenários de Borda

| Cenário | Comportamento Esperado |
|---|---|
| `basis='per_serving'` + `serving_size_g=0` | `_resolve_basis_and_scale` divide por zero → `ValueError` (defensivo). |
| `also_consumed` sem `day_log_id` | Só cadastra o fato; não registra consumo (linha 624-626). |
| `also_consumed` com `servings` mas fato sem `serving_grams` | `_resolve_consumed_amount` cai para `quantity` interpretado por basis. |
| `PATCH` em id inexistente | `NotFoundError(code='not_found')` (404). |
| `PATCH` sem campos (payload vazio) | `verified_by_user=true` é setado mesmo sem mudança de valor. |
| Sem `label_media_id` (mensagem sem foto) | `label_media_id=null` no fato; cadastro prossegue. |
| `barcode` presente mas não casa | Fallback para `(canonical_name, brand)`. |

## Critérios de Não-Funcionalidade

| Critério | Threshold | Notas |
|---|---|---|
| Latência de `upsert_from_label` | < 100ms | Sem chamada LLM aqui; só DB. |
| Latência de `register_consumption` | < 150ms | Inclui `NutritionCalculator` + recompute. |
| Latência de `PATCH /nutrient-facts/{id}` | < 100ms | Só UPDATE + audit. |
| Determinismo de normalização | 100% | Mesmo `per_serving` + `serving_size` → mesmo `per_100g`. |
