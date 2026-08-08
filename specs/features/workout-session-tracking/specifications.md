# Especificações Técnicas — Treino estruturado (Bloco 3)

> **Rastreabilidade**: SP-120..SP-127, INV-11/12/13 · ADR-011 (`research.md`) · Bloco 3 T-B301..T-B308 (`tasks.md`). Status: **`documented-only`** — toda seção referenciada como `[Implementação não localizada]`. Nenhum arquivo referenciado existe fisicamente.

## Escopo técnico

Adicionar módulo hierárquico de treino de força ao backend, sem alterar o contrato `activity_records` consumido por snapshot/semanal. Tudo o que está abaixo é **planejado (spec)**; nenhum dos arquivos fluxos referenciados está implementado.

## Interface — endpoints (planejado)

> Nenhum endpoint HTTP novo planejado — todos os intents são tratados pelo fluxo existente `POST /chat/messages` via `record_intent` tool. Consumer continua sendo o chat. Status: `[Implementação não localizada]`.

A interação acontece via `intent` enum estendido:

```text
POST /chat/messages
  { text: "iniciando treino de push", media_ids: [] }
  → MessageProcessor → IntentDispatcher → _handle_workout_start
```

A resposta é composta por `message_formatter.compose_workout_*` em markdown (consistência SP-118).

## Interface — schemas (planejado, `[Implementação não localizada]`)

`apps/api/app/schemas/llm.py` — novos payloads `_LenientBase`:

```py
class WorkoutStartIn(_LenientBase):
    workout_type: Literal["push","pull","legs","upper","lower","full_body","cardio","other"]
    detected_name: str | None

class WorkoutExerciseIn(_LenientBase):
    exercise_name: str

class WorkoutSetIn(_LenientBase):
    weight_kg: Decimal
    reps: int
    notes: str | None = None
    # multiplas series: backend cria N sets quando reps explicito
    # ("3x8 60 kg" → 3 sets iguais)

class WorkoutEndIn(_LenientBase):
    pass  # sem payload — só dispara end

class WorkoutHistoryQueryIn(_LenientBase):
    exercise_name: str
    # opcional: limit (default 3 últimas sessões)
```

`Intent` enum estendido com `workout_start`, `workout_add_exercise`, `workout_log_set`, `workout_end`, `workout_history`.

Tool schema `record_intent` (em `apps/api/app/integrations/anthropic/prompts/system_v2.md`) ganha regra 19 explicando os 5 intents.

## Interface — `WorkoutService` (planejado, `[Implementação não localizada]`)

`apps/api/app/services/workout.py`:

```py
class WorkoutService:
    async def start_session(self, user_id, day_log_id, workout_type, detected_name) -> WorkoutSession
    async def add_exercise(self, session_id, exercise_name) -> tuple[WorkoutExercise, HistoryContext]
    async def log_set(self, session_id, weight_kg, reps, notes=None) -> WorkoutSet
    async def end_session(self, session_id, end_reason: Literal["user", "auto_new_session", "auto_close_day"]) -> WorkoutSession
    async def consolidate_to_activity(self, session_id) -> ActivityRecord
    async def history(self, user_id, exercise_name, limit=3) -> HistoryContext
```

- `HistoryContext` inclui `last_session_date`, `last_sets`, `pr_weight_kg`, `pr_reps_at_pr`, `pr_date`, `first_time: bool`.
- Métodos autônomos (T-B303); `add_exercise`/`log_set`/`history` fazem fuzzy match em `normalized_name` (e.g., "supino reto" casa com "supino reto barra" e "supino reto halteres").
- `consolidate_to_activity` chamado por `end_session` (SP-124) e por `_handle_close_day` quando há sessão ativa (SP-125/SP-126).

## Modelo de dados

### Migration `0008_workout_tracking.py` (T-B301, `[Implementação não localizada]`)

```sql
CREATE TYPE workout_type AS ENUM ('push','pull','legs','upper','lower','full_body','cardio','other');
CREATE TYPE workout_session_status AS ENUM ('active','ended');
CREATE TYPE workout_end_reason AS ENUM ('user','auto_new_session','auto_close_day');

CREATE TABLE workout_sessions (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  day_log_id UUID NOT NULL REFERENCES day_logs(id),
  workout_type workout_type NOT NULL,
  detected_name TEXT,
  started_at TIMESTAMPTZ NOT NULL,
  ended_at TIMESTAMPTZ,
  status workout_session_status NOT NULL DEFAULT 'active',
  end_reason workout_end_reason,
  created_at/updated_at (TimestampMixin)
);
CREATE INDEX idx_workout_sessions_active ON workout_sessions(user_id) WHERE status = 'active';

CREATE TABLE workout_exercises (
  id UUID PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES workout_sessions(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  sequence_index INT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL,
  UNIQUE(session_id, sequence_index)
);
CREATE INDEX idx_workout_exercises_history ON workout_exercises(normalized_name, user_id_via_join, ended_at DESC);

CREATE TABLE workout_sets (
  id UUID PRIMARY KEY,
  exercise_id UUID NOT NULL REFERENCES workout_exercises(id) ON DELETE CASCADE,
  sequence_index INT NOT NULL,
  weight_kg NUMERIC(6,2) NOT NULL CHECK (weight_kg > 0),
  reps INT NOT NULL CHECK (reps > 0),
  notes TEXT,
  UNIQUE(exercise_id, sequence_index)
);

ALTER TABLE activity_records
  ADD COLUMN workout_session_id UUID REFERENCES workout_sessions(id);
  -- FK opcional: dado activity_record, achar a sessão original.
```

