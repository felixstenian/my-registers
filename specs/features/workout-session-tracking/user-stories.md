# Histórias de Usuário — Módulo de Treino (Workout Module)

> **Rastreabilidade**: SP-120..SP-127, INV-15/16/17 (núcleo) · SP-170..179 propostos (módulo) · ADR-011 · Status: **`documented-only`** — feature planejada + expansão do cliente (2026-08-14), ainda não implementada.

## Personas

- **Felix (levantador de peso)**: quer detalhar séries por exercício, acompanhar PR e executar treinos guiados.
- **Felix (cardio + força)**: quer manter o fluxo simples do "corri 40 min" sem obrigação de abrir sessão.
- **Felix (frequente)**: quer cadastrar treinos reutilizáveis (musculação com agrupamento muscular) e iniciá-los com um toque, cronometrando o tempo.
- **Felix (visual)**: quer enviar fotos da atividade realizada e que o app extraia título, atividade, intensidade e kcal.
- **Felix (depois de esquecido)**: esqueceu de encerrar o treino; quer que o sistema resolva ao fechar o dia.

---

### US-001 — Iniciar treino de força guiado
**Como** Felix (levantador de peso),
**Quero** tocar "Iniciar treino", escolher um treino cadastrado e começar pelos exercícios,
**Para que** eu execute o treino seguindo meus templates sem lembrar cada passo.

**Critérios de Aceitação resumidos:**
- [ ] Botão "Iniciar treino" lista `workout_templates` com `active=true` como botões.
- [ ] Ao escolher, chat lista **todos os exercícios** do template como botões.
- [ ] Ao escolher um exercício, chat busca a última realização e lista cargas/reps.
- [ ] Cada série concluída é registrada; a partir da 1ª o chat confirma + recapitula último treino + botão "Ir para o próximo exercício".

**Notas:**
- Fonte: RF-020 → SP-178 (proposto). [Implementação não localizada]

---

### US-002 — Cadastrar treino reutilizável
**Como** Felix (frequente),
**Quero** tocar "Cadastrar treino", ver um template de exemplo e enviar meu treino por texto,
**Para que** o app crie um treino reutilizável com data de cadastro.

**Critérios de Aceitação resumidos:**
- [ ] Botão "Cadastrar treino" envia mensagem amigável com exemplo (tipo, agrupamento muscular p/ musculação, séries/reps).
- [ ] LLM lê o texto e cria `workout_templates` + exercícios-alvo.
- [ ] `created_at` = data de cadastro informado na confirmação.
- [ ] Novo treino nasce `active=true`.

**Notas:**
- Fonte: RF-015 → SP-171 (proposto). [Implementação não localizada]

---

### US-003 — Adicionar exercício com histórico contextual (núcleo SP-121)
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

### US-004 — Registrar séries em pt-BR (núcleo SP-122)
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

### US-005 — Encerrar treino com cronômetro e tempo registrado
**Como** Felix (levantador de peso),
**Quero** finalizar o treino pelo botão "Finalizar treino" (ou texto) e que o cronômetro pare,
**Para que** o tempo do treino e o gasto calórico entrem no registro.

**Critérios de Aceitação resumidos:**
- [ ] Cronômetro exibido ao iniciar treino; **parado** ao encerrar.
- [ ] "Finalizar treino" aparece no mesmo lugar do "Iniciar treino" quando há treino ativo.
- [ ] `duration_minutes = ended_at - started_at` persistido.
- [ ] `consolidate_to_activity` cria `activity_record` (kcal reportada ou MET).

**Notas:**
- Fonte: RF-021 → SP-179; RF-019 → SP-173; SP-124. [Implementação não localizada]

---

### US-006 — Esquecer de encerrar e ainda assim fechar o dia (núcleo SP-125)
**Como** Felix (depois de esquecido),
**Quero** que fechar o dia encerre minha sessão ativa automaticamente,
**Para que** eu não fique com sessão órfã e o gasto entre no snapshot.

**Critérios de Aceitação resumidos:**
- [ ] `_handle_close_day` encerra sessão ativa com `end_reason='auto_close_day'` **antes** do recompute.
- [ ] `activity_record` aparece no snapshot.

**Notas:**
- Fonte: SP-125. [Implementação não localizada]

