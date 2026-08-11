# Critérios de Aceitação — Registro de bebidas calóricas

> **Rastreabilidade**: SP-50..SP-52, INV-3, INV-4, INV-10 · Tests em `apps/api/tests/test_hydration_beverage_activity.py`, `apps/api/tests/test_log_liquids_activity_flow.py`, `apps/api/tests/test_message_formatter.py`.

## AC-001 — Bebida com hit no catálogo
**Dado que** Felix envia "200ml de leite integral" e o catálogo TBCA tem `leite_integral = 57 kcal/100ml`,
**Quando** a LLM retorna `intent=log_beverage, beverage={detected_name:"leite integral", volume_ml:200, confidence:0.9}`,
**Então** `beverage_records` é criado com `kcal=114.00` (57×2), `protein_g>0`, `catalog_ref_id` preenchido, `needs_confirmation=false`,
**E** `daily_snapshots.kcal_in` inclui 114, `other_liquids_ml` inclui 200.

**Notas de validação:**
- Teste: `test_sp50_beverage_with_catalog_hit` (linha 126). `assert result.record.kcal == Decimal("114.00")`.

---

## AC-002 — Bebida sem catálogo fica zerada e pendente
**Dado que** Felix envia "300ml de kombucha artesanal casa" sem hit no catálogo,
**Quando** `BeverageService.create_from_llm` executa,
**Então** `catalog_ref_id=null`, `kcal=Decimal("0")`, `needs_confirmation=true`,
**E** `warnings` contém `{code:"no_catalog_hit"}`.

**Notas de validação:**
- Teste: `test_sp52_beverage_no_catalog_zeros` (linha 155).

---

## AC-003 — Bebida nunca vaza para water_records (INV-3)
**Dado que** Felix envia "100ml de café" como `intent=log_beverage`,
**Quando** a transação commita,
**Então** `SELECT water_records` está vazio,
**E** `SELECT beverage_records` tem 1 linha.

**Notas de validação:**
- Teste: `test_beverage_never_lands_in_water_table` (linha 183). Valida INV-3 estrutural.

---

## AC-004 — Auditoria de criação
**Dado que** um `beverage_records` é criado com sucesso,
**Quando** a transação commita,
**Então** 1 `audit_events` com `entity_type="beverage_record"`, `action="create"`, `actor="llm"`,
**E** `after={volume_ml, detected_name, occurred_at}`.

**Notas de validação:**
- [Inferido do código] `BeverageService.create_from_llm` linha 114-126 — mesmo padrão de `HydrationService`.

---

## AC-005 — Mix de 4 registros no mesmo dia
**Dado que** Felix registra arroz 100g, café 200ml, água 750ml e caminhada 30min no mesmo dia,
**Quando** o snapshot recompute executa,
**Então**:
- `kcal_in = 134.00` (arroz 130 + café 4)
- `kcal_out = 109.20` (caminhada)
- `kcal_balance = 24.80`
- `water_ml = 750` (só água)
- `other_liquids_ml` inclui 200 (só café)

**Notas de validação:**
- Teste: `test_snapshot_mixes_food_beverage_activity_water` (linha 217).

---

## AC-006 — Formatter compõe resposta de bebida
**Dado que** uma bebida é criada com `volume_ml=200`, `detected_name="café"`, `kcal=4`,
**Quando** `compose_beverage` é chamado,
**Então** a string contém "Registrei 200 ml de café.", tabela com Calorias/Proteínas/Carboidratos/Gorduras/Fibras/Volume, totais do dia e disclaimer legal.

**Notas de validação:**
- Teste: `test_compose_beverage_table_with_volume_row` (linha 215 em `test_message_formatter.py`).

---

## AC-007 — Confiança baixa marca needs_confirmation
**Dado que** a LLM retorna `confidence=0.3` para uma bebida com hit no catálogo,
**Quando** `BeverageService.create_from_llm` executa,
**Então** `needs_confirmation=true` e `warnings` contém `{code:"low_confidence_item"}`.

**Notas de validação:**
- [Inferido do código] linha 68: `needs_confirmation = confidence < LOW_CONFIDENCE_THRESHOLD or hit is None`; linha 105-112 adiciona warning.

---

## Cenários de Borda

| Cenário | Comportamento Esperado |
|---|---|
| `volume_ml = 0` | `BeverageIn` Pydantic rejeita (`Field(ge=1)`); `CheckConstraint volume_ml > 0` no Postgres. |
| `intent=log_beverage` mas `envelope.beverage is None` | `ValidationAppError(code="invalid_beverage_envelope")`. |
| Bebida com `detected_name="água"` classificada como `log_beverage` | Persiste com `kcal=0` (sem hit), `other_liquids_ml` soma — tecnicamente incorreto mas sem gate defensivo (ver `<!-- TODO -->` em specifications.md). |
| Catálogo com `per_100g` para bebida | `NutritionCalculator` cai em `unknown_basis`; kcal pode ser 0 ou estimativa grosseira. |
| Múltiplas bebidas no mesmo `day_log` | Todas somam em `other_liquids_ml` + `kcal_in`; recompute agrega vivos. |
| Bebida soft-deletada | Não entra em `SUM` (filtro `deleted_at IS NULL`). |
| Dia já fechado | Criação bloqueada antes por `IntentDispatcher` (INV-5). |

## Critérios de Não-Funcionalidade

| Critério | Threshold | Notas |
|---|---|---|
| Latência de `BeverageService.create_from_llm` | < 100ms | Inclui lookup no catálogo (em memória) + cálculo. |
| Latência de recompute de `other_liquids_ml` | < 100ms | `SELECT SUM` em tabela pequena. |
| Cobertura de testes em `app/services/beverage.py` | ≥ 80% | Meta MVP. |
| Determinismo | 100% | Mesmo envelope + catálogo → mesmos macros. |
