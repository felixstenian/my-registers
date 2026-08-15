# Requisitos — Módulo de Treino (Workout Module)

> **Rastreabilidade**: SP-120..SP-127 + INV-15/16/17 em [`specs/001-mvp-registro-diario/spec.md`](../../001-mvp-registro-diario/spec.md#312-registro-estruturado-de-treino) · ADR-011 em [`research.md`](../../001-mvp-registro-diario/research.md) · Bloco 3 (T-B301..T-B308) em [`tasks.md`](../../001-mvp-registro-diario/tasks.md).
> **Expansão do cliente (2026-08-14)**: workout vira **módulo** com chat próprio, tela `/workouts` (abas ativos/inativos/histórico), cadastro de treinos por texto/seguindo template, fluxo guiado de execução, registro por imagem, edição de peso/séries/kcal e seção de treinos no `/day`. Novos SP propostos (SP-170..SP-179) abaixo — **exigem `spec:` PR** na spec canônica para entrar; esta pasta é a visão por feature.
> Status: **`documented-only`** — spec aceita + expansão solicitada; implementação **pendente**. Não há `WorkoutService`, schemas, migration, intents nem handlers no `apps/api`/`apps/web`.

## Visão geral

Módulo hierárquico de treino (`workout_templates` → exercícios-alvo → `workout_sessions` → `workout_exercises` → `workout_sets`) que coexiste com `log_activity` (cardio genérico) via **consolidação em `activity_record`** no encerramento da sessão (SP-126, ADR-011). Mantém snapshot diário / relatório semanal agnósticos (continuam lendo só `activity_records`). Estado conversacional vive no banco (sessão ativa + último exercício/última série); LLM consulta a cada mensagem. **Dois fluxos de entrada no chat de treino: (a) cadastrar templates reutilizáveis e (b) executar um treino guiado** — ambos trackeados na mesma estrutura de sessões. Histórico contextual por `normalized_name` fuzzy match (SP-121/SP-127) com PR pessoal. Registro por **imagem** extrai título/atividade/intensidade/kcal.

## Requisitos funcionais

**Núcleo — sessão estruturada (canônico, SP-120..127):**

| ID | Requisito | SP | Prioridade |
|---|---|---|---|
| RF-001 | `intent=workout_start` cria `workout_sessions` com `started_at=now()`, `status='active'`, `workout_type` enum canônico (`push`/`pull`/`legs`/`upper`/`lower`/`full_body`/`cardio`/`other`), `detected_name` livre. Se já existe sessão ativa, auto-encerra anterior (`end_reason='auto_new_session'`, INV-15). Assistant avisa + resumo curto. | SP-120 | May Have |
| RF-002 | `intent=workout_add_exercise` com `exercise_name` cria `workout_exercises` ligado à sessão ativa, `sequence_index` auto, `normalized_name` para lookup. Backend consulta histórico (última sessão com o exercício + todas as séries) e PR (maior peso × maior reps naquele peso, com data). "Primeira vez" se não há histórico. | SP-121 | May Have |
| RF-003 | `intent=workout_log_set` com `weight_kg`, `reps` (opcionalmente `notes`) cria `workout_sets` ligado ao **último** exercício da sessão ativa (INV-16) com `sequence_index` auto. Parser pt-BR pela LLM ("20 kg da barra + 20 kg de cada lado" → 60; "só a barra" → 20 default). Múltiplas séries em 1 mensagem ("3×8 60 kg" → 3 sets). Ambiguidade → `clarify`, nenhum set criado. | SP-122 | May Have |
| RF-004 | Adicionar exercício B encerra implicitamente o exercício A. Séries subsequentes ligam-se a B. | SP-123 | May Have |
| RF-005 | `intent=workout_end` marca `status='ended'`, `ended_at=now()`, `end_reason='user'`. Dispara SP-126 (consolidação). Assistant devolve resumo ("Treino de push encerrado (58 min). 4 exercícios · 14 séries · ~380 kcal") + tabela markdown. | SP-124 | May Have |
| RF-006 | `_handle_close_day` (SP-100) encerra sessão ativa **antes** do recompute com `end_reason='auto_close_day'`, dispara SP-126 para o `activity_record` aparecer no snapshot do dia. | SP-125 | May Have |
| RF-007 | `WorkoutService.consolidate_to_activity`: calcula `duration_minutes = ended_at - started_at`, `kcal_burned` via **MET fixo por `workout_type`** (`push`/`pull`/`upper` → 5.0; `legs`/`lower` → 6.0; `full_body` → 5.5) × `weight_kg` (perfil) × horas — **ou** via `kcal_burned_reported` quando o usuário informou o valor (texto/imagem/edição — INV-21). Cria 1 `activity_record` com `activity_type='strength'`, `calc_method='workout_session'`, `met_value` usado (ou `NULL` se reportado), `detected_name="Treino de {workout_type}"` ou nome livre, `notes=JSON` com IDs de exercícios/séries. | SP-126, INV-17 | May Have |
| RF-008 | Se usuário sem `weight_kg` no perfil **e** sem kcal reportado, `activity_record` é criado com `kcal_burned=NULL` + warning `weight_kg_required_for_kcal` (treino persistido, kcal pendente). | SP-126 | May Have |
| RF-009 | `intent=workout_history` com `exercise_name`: backend responde últimas 3 sessões que continham o exercício + PR pessoal (mesmo formato do SP-121 sem criar registro). `exercise_name` ausente → `clarify`. | SP-127 | May Have |
| RF-010 | `Intent` enum estendido (núcleo) com `workout_start`/`workout_add_exercise`/`workout_log_set`/`workout_end`/`workout_history`. Payloads Pydantic `_LenientBase` (`WorkoutStartIn`, etc.). Tool schema `record_intent` estendido. Prompt `system_v2.md` ganha regra 19. | T-B302 | Must Have (gate) |
| RF-011 | Schema das tabelas núcleo: `workout_sessions` (com `kcal_burned_reported` + `template_id` FK opcional), `workout_exercises`, `workout_sets`. Índices `(user_id, status)` parcial em session; `(normalized_name, user_id, ended_at DESC)` em exercise. FK opcional `activity_records.workout_session_id`. | T-B301 | Must Have (gate) |
| RF-012 | Componentes `compose_workout_*` em `message_formatter` (tabelas markdown em pt-BR, consistência com SP-118). | T-B305 | Should Have |
| RF-013 | Frontend `AssistantContent` renderiza destaque visual (peso PR em amber, série atual em verde); `WorkoutHistoryCard` no chat. | T-B308 | Could Have |

**Módulo Workouts — templates, chat dedicado, /workouts e /day (proposto SP-170..SP-179):**

| ID | Requisito | SP (proposto) | Prioridade |
|---|---|---|---|
| RF-014 | **Módulo Workouts**: nova rota `/workouts` protegida com 3 abas — *Ativos*, *Inativos*, *Histórico*. Adiciona `/workouts` e `/workouts/chat` a `PROTECTED_PREFIXES`/`matcher` do `proxy.ts`. | SP-170 | Must Have (gate) |
| RF-015 | **Cadastro de treino reutilizável por texto**: botão "Cadastrar treino" no chat de treino → assistant envia mensagem amigável com **template de exemplo** de como escrever o treino: tipo (ex. `Musculação`/`Força`/`LPO`), agrupamento muscular para musculação (ex. `Peito + ombro + triceps`) e séries/repetições por exercício. Após o usuário enviar o texto, LLM lê e **cadastra o treino** (novo `workout_templates` com `created_at` = data de cadastro). | SP-171 | Must Have (gate) |
| RF-016 | **Status ativo/inativo**: cada treino criado nasce `active=true`. Usuário pode **inativar/reativar** na listagem `/workouts` (toggle via PATCH). Aba *Ativos* lista só `active=true`; aba *Inativos* lista `active=false`. `active=false` fica **fora** da seleção do fluxo "Iniciar treino" (INV-19). | SP-172 | Must Have (gate) |
| RF-017 | **Histórico de treinos (log) com paginação**: aba *Histórico* lista sessões finalizadas — nome da atividade, data, hora inicial (se houver), calorias gastas; para musculação/variantes com carga inclui cargas, séries e repetições por exercício. Paginação (cursor `offset`/`limit` ou `page`); total determinístico. | SP-177 | Must Have (gate) |
| RF-018 | **Chat de treino dedicado** seguindo **exatamente o padrão do chat de alimentação** (composer + upload de mídia + polling `GET /chat/messages?after=`, `AssistantContent`, resposta pt-BR) no **mesmo pool de `messages` com `messages.via='workout'`** (filtro por `via`; default `'food'`; prompt selecionado pela `via`). **Header**: exibe as **atividades realizadas no dia e as calorias gastas** (variante do `DayTotalsBar` com foco em atividades). | SP-173 | Must Have (gate) |
| RF-019 | **Botões do header do chat de treino**: no lugar do botão "Encerrar dia", dois botões — **"Cadastrar treino"** e **"Iniciar treino"**. Quando há treino iniciado, o botão da direita vira **"Finalizar treino"** (mesma posição; lógica: sessão ativa → botão conclui aquele treino). Encerrar dia continua disponível (modal/chat de alimentação). | SP-173 | Must Have (gate) |
| RF-020 | **Fluxo guiado "Iniciar treino"**: botão busca `workout_templates` com `active=true` e lista como **botões**; ao escolher, chat lista **todos os exercícios** do template (também botões); ao escolher um exercício, chat busca no histórico a **última realização** daquele exercício e lista **cargas por série e repetições** realizadas. O usuário conclui séries enviando texto com carga e repetições (registrado via `workout_log_set`). **A partir da primeira série**, o chat sempre confirma o registro e **recapitula o último treino realizado** + exibe botão **"Ir para o próximo exercício"** → lista exercícios de novo e repete a sequência. | SP-178 | Must Have (gate) |
| RF-021 | **Cronômetro**: ao iniciar treino, exibir cronômetro na tela; **parado ao encerrar** (via "Finalizar treino" do botão ou texto no chat). **Tempo do treino registrado** (`duration_minutes` da sessão, SP-126). | SP-179 | Must Have (gate) |
| RF-022 | **Registro por imagem**: usuário envia imagem com atividade realizada; LLM extrai da imagem **título**, **atividade**, **intensidade** (se houver) e **calorias gastas durante a atividade** (se houver). Sem imagem, extrai do texto. Cria sessão/registro com `kcal_burned_reported` quando o usuário trouxe o valor (INV-21). | SP-174 | Must Have (gate) |
| RF-023 | **Edição de peso, séries e calorias gastas** — (a) via **chat de treino** (intent `workout_correct` sobre `workout_sets`/sessão) e (b) via **resumo do dia `/day`** (formulários inline na nova seção de treinos, espelhando `EditActivityForm`); mutação respeita dia fechado (409) e grava `audit_events`. | SP-175 | Must Have (gate) |
| RF-024 | **Seção de treinos no `/day`**: novo bloco "Treinos" listando os treinos realizados naquele dia (nome, duração, kcal gastas; para força, exercícios com cargas/séries/reps). **Calorias gastas** dos treinos entram no resumo do dia sempre que houver (reportadas ou consolidadas). | SP-176 | Should Have |

> **Status**: RF-001..013 = `[Implementação não localizada]` (núcleo canônico). RF-014..024 = `[Proposta — requer spec: PR na canônica]`. Apenas referência pontual `workout_session: 'sessão de treino'` em `apps/web/src/app/(app)/day/types.ts:142` (dicionário `CALC_METHOD_LABEL_PT`, pré-inserido).

## Requisitos não funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | **INV-15** — No máximo 1 `workout_sessions` por usuário com `status='active'`. Adicionar nova auto-encerra anterior (index parcial `(user_id, status='active')`). | Integridade |
| RNF-002 | **INV-16** — Todo `workout_sets` pertence ao **último** `workout_exercises` da sessão ativa (por `sequence_index`). | Integridade |
| RNF-003 | **INV-17** — `activity_record` gerado por SP-126 tem `calc_method='workout_session'` e **nunca** é criado por outro fluxo. Correção/deleção dele não afeta `workout_*` (idem vice-versa — consistência via recompute manual, fora do MVP). | Integridade |
| RNF-004 | INV-1 / Art. II (LLM não calcula): kcal é determinística no backend (`met_estimate` via MET × weight × horas ou `kcal_burned_reported` persistido pelo usuário/texto/imagem); LLM só classifica `workout_type`, extrai `weight_kg`/`reps`/`exercise_name` e campos de imagem. | Integridade (Art. II) |
| RNF-005 | INV-10 (auditoria total): mutações em `workout_templates`/`workout_*` gravam `audit_events` com `before/after/actor/message_id`. | Auditoria |
| RNF-006 | `user_id` em toda query de repositório (Art. V §21); isolamento por usuário. | Segurança |
| RNF-007 | ADR-011 adopt: `activity_record` continua fonte única de `kcal_out` no snapshot/semanal; `workout_*` só detalha. | Arquitetura |
| RNF-008 | Dias fechados imutáveis (Const. Art. VIII): sessões em dia `closed` não podem mutar. | Integridade |
| RNF-009 | `WorkoutService` métodos autônomos (sem depender de `MessageProcessor`) — testáveis isoladamente (T-B303). | Testabilidade |
| RNF-010 | Ordem crítica em `_handle_close_day` (T-B306): encerrar sessão **antes** do recompute para o `activity_record` entrar no snapshot. | Corretude |
| RNF-011 | **INV-18** — `workout_templates` sempre filtrados por `user_id`; nunca existe query de template sem isolamento. | Segurança |
| RNF-012 | **INV-19** — Template `active=false` não aparece na aba *Ativos* nem no seletor do fluxo guiado; sessões já finalizadas permanecem no histórico independente do status do template. | Integridade |
| RNF-013 | **INV-20** — Sessão guiada referencia o template escolhido (`workout_sessions.template_id`); inativar/alterar template **não** afeta sessões finalizadas (snapshot congelado). Edição de weight/reps/kcal em set/registro atualiza a sessão e, se a sessão está encerrada, reconsolida o `activity_record` (recompute) para manter `/day` consistente. | Integridade |
| RNF-014 | **INV-21** — kcal de treino: quando usuário informa kcal (texto/imagem/edição), `kcal_burned_reported` é a fonte (calc_method reflete origem); senão estimativa MET no backend. LLM nunca calcula. | Integridade (Art. II) |
| RNF-015 | Paginação do histórico determinística e estável (evitar duplicação/omissão entre páginas). | Corretude |
| RNF-016 | Testes: `tests/test_workout.py` cobrindo SP-120..127 + SP-170..179 + INV-15/16/17 (núcleo) e INV-18..21 (módulo) (T-B307 + novos). Cobertura alvo ≥ 80% em `app/services/workout.py` (regra do MVP). | Qualidade |

## Restrições e premissas

- **SP-120..127 todos `may`** — pós-MVP; especificado, ainda sem implementação.
- **SP-170..179 propostos (não canônicos)** — dependem de `spec:` PR na `specs/001-mvp-registro-diario/spec.md` (fluxo SDD obrigatório: `spec:` → `plan:` → `tasks:` → `feat:`).
- **ADR-011 aceita** — append-only; não reescrever. Documenta coexistência `log_activity` + `workout_session`.
- **Coexistência por design**: cardio genérico (corrida/natação/caminhada) continua usando `log_activity` (SP-60..64); treino de força/musculação usa módulo novo.
- **MET fixo por `workout_type` é aproximado** — refinamento futuro ("volume total × densidade") fora do MVP.
- **Dois fluxos**: cadastrar template (RF-015) e executar sessão guiada ou livre (RF-020/SP-120..124). Ambos convergem em `workout_sessions`.
- **`weight_kg` do perfil** necessário pra kcal sem valor reportado; sem ele, `activity_record.kcal_burned=NULL` (RF-008).
- **Três telas novas**: `/workouts` (RF-014, RF-016, RF-017), chat de treino dedicado no mesmo pool de `messages` com `via='workout'` (RF-018, RF-019, RF-020), seção de treinos no `/day` (RF-024). Navegação mobile (SP-NM) **não** adiciona tab nova neste módulo — acesso via link/CTA (decisão fixada nos trade-offs).
- **Sem gráficos de distribuição nem exportação** fora desta feature.

## Dependências

**Depende de:**
- [`authentication-session`](../authentication-session/requirements.md) — `user_id` isolation; cookie auth.
- [`activity-cardio-logging`](../activity-cardio-logging/requirements.md) — `log_activity`/`activity_records` (coexistência ADR-011); regras `kcal_burned`/`met_value` no snapshot.
- [`daily-snapshot`](../daily-snapshot/requirements.md) — `day_log_id` FK; snapshot aggregate via `activity_record`.
- [`day-close`](../day-close/requirements.md) — `_handle_close_day` hook para SP-125.
- [`weekly-report`](../weekly-report/requirements.md) — le via `activity_record` consolidado.
- [`anthropic-integration`](../anthropic-integration/requirements.md) — `record_intent` tool schema (intents de treino + imagem); prompt `system_v2.md` regra 19 + novas regras.
- [`chat-messaging`](../chat-messaging/requirements.md) — `MessageProcessor` handlers novos; polling `after`.
- [`chat-composer-ux`](../chat-composer-ux/requirements.md) — composer + upload de mídia do chat de treino (padrão do chat de alimentação).
- [`media-storage`](../media-storage/requirements.md) — `POST /media` para imagem de treino; compressão LLM.
- [`record-correction`](../record-correction/requirements.md) / [`record-deletion`](../record-deletion/requirements.md) — INV-17; edição de sets via `workout_correct`.
- [`audit-trail`](../audit-trail/requirements.md) — INV-10 em mutações de `workout_*`.
- [`daily-detail-view`](../daily-detail-view/requirements.md) — seção de treinos no `/day` (RF-024) reusa padrão `ActivitySection`/`AuxiliarySections`.
- [`inline-record-editing`](../inline-record-editing/requirements.md) — formulários inline de peso/séries/kcal no `/day` (RF-023).
- [`profile` features] — `weight_kg`/`height_cm` no `User` model (existentes) para kcal.

**Requerido por:**
- [`daily-detail-view`](../daily-detail-view/requirements.md) — `ActivitySection`/nova seção mapeiam `calc_method='workout_session'` → "sessão de treino" (label já pré-inserido em `types.ts:142`).
- [`weekly-report`](../weekly-report/requirements.md) — `activity_record` consolidado entra no semanal.