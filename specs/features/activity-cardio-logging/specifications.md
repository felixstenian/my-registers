# Especificações Técnicas — Registro de atividade física (cardio)

> **Rastreabilidade**: SP-60..SP-64 · Implementação: `apps/api/app/services/activity.py`, `apps/api/app/services/activity_calculator.py`, `apps/api/app/repositories/activity.py`, `apps/api/app/models/activity_record.py`, `apps/api/app/schemas/llm.py` (ActivityIn), `apps/api/app/services/daily_recompute.py:238` (`_aggregate_activity`).

## Escopo técnico

Backend cria e persiste `activity_records` a partir de um `LLMEnvelope` com `intent=log_activity` e bloco `activity` preenchido. `kcal_burned` é calculado por `ActivityCalculator` (fórmula MET) ou extraído de `kcal_burned_reported` (dispositivo). Sem endpoint HTTP próprio — toda criação via `POST /chat/messages`.

## Interface

### Entrada (LLMEnvelope via `tool_use`)

```python
class ActivityIn(_LenientBase):           # extra="ignore"
    detected_name: str
    activity_type: str                    # ex.: "cardio_run", "corrida", "strength"
    duration_minutes: float = Field(ge=1) # minutos ( aceita string numérica via validator)
    distance_km: float | None = None
    intensity: Literal["light","moderate","vigorous","unknown"] = "unknown"
    confidence: float
    kcal_burned_reported: float | None = Field(default=None, ge=0, le=10000)  # de smartwatch
```

`LLMEnvelope.intent == "log_activity"` + `LLMEnvelope.activity` preenchido. Campos extras (`pace`, `heart_rate`) são ignorados (`_LenientBase`).

**Validators especiais**:
- `intensity` aceita pt-BR ("moderada", "leve", "intenso") via `_normalize_intensity` antes do Literal.
- `duration_minutes` aceita string numérica ("40") e com unidade ("40 min") via validator before.

### Saída (snapshot do dia)

`daily_snapshots`:
- `kcal_out: Decimal` — soma de `kcal_burned` de `activity_records` vivos.
- `kcal_balance: Decimal` — `kcal_in - kcal_out`.

Exposto em `GET /days/today`, `GET /days/{date}`, `GET /weekly`.

### Erros de domínio

| Code / Exception | Quando | HTTP | Tradução |
|---|---|---|---|
| `invalid_activity_envelope` | `envelope.activity is None` | 422 | `validation_exhausted` |
| `WeightRequired` (exceção) | `users.weight_kg is None` e sem `kcal_burned_reported` | — | `MessageProcessor` traduz em `clarify` — pede peso |

### Warnings emitidos

| Code | Quando |
|---|---|
| `low_confidence_item` | `confidence < 0.5` |
| `unknown_activity_or_intensity` | par (activity_type, intensity) não está em `_MET_TABLE` → `kcal_burned=0`, `calc_method='llm_estimate'` |
| `missing_duration` | `duration_minutes <= 0` e sem estimativa por distância |
| `missing_weight_kg` | `weight_kg <= 0` (não deve ocorrer — `WeightRequired` levanta antes) |

## Modelo de dados

### `activity_records`

| Coluna | Tipo | Constraints | Notas |
|---|---|---|---|
| `id` | UUID PK | `uuid_generate_v4()` | |
| `user_id` | UUID FK → `users.id` | `NOT NULL`, `ON DELETE CASCADE` | Const. §21 |
| `day_log_id` | UUID FK → `day_logs.id` | `NOT NULL`, `ON DELETE RESTRICT` | |
| `message_id` | UUID FK → `messages.id` | nullable, `ON DELETE SET NULL` | |
| `occurred_at` | `DateTime(timezone=true)` | `NOT NULL` | |
| `detected_name` | `Text` | `NOT NULL` | o que a LLM leu |
| `normalized_name` | `Text` | `NOT NULL` | `normalize_name(detected_name)` |
| `activity_type` | `Text` | `NOT NULL` | canônico (ex.: `cardio_run`) |
| `duration_minutes` | `Numeric(6,2)` | `NOT NULL`, `CHECK > 0` | minutos |
| `distance_km` | `Numeric(6,3)` | nullable | |
| `intensity` | `Text` | `NOT NULL`, `CHECK IN ('light','moderate','vigorous','unknown')` | default `unknown` |
| `met_value` | `Numeric(4,2)` | nullable | MET usado no cálculo (SP-64) |
| `kcal_burned` | `Numeric(10,2)` | `NOT NULL`, default `0` | materializado |
| `calc_method` | `Text` | `NOT NULL`, `CHECK IN ('mets_body_weight','llm_estimate','user_manual')` | SP-64 |
| `confidence` | `Numeric(3,2)` | nullable | |
| `notes` | `Text` | nullable | |
| `created_at` / `updated_at` | `DateTime(timezone=true)` | `NOT NULL`, trigger | |
| `deleted_at` | `DateTime(timezone=true)` | nullable | soft delete |

