# Especificações Técnicas — Registro de água pura

> **Rastreabilidade**: SP-40..SP-42 · Implementação: `apps/api/app/services/hydration.py`, `apps/api/app/repositories/hydration.py`, `apps/api/app/models/water_record.py`, `apps/api/app/schemas/llm.py` (WaterIn).

## Escopo técnico

Backend cria e persiste `water_records` a partir de um `LLMEnvelope` com `intent=log_water` e bloco `water` preenchido. Não há endpoint HTTP próprio para criar água — toda criação passa pelo `POST /chat/messages` (`chat-messaging`). Correção e deleção são feitas por endpoints genéricos em `records.py` (`record-correction`, `record-deletion`).

## Interface

### Entrada (LLMEnvelope via `tool_use`)

```python
class WaterIn(_StrictBase):           # extra="forbid"
    volume_ml: float = Field(ge=1)    # ml, mínimo 1
    confidence: float                 # 0..1, Decimal(3,2) no banco
```

`LLMEnvelope.intent == "log_water"` + `LLMEnvelope.water` preenchido. Campos extra fora de `WaterIn` são recusados (`_StrictBase`).

### Saída (snapshot do dia)

`daily_snapshots.water_ml: int` — soma de `volume_ml` de todos `water_records` do `day_log` com `deleted_at IS NULL`. Exposto em:
- `GET /days/today`, `GET /days/{date}` (`days.py`) → campo `water_ml` + lista `water` (registros individuais).
- `GET /weekly` → soma de `water_ml` entre dias fechados.

### Erros de domínio

| Code | Quando | HTTP | Tradução no `MessageProcessor` |
|---|---|---|---|
| `water_intent_rejected` | `user_text_summary` contém hint de bebida calórica | 422 (interno) | `clarify` — assistente pede confirmação se era água ou bebida |
| `invalid_water_envelope` | `envelope.water is None` em `intent=log_water` | 422 | `validation_exhausted` — "Não consegui interpretar" |

## Modelo de dados

### `water_records`

| Coluna | Tipo | Constraints | Notas |
|---|---|---|---|
| `id` | UUID PK | `uuid_generate_v4()` | herda de `UUIDPrimaryKeyMixin` |
| `user_id` | UUID FK → `users.id` | `NOT NULL`, `ON DELETE CASCADE` | isolamento (Const. §21) |
| `day_log_id` | UUID FK → `day_logs.id` | `NOT NULL`, `ON DELETE RESTRICT` | não deixa apagar day_log com registros |
| `message_id` | UUID FK → `messages.id` | nullable, `ON DELETE SET NULL` | rastreabilidade do chat |
| `occurred_at` | `DateTime(timezone=true)` | `NOT NULL` | quando o evento aconteceu (não quando foi gravado) |
| `volume_ml` | `Integer` | `NOT NULL`, `CHECK volume_ml > 0` | SP-40 |
| `source` | `Text` | `NOT NULL`, `CHECK source IN ('manual','llm','user_corrected')` | origem do registro |
| `confidence` | `Numeric(3,2)` | nullable | confiança da LLM (0..1) |
| `is_estimate` | `Boolean` | `NOT NULL`, default `false` | SP-42 |
| `created_at` / `updated_at` | `DateTime(timezone=true)` | `NOT NULL`, trigger `set_updated_at` | `TimestampMixin` |
| `deleted_at` | `DateTime(timezone=true)` | nullable | soft delete (SP-80..82, feature `record-deletion`) |

**Sem colunas de kcal/macros/micros** — INV-2 estrutural. A ausência física da coluna é o enforcement.

### Migration

`apps/api/alembic/versions/0004_hydration_beverage_activity.py` — cria `water_records`, `beverage_records`, `activity_records` em uma migration (Fase 5, T-501).

## Fluxo de dados

