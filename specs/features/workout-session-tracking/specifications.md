# Especificações Técnicas — Módulo de Treino (Workout Module)

> **Rastreabilidade**: SP-120..SP-127, INV-15/16/17 · ADR-011 (`research.md`) · Bloco 3 (T-B301..T-B308) em [`tasks.md`](../../001-mvp-registro-diario/tasks.md) · Expansão do cliente (SP-170..179 propostos), 2026-08-14. Status: **`documented-only`** — núcleo `[Implementação não localizada]`; módulo `[Proposta — requer spec: PR]`.

## Escopo técnico

Adicionar **módulo de treino** de ponta a ponta:
1. **Núcleo hierárquico** (sessão → exercício → séries) com consolidação em `activity_record` (ADR-011) — inalterado.
2. **`workout_templates`** — treinos reutilizáveis cadastrados por texto (RF-015) com status `active` (RF-016) e exercícios-alvo.
3. **Chat de treino dedicado** (`/workouts/chat`) espelhando o chat de alimentação, com header de atividades do dia + kcal gastas e botões "Cadastrar treino"/"Iniciar treino"/"Finalizar treino" (RF-018/019).
4. **Fluxo guiado** de execução (RF-020) com cronômetro (RF-021) e tempo registrado.
5. **Registro por imagem** (RF-022) extraindo título/atividade/intensidade/kcal.
6. **Edição** de peso/séries/kcal via chat e `/day` (RF-023).
7. **Seção de treinos no `/day`** (RF-024) e **histórico paginado** em `/workouts` (RF-017).

## Interface — endpoints (planejado)

> Chat de treino reusa `POST /chat/messages` (mesmo pipeline, novo espaço de contexto). Endpoints novos abaixo (propostos). Status: núcleo `[Implementação não localizada]`, módulo `[Proposta]`.

```text
# Núcleo (já desenhado em SP-120..127)
POST /chat/messages
  { text: "iniciando treino de push", media_ids: [] }
  → MessageProcessor → IntentDispatcher → _handle_workout_start

# Chat de treino — mesma rota e mesmo pool de messages, filtrando por via
POST /chat/messages
  { text: "…", media_ids: [...], via: "workout" }   # messages.via='workout'

# Módulo — templates
GET    /workouts/templates?active=true&page=1&page_size=20   # listagem (abas Ativos/Inativos)
POST   /workouts/templates                      # (opcional; preferência: criar via chat/texto LLM)
PATCH  /workouts/templates/{id}                 # toggle active (RF-016), nome, agrupamento
GET    /workouts/templates/{id}/exercises       # exercícios-alvo do template

# Módulo — histórico paginado
GET    /workouts/history?page=1&page_size=20&from=&to=   # log de sessões finalizadas (RF-017)

# Módulo — edição de sets/kcal (RF-023) via chat e /day
PATCH  /records/workout-sets/{id}              # weight_kg, reps, notes (INV-16, INV-20)
PATCH  /records/workout-sessions/{id}          # kcal_burned_reported, duration_minutes

# Dias — seção de treinos (RF-024) via snapshot existente ou endpoint específico
GET /days/{date}/records   # já existe; inclui activity_records consolidados da sessão
```

> **Nota**: chat de treino usa o mesmo pool de `messages` com a coluna `via` (`'food'` default / `'workout'`); `GET /chat/messages` e `MessageProcessor` filtram por `via` e o prompt é selecionado a partir dela (decisão 2026-08-14). `GET /chat/messages?after=` já suporta polling incremental.

## Interface — schemas (planejado)

`apps/api/app/schemas/llm.py` — payloads núcleo (`[Implementação não localizada]`):

```py
class WorkoutStartIn(_LenientBase):
    workout_type: Literal["push","pull","legs","upper","lower","full_body","cardio","other"]
    detected_name: str | None
    template_id: UUID | None = None      # NOVO: fluxo guiado (RF-020)

class WorkoutExerciseIn(_LenientBase):
    exercise_name: str

class WorkoutSetIn(_LenientBase):
    weight_kg: Decimal | None             # None → DEFAULT_OLYMPIC_BAR_KG
    reps: int
    notes: str | None = None

class WorkoutEndIn(_LenientBase):
    pass

class WorkoutHistoryQueryIn(_LenientBase):
    exercise_name: str
```

Novos payloads de módulo (`[Proposta]`):

