# Casos de Teste — Módulo de Treino (Workout Module)

> **Rastreabilidade**: SP-120..SP-127, INV-15/16/17 (núcleo) · SP-170..179 (proposto) · Fase planejada: T-B307 (`tests/test_workout.py`) + novos testes do módulo.
> Status: **`documented-only`** — `apps/api/tests/test_workout.py` ainda não existe; casos abaixo são a especificação de cobertura alvo quando o módulo for implementado.

## Cobertura alvo

- **Unitários**: `WorkoutService` (`start_session`, `add_exercise`, `log_set`, `end_session`, `consolidate_to_activity`, `history`, `register_template`, `list_templates`, `set_template_active`, `history_paginated`, `correct_set`, `set_reported_kcal`); `normalized_name` fuzzy matcher; `message_formatter.compose_workout_*`.
- **Integração**: route `POST /chat/messages` → `IntentDispatcher` → handlers → persistência + audit + recompute (SP-125/126); rotas de módulo `/workouts/*`.
- **Invariantes**: INV-15/16/17 (núcleo) + INV-18/19/20/21 (módulo).
- **LLM**: mock em `tests/fixtures/anthropic/*.json` para `workout_*` intents e extração de imagem (Inv. II — determinismo).
- **Frontend**: E2E Playwright (`apps/web/e2e/`) — fluxos de chat de treino, guiado, `/workouts` e `/day`.

---

## Testes Unitários (alvo pendente — T-B307 + módulo)

### TC-U-001 — `start_session` cria sessão ativa em DB vazio (SP-120)
- **Módulo**: `apps/api/app/services/workout.py::WorkoutService.start_session`
- **Entrada**: `user_id`, `day_log_id`, `workout_type='push'`, `detected_name='treino de push'`.
- **Saída esperada**: `WorkoutSession` com `status='active'`, `started_at=now()`, `ended_at=None`, `end_reason=None`, `kcal_burned_reported=None`, `template_id=None`.
- **Tipo**: Happy path

### TC-U-002 — `start_session` auto-encerra sessão anterior (INV-15)
- **Pré-condições**: já existe `WorkoutSession(user_id, status='active')`.
- **Passos**: chama `start_session` com mesmo `user_id`.
- **Resultado esperado**: anterior `status='ended'`, `end_reason='auto_new_session'`; `consolidate_to_activity` chamado; nova `active`.
- **Tipo**: Edge case (INV-15)

### TC-U-003 — `start_session` guiado com template (RF-020)
- **Entrada**: `template_id` de template `active=true` com 3 exercícios-alvo.
- **Resultado esperado**: sessão criada com `template_id`; `compose_workout_start` lista 3 exercícios como botões.
- **Tipo**: Happy path

### TC-U-004 — `start_session` com template `active=false` (INV-19)
- **Entrada**: `template_id` inativo.
- **Resultado esperado**: rejeitado (não inicia); mensagem orienta reativar.
- **Tipo**: Error case (INV-19)

### TC-U-005 — `register_template` a partir de texto (RF-015)
- **Entrada**: `WorkoutTemplateIn(name="Treino A", kind="musculacao", muscle_groups=["peito","ombro","triceps"], exercises=[{exercise_name="supino", target_sets=4, target_reps=8},...])`.
- **Resultado esperado**: cria `workout_templates` com `active=true` e `created_at=now()`; exercícios-alvo com `sequence_index` 1..N.
- **Tipo**: Happy path

### TC-U-006 — `register_template` com dados parciais (RF-015)
- **Entrada**: `WorkoutTemplateIn(name="Corrida", kind="cardio")` sem exercises/muscle_groups.
- **Resultado esperado**: template criado; exercises vazio; `normalized_name` tratado.
- **Tipo**: Edge case

### TC-U-007 — `list_templates` por status (RF-014/016)
- **Entrada**: `active=True` / `active=False`.
- **Resultado esperado**: filtro correto; sempre `user_id`-scoped (INV-18); paginação respeitada.
- **Tipo**: Happy path

### TC-U-008 — `set_template_active` toggle (RF-016)
- **Entrada**: template com sessões finalizadas.
- **Resultado esperado**: `active` vira `false`; sessões finalizadas **intactas** (INV-19/20); audit gravado.
- **Tipo**: Happy path + edge (INV-20)

