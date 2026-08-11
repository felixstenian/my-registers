# Histórias de Usuário — Registro de água pura

> **Rastreabilidade**: SP-40..SP-42 · Persona principal: Felix (usuário único do MVP).

## Personas

- **Felix (usuário)**: dono do registro diário. Registra alimentação, hidratação e atividade por chat de texto. Quer resposta rápida e confiável, sem se preocupar com cálculos.
- **Sistema (assistentes)**: LLM que interpreta a mensagem e o backend que valida/persiste. A LLM não é uma persona, mas é o "intermediário" que Felix enxerga.

---

### US-001 — Registrar copo de água
**Como** Felix,
**Quero** enviar "500 ml de água" no chat e ver o volume somado ao total do dia,
**Para que** eu acompanhe minha hidratação sem precisar anotar manualmente.

**Critérios de Aceitação resumidos:**
- [ ] Mensagem "500 ml de água" → `water_records.volume_ml=500`.
- [ ] Snapshot do dia atualiza `water_ml` incluindo o novo volume.
- [ ] Resposta do assistente mostra "Água Pura: 500 ml".
- [ ] Nenhum valor de kcal aparece (água não tem calorias — INV-2).

**Notas:**
- Fonte: SP-40. O volume vem direto do `WaterIn.volume_ml` extraído pela LLM.

---

### US-002 — Impedir registro de café como água
**Como** Felix,
**Quero** que o sistema recuse "café" como água mesmo se a LLM classificar errado,
**Para que** minha hidratação não seja inflada por bebidas calóricas.

**Critérios de Aceitação resumidos:**
- [ ] Mensagem "um café expresso" com `intent=log_water` e `user_text_summary` contendo "café" → `ValidationAppError(code="water_intent_rejected")`.
- [ ] Nenhum `water_records` é persistido.
- [ ] Assistente pede esclarecimento (fluxo `clarify`).

**Notas:**
- Fonte: SP-41 / Art. IV §14. `_NON_WATER_HINTS` cobre café, leite, suco, refrigerante, chá, cerveja, vinho, açúcar, mel, leite_condensado. A rejeição é defensiva — o schema já bloqueia kcal, mas isso impede que o volume vaze para `water_ml`.

---

### US-003 — Estimar volume por unidade doméstica
**Como** Felix,
**Quero** dizer "um copo de água" e o sistema estimar 250 ml,
**Para que** eu não precise medir toda vez.

**Critérios de Aceitação resumidos:**
- [ ] "Um copo" → `volume_ml≈250`, `is_estimate=true`.
- [ ] "Uma garrafinha" → `volume_ml≈500`, `is_estimate=true`.
- [ ] Volume explícito ("500 ml") → `is_estimate=false`.

**Notas:**
- Fonte: SP-42. A estimativa é feita pela LLM no envelope; o backend só persiste o flag. `is_estimate` não bloqueia o registro.

---

### US-004 — Registrar água consumida mais cedo
**Como** Felix,
**Quero** registrar água que bebi de manhã quando lembro à tarde,
**Para que** o registro fique no horário certo do dia.

**Critérios de Aceitação resumidos:**
- [ ] Se `envelope.occurred_at_hint` presente, `water_records.occurred_at` usa esse valor.
- [ ] Se ausente, usa `datetime.now(UTC)`.
- [ ] Snapshot agrega independente do `occurred_at` (soma por `day_log_id`).

**Notas:**
- [Inferido do código] `HydrationService.create_from_llm` linha 82: `occurred = occurred_at or envelope.occurred_at_hint or datetime.now(UTC)`.

---

### US-005 — Ver total de água do dia
**Como** Felix,
**Quero** ver o total de `water_ml` no snapshot do dia,
**Para que** eu saiba quanto já bebi hoje.

**Critérios de Aceitação resumidos:**
- [ ] `GET /days/today` retorna `water_ml` como soma de todos `water_records` vivos.
- [ ] Registros deletados (`deleted_at IS NOT NULL`) não entram na soma.
- [ ] Recomputo é from-scratch a cada mutação (INV-4).

**Notas:**
- Fonte: INV-4, T-506. `DailyRecomputeService._aggregate_water` faz `SELECT SUM(volume_ml)`.