```py
class WorkoutTemplateIn(_LenientBase):      # RF-015 — cadastro por texto
    name: str
    workout_type: Literal["musculacao","forca","lpo","cardio","funcional","outro"]
    muscle_groups: list[str] | None = None  # ["peito","ombro","triceps"] para musculação
    exercises: list[WorkoutTemplateExerciseIn] | None = None  # nome + target sets/reps

class WorkoutTemplateExerciseIn(_LenientBase):
    exercise_name: str
    target_sets: int | None = None
    target_reps: int | None = None

class WorkoutImageIn(_LenientBase):         # RF-022 — extração de imagem
    title: str | None = None                # título da atividade
    activity_type: str | None = None        # ex. strength/cardio/bike
    intensity: Literal["light","moderate","vigorous","unknown"] | None = None
    kcal_burned_reported: Decimal | None = None  # calorias gastas (se visível na imagem)

class WorkoutCorrectSetIn(_LenientBase):    # RF-023
    set_id: UUID
    weight_kg: Decimal | None
    reps: int | None
    notes: str | None = None
```

`Intent` enum estendido (núcleo) com `workout_start`, `workout_add_exercise`, `workout_log_set`, `workout_end`, `workout_history` + propostos: `workout_register` (cadastrar template), `workout_next_exercise`, `workout_correct`, `workout_image`. Tool schema `record_intent` estendido (regra 19 + novas regras no `system_v2.md`).

## Interface — `WorkoutService` (planejado)

`apps/api/app/services/workout.py`:

```py
class WorkoutService:
    async def start_session(self, user_id, day_log_id, workout_type, detected_name=None, template_id=None) -> WorkoutSession
    async def add_exercise(self, session_id, exercise_name) -> tuple[WorkoutExercise, HistoryContext]
    async def log_set(self, session_id, weight_kg, reps, notes=None) -> WorkoutSet
    async def end_session(self, session_id, end_reason: Literal["user","auto_new_session","auto_close_day"]) -> WorkoutSession
    async def consolidate_to_activity(self, session_id) -> ActivityRecord
    async def history(self, user_id, exercise_name, limit=3) -> HistoryContext

    # Módulo (propostos)
    async def register_template(self, user_id, payload: WorkoutTemplateIn) -> WorkoutTemplate   # RF-015
    async def list_templates(self, user_id, active: bool | None, page, page_size) -> Page[WorkoutTemplate]  # RF-014/016/017
    async def set_template_active(self, template_id, active) -> WorkoutTemplate                  # RF-016
    async def history_paginated(self, user_id, page, page_size, from_, to_) -> Page[WorkoutHistoryItem]  # RF-017
    async def correct_set(self, set_id, weight_kg, reps, notes) -> WorkoutSet                    # RF-023
    async def set_reported_kcal(self, session_id, kcal_burned_reported) -> WorkoutSession        # RF-022/023
    async def next_exercise_prompt(self, session_id) -> list[WorkoutExercise]                    # RF-020
```

- `HistoryContext` inclui `last_session_date`, `last_sets`, `pr_weight_kg`, `pr_reps_at_pr`, `pr_date`, `first_time: bool`.
- `consolidate_to_activity`: se `session.kcal_burned_reported` existe → usa o valor (INV-21, `met_value=NULL`); senão MET fixo por `workout_type` × `weight_kg` × horas.
- `register_template` gera `created_at` (= data de cadastro, RF-015) e exercícios-alvo derivados do texto/imagem.

## Modelo de dados

### Migration núcleo `0008_workout_tracking.py` (T-B301, `[Implementação não localizada]`)

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
  kcal_burned_reported NUMERIC(10,2),          -- NOVO (RF-022/023): valor informado p/ o usuário/texto/imagem
  template_id UUID,                            -- NOVO (RF-020): FK workout_templates SET NULL
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

ALTER TABLE messages
  ADD COLUMN via TEXT NOT NULL DEFAULT 'food';   -- via='workout' p/ chat de treino (decisão 2026-08-14)
CREATE INDEX idx_messages_user_via ON messages(user_id, via, created_at);
```

### Migration módulo `0011_workout_templates.py` (proposto, RF-014..017)

```sql
CREATE TYPE template_kind AS ENUM ('musculacao','forca','lpo','cardio','funcional','outro');

CREATE TABLE workout_templates (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  name TEXT NOT NULL,
  kind template_kind NOT NULL,
  muscle_groups TEXT[],                        -- ["peito","ombro","triceps"] p/ musculação
  active BOOLEAN NOT NULL DEFAULT true,        -- RF-016
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),  -- data de cadastro (RF-015)
  updated_at TIMESTAMPTZ
);
CREATE INDEX idx_workout_templates_user_active ON workout_templates(user_id, active);

