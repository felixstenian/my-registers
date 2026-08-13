# Requisitos — Registro de alimentos

> **Rastreabilidade**: SP-20..SP-26 em [`specs/001-mvp-registro-diario/spec.md`](../../001-mvp-registro-diario/spec.md#33-registro-de-alimentos) · Fase 4 em [`plan.md`](../../001-mvp-registro-diario/plan.md) · Invariantes: INV-1, INV-4, INV-10.

## Visão geral

Registrar alimentação por chat (texto e/ou foto), com o backend calculando kcal/macros/micros de forma determinística a partir do catálogo local TBCA. A LLM apenas interpreta a mensagem e extrai itens estruturados via `tool_use`; nenhuma soma nutricional depende dela (Const. Art. II §5, INV-1). Cada envio produz 1 `food_records` + N `food_items` na mesma `day_log` e dispara recomputo completo do snapshot do dia.

## Requisitos funcionais

| ID | Requisito | SP | Prioridade |
|---|---|---|---|
| RF-001 | Aceitar texto com quantidades explícitas ("150 g de arroz, 90 g de feijão, 180 g de frango") e criar 1 `food_records` + 3 `food_items` com macros resolvidos via catálogo. | SP-20 | Must Have |
| RF-002 | Interpretar unidade doméstica (concha, colher, xícara, prato, pote) marcando `is_estimate=true` e `confidence ≤ 0.7`; UI destaca visualmente. | SP-21 | Must Have |
| RF-003 | Aceitar até 4 fotos por mensagem (SP-11) e transformá-las em 1 `food_records`; cada alimento visível vira `food_items` com `is_estimate=true` e `confidence ≤ 0.7`, com pedido de confirmação. | SP-22, SP-25 | Must Have |
| RF-004 | Persistir item mesmo sem hit no catálogo (`catalog_ref_id=null`, macros zerados) e emitir `warnings: {code:"no_catalog_hit"}` no snapshot; assistente pergunta valores por 100g/marca. | SP-23 | Must Have |
| RF-005 | Marcar `needs_confirmation=true` quando `confidence < 0.5`; item aparece destacado até ser confirmado por chat (SP-24a) ou por `PATCH /records/food-items/{id}`. | SP-24 | Must Have |
| RF-006 | Aceitar `meal_slot` opcional; ausente ou indeterminado → `unspecified` (não bloqueia registro). | SP-26 | Should Have |
| RF-007 | Recomputar `daily_snapshots` do dia inteiro from-scratch após cada criação (INV-4). | INV-4 | Must Have |
| RF-008 | Gravar `audit_events(actor='llm', action='create', entity_type='food_record')` referenciando `message_id` de origem. | INV-10 | Must Have |
| RF-009 | Reter `raw_llm_response` para debugging e não persistir texto livre da LLM fora do envelope `tool_use`. | INV-9 | Must Have |

## Requisitos não funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | Cobertura mínima de testes em `NutritionCalculator` e `MealService`: 90% (plan.md §5.3). | Qualidade |
| RNF-002 | Isolamento por usuário: `MealService` e todos os repositórios recebem `user_id` obrigatório (Const. §21). | Segurança |
| RNF-003 | Determinismo: dado o mesmo envelope + mesmo estado de catálogo, `create_from_llm` gera itens com macros idênticos (Decimal quantize `0.01`). | Confiabilidade |
| RNF-004 | Fotos vão para Anthropic via base64, nunca URL (Const. Art. VII §26, privacidade). | Privacidade |
| RNF-005 | Aviso legal obrigatório em toda resposta do assistente (Const. Art. VII §26). | Compliance |

## Restrições e premissas

- **LLM não calcula**: qualquer valor nutricional emitido pela LLM (kcal, macros) é **descartado**. Só extrai `detected_name`, `normalized_name`, `brand`, `quantity`, `unit`, `grams_estimate`, `ml_estimate`, `confidence`, `is_estimate`. Cálculo cabe ao `NutritionCalculator` sobre o `CatalogHit` do `LocalTBCACatalog`.
- **Catálogo local**: fonte primária é o seed TBCA (`app.integrations.nutrition.catalog.LocalTBCACatalog`, semeado por `pnpm db:bootstrap`); ordem de precedência definida em SP-35.
- **Envelope aceita 0..N itens**: `food_items=[]` levanta `ValueError` em `MealService.create_from_llm` (invocar só quando `intent=log_food` e a LLM retornou itens).
- **Basis fixo**: catálogo só suporta `per_100g` ou `per_100ml`; `per_serving` fica com o fluxo de rótulo (feature `nutrition-label-ocr`).
- **Sem edição inline no MVP**: correção e deleção são features separadas (`record-correction`, `record-deletion`).

## Dependências

**Depende de:**
- [`anthropic-integration`](../anthropic-integration/requirements.md) — `LLMEnvelope` via `tool_use` forçado com retry semântico.
- [`chat-messaging`](../chat-messaging/requirements.md) — pipeline `POST /chat/messages` → `MessageProcessor` → `IntentDispatcher._handle_log_food`.
- [`media-storage`](../media-storage/requirements.md) — quando envelope inclui fotos (SP-22, SP-25); mídia já foi validada e ligada à `messages` antes.
- Seed TBCA (`app/integrations/nutrition/tbca_seed.py`) — via `app.cli bootstrap`.
- [`daily-snapshot`](../daily-snapshot/requirements.md) — `DailyRecomputeService.recompute(day_log_id)` roda ao final.

**Requerido por:**
- [`daily-snapshot`](../daily-snapshot/requirements.md) — snapshot lê `food_items` vivos.
- [`day-close`](../day-close/requirements.md) — encerramento agrega totais do dia.
- [`weekly-report`](../weekly-report/requirements.md) — relatório semanal roda por cima dos snapshots fechados.
- [`assistant-message-rendering`](../assistant-message-rendering/requirements.md) — SP-115..118 renderizam a resposta.
- [`record-correction`](../record-correction/requirements.md) e [`record-deletion`](../record-deletion/requirements.md) — mutações posteriores.
- [`manual-catalog-recovery`](../manual-catalog-recovery/requirements.md) — quando SP-23 dispara, o usuário pode entrar aqui.