### TC-U-009 — `history_paginated` (RF-017)
- **Entrada**: 45 sessões; `page=2&page_size=20`.
- **Resultado esperado**: 20 itens; página 2 retorna itens 21-40; ordenação determinística (sem dup/omissão).
- **Tipo**: Happy path

### TC-U-010 — `consolidate_to_activity` com kcal reportada (INV-21)
- **Entrada**: `kcal_burned_reported=380`, `workout_type='push'`.
- **Resultado esperado**: `activity_record.kcal_burned=380`, `met_value=NULL`, `calc_method='workout_session'`.
- **Tipo**: Happy path

### TC-U-011 — `consolidate_to_activity` MET por tipo (SP-126)
- **Entradas**: `workout_type='push'` (MET=5.0); `weight_kg=80`, `duration=60min`.
- **Resultado esperado**: `activity_type='strength'`, `calc_method='workout_session'`, `met_value=5.0`, `kcal_burned=5.0×80×1=400`, `detected_name='Treino de push'`.
- **Tipo**: Happy path

### TC-U-012 — `consolidate_to_activity` sem `weight_kg` (SP-126)
- **Pré-condições**: `User.weight_kg=None`; sem kcal reportada.
- **Resultado esperado**: `kcal_burned=None`; warning `weight_kg_required_for_kcal`.
- **Tipo**: Edge case

### TC-U-013 — `correct_set` (RF-023, INV-16/20)
- **Entrada**: `WorkoutCorrectSetIn(set_id, weight_kg=65, reps=9)`.
- **Resultado esperado**: set atualizado; audit; se sessão encerrada → `consolidate_to_activity` re-roda.
- **Tipo**: Happy path (RF-023, INV-20)

### TC-U-014 — `correct_set` em dia fechado (Const. VIII)
- **Pré-condições**: day_log `status='closed'`.
- **Resultado esperado**: 409 `conflict_closed_day`; nada mutado.
- **Tipo**: Error case

### TC-U-015 — `add_exercise` com histórico (SP-121)/primeira vez
- **Entrada**: `exercise_name='supino reto com barra'` com e sem histórico.
- **Resultado esperado**: `first_time=False` com PR/last_sets; `first_time=True` sem histórico.
- **Tipo**: Happy path + edge

### TC-U-016 — `log_set` múltiplas séries (SP-122)
- **Entrada**: `weight_kg=60, reps=8, multiplier=3`.
- **Resultado esperado**: 3 sets, `sequence_index` 1..3.
- **Tipo**: Happy path

### TC-U-017 — `log_set` ambíguo rejeita (`clarify`)
- **Entrada**: LLM não consegue extrair peso/reps claros.
- **Resultado esperado**: nenhum set; assistant pede esclarecimento.
- **Tipo**: Error case

### TC-U-018 — `end_session` com `end_reason='user'` + cronômetro (SP-124/RF-021)
- **Entrada**: sessão ativa.
- **Resultado esperado**: `status='ended'`, `ended_at=now()`, `duration_minutes` calculado; consolidação dispara.
- **Tipo**: Happy path

### TC-U-019 — `end_session` idempotência — dia já fechado
- **Contexto**: `end_session` chamado por `_handle_close_day`; se dia já `closed`, retorna snapshot sem regravar `closed_at`.
- **Resultado esperado**: nenhuma mutação; warning se aplicável.
- **Tipo**: Edge case

### TC-U-020 — `history` fuzzy match (SP-127)
- **Entrada**: `exercise_name='supino reto'`, histórico com "supino reto barra"/"supino reto halteres".
- **Resultado esperado**: casa com ambos; últimas 3 + PR.
- **Tipo**: Happy path

### TC-U-021 — `next_exercise_prompt` (RF-020)
- **Pré-condições**: sessão ativa com template de 3 exercícios; 2 já executados.
- **Resultado esperado**: retorna lista de exercícios restantes (ou todos) para reinício da sequência.
- **Tipo**: Happy path

### TC-U-022 — `set_reported_kcal` (RF-022/023)
- **Entrada**: `kcal_burned_reported=450`.
- **Resultado esperado**: sessão atualizada; consolidação posterior usa o valor (INV-21).
- **Tipo**: Happy path

---

