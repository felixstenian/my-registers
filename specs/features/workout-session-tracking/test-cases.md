# Casos de Teste — Treino estruturado (Bloco 3)

> **Rastreabilidade**: SP-120..SP-127, INV-11/12/13, ADR-011 · Fase planejada: T-B307 (`tests/test_workout.py`).
> Status: **`documented-only`** — `apps/api/tests/test_workout.py` ainda não existe; casos abaixo são a especificação de cobertura alvo quando o Bloco 3 for implementado.

## Cobertura alvo

- **Unitários**: `WorkoutService` (`start_session`, `add_exercise`, `log_set`, `end_session`, `consolidate_to_activity`, `history`); `normalized_name` fuzzy matcher; `message_formatter.compose_workout_*`.
- **Integração**: route `POST /chat/messages` → `IntentDispatcher` → 5 handlers → persistência + audit + recompute (no caso SP-125/126).
- **Invariantes**: INV-11 (≤1 sessão ativa), INV-12 (set no último exercício), INV-13 (unlink).
- **LLM**: mock em `tests/fixtures/anthropic/*.json` para `workout_*` intents (Inv. II — determinismo).

---

## Testes Unitários (alvo pendente — T-B307)

### TC-U-001 — `start_session` cria sessão ativa em DB vazio (SP-120)
- **Módulo**: `apps/api/app/services/workout.py::WorkoutService.start_session`
- **Entrada**: `user_id`, `day_log_id`, `workout_type='push'`, `detected_name='treino de push'`.
- **Saída esperada**: `WorkoutSession` com `status='active'`, `started_at=now()`, `ended_at=None`, `end_reason=None`.
- **Tipo**: Happy path

### TC-U-002 — `start_session` auto-encerra sessão anterior (INV-11)
- **Pré-condições**: já existe `WorkoutSession(user_id, status='active')`.
- **Passos**: chama `start_session` com mesmo `user_id`.
- **Resultado esperado**: sessão anterior atualizada `status='ended'`, `ended_at=now`, `end_reason='auto_new_session'`; `consolidate_to_activity` chamado para ela; nova sessão criada `active`.
- **Tipo**: Edge case (INV-11)

### TC-U-003 — `add_exercise` lookup histórico + PR (SP-121)
- **Pré-condições**: sessão ativa; histórico com "supino reto" em 3 sessões anteriores com PR 70×10 em 15/07.
- **Entrada**: `session_id`, `exercise_name='supino reto com barra'`.
- **Resultado esperado**: cria `WorkoutExercise` (sequence_index=max+1); `HistoryContext.first_time=False`; `last_session_date=28/07`; `last_sets=[{weight:60,reps:10},...]`; `pr_weight_kg=70`, `pr_reps_at_pr=10`, `pr_date=15/07`.
- **Tipo**: Happy path

### TC-U-004 — `add_exercise` "primeira vez" (SP-121)
- **Pré-condições**: sem histórico.
- **Resultado esperado**: `HistoryContext.first_time=True`.
- **Tipo**: Edge case

### TC-U-005 — `log_set` atribui ao último exercício (INV-12)
- **Pré-condições**: sessão ativa com 2 exercises (seq 1 e 2, último = seq 2).
- **Entrada**: `weight_kg=60, reps=10`.
- **Resultado esperado**: cria `WorkoutSet` ligado ao exercise seq 2 (não seq 1).
- **Tipo**: Happy path (INV-12)

### TC-U-006 — `log_set` sem exercício na sessão
- **Pré-condições**: sessão ativa sem exercises.
- **Resultado esperado**: raises exception (ou retorna warning); nenhum set criado.
- **Tipo**: Error case

### TC-U-007 — `log_set` múltiplas séries ("3×8 60 kg") (SP-122)
- **Entrada**: `weight_kg=60, reps=8, multiplier=3`.
- **Resultado esperado**: 3 `WorkoutSet` criados em sequência, mesma `weight_kg`/`reps`, `sequence_index` incrementando.
- **Tipo**: Happy path

### TC-U-008 — `log_set` parser fallback ("só a barra") (SP-122)
- **Entrada**: LLM output `"weight_kg": null` ou note `só_a_barra` — backend assume `DEFAULT_OLYMPIC_BAR_KG=20`.
- **Resultado esperado**: 1 set com `weight_kg=20`.
- **Tipo**: Edge case

### TC-U-009 — `log_set` input ambíguo rejeita (`clarify`)
- **Entrada**: LLM não consegue extrair `weight_kg`/`reps` claros; emite `clarify`.
- **Resultado esperado**: nenhum `WorkoutSet` criado; assistant pede esclarecimento.
- **Tipo**: Error case

### TC-U-010 — `end_session` com `end_reason='user'` (SP-124)
- **Entrada**: sessão ativa.
- **Resultado esperado**: `status='ended'`, `ended_at=now()`, `end_reason='user'`; `consolidate_to_activity` dispara.
- **Tipo**: Happy path

