# Casos de Teste — Registro de água pura

> **Rastreabilidade**: SP-40..SP-42, INV-2, INV-4, INV-10 · Testes reais em `apps/api/tests/test_hydration_beverage_activity.py`, `apps/api/tests/test_log_liquids_activity_flow.py`, `apps/api/tests/test_message_formatter.py`.

## Cobertura alvo

- **Unitários**: `HydrationService.create_from_llm`, `_strip_accents`, casamento `_NON_WATER_HINTS`, `WaterRecordRepository.create`.
- **Integração**: `IntentDispatcher._handle_log_water` → `HydrationService` → `DailyRecomputeService._aggregate_water`; audit gravado.
- **E2E**: `POST /chat/messages` → resposta do assistente com `water_ml` no snapshot do dia.
- **Invariantes**: INV-2 (água sem kcal por schema), INV-3 (bebida não vaza para `water_records`), INV-4 (recompute from-scratch), INV-10 (audit).

---

## Testes Unitários

### TC-U-001 — Volume persistido corretamente
- **Módulo**: `apps/api/app/services/hydration.py`
- **Função/Método**: `HydrationService.create_from_llm`
- **Entrada**: `LLMEnvelope(intent="log_water", water={volume_ml: 500, confidence: 0.95}, user_text_summary="Registro de líquido/atividade.")`
- **Saída esperada**: `HydrationResult(record.volume_ml=500, record.user_id=admin_user.id, record.source="llm")`. `record` não tem atributo `kcal` (INV-2 estrutural).
- **Tipo**: Happy path
- **Teste real**: `test_sp40_water_records_volume` (linha 64)

### TC-U-002 — Rejeição quando resumo sugere café
- **Módulo**: `apps/api/app/services/hydration.py`
- **Função/Método**: `HydrationService.create_from_llm`
- **Entrada**: `LLMEnvelope(intent="log_water", water={volume_ml: 50, confidence: 0.9}, user_text_summary="Usuário tomou um café expresso.")`
- **Saída esperada**: `ValidationAppError(code="water_intent_rejected")`. Nenhum `WaterRecord` persistido.
- **Tipo**: Edge case / Error case
- **Teste real**: `test_sp41_rejects_water_intent_when_summary_hints_beverage` (linha 79)

### TC-U-003 — Auditoria gravada na criação
- **Módulo**: `apps/api/app/services/hydration.py` + `app/repositories/food.py` (AuditEventRepository)
- **Função/Método**: `HydrationService.create_from_llm` → `AuditEventRepository.record`
- **Entrada**: envelope válido com `water={volume_ml: 250, confidence: 0.9}`
- **Saída esperada**: 1 `AuditEvent` com `entity_type="water_record"`, `action="create"`, `actor="llm"`.
- **Tipo**: Happy path
- **Teste real**: `test_hydration_grava_audit_event` (linha 105)

### TC-U-004 — Normalização NFKD remove acentos
- **Módulo**: `apps/api/app/services/hydration.py`
- **Função/Método**: `_strip_accents`
- **Entrada**: `"café"`
- **Saída esperada**: `"cafe"` (combining marks removidos)
- **Tipo**: Edge case
- **Notas**: [Inferido do código] garante que "café" case com hint "cafe".

### TC-U-005 — Envelope sem bloco water
- **Módulo**: `apps/api/app/services/hydration.py`
- **Função/Método**: `HydrationService.create_from_llm`
- **Entrada**: `LLMEnvelope(intent="log_water", water=None)`
- **Saída esperada**: `ValidationAppError(code="invalid_water_envelope")`
- **Tipo**: Error case
- **Notas**: [Inferido do código] linha 69-70.

---

## Testes de Integração

### TC-I-001 — Snapshot agrega water_ml após criar água
- **Fluxo**: `MessageProcessor` → `IntentDispatcher` → `HydrationService` → `DailyRecomputeService._aggregate_water`
- **Pré-condições**: usuário autenticado, `day_log` do dia criado.
- **Passos**:
  1. `POST /chat/messages {text: "750ml de água"}` com LLM mock devolvendo `intent=log_water, water={volume_ml: 750}`.
  2. Aguardar BackgroundTask.
  3. `SELECT daily_snapshots WHERE day_log_id=...`
