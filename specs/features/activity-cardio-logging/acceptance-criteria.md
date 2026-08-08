# Critérios de Aceitação — Registro de atividade física (cardio)

> **Rastreabilidade**: SP-60..SP-64, INV-4, INV-10 · Tests em `apps/api/tests/test_hydration_beverage_activity.py`, `apps/api/tests/test_activity_calculator.py`, `apps/api/tests/test_activity_reported_kcal.py`, `apps/api/tests/test_activity_type_aliases.py`, `apps/api/tests/test_log_liquids_activity_flow.py`.

## AC-001 — Cálculo MET com peso e duração
**Dado que** Felix (peso 78kg) envia "corri 40 min moderado",
**Quando** a LLM retorna `intent=log_activity, activity={activity_type:"cardio_run", duration_minutes:40, intensity:"moderate", confidence:0.9}`,
**Então** `activity_records` com `met_value=8.3`, `kcal_burned=431.60` (8.3×78×40/60), `calc_method='mets_body_weight'`,
**E** `kcal_out` do snapshot inclui 431.60,
**E** `kcal_balance = kcal_in - 431.60`.

**Notas de validação:**
- Teste: `test_sp60_activity_computes_kcal_burned` (linha 222).

---

## AC-002 — Peso faltante levanta WeightRequired
**Dado que** `users.weight_kg is None` e sem `kcal_burned_reported`,
**Quando** `ActivityService.create_from_llm` executa,
**Então** `WeightRequired` é levantada,
**E** nenhum `activity_records` persistido,
**E** assistente pede peso (clarify).

**Notas de validação:**
- Teste: `test_sp61_missing_weight_raises_weight_required` (linha 251).

---

## AC-003 — Strength sem intensidade usa moderate
**Dado que** Felix (peso 80kg) envia "musculação 60 min" sem intensidade,
**Quando** a LLM retorna `activity_type="strength", intensity="unknown"`,
**Então** `met_value=5.0` (moderate), `kcal_burned=400.00` (5×80×1),
**E** `record.intensity='unknown'` (preservado para auditoria).

**Notas de validação:**
- Teste: `test_sp62_strength_unknown_intensity_uses_moderate_met` (linha 276).

---

## AC-004 — Audit registra met_value e calc_method
**Dado que** uma atividade é criada,
**Quando** a transação commita,
**Então** 1 `audit_events` com `entity_type='activity_record'`, `action='create'`, `actor='llm'`,
**E** `after={activity_type, duration_minutes, kcal_burned, calc_method, occurred_at}`.

**Notas de validação:**
- Teste: `test_sp64_audit_and_calc_method_stored` (linha 307).

---

## AC-005 — kcal reportado sobrescreve cálculo MET
**Dado que** Felix envia print de smartwatch com `kcal_burned_reported=500`,
**Quando** `ActivityService.create_from_llm` executa,
**Então** `kcal_burned=500`, `calc_method='user_manual'`,
**E** peso não é necessário (WeightRequired não levanta).

**Notas de validação:**
- Teste: `test_reported_kcal_wins_over_met_calculation` e `test_reported_kcal_bypasses_weight_required` em `test_activity_reported_kcal.py`.

---

## AC-006 — Mix de 4 registros com kcal_out
**Dado que** Felix registra arroz 100g, café 200ml, água 750ml e caminhada 30min (peso 78kg),
**Quando** o snapshot recompute executa,
**Então**:
- `kcal_in=134.00`, `kcal_out=109.20` (2.8×78×0.5),
- `kcal_balance=24.80`, `water_ml=750`.

**Notas de validação:**
- Teste: `test_snapshot_mixes_food_beverage_activity_water` (linha 217).

---

## AC-007 — Aliases pt-BR canonicalizam
**Dado que** a LLM retorna `activity_type="corrida"`,
**Quando** `_canonicalize_activity_type` executa,
**Então** retorna `"cardio_run"` e o lookup MET funciona.

**Notas de validação:**
- Teste: `test_canonicalize` e `test_lookup_met_accepts_pt_br_alias` em `test_activity_type_aliases.py`.

---

## AC-008 — Intensidade pt-BR passa no Pydantic
**Dado que** a LLM retorna `intensity="moderada"`,
**Quando** `ActivityIn` valida,
**Então** `_normalize_intensity` converte para `"moderate"` antes do Literal.

**Notas de validação:**
- Teste: `test_intensity_ptbr_aliases_pass_pydantic` em `test_activity_type_aliases.py`.

---

## Cenários de Borda

| Cenário | Comportamento Esperado |
|---|---|
| `duration_minutes = 0` + `distance_km` presente | SP-63: estimar duração por velocidade média. |
| `duration_minutes = 0` + sem `distance_km` | `kcal_burned=0`, warning `missing_duration`. |
| Par (type, intensity) não mapeado | `calc_method='llm_estimate'`, `kcal_burned=0`, warning `unknown_activity_or_intensity`. |
| `kcal_burned_reported = 0` | Tratado como reportado (`calc_method='user_manual'`, kcal=0). |
| `kcal_burned_reported > 10000` | `ActivityIn` Pydantic rejeita (`Field(le=10000)`). |
| `weight_kg = 0` | `ActivityCalculator.compute` retorna `kcal=0` + warning `missing_weight_kg` (não deve ocorrer — `WeightRequired` levanta antes se `None`). |
| Atividade soft-deletada | Não entra em `SUM(kcal_out)` (filtro `deleted_at IS NULL`). |
| Dia já fechado | Criação bloqueada antes por `IntentDispatcher` (INV-5). |

## Critérios de Não-Funcionalidade

| Critério | Threshold | Notas |
|---|---|---|
| Latência de `ActivityService.create_from_llm` | < 50ms | Sem chamada LLM aqui; só cálculo + persistência. |
| Latência de `ActivityCalculator.compute` | < 1ms | Pure function, tabela em memória. |
| Cobertura em `activity_calculator.py` | ≥ 90% | plan.md §5.3. |
| Determinismo | 100% | Mesmos inputs → mesmo `kcal_burned`. |