### TC-U-011 — `consolidate_to_activity` MET por tipo (SP-126)
- **Entradas**: `workout_type='push'` (MET=5.0); `weight_kg=80`, `duration=60min`.
- **Resultado esperado**: `activity_record.activity_type='strength'`, `calc_method='workout_session'`, `met_value=5.0`, `kcal_burned=5.0×80×1=400` (quase), `detected_name='Treino de push'`, `notes=JSON{exercise_ids, set_ids}`.
- **Tipo**: Happy path

### TC-U-012 — `consolidate_to_activity` sem `weight_kg` no perfil (SP-126)
- **Pré-condições**: `User.weight_kg = None`.
- **Resultado esperado**: `activity_record.kcal_burned=None`; warning `weight_kg_required_for_kcal` retornado; `activity_record` ainda persiste.
- **Tipo**: Edge case

### TC-U-013 — `end_session` idempotência? — encerrar dia já fechado
- **Contexto**: em Bloco 3, `end_session` é chamado por `_handle_close_day`; se dia já está `closed` (Const. Art. VIII), `close_day` retorna snapshot atual e não regrava `closed_at`. Sessão órfã permanece.
- **Resultado esperado**: nenhuma mutação; warning emitido se o caso for aplicável (MVP silencia).
- **Tipo**: Edge case

### TC-U-014 — `history` fuzzy match (SP-127)
- **Pré-condições**: histórico com "supino reto barra" e "supino reto halteres".
- **Entrada**: `exercise_name='supino reto'`, `limit=3`.
- **Resultado esperado**: lookup fuzzy casa com ambos; devolve últimos 3 registrados + PR.
- **Tipo**: Happy path

### TC-U-015 — `history` sem `exercise_name` lança `clarify`
- **Entrada**: `exercise_name=None`.
- **Resultado esperado**: assistant pede "Qual exercício?".
- **Tipo**: Error case

### TC-U-016 — `end_session` sem prévia `start` (sessão não encontrada)
- **Entrada**: `session_id` inválido.
- **Resultado esperado**: raises `NotFoundError`; nenhum update.
- **Tipo**: Error case

---

## Testes de Integração

### TC-I-001 — `POST /chat/messages` com `intent=workout_start` (SP-120, T-B305)
- **Fluxo**: `POST /chat/messages` → `IntentDispatcher` → `_handle_workout_start` → `WorkoutService.start_session` → `compose_workout_start` → persiste assistant message.
- **Pré-condições**: auth; LLM mockado em `tests/fixtures/anthropic/workout_start.json`.
- **Resultado esperado**: `workout_sessions.status='active'` no DB; assistant message content tem "Iniciei treino de push"; `audit_events(action='create', entity_type='workout_session')`.

### TC-I-002 — Fluxo completo sessão + 2 exercícios + séries + end (SP-120..SP-124)
- **Passos**:
  1. `intent=workout_start` → sessão ativa.
  2. `intent=workout_add_exercise` (exercicio A) → exercised created.
  3. `intent=workout_log_set` ×2 → 2 sets ligados a A.
  4. `intent=workout_add_exercise` (exercicio B) → implicit close A; B criado.
  5. `intent=workout_log_set` (B) → set em B ( INV-12).
  6. `intent=workout_end` → sessão ended; SP-126 dispara `consolidate_to_activity`.
- **Resultado esperado**: `activity_record.calc_method='workout_session'`, `activity_type='strength'`; audit em cada passo.

### TC-I-003 — `_handle_close_day` com sessão ativa encerra首先 (SP-125)
- **Pré-condições**: sessão ativa no `day_log` que está sendo fechado.
- **Passos**: trigger `close_day`;眼底 `WorkoutService.end_session(end_reason='auto_close_day')` happen before `recompute_snapshot`.
- **Resultado esperado**: snapshot inclui `kcal_out` da atividade consolidada; `activity_record.activity_type='strength'`.

### TC-I-004 — INV-13 unlink: delete `activity_record` não afeta `workout_*`
- **Pré-condições**: `activity_record.workout_session_id=SESSION_ID`; `workout_sessions/exercises/sets` populated.
- **Passos**: `DELETE /records/activities/{activity_id}` (via `record-deletion` feature).
- **Resultado esperado**: `activity_record.deleted_at=now()`; `workout_sessions` etc permanecem with `deleted_at=null`.

### TC-I-005 — INV-13 unlink reverse: delete `workout_set` não afeta `activity_record`
- **Passos**: `DELETE /records/workout-sets/{set_id}` (se endpoint criado) ou script direto.
- **Resultado esperado**: `workout_set.deleted_at=now()`; `activity_record` unchanged (kcal_burned persiste).

### TC-I-006 — INV-11 violação rejeitada
- **Passos** (race simulation): 2 `workout_start` quase simultâneos.
- **Resultado esperado**: Index parcial `(user_id WHERE status='active')` + unique constraint garantem 1 — segundo falha com erro claro; ou service detecta e encerra primeiro.