## Testes de Integração

### TC-I-001 — `POST /chat/messages` com `intent=workout_start` (SP-120)
- **Fluxo**: `POST /chat/messages` → `IntentDispatcher` → `_handle_workout_start` → `WorkoutService.start_session` → `compose_workout_start` → persiste assistant message.
- **Pré-condições**: auth; LLM mockado em `tests/fixtures/anthropic/workout_start.json`.
- **Resultado esperado**: `workout_sessions.status='active'`; assistant content "Iniciei treino de push"; `audit_events(action='create', entity_type='workout_session')`.

### TC-I-002 — Fluxo completo sessão + 2 exercícios + séries + end (SP-120..124)
- **Passos**: start → add A → log_set×2 → add B (implicit close A) → log_set → end.
- **Resultado esperado**: `activity_record.calc_method='workout_session'`, `activity_type='strength'`; audit em cada passo.

### TC-I-003 — `_handle_close_day` com sessão ativa encerra antes do recompute (SP-125)
- **Pré-condições**: sessão ativa no `day_log` fechado.
- **Resultado esperado**: snapshot inclui `kcal_out`; `end_reason='auto_close_day'`.

### TC-I-004 — INV-17 unlink: delete `activity_record` não afeta `workout_*`
- **Passos**: `DELETE /records/activities/{activity_id}`.
- **Resultado esperado**: `activity_record.deleted_at=now()`; `workout_sessions/exercises/sets` intactos.

### TC-I-005 — INV-17 unlink reverse: delete `workout_set` não afeta `activity_record`
- **Passos**: `DELETE /records/workout-sets/{set_id}` (se endpoint criado) ou script direto.
- **Resultado esperado**: `workout_set.deleted_at=now()`; `activity_record` unchanged.

### TC-I-006 — INV-15 violação rejeitada
- **Passos**: 2 `workout_start` quase simultâneos.
- **Resultado esperado**: index parcial + unique garantem 1; service encerra o primeiro.

### TC-I-007 — INV-16 violação rejeitada
- **Passos**: `log_set` com `exercise_id` = exercício que não o último.
- **Resultado esperado**: rejeitado (`LastExerciseOnlyError`); nenhum set; assistant clarifies.

### TC-I-008 — `intent=workout_history` com `exercise_name` (SP-127)
- **Resultado esperado**: últimas 3 sessões + PR; zero registro novo.

### TC-I-009 — Cadastro de template via chat (RF-015)
- **Passos**: botão "Cadastrar treino" → mensagem de exemplo; usuário envia texto; LLM mockado retorna `WorkoutTemplateIn`.
- **Resultado esperado**: `workout_templates` criado com `created_at=now()`; audit; assistant confirma nome/agrupamento/Série-rep.

### TC-I-010 — Registro por imagem (RF-022)
- **Setup**: mensagem com `media_ids` (imagem de esteira com kcal visível); LLM mock retorna `WorkoutImageIn(title="Esteira 30min", activity_type="cardio_run", intensity="moderate", kcal_burned_reported=250)`.
- **Resultado esperado**: sessão/registro com `kcal_burned_reported=250`; consolidação usa valor (INV-21); snapshot reflete.
- **Tipo**: integration (Inv. II — determinismo)

### TC-I-011 — Bug fix: imagem com garbage LLM não cria dados errados (INV-1)
- **Setup**: mock Anthropic devolve lixo sem tool_use.
- **Resultado esperado**: backend descarta; nenhum `workout_*` mutado.

### TC-I-012 — `PATCH /records/workout-sets/{id}` via `/day` (RF-023)
- **Fluxo**: formulário inline → PATCH → recompute → refresh `/day`.
- **Resultado esperado**: set atualizado; se sessão encerrada, `activity_record` reconsolidado (INV-20); audit.

### TC-I-013 — `GET /workouts/history` paginado (RF-017)
- **Passos**: seed 45 sessões; `page=1` e `page=2`.
- **Resultado esperado**: páginas consistentes; total = 45.

### TC-I-014 — LLM client mocked — `intent=workout_register` sem imagens (RF-015)
- **Setup**: mock Anthropic texto estruturado.
- **Resultado esperado**: template criado a partir do texto; zero cálculos na LLM.

---

## Testes E2E (alvo pendente)