### Modelos SQLAlchemy (planejado, `[Implementação não localizada]`)

- `WorkoutSession(UUIDPrimaryKeyMixin, TimestampMixin, Base)` — tabela `workout_sessions`.
- `WorkoutExercise(UUIDPrimaryKeyMixin, Base)` — `session_id` FK + `sequence_index`.
- `WorkoutSet(UUIDPrimaryKeyMixin, Base)` — `exercise_id` FK + `weight_kg: Decimal(6,2)` + `reps: int`.
- `ActivityRecord.workout_session_id: Mapped[UUID|None]` adicionado por migration.

## Fluxo de dados

### Iniciar sessão (SP-120)
1. LLM detecta `intent=workout_start` com `workout_type` + `detected_name`.
2. `IntentDispatcher` roteia pra `_handle_workout_start` (T-B305).
3. `WorkoutService.start_session`:
   a. Query `(user_id, status='active')` — se existe, encerra (INV-11) com `end_reason='auto_new_session'`, chama `consolidate_to_activity` (SP-126) pro `activity_record` da sessão anterior entrar no snapshot (se mesmo `day_log`).
   b. Cria `day_log` se necessário; cria `workout_sessions` com `started_at=now()`, `workout_type`, `detected_name`.
4. `MessageProcessor` chama `compose_workout_start` (T-B305); assistant message: cabeçalho "Iniciei treino de push." + nota se fechou anterior.

### Adicionar exercício (SP-121)
1. LLM detecta `intent=workout_add_exercise` com `exercise_name`.
2. `_handle_workout_add_exercise` → `WorkoutService.add_exercise`:
   a. Valida sessão ativa (INV-11).
   b. `normalized_name` derivado de `exercise_name` (slug-like + sinônimos catalogados).
   c. `sequence_index = max+1` da sessão.
   d. Cria `workout_exercises`.
   e. Fuzzy lookup histórico por `(normalized_name, user_id, ended_at DESC)` → últimas 3 sessões + PR.
3. `compose_workout_add_exercise` monta:
   - "Adicionei supino reto com barra à sessão."
   - Histórico: "Última vez (28/07): 4×10@60, 4×8@65, 4×6@70. PR: 70 kg × 10 em 15/07/2026."
   - Ou "Primeira vez registrando esse exercício."

### Registrar série (SP-122)
1. LLM detecta `intent=workout_log_set` com `weight_kg`/`reps` (+ `notes`/`multiplier` se múltiplas séries).
2. `WorkoutService.log_set`:
   a. Acha **último** `workout_exercises` da sessão ativa (INV-12; nada de "adicionar ao exercício X que não é o último").
   b. `sequence_index = max+1`.
   c. Cria N sets iguais se payload indica múltiplas séries (e.g. "3×8 60 kg" → 3 sets).
3. `compose_workout_log_set`: "Série 3 registrada: 60 kg × 10 (última vez você fez 55 kg × 10)".

### Encerramento explícito (SP-124)
1. `intent=workout_end`.
2. `WorkoutService.end_session(end_reason='user')`:
   - Atualiza `status='ended'`, `ended_at=now()`.
   - Chama `consolidate_to_activity` (SP-126).
3. `compose_workout_end`: "Treino de push encerrado (58 min). 4 exercícios · 14 séries · ~380 kcal estimados." + tabela markdown com séries totais por exercício.

### Encerramento ao fechar dia (SP-125)
1. `_handle_close_day` (SP-100) detecta sessão ativa.
2. **Antes** do recompute: `WorkoutService.end_session(end_reason='auto_close_day')` + `consolidate_to_activity`.
3. Recompute do snapshot agora inclui o novo `activity_record`.
4. Geração da narrativa LLM do dia considera o treino.

### Histórico (SP-127)
1. `intent=workout_history` com `exercise_name`.
2. `WorkoutService.history` retorna últimas 3 sessões + PR — mesma estrutura de SP-121 sem criar novo registro.
3. `compose_workout_history` monta resposta tabular.