1. Usuário envia "500 ml de água" via `POST /chat/messages`.
2. `chat.router` insere `messages(role=user)` e retorna `202 {message_id, status: processing}`.
3. `MessageProcessor.process(message_id)` (BackgroundTask):
   a. `AnthropicClient.classify(history, current_message)` → `LLMEnvelope(intent="log_water", water={volume_ml: 500, confidence: 0.95}, user_text_summary="Usuário bebeu 500ml de água.")`.
   b. `IntentDispatcher.dispatch` → `_handle_log_water` → `HydrationService.create_from_llm(user, day_log_id, message_id, envelope)`.
   c. `HydrationService`:
      - normaliza `user_text_summary` (sem acentos, lowercase) e checa contra `_NON_WATER_HINTS`;
      - se match → `ValidationAppError(code="water_intent_rejected")` (SP-41);
      - senão → `WaterRecordRepository.create(...)` + `AuditEventRepository.record(action="create", entity_type="water_record", actor="llm", after={volume_ml, occurred_at})`.
   d. `DailyRecomputeService.recompute(day_log_id)` — `SELECT SUM(water_records.volume_ml) WHERE deleted_at IS NULL` + UPSERT em `daily_snapshots.water_ml`.
   e. `MessageFormatter` compõe assistant message (linha "Água Pura: X ml" no resumo do dia).
   f. `MessageProcessor` insere `messages(role=assistant)`.
4. Cliente faz polling `GET /chat/messages?after=<user_msg_id>` e recebe a resposta.

## Regras de negócio

1. **Água ≠ bebida** (Art. IV §12-14, INV-2/INV-3): `water_records` só recebe água pura. A validação semântica em `HydrationService` é **defensiva** — o schema já bloqueia kcal, mas se a LLM mandar `log_water` para "café expresso", o backend rejeita antes de persistir (SP-41).
2. **Hints de bebida** (`_NON_WATER_HINTS`): `cafe`, `cafezinho`, `leite`, `suco`, `refrigerante`, `cha`, `cerveja`, `vinho`, `acucar`, `mel`, `leite_condensado`. Match = rejeição. Normalização NFKD remove acentos antes do casamento.
3. **`occurred_at`**: usa `envelope.occurred_at_hint` se presente, senão `datetime.now(UTC)`. Permite registrar água consumida mais cedo no dia.
4. **`source="llm"`** em criação via chat. `manual` e `user_corrected` são usados pelos fluxos de correção (feature `record-correction`).
5. **Sem `needs_confirmation`**: água não tem macros para confirmar. `confidence` é gravado mas não aciona fluxo de confirmação.
6. **Recompute from-scratch** (INV-4): sempre `SUM` completo, nunca delta incremental.

## Configurações e variáveis de ambiente

| Variável | Descrição | Padrão | Obrigatória |
|---|---|---|---|
| `ANTHROPIC_MODEL` | Modelo que classifica intent e extrai `water.volume_ml` | `claude-sonnet-4-6` | Sim |
| `ANTHROPIC_FALLBACK_MODEL` | Fallback se primário falhar | `claude-haiku-4-5-20251001` | Não |

Sem variáveis específicas de hidratação — toda config vem de `anthropic-integration` e `chat-messaging`.

## Referências de implementação

- **Service**: `apps/api/app/services/hydration.py` — `HydrationService.create_from_llm`, `_strip_accents`, `_NON_WATER_HINTS`.
- **Repository**: `apps/api/app/repositories/hydration.py` — `WaterRecordRepository.create`.
- **Model**: `apps/api/app/models/water_record.py` — `WaterRecord` (schema sem kcal).
- **Schema LLM**: `apps/api/app/schemas/llm.py:67` — `WaterIn(_StrictBase)`.
- **Integração no pipeline**: `apps/api/app/services/message_processor.py:214` — `elif envelope.intent == "log_water"`.
- **Erro traduzido**: `apps/api/app/services/message_processor.py:1164` — mapa `"water_intent_rejected"`.
- **Recompute**: `apps/api/app/services/daily_recompute.py:232` — `_aggregate_water`.
- **Prompt**: `apps/api/app/integrations/anthropic/prompts/system_v2.md:21` — "Água pura → `intent=log_water`, campo `water`".
- **Migration**: `apps/api/alembic/versions/0004_hydration_beverage_activity.py`.
- **Tests**: `apps/api/tests/test_hydration_beverage_activity.py` — `test_sp40_water_records_volume`, `test_sp41_rejects_water_intent_when_summary_hints_beverage`, `test_hydration_grava_audit_event`; `apps/api/tests/test_log_liquids_activity_flow.py` (E2E com mix de registros).
