# Requisitos — Treino estruturado (Bloco 3)

> **Rastreabilidade**: SP-120..SP-127 + INV-11/12/13 em [`specs/001-mvp-registro-diario/spec.md`](../../001-mvp-registro-diario/spec.md#312-registro-estruturado-de-treino) · ADR-011 em [`research.md`](../../001-mvp-registro-diario/research.md) · Bloco 3 (T-B301..T-B308) em [`tasks.md`](../../001-mvp-registro-diario/tasks.md). Status: **`documented-only`** — spec aceita, implementação **pendente** (todo bloqueado desde v1.6/v1.2). Não há `WorkoutService`, schemas, migration, intents nem handlers no `apps/api`/`apps/web`.

## Visão geral

Módulo hierárquico de treino de força (`workout_sessions` → `workout_exercises` → `workout_sets`) coexistindo com `log_activity` (cardio genérico), via **consolidação em `activity_record`** no encerramento da sessão (SP-126). Mantém snapshot diário / relatório semanal agnósticos (continuam lendo só `activity_records`). Estado conversacional vive no banco (sessão ativa + último exercício); LLM consulta a cada mensagem. Histórico contextual por `normalized_name` fuzzy match (SP-121/SP-127) com PR pessoal.

## Requisitos funcionais

| ID | Requisito | SP | Prioridade |
|---|---|---|---|
| RF-001 | `intent=workout_start` cria `workout_sessions` com `started_at=now()`, `status='active'`, `workout_type` enum canônico (`push`/`pull`/`legs`/`upper`/`lower`/`full_body`/`cardio`/`other`), `detected_name` livre. Se já existe sessão ativa, auto-encerra anterior (`end_reason='auto_new_session'`, INV-11). Assistant avisa + resumo curto. | SP-120 | May Have |
| RF-002 | `intent=workout_add_exercise` com `exercise_name` cria `workout_exercises` ligado à sessão ativa, `sequence_index` auto-incrementado, `normalized_name` para lookup. Backend consulta histórico (última sessão com o exercício + todas as séries) e PR (maior peso × maior reps naquele peso, com data). Mensagem "Primeira vez" se não há histórico. | SP-121 | May Have |
| RF-003 | `intent=workout_log_set` com `weight_kg`, `reps` (opcionalmente `notes`) cria `workout_sets` ligado ao **último** exercício da sessão ativa (INV-12) com `sequence_index` auto. Parser pt-BR pela LLM (e.g. "20 kg da barra + 20 kg de cada lado" → 60; "só a barra" → 20 default). Múltiplas séries em 1 mensagem ("3×8 60 kg" → 3 sets). Ambiguidade → `clarify`, nenhum set criado. | SP-122 | May Have |
| RF-004 | Adicionar novo exercício B encerra implicitamente o exercício A (sem `ended_at` em exercício; só `sequence_index > A.sequence_index` estabelece ordem). Séries subsequentes ligam-se a B. | SP-123 | May Have |
| RF-005 | `intent=workout_end` marca `status='ended'`, `ended_at=now()`, `end_reason='user'`. Dispara SP-126 (consolidação). Assistant devolve resumo ("Treino de push encerrado (58 min). 4 exercícios · 14 séries · ~380 kcal") + tabela markdown. | SP-124 | May Have |
| RF-006 | `_handle_close_day` (SP-100) encerra sessão ativa **antes** do recompute com `end_reason='auto_close_day'`, dispara SP-126 para o `activity_record` aparecer no snapshot do dia. | SP-125 | May Have |
| RF-007 | `WorkoutService.consolidate_to_activity`: calcula `duration_minutes = ended_at - started_at`, `kcal_burned` via **MET fixo por `workout_type`** (`push`/`pull`/`upper` → 5.0; `legs`/`lower` → 6.0; `full_body` → 5.5) × `weight_kg` (perfil) × horas. Cria 1 `activity_record` com `activity_type='strength'`, `calc_method='workout_session'`, `met_value` usado, `detected_name="Treino de {workout_type}"`, `notes=JSON` com IDs de exercícios/séries. | SP-126, INV-13 | May Have |
| RF-008 | Se usuário sem `weight_kg` no perfil, `activity_record` é criado com `kcal_burned=NULL` + warning `weight_kg_required_for_kcal` (treino persistido, kcal pendente). | SP-126 | May Have |
| RF-009 | `intent=workout_history` com `exercise_name`: backend responde últimas 3 sessões que continham o exercício + PR pessoal (mesmo formato do SP-121 sem criar registro). `exercise_name` ausente → `clarify`. | SP-127 | May Have |
| RF-010 | `Intent` enum estendido com `workout_start`/`workout_add_exercise`/`workout_log_set`/`workout_end`/`workout_history`. Payloads Pydantic `_LenientBase` (`WorkoutStartIn`, etc.). Tool schema `record_intent` estendido. Prompt `system_v2.md` ganha regra 19 explicando os intents. | T-B302 | Must Have (gate) |
| RF-011 | Schema das 3 tabelas: `workout_sessions` (id, user_id, day_log_id FK, workout_type enum, detected_name, started_at, ended_at nullable, status `active|ended`, end_reason enum); `workout_exercises` (id, session_id FK, name, normalized_name, sequence_index, started_at); `workout_sets` (id, exercise_id FK, sequence_index, weight_kg NUMERIC, reps INT, notes nullable). Índices: `(user_id, status)` parcial em session; `(normalized_name, user_id, ended_at DESC)` em exercise. FK opcional `activity_records.workout_session_id`. | T-B301 | Must Have (gate) |
| RF-012 | Componentes `compose_workout_*` em `message_formatter` (tabelas markdown em pt-BR, consistência com SP-118). | T-B305 | Should Have |
| RF-013 | Frontend `AssistantContent` renderiza destaque visual (peso PR em amber, série atual em verde); `WorkoutHistoryCard` no chat. | T-B308 | Could Have |

> **Status**: todas RF-[001..013] = `[Implementação não localizada]`. Apenas a referência pontual `workout_session: 'sessão de treino'` em `apps/web/src/app/(app)/day/types.ts:137` (dicionário `CALC_METHOD_LABEL_PT`, pré-inserido em antecipação).

## Requisitos não funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | **INV-11** — No máximo 1 `workout_sessions` por usuário com `status='active'`. Adicionar nova auto-encerra anterior (index parcial `(user_id, status='active')` para lookup rápido). | Integridade |
| RNF-002 | **INV-12** — Todo `workout_sets` pertence ao **último** `workout_exercises` da sessão ativa (por `sequence_index`). Não existe "adicionar série ao exercício X que já não é o último". | Integridade |
| RNF-003 | **INV-13** — `activity_record` gerado por SP-126 tem `calc_method='workout_session'` e **nunca** é criado por outro fluxo. Correção/deleção desse `activity_record` não afeta `workout_sessions/exercises/sets` (idem vice-versa: apagar séries não apaga o `activity_record` já gerado — consistência via recompute manual, fora do MVP). | Integridade |
| RNF-004 | INV-1 (LLM não calcula): kcal da atividade é determinístico (`met_estimate` no backend via MET × weight × horas); LLM só classifica `workout_type`, extrai `weight_kg`/`reps`/`exercise_name`. | Integridade (Art. II) |
| RNF-005 | INV-10 (auditoria total): mutações em `workout_*` gravam `audit_events` com `before/after/actor/message_id`. | Auditoria |
| RNF-006 | `user_id` em toda query de repositório (Art. V §21); isolamento por usuário. | Segurança |
| RNF-007 | ADR-011 adopt: `activity_record` continua fonte única de `kcal_out` no snapshot/semanal; `workout_*` só detalha. | Arquitetura |
| RNF-008 | Dias fechados imutáveis (Const. Art. VIII): sessões em dia `closed` não podem mutar; se sessão ficou órfã (usuário nunca encerrou e dia foi fechado sem SP-125), permanece órfã — aceito no MVP. | Integridade |
| RNF-009 | `WorkoutService` métodos autônomos (sem depender de `MessageProcessor`) — testáveis isoladamente (T-B303). | Testabilidade |
| RNF-010 | Ordem crítica em `_handle_close_day` (T-B306): encerrar sessão **antes** do recompute para o `activity_record` entrar no snapshot. | Corretude |
| RNF-011 | `end_session` com idempotência? — encerrar dia já fechado retorna snapshot atual sem regravar `closed_at` (Const. Art. VIII); não há reabertura no MVP. | Corretude |
| RNF-012 | Testes: `tests/test_workout.py` cobrindo SP-120..SP-127 + INV-11/12/13 (T-B307). Cobertura alvo ≥ 80% em `app/services/workout.py` (regra do MVP). | Qualidade |

## Restrições e premissas

- **SP-120..127 todos `may`** — pós-MVP; não blocante; desde v1.2 especificado, ainda sem implementação.
- **ADR-011 aceita** — append-only; não reescrever. Documenta coexistência `log_activity` + `workout_session`.
- **Coexistência por design**: cardio genérico (corrida/natação/caminhada) continua usando `log_activity` (SP-60..64); treino de força/musculação usa módulo novo.
- **MET fixo por `workout_type` é aproximado** — musculação varia muito com carga/descanso. Refinamento futuro ("volume total × densidade") fora do MVP.
- **Sessões órfãs aceitas** — se usuário nunca encerrar dia e sessão nunca recebe `end_reason`, fica `active` indefinidamente. MVP não reclama.
- **`weight_kg` do perfil** necessário pra kcal; sem ele, `activity_record` fica com `kcal_burned=NULL`.
- **Sem gráficos de distribuição nem exportação** fora desta feature.
- **Não substitui `/weekly` nem `/day`**: detalhamento fica em consultas do chat (SP-121/127) + preview no snapshot agregado.

## Dependências

**Depende de:**
- [`authentication-session`](../authentication-session/requirements.md) — `user_id` isolation; cookie auth.
- [`activity-cardio-logging`](../activity-cardio-logging/requirements.md) — `log_activity`/`activity_records` (coexistência ADR-011); regras `kcal_burned`/`met_value` no snapshot.
- [`daily-snapshot`](../daily-snapshot/requirements.md) — `day_log_id` FK; snapshot aggregate via `activity_record`.
- [`day-close`](../day-close/requirements.md) — `_handle_close_day` hook para SP-125.
- [`weekly-report`](../weekly-report/requirements.md) — le via `activity_record` consolidado.
- [`anthropic-integration`](../anthropic-integration/requirements.md) — `record_intent` tool schema (5 novos intents); prompt `system_v2.md` regra 19.
- [`chat-messaging`](../chat-messaging/requirements.md) — `MessageProcessor` handlers novos.
- [`record-correction`](../record-correction/requirements.md) / [`record-deletion`](../record-deletion/requirements.md) — INV-13: mutar `activity_record` não propaga.
- [`audit-trail`](../audit-trail/requirements.md) — INV-10 em mutações de `workout_*`.
- [`profile` features] — `weight_kg`/`height_cm` no `User` model (existentes) para kcal.

**Requerido por:**
- [`daily-detail-view`](../daily-detail-view/requirements.md) — `ActivitySection` já mapeia `calc_method='workout_session'` → "sessão de treino" em `CALC_METHOD_LABEL_PT` (preempt).
- [`weekly-report`](../weekly-report/requirements.md) — `activity_record` consolidado entra no semanal.