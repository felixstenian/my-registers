# Casos de Teste — Registro de atividade física (cardio)

> **Rastreabilidade**: SP-60..SP-64, INV-4, INV-10 · Testes reais em `apps/api/tests/test_hydration_beverage_activity.py`, `apps/api/tests/test_activity_calculator.py`, `apps/api/tests/test_activity_reported_kcal.py`, `apps/api/tests/test_activity_type_aliases.py`, `apps/api/tests/test_log_liquids_activity_flow.py`, `apps/api/tests/test_message_formatter.py`.

## Cobertura alvo

- **Unitários**: `ActivityCalculator.compute`, `lookup_met`, `estimate_duration_from_distance`, `_canonicalize_activity_type`, `_normalize_intensity`, `ActivityRecordRepository.create`.
- **Integração**: `IntentDispatcher._handle_log_activity` → `ActivityService` → `DailyRecomputeService._aggregate_activity`; audit gravado; `WeightRequired` traduzido em clarify.
- **E2E**: `POST /chat/messages` → resposta do assistente com `kcal_out` no snapshot.
- **Invariantes**: INV-4 (recompute from-scratch), INV-10 (audit), INV-1 (LLM não calcula).

---

## Testes Unitários

### TC-U-001 — Cálculo MET com peso e duração
- **Módulo**: `apps/api/app/services/activity.py`
- **Função/Método**: `ActivityService.create_from_llm`
- **Entrada**: `user.weight_kg=78`; `LLMEnvelope(intent="log_activity", activity={activity_type:"cardio_run", duration_minutes:40, intensity:"moderate", confidence:0.9})`.
- **Saída esperada**: `record.met_value=8.3`, `record.kcal_burned=431.60`, `record.calc_method='mets_body_weight'`.
- **Tipo**: Happy path
- **Teste real**: `test_sp60_activity_computes_kcal_burned` (linha 222)

### TC-U-002 — Peso faltante levanta WeightRequired
- **Módulo**: `apps/api/app/services/activity.py`
- **Função/Método**: `ActivityService.create_from_llm`
- **Entrada**: `user.weight_kg=None`; `activity={activity_type:"cardio_run", duration_minutes:30, intensity:"moderate"}` (sem `kcal_burned_reported`).
- **Saída esperada**: `WeightRequired` levantada; nenhum `activity_records` persistido.
- **Tipo**: Error case
- **Teste real**: `test_sp61_missing_weight_raises_weight_required` (linha 251)

### TC-U-003 — Strength unknown usa moderate
- **Módulo**: `apps/api/app/services/activity.py` + `activity_calculator.py`
- **Função/Método**: `ActivityService.create_from_llm` → `ActivityCalculator.compute`
- **Entrada**: `user.weight_kg=80`; `activity={activity_type:"strength", duration_minutes:60, intensity:"unknown", confidence:0.6}`.
- **Saída esperada**: `record.met_value=5.0`, `record.kcal_burned=400.00`, `record.intensity='unknown'` (preservado).
- **Tipo**: Edge case (SP-62)
- **Teste real**: `test_sp62_strength_unknown_intensity_uses_moderate_met` (linha 276)

### TC-U-004 — Audit grava met_value e calc_method
- **Módulo**: `apps/api/app/services/activity.py`
- **Função/Método**: `ActivityService.create_from_llm` → `AuditEventRepository.record`
- **Entrada**: `user.weight_kg=75`; `activity={activity_type:"cardio_walk", duration_minutes:30, intensity:"light"}`.
- **Saída esperada**: 1 `AuditEvent` com `entity_type='activity_record'`, `actor='llm'`, `after` contendo `calc_method`, `kcal_burned`.
- **Tipo**: Happy path (SP-64)
- **Teste real**: `test_sp64_audit_and_calc_method_stored` (linha 307)

