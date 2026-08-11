# Histórias de Usuário — Registro de atividade física (cardio)

> **Rastreabilidade**: SP-60..SP-64 · Persona principal: Felix.

## Personas

- **Felix (usuário)**: pratica corrida, caminhada, musculação etc. Quer registrar treinos por chat e ver kcal gasto no saldo do dia.
- **Felix com smartwatch**: às vezes tira print do app do smartwatch e envia; quer que o kcal do dispositivo seja respeitado.
- **Sistema (assistentes)**: LLM que interpreta a mensagem e backend que calcula kcal por MET.

---

### US-001 — Registrar corrida com duração
**Como** Felix,
**Quero** enviar "corri 40 min moderado" e ver o kcal gasto calculado,
**Para que** meu saldo calórico reflita o treino.

**Critérios de Aceitação resumidos:**
- [ ] `activity_records` com `activity_type='cardio_run'`, `duration_minutes=40`, `intensity='moderate'`.
- [ ] `kcal_burned = 8.3 × weight_kg × (40/60)`.
- [ ] `met_value=8.3`, `calc_method='mets_body_weight'`.
- [ ] `kcal_out` do snapshot inclui o kcal gasto.

**Notas:**
- Fonte: SP-60, SP-64. Peso vem de `users.weight_kg`.

---

### US-002 — Ser avisado quando peso está faltando
**Como** Felix,
**Quero** que o assistente peça meu peso antes de registrar treino,
**Para que** o cálculo de kcal não seja feito com valor errado.

**Critérios de Aceitação resumidos:**
- [ ] Se `users.weight_kg is None` e sem `kcal_burned_reported` → `WeightRequired`.
- [ ] Nenhum `activity_records` persistido.
- [ ] Assistente pede peso (fluxo `clarify`).

**Notas:**
- Fonte: SP-61.

---

### US-003 — Registrar musculação sem intensidade
**Como** Felix,
**Quero** dizer "fiz musculação 60 min" sem especificar intensidade,
**Para que** o sistema use um padrão razoável.

**Critérios de Aceitação resumidos:**
- [ ] `activity_type='strength'`, `intensity='unknown'` no registro.
- [ ] Cálculo usa `intensity='moderate'` (met=5.0).
- [ ] `kcal_burned = 5.0 × weight_kg × 1`.

**Notas:**
- Fonte: SP-62.

---

### US-004 — Estimar duração por distância
**Como** Felix,
**Quero** dizer "caminhei 4 km" e o sistema estimar duração,
**Para que** eu não precise cronometrar.

**Critérios de Aceitação resumidos:**
- [ ] `distance_km=4`, sem `duration_minutes` → estimativa por `_SPEED_KMH[cardio_walk]=5.0`.
- [ ] `duration_minutes = (4 / 5.0) × 60 = 48`.

**Notas:**
- Fonte: SP-63. Se tipo não tem velocidade mapeada, estimativa falha.

---

### US-005 — Respeitar kcal do smartwatch
**Como** Felix com smartwatch,
**Quero** enviar print do app com kcal já calculado,
**Para que** o valor do dispositivo seja usado em vez da estimativa MET.

**Critérios de Aceitação resumidos:**
- [ ] LLM extrai `kcal_burned_reported` da foto.
- [ ] `kcal_burned` = valor reportado, `calc_method='user_manual'`.
- [ ] Peso não é necessário (dispositivo já resolveu).
- [ ] `met_value` ainda gravado para contexto.

**Notas:**
- [Inferido do código] `activity.py:89-95`. Const. Art. III §10 — recompute mantém valor materializado.

---

### US-006 — Usar termos em português
**Como** Felix,
**Quero** dizer "corrida", "musculação", "bicicleta" e o sistema entender,
**Para que** eu não precise traduzir.

**Critérios de Aceitação resumidos:**
- [ ] "corrida" → `cardio_run`, "musculação" → `strength`, "bicicleta" → `bike`.
- [ ] `_ACTIVITY_TYPE_ALIASES` cobre pt-BR e EN.
- [ ] Intensidade "moderada" → `moderate` via `_normalize_intensity`.

**Notas:**
- [Inferido do código] `activity_calculator.py:66-116` e `llm.py:80-103`.
