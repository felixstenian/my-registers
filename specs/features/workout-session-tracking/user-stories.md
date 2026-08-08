# Histórias de Usuário — Treino estruturado (Bloco 3)

> **Rastreabilidade**: SP-120..SP-127, INV-11/12/13 · ADR-011 · Status: **`documented-only`** — feature planejada, ainda não implementada.

## Personas

- **Felix (levantador de peso)**: quer detalhar séries por exercício e acompanhar PR ao longo do tempo.
- **Felix (cardio + força)**: quer manter o fluxo simples do "corri 40 min" sem ser obrigado a abrir sessão.
- **Felix (depois de esquecido)**: esqueceu de encerrar o treino no app; quer que o sistema resolva ao fechar o dia.

---

### US-001 — Iniciar treino de força
**Como** Felix (levantador de peso),
**Quero** dizer "iniciando treino de push" no chat e criar a sessão,
**Para que** eu registre exercícios/séries subsequentes como parte dela.

**Critérios de Aceitação resumidos:**
- [ ] Cria `workout_sessions` com `workout_type` classificado pela LLM.
- [ ] Se já havia sessão ativa, encerra a anterior automaticamente.
- [ ] Assistant avisa e mostra resumo curto.

**Notas:**
- Fonte: SP-120, INV-11. [Implementação não localizada]

---

### US-002 — Adicionar exercício com histórico contextual
**Como** Felix (levantador de peso),
**Quero** adicionar "supino reto com barra" e ver minha última sessão + PR,
**Para que** eu saiba quanto tirei antes e tente superar.

**Critérios de Aceitação resumidos:**
- [ ] Cria `workout_exercises` com `normalized_name`.
- [ ] Resposta mostra última sessão (data + séries "peso × reps") + PR.
- [ ] "Primeira vez" se nunca fez.

**Notas:**
- Fonte: SP-121. [Implementação não localizada]

---

### US-003 — Registrar séries em pt-BR
**Como** Felix (levantador de peso),
**Quero** dizer "3×8 60 kg" e criar 3 séries iguais,
**Para que** eu não precise repetir número de vezes.

**Critérios de Aceitação resumidos:**
- [ ] Cria N sets iguais em 1 mensagem.
- [ ] Parser pt-BR pela LLM (backend só valida `weight_kg>0`, `reps>0`).
- [ ] Resposta "Série 3 registrada: 60 kg × 10".
- [ ] Ambíguo → `clarify`, nenhum set criado.

**Notas:**
- Fonte: SP-122. [Implementação não localizada]

---

### US-004 — Múltiplos exercícios numa sessão
**Como** Felix (levantador de peso),
**Quero** adicionar "leg press" depois de ter "agachamento" sem encerrar explicitamente,
**Para que** eu flua pela sessão sem overhead.

**Critérios de Aceitação resumidos:**
- [ ] Adicionar B encerra implicitamente A.
- [ ] Séries seguintes passam a pertencer a B.
- [ ] Sem `ended_at` no exercício (só `sequence_index`).

**Notas:**
- Fonte: SP-123, INV-12. [Implementação não localizada]

---

### US-005 — Encerrar treino explicitamente
**Como** Felix (levantador de peso),
**Quero** dizer "finalizar treino" e receber resumo,
**Para que** eu finalize a sessão e saiba gasto calórico estimado.

**Critérios de Aceitação resumidos:**
- [ ] `status='ended'`, `end_reason='user'`.
- [ ] Dispara SP-126 (consolida em `activity_record`).
- [ ] Assistant devolve "Treino de push encerrado (58 min). 4 ex · 14 séries · ~380 kcal".

**Notas:**
- Fonte: SP-124. [Implementação não localizada]

---

### US-006 — Esquecer de encerrar e ainda assim fechar o dia
**Como** Felix (depois de esquecido),
**Quero** que fechar o dia encerre minha sessão ativa automaticamente,
**Para que** eu não fique com sessão órfã e o gasto calórico entre no snapshot.

**Critérios de Aceitação resumidos:**
- [ ] `_handle_close_day` encerra sessão ativa com `end_reason='auto_close_day'`.
- [ ] Ordem crítica: encerra **antes** do recompute.
- [ ] `activity_record` aparece no snapshot do dia.

**Notas:**
- Fonte: SP-125. [Implementação não localizada]

---

### US-007 — Snapshot e semanal continuam agnósticos
**Como** Felix (cardio + força),
**Quero** que minha corrida e meu treino ambos apareçam como atividades do dia,
**Para que** eu tenha uma visão consolidada sem precisar pensar nas tabelas.

**Critérios de Aceitação resumidos:**
- [ ] Sessão encerrada cria 1 `activity_record` com `activity_type='strength'`.
- [ ] `daily-snapshot` lê `activity_records` como fonte única (`kcal_out`).
- [ ] `weekly-report` idem.

**Notas:**
- Fonte: SP-126, ADR-011 (decisão de design). [Implementação não localizada]

---

### US-008 — kcal estimado mesmo sem peso no perfil
**Como** Felix (levantador de peso),
**Quero** que o treino seja registrado mesmo se eu não preenchi `weight_kg` no perfil,
**Para que** eu não perca os registros por causa de um campo opcional.

**Critérios de Aceitação resumidos:**
- [ ] `activity_record.kcal_burned=NULL` se sem `weight_kg`.
- [ ] Warning `weight_kg_required_for_kcal`.
- [ ] Treino persistido e histórico disponível.

**Notas:**
- Fonte: SP-126. [Implementação não localizada]

---

### US-009 — Consultar histórico de um exercício
**Como** Felix (levantador de peso),
**Quero** perguntar "qual meu PR no agachamento?" e ver últimos 3 treinos + record,
**Para que** eu acompanhe evolução sem adivinhar datas.

**Critérios de Aceitação resumidos:**
- [ ] `intent=workout_history` com `exercise_name`.
- [ ] Backend responde últimas 3 sessões + PR (mesmo formato do SP-121, sem criar registro).
- [ ] `exercise_name` ausente → `clarify`.

**Notas:**
- Fonte: SP-127. [Implementação não localizada]

---

### US-010 — Corrigir/excluir treino não apaga detalhes
**Como** Felix (levantador de peso),
**Quero** que apagar o `activity_record` consolidado (do snapshot) não apague minhas séries,
**Para que** eu mantenha histórico detalhado mesmo desfazendo o fechamento do dia.

**Critérios de Aceitação resumidos:**
- [ ] INV-13: delete de `activity_record` não afeta `workout_sessions/exercises/sets`.
- [ ] Delete de `workout_sets` não apaga `activity_record` já gerado.
- [ ] Consistência via recompute manual (fora do escopo do MVP-de-treino).

**Notas:**
- Fonte: INV-13, ADR-011. [Implementação não localizada]

---

### US-011 — Auditoria das mutações de treino
**Como** Felix (segurança),
**Quero** que toda mutação em `workout_*` grave `audit_events`,
**Para que** eu tenha trilha do que foi registrado/corrigido/excluído.

**Critérios de Aceitação resumidos:**
- [ ] INV-10: `audit_events` em CREATE/UPDATE/DELETE de sessions/exercises/sets.
- [ ] `actor`, `before`, `after`, `message_id` presentes.

**Notas:**
- Fonte: INV-10. [Implementação não localizada]