### `message_formatter.compose_workout_*` (T-B305)
Componentes análogos ao `compose_meal`/`compose_activity` (feature `assistant-message-rendering`):

- `compose_workout_start(session)` — cabeçalho + nota de encerramento anterior.
- `compose_workout_add_exercise(exercise, history)` — adição + bloco histórico/PR.
- `compose_workout_log_set(set, last_set)` — série + compara com última.
- `compose_workout_end(session, totals_table)` — resumo + tabela por exercício.
- `compose_workout_history(history_context)` — últimas 3 sessões + PR.

## Regras de negócio

1. **INV-11 — única sessão ativa**: `start_session` encerra anterior automaticamente se `status='active'`. Index `(user_id WHERE status='active')` para lookup rápido.
2. **INV-12 — set no último exercício**: `log_set` sempre atribui ao último `workout_exercises` da sessão ativa (por `sequence_index`).
3. **INV-13 — unlink bidirectional**: corrigir/deletar `activity_record` consolidado não afeta `workout_*`; vice-versa.
4. **MET fixo por tipo** (`push`/`pull`/`upper` → 5.0; `legs`/`lower` → 6.0; `full_body` → 5.5): `kcal = MET × weight_kg × (duration_min / 60)`.
5. **Sem `weight_kg` no perfil** → `activity_record.kcal_burned=NULL` + warning `weight_kg_required_for_kcal`.
6. **`normalized_name` fuzzy match** — sinonimos catalogs (ex.: "supino reto" == "supino reto barra" == "supino reto halteres"); implementação pendente.
7. **Múltiplas séries em 1 mensagem** ("3×8 60 kg") → backend cria 3 workouts iguais sem LLM re-invocar.
8. **Parser pt-BR pela LLM** (backend só valida): "20 kg da barra + 20 kg de cada lado" → 60; "só a barra" → 20; se ambíguo → `clarify`, sem set criado.
9. **Sessão órfã possível** se `close_day` não dispara SP-125 (e.g., user nunca encerra; dia nunca fecha). Aceito no MVP.
10. **Audit gravado em toda mutação** (`workout_sessions`/`exercises`/`sets`) com `before`/`after`/`actor`/`message_id` (INV-10).
11. **`user_id` em toda query** (Art. V §21).
12. **Dia fechado imutável** (Const. VIII): sessão em `day_log` com `status='closed'` não pode mutar; se sessão `active` em dia `closed`, permanece órfã (MVP não reclama).

## Configurações e variáveis de ambiente

| Variável | Descrição | Padrão | Obrigatória |
|---|---|---|---|
| `DEFAULT_OLYMPIC_BAR_KG` | Peso default da barra olímpica para "só a barra" parser | `20` | Não (hardcoded seletivo) |

Sem variáveis específicas planejadas (tudo via constants no `workout.py` e prompt `system_v2.md`). `[Implementação não localizada]`.

## Referências de implementação

- **Spec (fonte primária)**: `specs/001-mvp-registro-diario/spec.md` §3.13 "Registro estruturado de treino" (linhas ~366-433).
- **ADR**: `specs/001-mvp-registro-diario/research.md::ADR-011` (aceita 2026-07-26).
- **Tasks**: `specs/001-mvp-registro-diario/tasks.md:256-271` Bloco 3 (T-B301..T-B308).
- **Arquivos planejados ainda não existem**:
  - Migration: `apps/api/alembic/versions/0008_workout_tracking.py`
  - Modelos: `apps/api/app/models/workout.py` (3 modelos)
  - Schemas: `apps/api/app/schemas/llm.py` (5 novos payloads)
  - Service: `apps/api/app/services/workout.py` (`WorkoutService`)
  - Handlers: `apps/api/app/services/message_processor.py` (5 novos `_handle_workout_*`)
  - Formatter: `apps/api/app/services/message_formatter.py` (5 novos `compose_workout_*`)
  - Intent dispatcher: `apps/api/app/services/intent_dispatcher.py` (roteia 5 intents fora de `_STRUCTURED_INTENTS`)
  - Prompt: `apps/api/app/integrations/anthropic/prompts/system_v2.md` (regra 19)
  - Tests: `apps/api/tests/test_workout.py`
- **Antecipação já presente**: `apps/web/src/app/(app)/day/types.ts:137` — `CALC_METHOD_LABEL_PT['workout_session'] = 'sessão de treino'` (pré-inserido quando `ActivitySection` SP-153 foi feito).
- **Coexistência**: `apps/api/app/services/activity.py` (feature `activity-cardio-logging`, `/log_activity` intocado).
- **Consolidação**: `apps/web/src/app/(app)/day/AuxiliarySections.tsx::ActivitySection` já renderiza `activity_record.workout_session_id` se `calc_method='workout_session'` (já mapeia label pt-BR).