### Tabela MET (`_MET_TABLE` em `activity_calculator.py`)

| activity_type \ intensity | light | moderate | vigorous | unknown |
|---|---|---|---|---|
| `cardio_run` | 6.0 | 8.3 | 11.5 | 8.3 |
| `cardio_walk` | 2.8 | 3.8 | 5.0 | 3.5 |
| `bike` | 4.0 | 6.8 | 10.0 | 6.0 |
| `swim` | 4.0 | 7.0 | 10.0 | 6.0 |
| `strength` | 3.5 | 5.0 | 6.0 | 5.0 |
| `yoga` | 2.0 | 3.0 | 4.0 | 2.5 |
| `cardio` | 4.0 | 6.5 | 9.0 | 6.0 |

### Velocidades médias (`_SPEED_KMH`) — SP-63

| activity_type | km/h |
|---|---|
| `cardio_walk` | 5.0 |
| `cardio_run` | 9.0 |
| `bike` | 20.0 |
| `swim` | 3.5 |
| `cardio` | 7.0 |

### Migration

`apps/api/alembic/versions/0004_hydration_beverage_activity.py` (Fase 5, T-501).

## Fluxo de dados

1. Usuário envia "corri 40 min moderado" via `POST /chat/messages`.
2. `chat.router` insere `messages(role=user)`, retorna `202`.
3. `MessageProcessor.process(message_id)`:
   a. `AnthropicClient.classify` → `LLMEnvelope(intent="log_activity", activity={detected_name:"corrida", activity_type:"cardio_run", duration_minutes:40, intensity:"moderate", confidence:0.9})`.
   b. `IntentDispatcher._handle_log_activity` → `ActivityService(self.session).create_from_llm(...)`.
   c. `ActivityService`:
      - se `kcal_burned_reported` presente → usa como `kcal_burned`, `calc_method='user_manual'`, `met_value` do lookup para contexto.
      - senão, se `users.weight_kg is None` → `WeightRequired` (SP-61).
      - senão → `ActivityCalculator.compute(activity_type, intensity, duration, weight_kg)` → `ActivityComputation(met_value, kcal_burned, calc_method, reasons)`.
      - SP-62: `strength` + `unknown` → `intensity_for_calc='moderate'` (registro guarda `unknown`).
      - SP-63: se `duration <= 0` e `distance_km` presente → `estimate_duration_from_distance`.
      - `ActivityRecordRepository.create(...)` com `met_value`, `kcal_burned`, `calc_method` materializados.
      - coleta `warnings` (`low_confidence_item`, `unknown_activity_or_intensity`, etc.).
      - `AuditEventRepository.record(action="create", entity_type="activity_record", actor="llm", after={activity_type, duration_minutes, kcal_burned, calc_method, occurred_at})`.
   d. `DailyRecomputeService.recompute(day_log_id)`:
      - `_aggregate_activity`: `SELECT SUM(kcal_burned) WHERE deleted_at IS NULL` → `kcal_out`.
      - `kcal_balance = kcal_in - kcal_out`.
      - UPSERT em `daily_snapshots`.
   e. `MessageFormatter.compose_activity(activity, recompute, local_today)` → "Registrei 40 min de corrida (moderada).\\n\\n<table>\\n\\n<daily>\\n\\n<disclaimer>".
   f. `MessageProcessor` insere `messages(role=assistant)`.