---

### US-007 — Snapshot e semanal continuam agnósticos (núcleo SP-126, ADR-011)
**Como** Felix (cardio + força),
**Quero** que corrida e treino apareçam como atividades no dia,
**Para que** eu tenha visão consolidada sem pensar nas tabelas.

**Critérios de Aceitação resumidos:**
- [ ] Sessão encerrada cria 1 `activity_record` com `activity_type='strength'`.
- [ ] `daily-snapshot` e `weekly-report` leem `activity_records` (fonte única `kcal_out`).

**Notas:**
- Fonte: SP-126, ADR-011.

---

### US-008 — kcal estimado mesmo sem peso no perfil (núcleo SP-126)
**Como** Felix (levantador de peso),
**Quero** que o treino seja registrado mesmo se eu não preenchi `weight_kg`,
**Para que** eu não perca registros por um campo opcional.

**Critérios de Aceitação resumidos:**
- [ ] `activity_record.kcal_burned=NULL` se não há valor reportado nem `weight_kg`.
- [ ] Warning `weight_kg_required_for_kcal`.

---

### US-009 — Registrar atividade por imagem
**Como** Felix (visual),
**Quero** enviar uma foto da atividade realizada,
**Para que** o app extraia título, atividade, intensidade e calorias gastas.

**Critérios de Aceitação resumidos:**
- [ ] Imagem anexada ao chat de treino (mesmo `POST /media`).
- [ ] LLM extrai `WorkoutImageIn`: título, atividade, intensidade (se houver), kcal (se houver).
- [ ] kcal visível na imagem vira `kcal_burned_reported` (INV-21).

**Notas:**
- Fonte: RF-022 → SP-174 (proposto). [Implementação não localizada]

---

### US-010 — Corrigir peso, séries e kcal via chat e /day
**Como** Felix (levantador de peso),
**Quero** corrigir peso, séries ou calorias gastas pelo chat e também pelo resumo do dia,
**Para que** meus registros fiquem fiéis ao que realmente fiz.

**Critérios de Aceitação resumidos:**
- [ ] `intent=workout_correct` ajusta `workout_sets` (peso/reps) e `kcal_burned_reported` da sessão.
- [ ] `/day` tem seção de treinos com edição inline (padrão `EditActivityForm`).
- [ ] Dia fechado → 409; audit gravado; sessão encerrada → reconsolidação (INV-20).

**Notas:**
- Fonte: RF-023 → SP-175 (proposto). [Implementação não localizada]

---

### US-011 — Histórico de treinos paginado
**Como** Felix (levantador de peso),
**Quero** ver o log dos treinos realizados com paginação,
**Para que** eu acompanhe evolução sem procurar em listas infinitas.

**Critérios de Aceitação resumidos:**
- [ ] Aba *Histórico* lista sessões finalizadas: nome, data, hora, kcal (e cargas/séries/reps p/ força).
- [ ] Paginação determinística (sem duplicar/omitir itens entre páginas).
- [ ] Template `active=false` não remove sessões já finalizadas (INV-19).

**Notas:**
- Fonte: RF-017 → SP-177 (proposto). [Implementação não localizada]

---

### US-012 — Ativar/inativar treino na listagem
**Como** Felix (frequente),
**Quero** desativar treinos que não vou usar e ativá-los depois,
**Para que** a lista de início fique enxuta.

**Critérios de Aceitação resumidos:**
- [ ] Toggle `active` na listagem `/workouts`.
- [ ] Abas *Ativos* / *Inativos* separam por status.
- [ ] Inativo não aparece no fluxo guiado (INV-19).

**Notas:**
- Fonte: RF-016 → SP-172 (proposto). [Implementação não localizada]

---

### US-013 — Auditoria das mutações de treino (núcleo INV-10)
**Como** Felix (segurança),
**Quero** que toda mutação em `workout_*` e `workout_templates` grave `audit_events`,
**Para que** eu tenha trilha do que foi registrado/corrigido/excluído.

**Critérios de Aceitação resumidos:**
- [ ] `audit_events` em CREATE/UPDATE/DELETE de templates/sessions/exercises/sets.
- [ ] `actor`, `before`, `after`, `message_id` presentes.

**Notas:**
- Fonte: INV-10.