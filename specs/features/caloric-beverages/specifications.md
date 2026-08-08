# Especificações Técnicas — Registro de bebidas calóricas

> **Rastreabilidade**: SP-50..SP-52 · Implementação: `apps/api/app/services/beverage.py`, `apps/api/app/repositories/beverage.py`, `apps/api/app/models/beverage_record.py`, `apps/api/app/schemas/llm.py` (BeverageIn), `apps/api/app/services/daily_recompute.py:181` (`_aggregate_beverage`).

## Escopo técnico

Backend cria e persiste `beverage_records` a partir de um `LLMEnvelope` com `intent=log_beverage` e bloco `beverage` preenchido. Sem endpoint HTTP próprio — toda criação passa pelo `POST /chat/messages` (`chat-messaging`). Correção e deleção por endpoints genéricos em `records.py`.

## Interface

### Entrada (LLMEnvelope via `tool_use`)

```python
class BeverageIn(_LenientBase):           # extra="ignore" — tolera campos extras da LLM
    detected_name: str
    brand: str | None = None
    volume_ml: float = Field(ge=1)        # ml, mínimo 1
    beverage_kind: Literal["other"] = "other"   # fixo no MVP
    confidence: float                     # 0..1, Decimal(3,2) no banco
```

`LLMEnvelope.intent == "log_beverage"` + `LLMEnvelope.beverage` preenchido. Campos extras (ex.: `kcal`, `sugars_g` inventados pela LLM) são **ignorados** (`_LenientBase`), não rejeitados — estratégia oposta ao `WaterIn` (`_StrictBase`).

### Saída (snapshot do dia)

`daily_snapshots`:
- `other_liquids_ml: int` — soma de `volume_ml` de `beverage_records` vivos.
- `kcal_in: Decimal` — `food_totals.kcal + bev_totals.kcal` (Const. Art. IV §13).
- macros/micros somados igual a alimentos.

Exposto em:
- `GET /days/today`, `GET /days/{date}` → campos `other_liquids_ml`, `kcal_in` + lista `beverage`.
- `GET /weekly` → soma entre dias fechados.

### Erros de domínio

| Code | Quando | HTTP | Tradução no `MessageProcessor` |
|---|---|---|---|
| `invalid_beverage_envelope` | `envelope.beverage is None` em `intent=log_beverage` | 422 | `validation_exhausted` — "Não consegui interpretar" |

Não há equivalente de `water_intent_rejected` para beverage — o backend aceita qualquer bebida; a validação anti-dupla-contagem (SP-51) é estrutural (tabelas separadas).

## Modelo de dados

### `beverage_records`

| Coluna | Tipo | Constraints | Notas |
|---|---|---|---|
| `id` | UUID PK | `uuid_generate_v4()` | herda de `UUIDPrimaryKeyMixin` |
| `user_id` | UUID FK → `users.id` | `NOT NULL`, `ON DELETE CASCADE` | isolamento (Const. §21) |
| `day_log_id` | UUID FK → `day_logs.id` | `NOT NULL`, `ON DELETE RESTRICT` | |
| `message_id` | UUID FK → `messages.id` | nullable, `ON DELETE SET NULL` | |
| `occurred_at` | `DateTime(timezone=true)` | `NOT NULL` | |
| `detected_name` | `Text` | `NOT NULL` | o que a LLM leu |
| `normalized_name` | `Text` | `NOT NULL` | `normalize_name(detected_name)` |
| `brand` | `Text` | nullable | |
| `volume_ml` | `Integer` | `NOT NULL`, `CHECK volume_ml > 0` | SP-50 |
| `source` | `Text` | `NOT NULL`, `CHECK source IN ('manual','llm','user_corrected','catalog')` | nota: aceita `catalog`, water não |
| `confidence` | `Numeric(3,2)` | nullable | |
| `is_estimate` | `Boolean` | `NOT NULL`, default `false` | |
| `needs_confirmation` | `Boolean` | `NOT NULL`, default `false` | SP-52: `confidence<0.5` ou `hit is None` |
| `catalog_ref_id` | UUID FK → `nutrient_facts.id` | nullable, `ON DELETE SET NULL` | null = sem catálogo (SP-52) |
| `kcal` | `Numeric(10,2)` | nullable | materializado (não calcula sob demanda) |
| `protein_g`, `carbs_g`, `fat_g`, `fiber_g` | `Numeric(10,2)` | nullable | macros materializados |
| `sodium_mg`, `calcium_mg`, `iron_mg`, `potassium_mg` | `Numeric(10,2)` | nullable | micros materializados |
| `created_at` / `updated_at` | `DateTime(timezone=true)` | `NOT NULL`, trigger | `TimestampMixin` |
| `deleted_at` | `DateTime(timezone=true)` | nullable | soft delete |

**Diferença vs. `water_records`**: tem colunas de kcal/macros/micros + `catalog_ref_id` + `needs_confirmation`. INV-3 estrutural: a separação física impede que bebida vaze para `water_ml`.

### Migration

`apps/api/alembic/versions/0004_hydration_beverage_activity.py` (Fase 5, T-501) — cria `water_records`, `beverage_records`, `activity_records` juntos.

## Fluxo de dados