### TC-I-007 — INV-12 violação rejeitada
- **Passos**: `log_set` com `exercise_id` explícito = exercise seq 1 (não último).
- **Resultado esperado**: service rejeita com `LastExerciseOnlyError`; **nenhum** set criado; assistant message clarifies.

### TC-I-008 — `intent=workout_history` com `exercise_name` (SP-127)
- **Passos**: `POST /chat/messages` text "qual meu histórico no agachamento".
- **Resultado esperado**: assistant message mostra últimas 3 sessões + PR; nenhum novo registro criado (audit `action='query'` se aplicável).

### TC-I-009 — `intent=workout_history` sem `exercise_name` (clarify)
- **Resultado esperado**: assistant pede "Qual exercício?".

### TC-I-010 — LLM client mocked — INV-1 determinismo
- **Setup**: mock `anthropic` return garbage text without `tool_use`.
- **Resultado esperado**: backend descarta text; ou fallback rejeita com `LLMNoToolUseError`; nenhum `workout_*` mutado.

---

## Testes E2E (alvo pendente)

> [Implementação não localizada] — sem Playwright/Cypress no `apps/web`. <funcionalidade deveria ser testada manualmente quando Bloco 3 implementado.

### TC-E-001 — Jornada chat: treino completo
- **Persona**: Felix (levantador de peso).
- **Passos**:
  1. `/login` → /chat.
  2. "iniciando treino de push".
  3. "supino reto com barra" — verificar histórico (ou "primeira vez").
  4. "3x8 60 kg" — verificar 3 séries registradas.
  5. "agachamento livre" — verificar implicit close + histórico.
  6. "3x10 80 kg" — verificar 3 séries no agachamento.
  7. "finalizar treino" — verificar resumo e kcal.
  8. Verificar `/day` mostra atividade "Treino de push" com método "sessão de treino".
- **Resultado esperado**: fluxo natural; feedback visual; dados consistentes.

### TC-E-002 — Close day encerra treino automaticamente
- **Passos**:
  1. Inicia sessão; adiciona exercícios/séries.
  2. **Não** encerra explicitamente; clica "Encerrar dia" no `/chat` ou `/day`.
- **Resultado esperado**: snapshot pós-fechamento mostra atividade 'strength'; sessão `status='ended'`, `end_reason='auto_close_day'`.

### TC-E-003 — Histórico cross-session persiste
- **Passos**:
  1. Sessão A em dia D-7 com "supino reto 70×10".
  2. Sessão B em dia D-0 adicionando "supino reto"; verificar histórico mostra D-7 + PR 70×10.
- **Resultado esperado**: histórico contextual enxerga transações passadas.

### TC-E-004 — Perfil sem `weight_kg` produz warning
- **Passos**: configura perfil sem `weight_kg`; inicia + encerra treino.
- **Resultado esperado**: `activity_record.kcal_burned=null`; warning `weight_kg_required_for_kcal` aparece no `/day` (via `ActivitySection`).

---

## Testes de Regressão (a criar com o bloco)

Casos críticos a manter a cada release do Bloco 3:

- **R-001** (INV-11): `start_session` sempre encerra anterior ativa; query `WHERE status='active'` retorna ≤1.
- **R-002** (INV-12): `log_set` nunca atribui a exercise que não o último da sessão ativa.
- **R-003** (INV-13): delete `activity_record` não cascadeia em `workout_*`; reverse idem.
- **R-004** (SP-125): `_handle_close_day` chama `end_session` BEFORE `recompute_snapshot`.
- **R-005** (SP-126): `consolidate_to_activity` cria `activity_record` com `calc_method='workout_session'`, `activity_type='strength'`, `met_value=MET_fixo`.
- **R-006** (SP-121): histórico fuzzy match em `normalized_name`; "primeira vez" quando sem match.
- **R-007** (SP-122): parser múltiplas séries "3×8 60 kg" cria N sets em 1 mensagem.
- **R-008** (INV-1): LLM mockado com garbage não cria `workout_*` (backend rejeita).
- **R-009** (INV-10): `audit_events` em toda mutação de `workout_*`.
- **R-010** (Const. V §21): todas queries de `WorkoutService` têm `user_id` filter.
- **R-011** (Const. Art. VIII): sessão não muta em `day_log.status='closed'` (exceto SP-125 que roda antes do close).
- **R-012** (ADR-011): `kcal_out` no snapshot vem de `activity_records` (não de `workout_*` direto).
- **R-013** (SP-127): "qual meu histórico em X" cria zero novo registro; só consulta.
- **R-014** (T-B305): `compose_workout_*` segue SP-118 (markdown 2-cols pt-BR; `≈` não se aplica em métricas).

> Todos marcados `[Implementação não localizada]` — serão aplicáveis quando Bloco 3 for implementado.