CREATE TABLE workout_template_exercises (
  id UUID PRIMARY KEY,
  template_id UUID NOT NULL REFERENCES workout_templates(id) ON DELETE CASCADE,
  exercise_name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  target_sets INT,                             -- ex. 4
  target_reps INT,                             -- ex. 8
  sequence_index INT NOT NULL,
  UNIQUE(template_id, sequence_index)
);
```

> **INV-20**: `workout_sessions.template_id` referencia o template no momento do exercício; inativar template não apaga nem altera sessões finalizadas.

## Fluxo de dados

### Iniciar sessão (SP-120) / fluxo guiado (RF-020)

**Fluxo livre (canônico):**
1. LLM detecta `intent=workout_start` com `workout_type` + `detected_name`.
2. `WorkoutService.start_session`: auto-encerra anterior (INV-15) + `consolidate_to_activity`.
3. `compose_workout_start` → cabeçalho + nota de encerramento anterior.

**Fluxo guiado (proposto, RF-020):**
1. Botão "Iniciar treino" → frontend chama `GET /workouts/templates?active=true` → lista como botões.
2. Usuário escolhe template → frontend envia `POST /chat/messages` com texto estruturado do template (ou novo intent `workout_start` com `template_id`).
3. `start_session(template_id=…)` cria sessão; `compose_workout_start` lista **todos os exercícios** do template como botões.
4. Usuário clica num exercício → `workout_add_exercise` → histórico da última realização (cargas/reps) + lista séries passadas.
5. Usuário envia "carga × reps" → `workout_log_set` → confirmação + recaptula último treino + botão "Ir para o próximo exercício" (RF-020).
6. Botão → repete passo 4/5. "Finalizar treino" → `workout_end`.

### Registrar série (SP-122)
Idêntico ao canônico; INV-16 garante atribuição ao último exercício. NOVO `WorkoutCorrectSetIn` para edição (RF-023) — revalida INV-20 e reconsolida se sessão encerrada.

### Encerramento explícito (SP-124) + cronômetro (RF-021)
1. "Finalizar treino" (botão) ou `intent=workout_end` (texto).
2. Cronômetro é **parado** no frontend; `duration_minutes = ended_at - started_at`.
3. `consolidate_to_activity` cria `activity_record` com kcal reportada (INV-21) **ou** MET.
4. `compose_workout_end`: "Treino concluído (58 min). 4 exercícios · 14 séries · 380 kcal." + tabela.

### Encerramento ao fechar dia (SP-125)
Inalterado — `_handle_close_day` encerra sessão ativa **antes** do recompute.

### Cadastro de template (RF-015, proposto)
1. Botão "Cadastrar treino" → assistant envia **template de exemplo** (tipo, agrupamento muscular, séries/reps).
2. Usuário envia texto do treino (pode incluir imagem) → LLM extrai `WorkoutTemplateIn`.
3. `WorkoutService.register_template` → cria `workout_templates` + exercícios-alvo com `created_at=now()`.
4. Assistant confirma com nome do treino, agrupamento e nº de exercícios.

### Registro por imagem (RF-022, proposto)
1. Usuário anexa imagem ao mandar mensagem no chat de treino (mesmo `POST /media` + `media_ids`).
2. LLM (Sonnet, já para image) extrai `WorkoutImageIn`: título, atividade, intensidade, kcal.
3. Se representa atividade pontual → `workout_start`+`workout_end` seqüenciais (sessão curta) OU `log_activity` com `kcal_burned_reported`. Se descreve treino completo → `register_template`.
4. Assistant confirma com título/intensidade/kcal.

### Edição via `/day` (RF-023/024, proposto)
- Nova `WorkoutSection` em `AuxiliarySections.tsx` (padrão `ActivitySection`): lista treinos do dia com nome, duração, kcal.
- Formulário inline (padrão `EditActivityForm`): edita `weight_kg`/`reps` por set (PATCH `/records/workout-sets/{id}`) e `kcal_burned_reported` da sessão (PATCH `/records/workout-sessions/{id}`).

## Regras de negócio

1. **INV-15** — única sessão ativa por usuário; `start_session` encerra anterior.
2. **INV-16** — `log_set` sempre no último `workout_exercises` da sessão ativa.
3. **INV-17** — unlink bidirecional `workout_*` ↔ `activity_record`.
4. **INV-18** — templates sempre filtrados por `user_id`.
5. **INV-19** — `active=false` fora do fluxo guiado e da aba *Ativos*; histórico preservado.
6. **INV-20** — edição de set/sessão reconsolida `activity_record` de sessão encerrada; template inativado não muta sessões finalizadas.
7. **INV-21** — kcal: `kcal_burned_reported` (usuário/texto/imagem) é fonte; senão MET fixo por `workout_type`.
8. **MET fixo por tipo**: `push`/`pull`/`upper` → 5.0; `legs`/`lower` → 6.0; `full_body` → 5.5; `cardio` → tabela `ActivityCalculator`.
9. **Sem `weight_kg` no perfil** nem kcal reportado → `activity_record.kcal_burned=NULL` + warning `weight_kg_required_for_kcal`.
10. **`normalized_name` fuzzy match** — sinônimos catalogados.
11. **Múltiplas séries em 1 mensagem** ("3×8 60 kg") → N sets sem re-invocar LLM.
12. **Parser pt-BR pela LLM** (backend só valida `>0`); ambíguo → `clarify`.
13. **Sessão órfã possível** se `close_day` não dispara SP-125 — aceito no MVP.
14. **Audit gravado em toda mutação** (`workout_templates`/`sessions`/`exercises`/`sets`) com `before`/`after`/`actor`/`message_id` (INV-10).
15. **`user_id` em toda query** (Art. V §21).
16. **Dia fechado imutável** (Const. VIII): mutações em `workout_*` em `status='closed'` → 409 `conflict_closed_day`.
17. **Prompt do chat de treino**: contexto/instruções específicas (não misturar intents de alimentação); wrapper de espaço `workout_chat`.

## Configurações e variáveis de ambiente

| Variável | Descrição | Padrão | Obrigatória |
|---|---|---|---|
| `DEFAULT_OLYMPIC_BAR_KG` | Peso default da barra olímpica para "só a barra" | `20` | Não |
| `WORKOUT_HISTORY_PAGE_SIZE` | Tamanho de página do histórico paginado | `20` | Não |
| `WORKOUT_CHAT_ENABLED` | Liga o espaço de chat de treino dedicado | `false` (flag) | Não |

Sem variáveis específicas planejadas no núcleo (constants em `workout.py` + prompt `system_v2.md`).

## Referências de implementação

- **Spec (núcleo)**: `specs/001-mvp-registro-diario/spec.md` §3.13 (linhas ~366-434).
- **Spec (módulo, proposta)**: esta pasta — RF-014..024 → SP-170..179 (requer `spec:` PR).
- **ADR**: `specs/001-mvp-registro-diario/research.md::ADR-011`.
- **Tasks**: `specs/001-mvp-registro-diario/tasks.md:256-271` (Bloco 3 T-B301..T-B308).
- **Arquivos planejados ainda não existem**:
  - Migration: `apps/api/alembic/versions/0008_workout_tracking.py` (núcleo) e `0011_workout_templates.py` (módulo).
  - Modelos: `apps/api/app/models/workout.py` (5 modelos: Template, TemplateExercise, Session, Exercise, Set) + `apps/api/app/models/workout_templates.py`.
  - Schemas: `apps/api/app/schemas/llm.py` (payloads núcleo + `WorkoutTemplateIn`/`WorkoutImageIn`/`WorkoutCorrectSetIn`) + schemas Pydantic de módulo.
  - Service: `apps/api/app/services/workout.py` (`WorkoutService` estendido).
  - Repository: `apps/api/app/repositories/workout.py` (queries `user_id`-scoped, INV-18).
  - Handlers: `apps/api/app/services/message_processor.py` (intents de treino + módulo).
  - Formatter: `apps/api/app/services/message_formatter.py` (`compose_workout_*` + mensagens de template/exemplo).
  - Intent dispatcher: `apps/api/app/services/intent_dispatcher.py`.
  - Prompt: `apps/api/app/integrations/anthropic/prompts/system_v2.md` (regra 19 + regras de template/imagem).
  - Rotas: `apps/api/app/api/routes/workouts.py` (templates + histórico paginado) + PATCH de sets/sessões em `records.py`.
  - Tests: `apps/api/tests/test_workout.py`.
- **Frontend planejado (módulo)**:
  - `apps/web/src/app/(app)/workouts/page.tsx` — 3 abas (RF-014/016/017).
  - `apps/web/src/app/(app)/workouts/chat/page.tsx` — chat de treino (RF-018/019/020, espelha `(app)/chat/page.tsx`).
  - `apps/web/src/app/(app)/workouts/WorkoutTotalsHeader.tsx` — header de atividades do dia + kcal (variante `DayTotalsBar`).
  - `apps/web/src/app/(app)/workouts/Stopwatch.tsx` — cronômetro (RF-021).
  - `apps/web/src/app/(app)/workouts/WorkoutTemplateList.tsx` / `ExercisePicker.tsx` — botões de seleção (RF-020).
  - `apps/web/src/app/(app)/day/AuxiliarySections.tsx::WorkoutSection` — seção de treinos do dia (RF-024).
  - `apps/web/src/app/(app)/day/edit-forms.tsx::EditWorkoutSetForm`/`EditWorkoutSessionForm` — edição inline (RF-023).
  - `apps/web/src/proxy.ts` — adicionar `/workouts` a `PROTECTED_PREFIXES` + `matcher`.
- **Antecipação já presente**: `apps/web/src/app/(app)/day/types.ts:142` — `CALC_METHOD_LABEL_PT['workout_session'] = 'sessão de treino'` (pré-inserido em Bloco 6) e `ActivitySection` já renderiza `activity_record.workout_session_id` se `calc_method='workout_session'` (SP-153).
- **Coexistência**: `app/services/activity.py` (`/log_activity` intocado).