- **Resultado esperado**: `snap.water_ml == 750`.
- **Teste real**: parte de `test_snapshot_mixes_food_beverage_activity_water` (linha 217) — mistura 4 registros e valida `snap.water_ml == 750`.

### TC-I-002 — Mix de 4 registros no mesmo dia
- **Fluxo**: 4× `POST /chat/messages` (food, beverage, water, activity)
- **Pré-condições**: catálogo TBCA semeado, `user.weight_kg=78`.
- **Passos**: registrar arroz 100g, café 200ml, água 750ml, caminhada 30min.
- **Resultado esperado**:
  - `kcal_in = 134` (arroz 130 + café 4)
  - `kcal_out = 109.20` (caminhada 2.8 × 78 × 0.5)
  - `kcal_balance = 24.80`
  - `water_ml = 750` (só água; café vai para `other_liquids_ml`, INV-3)
- **Teste real**: `test_snapshot_mixes_food_beverage_activity_water` (linha 217).

### TC-I-003 — Bebida calórica não vaza para water_records
- **Fluxo**: `BeverageService.create_from_llm` com `intent=log_beverage`
- **Pré-condições**: catálogo semeado.
- **Passos**: criar beverage "café" 100ml.
- **Resultado esperado**: `SELECT water_records` vazio; `SELECT beverage_records` tem 1 linha.
- **Teste real**: `test_beverage_never_lands_in_water_table` (linha 183) — valida INV-3 estrutural.

---

## Testes E2E

### TC-E-001 — Registrar água por chat end-to-end
- **Persona**: Felix (logado via `/login`)
- **Jornada**: enviar texto de água e ver resposta do assistente
- **Passos**:
  1. `POST /login` → cookies setados.
  2. `POST /chat/messages {text: "500ml de água"}` com `fake_anthropic` devolvendo `intent=log_water, water={volume_ml:500, confidence:0.95}`.
  3. Polling `GET /chat/messages?after=<user_msg_id>`.
- **Resultado esperado**:
  - Mensagem assistant contém "Registrei 500 ml de água." (ou similar SP-118).
  - `GET /days/today` retorna `water_ml >= 500`.
- **Teste real**: `test_log_water_end_to_end` (linha 40).

### TC-E-002 — Café classificado como água vira clarify
- **Persona**: Felix
- **Jornada**: enviar "café" com LLM mock classificando como `log_water`
- **Passos**:
  1. `POST /chat/messages {text: "200ml café"}` com LLM devolvendo `intent=log_water, user_text_summary="café"`.
  2. Polling.
- **Resultado esperado**:
  - Nenhum `water_records` persistido.
  - Assistente pede esclarecimento (fluxo `clarify`).
- **Teste real**: `test_log_water_rejected_when_summary_hints_coffee` (linha 69).

### TC-E-003 — Formatter compõe resposta de água
- **Persona**: sistema (validação de UI string)
- **Jornada**: `MessageFormatter.compose_water` com snapshot `water_ml=1200`
- **Passos**: chamar `compose_water(hydration, ctx, date(2026,7,20))`
- **Resultado esperado**: string contém "Registrei 1.200 ml de água."
- **Teste real**: `test_compose_water_ptbr_header_and_table` (linha 199 em `test_message_formatter.py`).

---

## Testes de Regressão

- **INV-2 estrutural**: `assert not hasattr(record, "kcal")` — se alguém adicionar coluna kcal em `water_records`, o teste falha. Manter em toda release.
- **INV-3 separação**: `test_beverage_never_lands_in_water_table` — bebida não pode ir para `water_records`. Quebra se `IntentDispatcher` rotear errado.
- **Recompute from-scratch**: após deletar água, `water_ml` deve cair — valida INV-4.
- **Audit sempre**: `test_hydration_grava_audit_event` — toda criação grava audit. Quebra se alguém remover a chamada `AuditEventRepository.record`.
- **Hints de bebida**: adicionar nova bebida calórica comum ao mercado → adicionar em `_NON_WATER_HINTS` e criar teste.
