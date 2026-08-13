# Requisitos — Registro de bebidas calóricas

> **Rastreabilidade**: SP-50..SP-52 em [`specs/001-mvp-registro-diario/spec.md`](../../001-mvp-registro-diario/spec.md#36-registro-de-outros-liquidos-bebidas-caloricas) · Fase 5 em [`plan.md`](../../001-mvp-registro-diario/plan.md) · Invariantes: INV-3, INV-4, INV-10 · Constituição Art. IV §13-14 · T-501, T-506, T-508 em [`tasks.md`](../../001-mvp-registro-diario/tasks.md).

## Visão geral

Registrar consumo de **bebidas com calorias** (café, leite, suco, refrigerante, chá adoçado, álcool) por chat, com persistência em `beverage_records` — tabela **separada** de `water_records` (INV-3 estrutural). Macros/micros são resolvidos via `NutritionCatalog` + `NutritionCalculator` (mesmo pipeline de alimentos). Bebida calórica **nunca** contribui para `water_ml`, só para `other_liquids_ml` + `kcal_in` + macros. Sem catálogo → macros zerados + `warnings`. Cada criação dispara recompute from-scratch (INV-4) e grava `audit_events` (INV-10).

## Requisitos funcionais

| ID | Requisito | SP | Prioridade |
|---|---|---|---|
| RF-001 | Aceitar "200ml de café", "300ml de suco" → `beverage_records` com `volume_ml`, macros do catálogo (basis `per_100ml`) ou estimativa. Total soma em `other_liquids_ml` e `kcal_in`. | SP-50 | Must Have |
| RF-002 | Bebida calórica **nunca** contribui para `water_ml`. Água pura **nunca** para `other_liquids_ml`. Garantido por tabelas separadas + agregação distinta no `DailyRecomputeService` (INV-3 estrutural). | SP-51, Art. IV §13 | Must Have |
| RF-003 | Bebida sem hit no catálogo → `catalog_ref_id=null`, macros zerados, `needs_confirmation=true`, `warnings:[{code:"no_catalog_hit"}]`; assistente pergunta valores por 100g/marca (igual SP-23 para alimentos). | SP-52 | Must Have |
| RF-004 | Marcar `needs_confirmation=true` quando `confidence < 0.5` ou `hit is None`; assistente destaca visualmente (mesmo fluxo de SP-24). | SP-52 | Must Have |
| RF-005 | Recomputar `daily_snapshots` do dia inteiro from-scratch após cada criação — `other_liquids_ml = SUM(beverage_records.volume_ml)`, `kcal_in = food_totals.kcal + bev_totals.kcal`. | INV-4 | Must Have |
| RF-006 | Gravar `audit_events(actor='llm', action='create', entity_type='beverage_record')` referenciando `message_id` de origem; `after={volume_ml, detected_name, occurred_at}`. | INV-10 | Must Have |

## Requisitos não funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | Isolamento por usuário: `BeverageRecordRepository.create` recebe `user_id` obrigatório (Const. §21). | Segurança |
| RNF-002 | INV-3 garantido por **tabela separada**: `beverage_records` e `water_records` não compartilham schema. Nenhuma query de `SUM(water_ml)` toca `beverage_records`. | Confiabilidade |
| RNF-003 | Determinismo: dado o mesmo `BeverageIn` + mesmo estado de catálogo, `BeverageService.create_from_llm` gera registro com macros idênticos (Decimal quantize `0.01`). | Confiabilidade |
| RNF-004 | `volume_ml > 0` enforced por `CheckConstraint` no Postgres. | Integridade |
| RNF-005 | `source` restrito a `('manual','llm','user_corrected','catalog')` por `CheckConstraint` (nota: beverage aceita `catalog`, water não). | Integridade |
| RNF-006 | Aviso legal obrigatório em toda resposta do assistente (Const. Art. VII §26). | Compliance |

## Restrições e premissas

- **Bebida calórica apenas** (Const. Art. IV §13): café, leite, suco, refrigerante, chá adoçado, álcool. Água pura vai para `water-tracking` (feature irmã). Se a LLM classificar "café" como `log_water`, o `HydrationService` rejeita (SP-41) e o `MessageProcessor` traduz em `clarify`.
- **Catálogo local**: lookup via `NutritionCatalog.lookup(name, brand)` — mesmo catálogo de alimentos (TBCA). Ordem de precedência definida em SP-35.
- **Basis `per_100ml`**: `NutritionCalculator.compute(hit, grams=None, ml=volume_ml)` — bebidas sempre calculam por volume. Se o catálogo tiver `per_100g`, cai em `unknown_basis` (raro).
- **Sem `per_serving`**: rótulo de bebida com `per_serving` fica com a feature `nutrition-label-ocr`.
- **LLM não calcula**: valores nutricionais emitidos pela LLM em texto livre são descartados (INV-1, INV-9). Só `BeverageIn` é consumido.
- **`beverage_kind='other'`** fixo no schema hoje — não há subtipos (alcoólico, lácteo, etc.). <!-- TODO: verificar se SP futuro quer discriminar beverage_kind -->

## Dependências

**Depende de:**
- [`anthropic-integration`](../anthropic-integration/requirements.md) — `LLMEnvelope` via `tool_use`; `BeverageIn` é sub-schema.
- [`chat-messaging`](../chat-messaging/requirements.md) — pipeline `POST /chat/messages` → `MessageProcessor` → `IntentDispatcher._handle_log_beverage` → `BeverageService.create_from_llm`.
- [`food-logging`](../food-logging/requirements.md) — compartilha `NutritionCatalog` + `NutritionCalculator` + `normalize_name`.
- [`daily-snapshot`](../daily-snapshot/requirements.md) — `DailyRecomputeService._aggregate_beverage` roda ao final.

**Requerido por:**
- [`daily-snapshot`](../daily-snapshot/requirements.md) — snapshot lê `beverage_records` vivos.
- [`day-close`](../day-close/requirements.md) — encerramento usa `other_liquids_ml` + `kcal_in`.
- [`weekly-report`](../weekly-report/requirements.md) — soma `other_liquids_ml` + `kcal_in` entre dias fechados.
- [`record-correction`](../record-correction/requirements.md) e [`record-deletion`](../record-deletion/requirements.md) — mutam `beverage_records` posteriormente.
- [`water-tracking`](../water-tracking/requirements.md) — complementar: o que é rejeitado por `_NON_WATER_HINTS` em `log_water` deveria vir como `log_beverage`.
