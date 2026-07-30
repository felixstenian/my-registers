# Critérios de Aceitação — Registro de água pura

> **Rastreabilidade**: SP-40..SP-42, INV-2, INV-4, INV-10 · Tests em `apps/api/tests/test_hydration_beverage_activity.py` e `apps/api/tests/test_log_liquids_activity_flow.py`.

## AC-001 — Volume persistido corretamente
**Dado que** Felix envia "500 ml de água" no chat,
**Quando** a LLM retorna `intent=log_water, water={volume_ml: 500, confidence: 0.95}`,
**Então** um `water_records` é criado com `volume_ml=500`, `user_id=<felix>`, `source='llm'`,
**E** o snapshot do dia atualiza `water_ml` somando o novo volume,
**E** um `audit_events(action='create', entity_type='water_record', actor='llm')` é gravado.

**Notas de validação:**
- Teste: `test_sp40_water_records_volume` (linha 64).
- `assert not hasattr(result.record, "kcal")` — INV-2 estrutural (sem coluna).

---

## AC-002 — Rejeição de bebida calórica classificada como água
**Dado que** Felix envia "um café expresso" e a LLM devolve `intent=log_water, user_text_summary="Usuário tomou um café expresso."`,
**Quando** `HydrationService.create_from_llm` executa,
**Então** `ValidationAppError(code="water_intent_rejected")` é levantada,
**E** nenhum `water_records` é persistido (tabela permanece vazia),
**E** o `MessageProcessor` traduz o erro em fluxo `clarify`.

**Notas de validação:**
- Teste: `test_sp41_rejects_water_intent_when_summary_hints_beverage` (linha 79).
- `_NON_WATER_HINTS` contém `cafe` (sem acento após NFKD).

---

## AC-003 — Auditoria de criação
**Dado que** um `water_records` é criado com sucesso,
**Quando** a transação commita,
**Então** existe exatamente 1 `audit_events` com `entity_type='water_record'`, `action='create'`, `actor='llm'`,
**E** `after={volume_ml, occurred_at}`.

**Notas de validação:**
- Teste: `test_hydration_grava_audit_event` (linha 105).

---

## AC-004 — Estimativa de volume marcada
**Dado que** Felix envia "um copo de água",
**Quando** a LLM retorna `water={volume_ml: 250, confidence: 0.7}` com estimativa,
**Então** `water_records.is_estimate=true` e `volume_ml=250`.

**Notas de validação:**
- [Inferido do código] `is_estimate=False` é hardcoded em `HydrationService.create_from_llm` linha 91; a estimativa real de "um copo → 250ml" é feita pela LLM. O flag `is_estimate` seria `true` se a LLM indicar. <!-- TODO: verificar se LLM hoje envia is_estimate=true para copo/garrafinha — confirmar no prompt system_v2.md -->

---

## AC-005 — Snapshot agrega apenas registros vivos
**Dado que** Felix tem 3 `water_records` (250ml, 500ml, 200ml) no mesmo `day_log`,
**Quando** o registro de 500ml é soft-deletado,
**Então** `daily_snapshots.water_ml` recompute resulta em 450 (250 + 200),
**E** o recompute é from-scratch (INV-4), não delta.

**Notas de validação:**
- Fluxo de deleção em `record-deletion`; recompute chamado por `MessageProcessor`.

---

## AC-006 — Isolamento por usuário
**Dado que** dois usuários existem (Felix e outro),
**Quando** Felix registra água,
**Então** `water_records.user_id = <felix_id>` e nenhuma query de leitura do outro usuário vê esse registro.

**Notas de validação:**
- `WaterRecordRepository.create` recebe `user_id` explícito (Const. §21). MVP é single-user, mas o isolamento é enforced em application-layer.

---

## Cenários de Borda

| Cenário | Comportamento Esperado |
|---|---|
| `volume_ml = 0` | `WaterIn` Pydantic rejeita (`Field(ge=1)`); se passar, `CheckConstraint volume_ml > 0` no Postgres levanta `IntegrityError`. |
| `volume_ml` negativo | Mesmo que acima — rejeitado em Pydantic e no DB. |
| `intent=log_water` mas `envelope.water is None` | `ValidationAppError(code="invalid_water_envelope")`. |
| `user_text_summary` vazio | Não casa com nenhum hint → registro é criado (sem rejeição). |
| Hint com acento ("café") | NFKD normaliza para "cafe" → casa → rejeição. |
| Múltiplos registros no mesmo `day_log` | Todos somam em `water_ml`; recompute agrega todos vivos. |
| `message_id=None` | Permitido (registr__; auditoria grava `message_id=null`). |
| Dia já fechado (`status='closed'`) | Criação bloqueada por `IntentDispatcher` antes de chegar em `HydrationService` (INV-5, feature `day-close`). |

## Critérios de Não-Funcionalidade

| Critério | Threshold | Notas |
|---|---|---|
| Latência de `HydrationService.create_from_llm` | < 50ms | Sem chamada LLM aqui (já feita); só persistência + audit. |
| Latência de recompute de `water_ml` | < 100ms | `SELECT SUM` em tabela pequena (single-user). |
| Cobertura de testes em `app/services/hydration.py` | ≥ 80% | Meta MVP (plan.md §5.3). |
| Determinismo | 100% | Mesmo envelope → mesmo `water_records` (sem cálculo, só INSERT). |