4. Cliente faz polling.

## Regras de negócio

1. **Fórmula MET**: `kcal = met × weight_kg × (duration_minutes / 60)`. `met` vem de `_MET_TABLE[canonical_activity_type, intensity]`.
2. **`kcal_burned_reported` é autoritativo** (Const. Art. III §10): se presente, sobrescreve cálculo MET. `calc_method='user_manual'`. Não recalcula em recompute.
3. **SP-61 — peso obrigatório** (sempre que não houver `kcal_burned_reported`): `WeightRequired` impede persistência; `MessageProcessor` traduz em `clarify`.
4. **SP-62 — strength sem intensidade**: `intensity_for_calc='moderate'` (met=5.0), mas `record.intensity='unknown'` para auditoria.
5. **SP-63 — distância sem duração**: `estimate_duration_from_distance(type, km)` = `(km / speed) × 60`. Se tipo não tem velocidade mapeada, estimativa falha e duration fica 0 + warning.
6. **Canonicalização de activity_type**: `_canonicalize_activity_type` faz lowercase, troca espaço/hífen por `_`, remove acentos e consulta `_ACTIVITY_TYPE_ALIASES`. Se não bater, retorna o valor original (lookup direto no `_MET_TABLE` pode ainda funcionar).
7. **Par não mapeado**: `calc_method='llm_estimate'`, `kcal_burned=0`, warning `unknown_activity_or_intensity`. Não bloqueia registro.
8. **Recompute from-scratch** (INV-4): `kcal_out = SUM(kcal_burned)` sempre completo.
9. **Sem `needs_confirmation`** para activity no MVP — só `low_confidence_item` warning.

## Configurações e variáveis de ambiente

| Variável | Descrição | Padrão | Obrigatória |
|---|---|---|---|
| `ANTHROPIC_MODEL` | Modelo que classifica intent e extrai `activity` | `claude-sonnet-4-6` | Sim |
| `ANTHROPIC_FALLBACK_MODEL` | Fallback | `claude-haiku-4-5-20251001` | Não |

Sem variáveis específicas de atividade — toda config vem de `anthropic-integration`.

## Referências de implementação

- **Service**: `apps/api/app/services/activity.py` — `ActivityService.create_from_llm`, `WeightRequired`, `LOW_CONFIDENCE_THRESHOLD=0.5`.
- **Calculator**: `apps/api/app/services/activity_calculator.py` — `ActivityCalculator.compute`, `lookup_met`, `estimate_duration_from_distance`, `_MET_TABLE`, `_SPEED_KMH`, `_ACTIVITY_TYPE_ALIASES`, `_canonicalize_activity_type`.
- **Repository**: `apps/api/app/repositories/activity.py` — `ActivityRecordRepository.create`.
- **Model**: `apps/api/app/models/activity_record.py` — `ActivityRecord` (com `met_value`, `kcal_burned`, `calc_method`).
- **Schema LLM**: `apps/api/app/schemas/llm.py:126` — `ActivityIn(_LenientBase)`, `_normalize_intensity`, validators de `duration_minutes`.
- **Integração no pipeline**: `apps/api/app/services/message_processor.py:245` — `elif envelope.intent == "log_activity"`.
- **Recompute**: `apps/api/app/services/daily_recompute.py:238` — `_aggregate_activity`.
- **Formatter**: `apps/api/app/services/message_formatter.py:282` — `compose_activity`.
- **Correção**: `apps/api/app/services/correction.py:253` — `_apply_activity_changes` (recalcula kcal via `ActivityCalculator`).
- **Migration**: `apps/api/alembic/versions/0004_hydration_beverage_activity.py`.
- **Tests**: `apps/api/tests/test_hydration_beverage_activity.py` (SP-60..64); `apps/api/tests/test_activity_calculator.py` (11 unit); `apps/api/tests/test_activity_reported_kcal.py` (kcal de dispositivo); `apps/api/tests/test_activity_type_aliases.py` (aliases pt-BR/EN); `apps/api/tests/test_log_liquids_activity_flow.py` (E2E).