### TC-U-005 — kcal reportado sobrescreve MET
- **Módulo**: `apps/api/app/services/activity.py`
- **Função/Método**: `ActivityService.create_from_llm`
- **Entrada**: `user.weight_kg=None` (sem peso); `activity={activity_type:"cardio_run", duration_minutes:30, kcal_burned_reported:500, confidence:0.9}`.
- **Saída esperada**: `record.kcal_burned=500`, `record.calc_method='user_manual'`. `WeightRequired` **não** levanta.
- **Tipo**: Happy path (kcal de dispositivo)
- **Teste real**: `test_reported_kcal_bypasses_weight_required` em `test_activity_reported_kcal.py`

### TC-U-006 — Canonicaliza activity_type pt-BR
- **Módulo**: `apps/api/app/services/activity_calculator.py`
- **Função/Método**: `_canonicalize_activity_type`
- **Entrada**: `"corrida"`, `"musculação"`, `"bicicleta"`
- **Saída esperada**: `"cardio_run"`, `"strength"`, `"bike"`
- **Tipo**: Edge case
- **Teste real**: `test_canonicalize` em `test_activity_type_aliases.py`

### TC-U-007 — Intensidade pt-BR passa no Pydantic
- **Módulo**: `apps/api/app/schemas/llm.py`
- **Função/Método**: `ActivityIn._accept_ptbr_intensity`
- **Entrada**: `"moderada"`, `"leve"`, `"intenso"`
- **Saída esperada**: `"moderate"`, `"light"`, `"vigorous"`
- **Tipo**: Edge case
- **Teste real**: `test_intensity_ptbr_aliases_pass_pydantic` em `test_activity_type_aliases.py`

### TC-U-008 — Estimativa de duração por distância (SP-63)
- **Módulo**: `apps/api/app/services/activity_calculator.py`
- **Função/Método**: `ActivityCalculator.estimate_duration_from_distance`
- **Entrada**: `activity_type="cardio_walk"`, `distance_km=4`
- **Saída esperada**: `(4 / 5.0) × 60 = 48` minutos
- **Tipo**: Happy path
- **Notas**: [Inferido do código] `_SPEED_KMH[cardio_walk]=5.0`.

### TC-U-009 — Par não mapeado retorna llm_estimate
- **Módulo**: `apps/api/app/services/activity_calculator.py`
- **Função/Método**: `ActivityCalculator.compute`
- **Entrada**: `activity_type="surf"`, `intensity="moderate"` (não está em `_MET_TABLE`).
- **Saída esperada**: `kcal_burned=0`, `calc_method='llm_estimate'`, `reasons=['unknown_activity_or_intensity']`.
- **Tipo**: Edge case
- **Notas**: [Inferido do código] `activity_calculator.py:174-180`.

### TC-U-010 — ActivityIn ignora campos extras
- **Módulo**: `apps/api/app/schemas/llm.py`
- **Função/Método**: `ActivityIn` (validação)
- **Entrada**: payload com `pace`, `heart_rate`, `kcal` (campos não consumidos).
- **Saída esperada**: validação passa; extras ignorados (`_LenientBase`).
- **Tipo**: Edge case
- **Teste real**: `test_activity_in_ignores_extra_fields_from_llm` em `test_activity_type_aliases.py`

---

## Testes de Integração

### TC-I-001 — Snapshot agrega kcal_out
- **Fluxo**: `MessageProcessor` → `IntentDispatcher` → `ActivityService` → `DailyRecomputeService._aggregate_activity`
- **Pré-condições**: usuário autenticado, `weight_kg=78`.
- **Passos**:
  1. `POST /chat/messages {text: "caminhei 30 min leves"}` com LLM mock.
  2. Aguardar BackgroundTask.
  3. `SELECT daily_snapshots`.
- **Resultado esperado**: `kcal_out=109.20` (2.8×78×0.5).
- **Teste real**: parte de `test_snapshot_mixes_food_beverage_activity_water` (linha 217).