1. Usuário envia "200ml de café" via `POST /chat/messages`.
2. `chat.router` insere `messages(role=user)`, retorna `202`.
3. `MessageProcessor.process(message_id)`:
   a. `AnthropicClient.classify` → `LLMEnvelope(intent="log_beverage", beverage={detected_name:"cafe coado sem acucar", volume_ml:200, confidence:0.9}, user_text_summary=".")`.
   b. `IntentDispatcher._handle_log_beverage` → `BeverageService(self.session, catalog).create_from_llm(...)`.
   c. `BeverageService`:
      - `normalize_name(entry.detected_name)` → lookup no `NutritionCatalog`.
      - `NutritionCalculator.compute(hit, grams=None, ml=200)` → `ComputedNutrition(kcal, macros, micros)`.
      - `needs_confirmation = confidence < 0.5 or hit is None`.
      - `BeverageRecordRepository.create(...)` com macros materializados.
      - coleta `warnings`: `no_catalog_hit` se `hit is None`, `low_confidence_item` se `confidence<0.5`.
      - `AuditEventRepository.record(action="create", entity_type="beverage_record", actor="llm", after={volume_ml, detected_name, occurred_at})`.
   d. `DailyRecomputeService.recompute(day_log_id)`:
      - `_aggregate_beverage`: `SELECT SUM(kcal), SUM(protein_g), ..., SUM(volume_ml) WHERE deleted_at IS NULL` → `bev_totals`.
      - `kcal_in = food_totals.kcal + bev_totals.kcal`.
      - `other_liquids_ml = bev_totals.volume_ml`.
      - UPSERT em `daily_snapshots`.
   e. `MessageFormatter.compose_beverage(beverage, recompute, local_today)` → "Registrei 200 ml de cafe coado sem acucar.\\n\\n<table>\\n\\n<daily>\\n\\n<disclaimer>".
   f. `MessageProcessor` insere `messages(role=assistant)`.
4. Cliente faz polling `GET /chat/messages?after=<user_msg_id>`.

## Regras de negócio

1. **Bebida ≠ água** (Art. IV §13-14, INV-3): `beverage_records` só recebe bebida calórica. Tabelas separadas garantem que `SUM(water_ml)` nunca inclui bebida e `SUM(other_liquids_ml)` nunca inclui água pura.
2. **`kcal_in` combina food + beverage**: `kcal_in = food_totals.kcal + bev_totals.kcal` (Const. Art. IV §13). Água (`water_records`) não entra em `kcal_in`.
3. **Catálogo opcional (SP-52)**: se `hit is None`, macros zerados, `needs_confirmation=true`, `warnings:[{code:"no_catalog_hit"}]`. Assistente pede valores por 100g/marca (fluxo `clarify` ou `manual-catalog-recovery`).
4. **`needs_confirmation` duplo gatilho**: `confidence < 0.5` (LOW_CONFIDENCE_THRESHOLD) **ou** `hit is None`.
5. **`normalize_name`** antes do lookup — mesmo utilitário de `food-logging`.
6. **Basis `per_100ml`**: `NutritionCalculator.compute(hit, grams=None, ml=volume_ml)` sempre por volume. Se catálogo tem `per_100g`, cai em `unknown_basis` (raro para bebidas).
7. **Recompute from-scratch** (INV-4): sempre `SUM` completo, nunca delta.
8. **Sem rejeição semântica como em water**: beverage aceita qualquer `detected_name`. Se a LLM mandar "água" como `log_beverage`, persiste (mas `kcal=0`, `other_liquids_ml` soma — tecnicamente incorreto, mas sem gate defensivo hoje). <!-- TODO: verificar se há teste para "água classificada como beverage" -->

## Configurações e variáveis de ambiente

| Variável | Descrição | Padrão | Obrigatória |
|---|---|---|---|
| `ANTHROPIC_MODEL` | Modelo que classifica intent e extrai `beverage.volume_ml` | `claude-sonnet-4-6` | Sim |
| `ANTHROPIC_FALLBACK_MODEL` | Fallback | `claude-haiku-4-5-20251001` | Não |

Sem variáveis específicas de beverage — toda config vem de `anthropic-integration` e `chat-messaging`.

## Referências de implementação

- **Service**: `apps/api/app/services/beverage.py` — `BeverageService.create_from_llm`, `LOW_CONFIDENCE_THRESHOLD=0.5`.
- **Repository**: `apps/api/app/repositories/beverage.py` — `BeverageRecordRepository.create`.
- **Model**: `apps/api/app/models/beverage_record.py` — `BeverageRecord` (com kcal/macros/micros + `catalog_ref_id`).
- **Schema LLM**: `apps/api/app/schemas/llm.py:72` — `BeverageIn(_LenientBase)`.
- **Integração no pipeline**: `apps/api/app/services/message_processor.py:228` — `elif envelope.intent == "log_beverage"`.
- **Recompute**: `apps/api/app/services/daily_recompute.py:181` — `_aggregate_beverage`; linha 72 — `kcal_in = food_totals.kcal + bev_totals.kcal`; linha 97 — `other_liquids_ml=bev_totals.volume_ml`.
- **Formatter**: `apps/api/app/services/message_formatter.py:249` — `compose_beverage`.
- **Prompt**: `apps/api/app/integrations/anthropic/prompts/system_v2.md` — "Bebidas calóricas → `intent=log_beverage`, campo `beverage`".
- **Migration**: `apps/api/alembic/versions/0004_hydration_beverage_activity.py`.
- **Tests**: `apps/api/tests/test_hydration_beverage_activity.py` — `test_sp50_beverage_with_catalog_hit`, `test_sp52_beverage_no_catalog_zeros`, `test_beverage_never_lands_in_water_table`; `apps/api/tests/test_log_liquids_activity_flow.py` (E2E).
