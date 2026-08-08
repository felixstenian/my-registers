# Casos de Teste — Leitura de rótulo nutricional (Fase 4.b)

> **Rastreabilidade**: SP-30..SP-35, INV-1, INV-4, INV-10 · Testes reais em `apps/api/tests/test_label_catalog.py` (17 testes).

## Cobertura alvo

- **Unitários**: `LabelCatalogService.upsert_from_label`, `_resolve_basis_and_scale`, `_scale_or_none`, `_resolve_consumed_amount`, `_find_existing_label_fact`, `NutritionLabelIn._serving_needs_size`.
- **Integração**: `_handle_log_nutrition_label` → `LabelCatalogService` → `register_consumption` → `DailyRecomputeService`; `PATCH /nutrient-facts/{id}`.
- **E2E**: `POST /chat/messages` com foto de rótulo → resposta com `nutrient_fact_id`.
- **Invariantes**: INV-1 (LLM não calcula; `NutritionCalculator` só em `also_consumed`), INV-4 (recompute só se consumo), INV-10 (audit em upsert e PATCH).

---

## Testes Unitários

### TC-U-001 — Upsert cria fato label_ocr
- **Módulo**: `apps/api/app/services/label_catalog.py`
- **Função/Método**: `LabelCatalogService.upsert_from_label`
- **Entrada**: `NutritionLabelIn(product_name="iogurte", basis="per_100g", kcal=68)`; sem fato existente.
- **Saída esperada**: `LabelResult.fact.source='label_ocr'`, `fact.verified_by_user=False`, `fact.basis='per_100g'`.
- **Tipo**: Happy path (SP-30)
- **Teste real**: `test_upsert_creates_fact_with_source_label_ocr` (linha 79)

### TC-U-002 — Upsert atualiza por barcode
- **Módulo**: `apps/api/app/services/label_catalog.py`
- **Função/Método**: `upsert_from_label` → `_find_existing_label_fact`
- **Entrada**: fato existente com `barcode="789123"`; novo upload com mesmo barcode e kcal diferente.
- **Saída esperada**: fato existente atualizado; `action='update'` no audit; sem duplicação.
- **Tipo**: Edge case (idempotência)
- **Teste real**: `test_upsert_updates_existing_on_repeat_barcode` (linha 89)

### TC-U-003 — `verified_by_user` preservado no reupload
- **Módulo**: `apps/api/app/services/label_catalog.py`
- **Função/Método**: `upsert_from_label`
- **Entrada**: fato existente com `verified_by_user=true`; reupload.
- **Saída esperada**: `fact.verified_by_user` permanece `true`.
- **Tipo**: Edge case
- **Teste real**: `test_upsert_preserves_verified_flag_on_reupload` (linha 108)

### TC-U-004 — `per_serving` normalizado para `per_100g`
- **Módulo**: `apps/api/app/services/label_catalog.py`
- **Função/Método**: `_resolve_basis_and_scale` + `_scale_or_none`
- **Entrada**: `basis='per_serving'`, `serving_size_g=30`, `kcal=60` (por porção).
- **Saída esperada**: `fact.basis='per_100g'`, `fact.kcal=200.00` (60 × 100/30).
- **Tipo**: Happy path (normalização)
- **Teste real**: `test_upsert_normalizes_per_serving_to_per_100g` (linha 129)

### TC-U-005 — `per_serving` sem tamanho rejeitado pelo schema
- **Módulo**: `apps/api/app/schemas/llm.py`
- **Função/Método**: `NutritionLabelIn._serving_needs_size` (model_validator)
- **Entrada**: `basis='per_serving'`, sem `serving_size_g` nem `serving_size_ml`.
- **Saída esperada**: `ValueError`.
- **Tipo**: Error case (SP-32)
- **Teste real**: `test_per_serving_without_size_rejected_by_schema` (linha 150)

### TC-U-006 — Micros ausentes geram warning
- **Módulo**: `apps/api/app/services/label_catalog.py`
- **Função/Método**: `upsert_from_label`
- **Entrada**: rótulo sem `calcium_mg`, `iron_mg`, `potassium_mg`.
- **Saída esperada**: `warnings` contém `{code:"micros_missing_for_product", missing:["calcium_mg","iron_mg","potassium_mg"]}`.
- **Tipo**: Edge case (SP-34)
- **Teste real**: `test_missing_micros_produces_warning` (linha 169)

### TC-U-007 — Micros completos não geram warning
- **Módulo**: `apps/api/app/services/label_catalog.py`
- **Função/Método**: `upsert_from_label`
- **Entrada**: rótulo com todos os micros preenchidos.
- **Saída esperada**: `warnings` não contém `micros_missing_for_product`.
- **Tipo**: Happy path
- **Teste real**: `test_complete_micros_no_warning` (linha 180)

