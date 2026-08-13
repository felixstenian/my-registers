# Requisitos — Leitura de rótulo nutricional (Fase 4.b)

> **Rastreabilidade**: SP-30..SP-35 em [`specs/001-mvp-registro-diario/spec.md`](../../001-mvp-registro-diario/spec.md#34-leitura-de-tabela-nutricional-rotulo) · Fase 4.b em [`plan.md`](../../001-mvp-registro-diario/plan.md) · Invariantes: INV-1, INV-4, INV-10 · Constituição Art. III §35 · Implementação: `apps/api/app/services/label_catalog.py`, `apps/api/app/api/routes/nutrient_facts.py`.

## Visão geral

Cadastrar produtos no catálogo (`nutrient_facts` com `source='label_ocr'`) a partir de fotos de rótulo enviadas no chat. A LLM extrai valores nutricionais via `tool_use` (não calcula — INV-1); o backend normaliza `per_serving` para `per_100g|per_100ml`, grava com `verified_by_user=false` e, se o usuário também consumiu, cria `food_records`/`food_items` referenciando o fato recém-criado. `PATCH /nutrient-facts/{id}` permite confirmar/ajustar valores (SP-33). Micros ausentes (Ca/Fe/K) geram warning (SP-34). Precedência do catálogo em SP-35.

## Requisitos funcionais

| ID | Requisito | SP | Prioridade |
|---|---|---|---|
| RF-001 | Foto do rótulo **sem** menção a consumo → nova linha em `nutrient_facts` com `source='label_ocr'`, `label_media_id`, `verified_by_user=false`. **Nenhum** `food_records`. Assistente exibe cartão com valores por 100g/100ml. | SP-30 | Must Have |
| RF-002 | Foto do rótulo + "comi um pote (170g)" → cria `nutrient_facts` **e** `food_records`/`food_items` com `catalog_ref_id` apontando para o fato. Cálculo via `NutritionCalculator` (INV-1). | SP-31 | Must Have |
| RF-003 | Rótulo com `basis='per_serving'` sem `serving_size_g`/`serving_size_ml` → `NutritionLabelIn.model_validator` rejeita; assistente pergunta tamanho da porção. | SP-32 | Must Have |
| RF-004 | `PATCH /nutrient-facts/{id}` aceita ajuste dos valores; seta `verified_by_user=true`. Recusa facts com `source` não-editável (`TBCA_2023`, `USDA_FDC`). | SP-33 | Must Have |
| RF-005 | Cálcio/ferro/potássio geralmente `null` em rótulos brasileiros (RDC 429/2020). Backend grava `null` + `warnings:[{code:"micros_missing_for_product"}]`. | SP-34 | Must Have |
| RF-006 | Precedência de lookup (SP-35): (1) marca casada; (2) `TBCA_2023` > `label_ocr` > `manual`; (3) `verified_by_user=true` > `false`; (4) mais recente. Garantida pelo `LocalTBCACatalog`. | SP-35 | Must Have |
| RF-007 | Idempotência: reupload de mesmo `barcode` (ou `(canonical_name, brand)` se sem barcode) **atualiza** valores em vez de duplicar. `verified_by_user=true` **nunca** é rebaixado por reupload. | [Inferido do código] | Must Have |
| RF-008 | `per_serving` com `serving_size_g|ml` é escalado para `per_100g|per_100ml` no upsert — catálogo só armazena basis canônico. | [Inferido do código] | Must Have |
| RF-009 | Se `also_consumed` presente, `DailyRecomputeService.recompute` roda após criar food_record (INV-4). | INV-4 | Must Have |
| RF-010 | Gravar `audit_events` em upsert (`action='create'` ou `'update'`, `entity_type='nutrient_fact'`) e em `PATCH` (`actor='user'`). | INV-10 | Must Have |

## Requisitos não funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | Isolamento por usuário: queries de `nutrient_facts` respeitam `user_id` onde aplicável (Const. §21). Nota: catálogo é parcialmente compartilhado entre usuários — `nutrient_facts` não tem `user_id`, mas `PATCH` exige auth. | Segurança |
| RNF-002 | LLM não calcula: valores nutricionais da LLM são persistidos como lidos; `per_serving` é **escalado** (matemática determinística), não recalculado. `NutritionCalculator` só roda para `also_consumed` (INV-1). | Confiabilidade |
| RNF-003 | `source` restrito a `('TBCA_2023','USDA_FDC','manual','label_ocr')` por `CheckConstraint`. | Integridade |
| RNF-004 | `basis` restrito a `('per_100g','per_100ml')` por `CheckConstraint` — `per_serving` é normalizado antes de persistir. | Integridade |
| RNF-005 | Aviso legal obrigatório em toda resposta do assistente (Const. Art. VII §26). | Compliance |
| RNF-006 | Foto do rótulo enviada base64 para Anthropic (Const. §26, privacidade). | Privacidade |

## Restrições e premissas

- **Catálogo é parcialmente compartilhado**: `nutrient_facts` não tem `user_id` — um produto cadastrado por label_ocr fica visível no lookup para todos. Decisão de MVP (single-user); em multi-tenant, precisaria `owner_user_id`. <!-- TODO: verificar se há plano para isolamento de catálogo por usuário -->
- **`label_media_id`** = primeira mídia da mensagem (ordem por `media_id`). Se múltiplas fotos, só a primeira vira referência do rótulo.
- **`also_consumed` é opcional**: `NutritionLabelIn.also_consumed: NutritionLabelAlsoConsumed | None`. Sem ele, só cadastra o fato (SP-30).
- **`PATCH` só edita `label_ocr` e `manual`**: facts `TBCA_2023`/`USDA_FDC` são canônicos e não editáveis (`code="not_editable"`).
- **Micros `calcium_mg`, `iron_mg`, `potassium_mg`** são os que rótulos BR geralmente omitem (RDC 429/2020). `sodium_mg` é obrigatório em rótulos BR.
- **`aliases`** gerado como `{canonical, normalize_name(product_name)}` — permite lookup por variações.

## Dependências

**Depende de:**
- [`anthropic-integration`](../anthropic-integration/requirements.md) — `LLMEnvelope` via `tool_use`; `NutritionLabelIn` é sub-schema.
- [`chat-messaging`](../chat-messaging/requirements.md) — pipeline `POST /chat/messages` → `MessageProcessor._handle_log_nutrition_label` → `LabelCatalogService`.
- [`media-storage`](../media-storage/requirements.md) — foto do rótulo já está em MinIO; `label_media_id` referencia.
- [`food-logging`](../food-logging/requirements.md) — `register_consumption` reutiliza `FoodRecordRepository`, `FoodItemRepository`, `NutritionCalculator`.
- [`daily-snapshot`](../daily-snapshot/requirements.md) — `DailyRecomputeService.recompute` roda se `also_consumed`.

**Requerido por:**
- [`food-logging`](../food-logging/requirements.md) — `LocalTBCACatalog.lookup` inclui facts `label_ocr` na precedência (SP-35).
- [`manual-catalog-recovery`](../manual-catalog-recovery/requirements.md) — fluxo relacionado de cadastro manual de produtos sem catálogo.