> [Implementação não localizada] — sem suites de treino no `apps/web`. <funcionalidade seria testada manualmente até módulo implementado.

### TC-E-001 — Jornada chat de treino: cadastrar + executar guiado
- **Persona**: Felix (levantador de peso).
- **Passos**:
  1. `/login` → abrir chat de treino (`/workouts/chat`).
  2. Header mostra atividades do dia + kcal gastas.
  3. Clicar "Cadastrar treino" → ler template de exemplo (tipo/agrupamento/séries-reps).
  4. Enviar texto do treino → confirmar `workout_templates` criado (data de cadastro exibida).
  5. Clicar "Iniciar treino" → selecionar template → ver lista de exercícios.
  6. Selecionar exercício → ver histórico (última realização + cargas/reps).
  7. Enviar "carga × reps" → confirmação + recaptulação + botão "Ir para o próximo exercício".
  8. Repetir até último exercício; "Finalizar treino" (botão ou texto) → cronômetro para; resumo + kcal.
- **Resultado esperado**: fluxo natural; tempo registrado; `/day` mostra seção de treinos.

### TC-E-002 — Registro por imagem
- **Passos**: abrir chat de treino, anexar foto da atividade, enviar.
- **Resultado esperado**: assistant confirma título/atividade/intensidade/kcal; `/day` mostra kcal.

### TC-E-003 — `/workouts` abas e paginação
- **Passos**: navegar para `/workouts`; verificar abas Ativos/Inativos/Histórico; inativar um treino; navegar páginas do histórico.
- **Resultado esperado**: status moves de aba; inativo some do seletor; paginação sem duplicação.

### TC-E-004 — Edição por `/day`
- **Passos**: abrir `/day` com treino; editar peso/séries/kcal inline; salvar.
- **Resultado esperado**: valores atualizados; snapshot/refresca; audit invisível ao usuário.

### TC-E-005 — Close day encerra treino automaticamente
- **Passos**: inicia treino guiado; não encerra; fecha dia pelo chat de alimentação.
- **Resultado esperado**: snapshot pós-fechamento mostra 'strength'; sessão `ended`, `end_reason='auto_close_day'`.

---

## Testes de Regressão (a criar com o módulo)

- **R-001** (INV-15): `start_session` sempre encerra anterior ativa; `WHERE status='active'` retorna ≤1.
- **R-002** (INV-16): `log_set` nunca atribui a exercício que não o último.
- **R-003** (INV-17): delete `activity_record` não cascadeia em `workout_*`; reverse idem.
- **R-004** (SP-125): `_handle_close_day` chama `end_session` BEFORE `recompute_snapshot`.
- **R-005** (SP-126): `consolidate_to_activity` cria `activity_record` com `calc_method='workout_session'`, `activity_type='strength'`, `met_value=MET_fixo` (ou `NULL` + kcal reportada).
- **R-006** (SP-121): histórico fuzzy em `normalized_name`; "primeira vez" sem match.
- **R-007** (SP-122): "3×8 60 kg" cria N sets em 1 mensagem.
- **R-008** (INV-1): LLM mockado com garbage não cria `workout_*`.
- **R-009** (INV-10): `audit_events` em toda mutação de `workout_*` e `workout_templates`.
- **R-010** (Const. V §21): todas queries de `WorkoutService` têm `user_id` filter.
- **R-011** (Const. Art. VIII): sessão não muta em `day_log.status='closed'`.
- **R-012** (ADR-011): `kcal_out` no snapshot vem de `activity_records` (não de `workout_*` direto).
- **R-013** (SP-127): "qual meu histórico em X" cria zero registro novo; só consulta.
- **R-014** (T-B305): `compose_workout_*` segue SP-118 (markdown 2-cols pt-BR).
- **R-015** (INV-18): templates sempre `user_id`-scoped.
- **R-016** (INV-19): `active=false` fora do fluxo guiado e da aba *Ativos*; histórico preservado.
- **R-017** (INV-20): edição reconsolida sessão encerrada; template inativado não muta sessões finalizadas.
- **R-018** (INV-21): kcal reportada é fonte; LLM nunca calcula.
- **R-019** (RF-017): paginação determinística.

> Todos marcados `[Implementação não localizada]` — aplicáveis quando o módulo for implementado.