### TC-U-008 — `also_consumed` cria food_record + food_item
- **Módulo**: `apps/api/app/services/label_catalog.py`
- **Função/Método**: `register_consumption`
- **Entrada**: fato criado; `also_consumed={quantity:170, unit:"g"}`.
- **Saída esperada**: `food_records` + `food_items` com `catalog_ref_id=fact.id`, `kcal` calculado via `NutritionCalculator`.
- **Tipo**: Happy path (SP-31)
- **Teste real**: `test_also_consumed_creates_food_record` (linha 195)

---

## Testes de Integração

### TC-I-001 — PATCH confirma valores (SP-33)
- **Fluxo**: `PATCH /nutrient-facts/{id}` → `AuditEventRepository.record`
- **Pré-condições**: fato `label_ocr` existe; usuário autenticado.
- **Passos**: `PATCH /nutrient-facts/{id} {kcal: 190}`.
- **Resultado esperado**: `kcal=190.00`, `verified_by_user=true`, audit `actor='user'`.
- **Teste real**: `test_patch_nutrient_fact_sets_verified` (linha 241)

### TC-I-002 — PATCH recusa fact TBCA
- **Fluxo**: `PATCH /nutrient-facts/{id}` em fato `TBCA_2023`
- **Resultado esperado**: `ValidationAppError(code='not_editable')` (422).
- **Teste real**: `test_patch_nutrient_fact_refuses_tbca_source` (linha 270)

### TC-I-003 — PATCH em id inexistente
- **Fluxo**: `PATCH /nutrient-facts/{id}` com id aleatório
- **Resultado esperado**: `NotFoundError(code='not_found')` (404).
- **Teste real**: `test_patch_nutrient_fact_not_found` (linha 287)

### TC-I-004 — Precedência TBCA > label_ocr (SP-35)
- **Fluxo**: `LocalTBCACatalog.lookup` com ambos os fatos
- **Resultado esperado**: retorna `TBCA_2023`.
- **Teste real**: `test_catalog_prefers_tbca_over_label_ocr` (linha 301)

### TC-I-005 — Precedência label_ocr verified > não-verified
- **Fluxo**: `LocalTBCACatalog.lookup` com dois fatos `label_ocr`
- **Resultado esperado**: retorna `verified_by_user=true`.
- **Teste real**: `test_catalog_prefers_label_ocr_when_verified` (linha 323)

---

## Testes E2E

### TC-E-001 — Cadastro via chat expõe nutrient_fact_id
- **Persona**: Felix (logado)
- **Jornada**: enviar foto de rótulo e receber `nutrient_fact_id` na resposta
- **Passos**:
  1. `POST /login`.
  2. `POST /chat/messages` com mídia + LLM mock devolvendo `intent=log_nutrition_label`.
  3. Polling `GET /chat/messages?after=...`.
- **Resultado esperado**: `raw_llm_response.dispatch.nutrient_fact_id` contém UUID.
- **Teste real**: `test_message_out_exposes_nutrient_fact_id` (linha 383)

### TC-E-002 — Mensagem não-label não tem nutrient_fact_id
- **Persona**: Felix
- **Jornada**: enviar mensagem de comida normal
- **Resultado esperado**: `dispatch` não contém `nutrient_fact_id`.
- **Teste real**: `test_non_label_message_has_no_nutrient_fact_id` (linha 411)

### TC-E-003 — Cadastro via chat cria só fato (sem food_record)
- **Persona**: Felix
- **Jornada**: enviar foto de rótulo sem `also_consumed`
- **Resultado esperado**: `nutrient_facts` criado, nenhum `food_records`.
- **Teste real**: `test_log_nutrition_label_via_chat_creates_fact_only` (linha 346)

---

## Testes de Regressão

- **INV-1 (LLM não calcula)**: valores do rótulo são persistidos como lidos; só `also_consumed` dispara `NutritionCalculator`. Se alguém calcular macros no upsert, falha.
- **INV-10 (audit em upsert e PATCH)**: `test_upsert_creates_fact` e `test_patch_sets_verified` validam audit.
- **Idempotência por barcode**: `test_upsert_updates_existing_on_repeat_barcode` — se alguém quebrar `_find_existing_label_fact`, duplica.
- **`verified_by_user` não rebaixado**: `test_upsert_preserves_verified_flag` — se alguém sobrescrever sem checar, falha.
- **`per_serving` normalizado**: `test_upsert_normalizes_per_serving` — se alguém parar de escalar, `basis='per_serving'` chega no banco (viola CheckConstraint).
- **SP-32 (validator)**: `test_per_serving_without_size_rejected` — se alguém remover o model_validator, valor inválido chega no service.
- **SP-35 (precedência)**: `test_catalog_prefers_tbca_over_label_ocr` — se alguém mudar ordem de precedência, falha.