### TC-I-002 — WeightRequired traduzido em clarify
- **Fluxo**: `MessageProcessor` → `ActivityService` (WeightRequired) → clarify
- **Pré-condições**: `user.weight_kg=None`.
- **Passos**: `POST /chat/messages {text: "corri 30 min"}`.
- **Resultado esperado**: nenhum `activity_records`; assistente pede peso.
- **Teste real**: `test_log_activity_without_weight_triggers_clarify` (linha 178 em `test_log_liquids_activity_flow.py`).

### TC-I-003 — kcal_balance = kcal_in - kcal_out
- **Fluxo**: `DailyRecomputeService.recompute`
- **Pré-condições**: food + activity no mesmo `day_log`.
- **Resultado esperado**: `kcal_balance = kcal_in - kcal_out`.
- **Notas**: [Inferido do código] `daily_recompute.py:87`.

---

## Testes E2E

### TC-E-001 — Registrar atividade por chat end-to-end
- **Persona**: Felix (logado, peso 78kg)
- **Jornada**: enviar texto de atividade e ver resposta
- **Passos**:
  1. `POST /login`.
  2. `POST /chat/messages {text: "caminhei 30 min leves"}` com `fake_anthropic` devolvendo `intent=log_activity`.
  3. Polling.
- **Resultado esperado**:
  - Mensagem assistant contém "Registrei 30 min de caminhada (leve)..." + tabela com kcal gasto.
  - `GET /days/today` retorna `kcal_out >= 109`.
- **Teste real**: `test_log_activity_end_to_end` (linha 139 em `test_log_liquids_activity_flow.py`).

### TC-E-002 — Smartwatch screenshot end-to-end
- **Persona**: Felix com smartwatch
- **Jornada**: enviar foto do print com kcal reportado
- **Passos**:
  1. `POST /chat/messages` com mídia (print do app) + texto.
  2. LLM mock extrai `kcal_burned_reported`.
- **Resultado esperado**: `activity_records.kcal_burned = valor reportado`, `calc_method='user_manual'`.
- **Teste real**: `test_end_to_end_smartwatch_screenshot` em `test_activity_reported_kcal.py`.

### TC-E-003 — Formatter compõe resposta de atividade
- **Persona**: sistema (validação de UI string)
- **Jornada**: `MessageFormatter.compose_activity`
- **Passos**: chamar com `duration_minutes=40`, `kcal_burned=431`, `intensity='moderate'`.
- **Resultado esperado**: string com "Registrei 40 min de...", tabela com Duração/Intensidade/Calorias gastas, totais do dia, disclaimer.
- **Teste real**: `test_compose_activity_table_with_duration_and_kcal` em `test_message_formatter.py`.

### TC-E-004 — Formatter mostra hint de dispositivo para user_manual
- **Persona**: sistema
- **Jornada**: `compose_activity` com `calc_method='user_manual'`
- **Resultado esperado**: string contém "(informado pelo dispositivo)".
- **Teste real**: `test_compose_activity_user_manual_shows_device_hint` em `test_message_formatter.py`.

---

## Testes de Regressão

- **INV-1 (LLM não calcula)**: `test_sp60` valida que `kcal_burned` vem do `ActivityCalculator`, não do envelope. Se alguém ler `kcal` do envelope, falha.
- **INV-4 (recompute from-scratch)**: após deletar atividade, `kcal_out` deve cair — valida recompute.
- **INV-10 (audit)**: `test_sp64_audit_and_calc_method_stored` — toda criação grava audit com `calc_method`.
- **SP-61 (peso obrigatório)**: `test_sp61` — se alguém remover o check de `weight_kg`, falha.
- **SP-62 (strength moderate)**: `test_sp62` — se alguém mudar default de `unknown` para outro valor, falha.
- **Aliases pt-BR**: se alguém remover "corrida" de `_ACTIVITY_TYPE_ALIASES`, `test_canonicalize` falha.
- **`kcal_burned_reported` autoritativo**: `test_reported_kcal_wins_over_met_calculation` — se alguém recalcular MET quando há reported, falha.
