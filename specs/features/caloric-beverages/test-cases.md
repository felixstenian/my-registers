# Casos de Teste — Registro de bebidas calóricas

> **Rastreabilidade**: SP-50..SP-52, INV-3, INV-4, INV-10 · Testes reais em `apps/api/tests/test_hydration_beverage_activity.py`, `apps/api/tests/test_log_liquids_activity_flow.py`, `apps/api/tests/test_message_formatter.py`.

## Cobertura alvo

- **Unitários**: `BeverageService.create_from_llm`, `NutritionCalculator.compute(hit, ml=...)`, `BeverageRecordRepository.create`, `needs_confirmation` duplo gatilho.
- **Integração**: `IntentDispatcher._handle_log_beverage` → `BeverageService` → `DailyRecomputeService._aggregate_beverage`; audit gravado.
- **E2E**: `POST /chat/messages` → resposta do assistente com `other_liquids_ml` + `kcal_in`.
- **Invariantes**: INV-3 (bebida não vaza para water), INV-4 (recompute from-scratch), INV-10 (audit).

---

## Testes Unitários

### TC-U-001 — Bebida com hit no catálogo calcula kcal
- **Módulo**: `apps/api/app/services/beverage.py`
- **Função/Método**: `BeverageService.create_from_llm`
- **Entrada**: catálogo semeado (`leite_integral = 57 kcal/100ml`); `LLMEnvelope(intent="log_beverage", beverage={detected_name:"leite integral", volume_ml:200, confidence:0.9})`.
- **Saída esperada**: `record.kcal=Decimal("114.00")`, `record.protein_g>0`, `record.catalog_ref_id` preenchido, `record.needs_confirmation=false`.
- **Tipo**: Happy path
- **Teste real**: `test_sp50_beverage_with_catalog_hit` (linha 126)

### TC-U-002 — Bebida sem catálogo fica zerada
- **Módulo**: `apps/api/app/services/beverage.py`
- **Função/Método**: `BeverageService.create_from_llm`
- **Entrada**: `beverage={detected_name:"kombucha artesanal casa", volume_ml:300, confidence:0.85}` (sem hit).
- **Saída esperada**: `record.catalog_ref_id=None`, `record.kcal=Decimal("0")`, `record.needs_confirmation=true`, `warnings` contém `{code:"no_catalog_hit"}`.
- **Tipo**: Edge case
- **Teste real**: `test_sp52_beverage_no_catalog_zeros` (linha 155)

### TC-U-003 — Bebida não vaza para water_records (INV-3)
- **Módulo**: `apps/api/app/services/beverage.py` + `IntentDispatcher`
- **Função/Método**: `BeverageService.create_from_llm` com `intent=log_beverage`
- **Entrada**: `beverage={detected_name:"café", volume_ml:100, confidence:0.9}`.
- **Saída esperada**: `SELECT water_records` vazio; `SELECT beverage_records` tem 1 linha.
- **Tipo**: Invariante
- **Teste real**: `test_beverage_never_lands_in_water_table` (linha 183)

### TC-U-004 — Envelope sem bloco beverage
- **Módulo**: `apps/api/app/services/beverage.py`
- **Função/Método**: `BeverageService.create_from_llm`
- **Entrada**: `LLMEnvelope(intent="log_beverage", beverage=None)`
- **Saída esperada**: `ValidationAppError(code="invalid_beverage_envelope")`
- **Tipo**: Error case
- **Notas**: [Inferido do código] linha 53-57.

### TC-U-005 — Confiança baixa dispara needs_confirmation
- **Módulo**: `apps/api/app/services/beverage.py`
- **Função/Método**: `BeverageService.create_from_llm`
- **Entrada**: `beverage={detected_name:"suco", volume_ml:200, confidence:0.3}` com hit.
- **Saída esperada**: `record.needs_confirmation=true`, `warnings` contém `{code:"low_confidence_item"}`.
- **Tipo**: Edge case
- **Notas**: [Inferido do código] `LOW_CONFIDENCE_THRESHOLD=0.5`; linha 68 e 105-112.

---

## Testes de Integração

### TC-I-001 — Snapshot agrega other_liquids_ml + kcal_in
- **Fluxo**: `MessageProcessor` → `IntentDispatcher` → `BeverageService` → `DailyRecomputeService._aggregate_beverage`
- **Pré-condições**: catálogo semeado, usuário autenticado.
- **Passos**:
  1. `POST /chat/messages {text: "200ml café"}` com LLM mock devolvendo `intent=log_beverage`.
  2. Aguardar BackgroundTask.
  3. `SELECT daily_snapshots`.
- **Resultado esperado**: `other_liquids_ml >= 200`, `kcal_in` inclui kcal do café.
- **Teste real**: parte de `test_snapshot_mixes_food_beverage_activity_water` (linha 217).

### TC-I-002 — Mix de 4 registros (food + beverage + water + activity)
- **Fluxo**: 4× `POST /chat/messages`
- **Pré-condições**: catálogo semeado, `user.weight_kg=78`.
- **Passos**: arroz 100g, café 200ml, água 750ml, caminhada 30min.
- **Resultado esperado**:
  - `kcal_in=134.00` (130 + 4)
  - `kcal_out=109.20`
  - `kcal_balance=24.80`
  - `water_ml=750` (só água)
  - `other_liquids_ml` inclui 200 (só café)
- **Teste real**: `test_snapshot_mixes_food_beverage_activity_water` (linha 217).

### TC-I-003 — kcal_in combina food + beverage
- **Fluxo**: `DailyRecomputeService.recompute`
- **Pré-condições**: registros de food e beverage no mesmo `day_log`.
- **Passos**: chamar `recompute(day_log_id)`.
- **Resultado esperado**: `kcal_in = food_totals.kcal + bev_totals.kcal` (Const. Art. IV §13).
- **Notas**: [Inferido do código] `daily_recompute.py:72`.

---

## Testes E2E

### TC-E-001 — Registrar bebida por chat end-to-end
- **Persona**: Felix (logado)
- **Jornada**: enviar texto de bebida e ver resposta
- **Passos**:
  1. `POST /login`.
  2. `POST /chat/messages {text: "200ml café"}` com `fake_anthropic` devolvendo `intent=log_beverage`.
  3. Polling `GET /chat/messages?after=...`.
- **Resultado esperado**:
  - Mensagem assistant contém "Registrei 200 ml de café..." + tabela.
  - `GET /days/today` retorna `other_liquids_ml >= 200`.
- **Teste real**: `test_log_beverage_end_to_end_with_catalog` (linha 102).

### TC-E-002 — Formatter compõe resposta de bebida
- **Persona**: sistema (validação de UI string)
- **Jornada**: `MessageFormatter.compose_beverage` com `volume_ml=200`, `other_liquids_ml=50`
- **Passos**: chamar `compose_beverage(beverage, ctx, date)`.
- **Resultado esperado**: string com "Registrei 200 ml de...", tabela com Calorias/Proteínas/.../Volume, totais do dia, disclaimer.
- **Teste real**: `test_compose_beverage_table_with_volume_row` (linha 215 em `test_message_formatter.py`).

### TC-E-003 — Formatter não mostra asterisco quando só água
- **Persona**: sistema
- **Jornada**: `compose_beverage` com `water_ml=500`, `other_liquids_ml=0`
- **Passos**: chamar com beverage "água com gás" mas `other_liquids_ml=0`.
- **Resultado esperado**: linha "Líquidos Totais" **não** tem `*` (sem outros líquidos).
- **Teste real**: `test_compose_beverage_no_star_when_only_water` (linha 238 em `test_message_formatter.py`).

---

## Testes de Regressão

- **INV-3 estrutural**: `test_beverage_never_lands_in_water_table` — bebida não pode ir para `water_records`. Quebra se `IntentDispatcher` rotear errado ou se alguém unificar tabelas.
- **`kcal_in` combina food + beverage**: se alguém mudar `kcal_in` para só food, o teste de mix (linha 217) falha.
- **`needs_confirmation` duplo gatilho**: se alguém remover `or hit is None`, bebida sem catálogo não fica pendente — `test_sp52_beverage_no_catalog_zeros` falha.
- **Audit sempre**: toda criação de beverage grava audit — manter fixture.
- **Catálogo opcional**: adicionar nova bebida ao seed TBCA não deve quebrar `test_sp52` (que testa ausência de hit).
