# Implementation Plan — MVP: Registro Diário por Chat com IA

**Feature ID:** 001-mvp-registro-diario
**Owner:** Felix
**Depende de:** [`spec.md`](spec.md) v1.0, [`../../.specify/memory/constitution.md`](../../.specify/memory/constitution.md) v1.0.0
**Referencia:** [`../../app_plan.md`](../../app_plan.md) (fonte canônica de arquitetura, DB, endpoints)

---

## Regras deste documento

- Este `plan.md` descreve **como** implementar o que está em `spec.md`, sem duplicar decisões.
- A fonte canônica de arquitetura é `app_plan.md` (20 seções). Aqui apenas: (a) mapeio SP-XX → seção do plano; (b) adiciono decisões SDD-específicas (gates, ADRs, ordem de execução); (c) registro divergências do plano quando houver.
- Alterações neste arquivo requerem PR próprio; alterações que atinjam artigos da Constituição exigem emenda constitucional.

---

## 1. Mapa SP-XX → seções do plano

| SP | Área | Plano | Arquivos-chave |
|----|------|-------|----------------|
| SP-01 a SP-06 | Autenticação | §7, §10 | `app/api/routes/auth.py`, `app/services/auth.py`, `app/core/security.py` |
| SP-10 a SP-14 | Chat | §4, §6 (messages), §10 | `app/api/routes/chat.py`, `app/services/chat.py`, `app/integrations/anthropic/` |
| SP-20 a SP-26 | Registro de alimentos | §6, §8, §9 | `app/api/routes/records.py`, `app/services/meal.py`, `app/services/nutrition_calculator.py` |
| SP-30 a SP-35 | Rótulo nutricional | §8.2 (extensão), §6 (nutrient_facts) | `app/services/label_catalog.py`, `app/integrations/nutrition/` |
| SP-40 a SP-42 | Água | §6, §10 | `app/services/hydration.py` |
| SP-50 a SP-52 | Outros líquidos | §6, §10 | `app/services/beverage.py` |
| SP-60 a SP-64 | Atividades | §6, §10 | `app/services/activity.py`, `app/services/activity_calculator.py` (METs) |
| SP-70 a SP-74 | Correções | §6 (audit_events), §10 | `app/services/correction.py` |
| SP-80 a SP-82 | Remoções | §6, §10 | `app/services/*` (soft delete + recompute) |
| SP-90 a SP-92 | Consulta do dia | §10 | `app/api/routes/days.py`, `app/services/daily_report.py` |
| SP-100 a SP-104 | Encerramento | §6, §10 | `app/services/daily_report.py` (close) |
| SP-110 a SP-113 | Relatório semanal | §6 (weekly_reports), §10 | `app/services/weekly_report.py` |
| SP-120 a SP-127 | Treino — núcleo hierárquico | §3.13, ADR-004/ADR-011 | `app/services/workout.py`, `app/models/workout.py`, `app/repositories/workout.py`, `app/services/message_processor.py`, `app/services/intent_dispatcher.py` |
| SP-170 a SP-179 | Treino — módulo (templates, chat dedicado, `/workouts`, `/day`) | §3.16, ADR-011 | `app/services/workout.py` (módulo), `app/api/routes/workouts.py`, `app/models/workout_templates.py`, `apps/web/src/app/(app)/workouts/*`, `apps/web/src/proxy.ts`, `apps/web/src/app/(app)/day/AuxiliarySections.tsx`, `apps/web/src/app/(app)/day/edit-forms.tsx` |
| SP-180 a SP-181 | Chat — paginação por dia (carga inicial + scroll-up) | §3.2, ADR-013 | `app/repositories/message.py`, `app/services/chat.py`, `app/api/routes/chat.py`, `app/schemas/chat.py`, `apps/web/src/app/(app)/chat/page.tsx` |
| SP-182 a SP-185 | `/day` — edição total + registro retroativo | §3.17, ADR-014 | `app/api/routes/records.py`, `app/api/routes/nutrient_facts.py`, `app/services/nutrient_fact_propagation.py` (clone), `app/services/message_processor.py` (`target_date`), `app/services/{meal,hydration,beverage,activity}.py`, `app/schemas/llm.py`, `apps/web/src/app/(app)/day/*`, `apps/web/src/app/(app)/chat/*` |

---

## 2. Ordem de execução (Fases)

Idêntica à §18 do plano, com sub-fase 4.b já incorporada.

| Fase | Nome | Estim. | Entrega os SPs |
|------|------|--------|----------------|
| 0 ✅ | Fundação | 2-3d | (esqueleto executável, sem SPs; base para as demais) |
| 1 | Autenticação + bootstrap admin | 1-2d | SP-01, SP-02, SP-03, SP-04, SP-05, SP-06 |
| 2 | Mensagens e upload de mídia | 2d | SP-10, SP-11, SP-12 (parcial), fluxo base para §3.3-§3.7 |
| 3 | Integração Anthropic | 3d | SP-13, SP-14, contrato JSON validado |
| 4 | Registro de alimentos | 3d | SP-20 a SP-26, INV-1 |
| 4.b | Leitura de tabela nutricional | 1-2d | SP-30 a SP-35 |
| 5 | Hidratação + atividades | 2d | SP-40 a SP-42, SP-50 a SP-52, SP-60 a SP-64, INV-2, INV-3 |
| 6 | Correções e remoções | 2d | SP-70 a SP-74, SP-80 a SP-82, INV-4, INV-10 |
| 7 | Encerramento + relatório diário | 1d | SP-90 a SP-92, SP-100 a SP-104, INV-5 |
| 8 | Relatório semanal | 1d | SP-110 a SP-113, INV-8 |
| 9 | Hardening + deploy | 2d | (segurança, backup, HTTPS; cross-cutting) |

Total: ~20-21 dias úteis focados.

---

## 3. Gates de fase

Cada fase só é considerada **entregue** quando:

1. **Todos os SPs `must` da fase têm teste automatizado verde** (unit ou integration).
2. **Nenhum artigo da Constituição é violado** — checklist manual (§4 abaixo).
3. **Nenhuma alteração de spec** foi feita sem PR próprio.
4. **`git log` do PR referencia SPs** cobertos: exemplo `feat(fase-4): SP-20 SP-21 SP-23 - registro por texto`.
5. **`app_plan.md` atualizado** se decisões arquiteturais mudaram.

Sem estes gates cumpridos, o merge é bloqueado.

---

## 4. Checklist de conformidade constitucional

Aplicado em **todo PR** que toca código de negócio (services, models, routes):

- [ ] Nenhuma soma nutricional passou pela LLM (Art. II §5).
- [ ] Snapshot recomputa from-scratch, não delta (Art. III §10).
- [ ] `audit_events` gravado em toda mutação (Art. III §11).
- [ ] Água e outros líquidos separados (Art. IV §12-14).
- [ ] `user_id` no filtro de toda query (Art. V §21).
- [ ] Nenhum segredo em código/logs/response (Art. V §19).
- [ ] Aviso legal presente em respostas de dia/semana (Art. VII §26).
- [ ] Nenhum endpoint HTTP de cadastro ou reset (Art. V §18).
- [ ] Dia fechado é imutável no path testado (Art. VIII §28).

---

## 5. Decisões técnicas SDD-específicas

### 5.1 Estrutura de branches

- `dev` — trunk. PRs entram por squash-merge.
- `feat/fase-N-<slug>` — por fase (ou sub-fase). Ex: `feat/fase-1-auth-bootstrap`.
- Merge para `dev` requer: (a) gates §3; (b) checklist §4.
- Push direto em `dev` é permitido só para hotfix da Fase 0 (ambiente).

### 5.2 Convenção de commits

Formato Conventional Commits + referência a SP-XX no primeiro parágrafo:

```
feat(fase-4): registrar alimentos por texto e foto

Cobre SP-20, SP-21, SP-23. Adiciona MealService.create_from_llm,
NutritionCalculator.compute, e recompute do snapshot ao criar itens.

Refs: spec §3.3, constitution Art. II
```

### 5.3 Testes obrigatórios por camada

- **INV-N** → teste de integração com Postgres real (via testcontainers ou banco de teste). Nunca mock.
- **SP-XX must** → teste unit de service + teste de integração ponta-a-ponta (route → service → repo → DB).
- **LLM** → mock do cliente Anthropic. Fixtures em `tests/fixtures/anthropic/*.json`.

Cobertura mínima aceitável no MVP: **80%** em `app/services/` e **90%** em `app/services/nutrition_calculator.py` + `app/services/activity_calculator.py`.

### 5.4 Formato das ADRs

Novas decisões que alteram trade-offs vivem em `research.md` como blocos:

```markdown
## ADR-NNN: título curto
**Data:** yyyy-mm-dd
**Status:** proposed | accepted | superseded by ADR-MMM
**Contexto:** ...
**Decisão:** ...
**Consequências:** ...
**Alternativas descartadas:** ...
```

### 5.5 Divergências vs. `app_plan.md`

Se durante uma fase a implementação divergir do plano, atualize esta seção antes de mergear:

| Fase | Divergência | Motivo |
|------|-------------|--------|
| 0 | Alembic pinado `>=1.14,<1.16` | Auto-discovery de `pyproject.toml` no 1.16+ quebra o `alembic.ini` (ADR-003 em research.md). |
| 0 | Backend rodado no host em macOS via `pnpm dev:api` | `EDEADLK` no bind mount do Docker Desktop (ADR-008). |

---

## 6. Fluxo SDD por feature

Ordem canônica quando uma nova feature entrar (pós-MVP ou dentro de fase):

1. **Escrever o SP-XX na `spec.md`** (What/Why + Given/When/Then). PR isolado, título `spec:`.
2. **Atualizar `plan.md`** com mapeamento SP-XX → arquivos e ordem, se necessário. PR isolado, título `plan:`.
3. **Adicionar tarefas em `tasks.md`** com IDs T-XXX. PR isolado, título `tasks:`.
4. **Implementar** com PR `feat:` cobrindo os T-XXX, marcando os SP-XX no commit body.
5. **Fechar** o SP no changelog do spec (histórico de alterações).

Pular a etapa 1-3 e ir direto pra `feat:` **não é permitido** neste projeto. Emergências (bugs de produção) usam `fix:` + issue vinculada; ainda assim, se afetar comportamento observável, retroativamente descrever em `spec.md`.

---

## 7. Onde vive o quê

```
.specify/
  memory/
    constitution.md          # princípios inegociáveis (Art. I-X)
specs/
  001-mvp-registro-diario/
    spec.md                  # WHAT + porquê
    plan.md                  # HOW (este arquivo)
    tasks.md                 # tarefas atômicas
    research.md              # ADRs
app_plan.md                  # design técnico canônico (referenciado por plan.md)
docs/
  architecture.md            # índice curto para navegação
```

Nada de conteúdo em `spec.md` deve descrever HOW. Nada em `plan.md` deve descrever WHAT novo (só mapeia SPs existentes).

---

## 8. Pós-MVP — Módulo de treino (SP-170..SP-179)

> **Contexto:** o núcleo (SP-120..127, todas `may`) já estava planejado como Bloco 3; a v1.13 da spec adiciona a expansão de módulo (§3.16). Esta seção descreve a ordem de execução do módulo; as tarefas atômicas vivem em `tasks.md` (Bloco 3 T-B301..T-B308 + T-B3xx novos do módulo).

**Ordem de execução do módulo:**

| Etapa | Entrega | SPs | Arquivos | Depende de |
|-------|---------|-----|----------|-----------|
| E1 — Fundação do módulo | Migration `messages.via` (`'food'` default) + índice `idx_messages_user_via`; filtro por `via` em `GET /chat/messages` e `MessageProcessor`; prompt `system_v2.md` selecionado pela `via` | SP-173 | `alembic/versions/`, `app/repositories/message.py`, `app/api/routes/chat.py`, `app/services/message_processor.py`, `prompts/system_v2.md` | Bloco 3 (núcleo) feito |
| E2 — Templates | `workout_templates` + `workout_template_exercises`; `register_template` via chat; rotas `/workouts/templates` (listagem/toggle `active`) | SP-170, SP-171, SP-172 | `alembic/versions/0011_workout_templates.py`, `app/models/workout_templates.py`, `app/repositories/workout.py`, `app/api/routes/workouts.py`, `app/services/workout.py` | E1 |
| E3 — Chat dedicado | `/workouts/chat` + header `WorkoutTotalsHeader` (atividades do dia + kcal gastas); botões Cadastrar/Iniciar/Finalizar | SP-173 | `apps/web/src/app/(app)/workouts/chat/page.tsx`, `WorkoutTotalsHeader.tsx`, `apps/web/src/proxy.ts` | E1 |
| E4 — Fluxo guiado + cronômetro | Template picker/exercício picker, lookup da última realização, `workout_next_exercise`, botão "Ir para o próximo exercício", `Stopwatch` | SP-178, SP-179 | `apps/web/src/app/(app)/workouts/`, `app/services/workout.py` | E2, E3 |
| E5 — Imagem + edição | `workout_register`/`workout_correct` por imagem/texto; `WorkoutImageIn`/`WorkoutCorrectSetIn`; PATCH `/records/workout-sets/{id}` e `/records/workout-sessions/{id}`; reconsolidação de sessão encerrada (INV-20) | SP-174, SP-175 | `app/schemas/llm.py`, `app/services/message_processor.py`, `app/api/routes/records.py`, `app/services/workout.py` | E2 |
| E6 — `/day` + histórico | Seção "Treinos" no `/day`; histórico paginado em `/workouts` | SP-176, SP-177 | `apps/web/src/app/(app)/day/AuxiliarySections.tsx` + `edit-forms.tsx`, `app/api/routes/workouts.py`, `app/repositories/workout.py` | E2 |

**Gates de fase (Bloco 3 / módulo):**
- Núcleo: probe de `tests/test_workout.py` (T-B307) cobrindo SP-120..127 + INV-15/16/17.
- Módulo: cada etapa E1..E6 com teste (unit de service + integração ponta-a-ponta) para os SPs `must` (`SP-170..SP-175`, `SP-177..SP-179`); `SP-176` (`should`) com ao menos test de site/`day`.
- Invariantes com teste obrigatório; INV-21 via fixture que troca cliente Anthropic por mock que devolve lixo.
- Sem PR sem referência a SP-XX/T-XXX no body.

**Divergências vs. `app_plan.md`:** nenhuma até aqui — o módulo estende `app_plan.md` §9/§11 (chat/workout) quando a primeira `feat:` for implementada; registrar nesta seção a partir daí.

---

## 9. Paginação do chat por dia (SP-180..SP-181)

> **Contexto:** hoje a carga inicial (`GET /chat/messages?limit=100`) devolve as N mensagens mais recentes de **todo** o histórico, e o cursor `before` já existe no backend mas nunca é usado no frontend. A v1.14 da spec (SP-180/SP-181) restringe a carga inicial ao dia corrente e liga o `before` ao scroll-up. Decisões de design em ADR-013.

**Ordem de execução:**

| Etapa | Entrega | SPs | Arquivos | Depende de |
|-------|---------|-----|----------|-----------|
| P1 — Cursor determinístico | `MessageRepository.list_messages` ganha `since` (datetime UTC) e `has_more_before`; ordenação `(created_at, id)` e âncoras exclusivas (INV-23) | SP-180, SP-181, INV-22, INV-23 | `app/repositories/message.py`, `app/services/chat.py`, `app/schemas/chat.py`, `app/api/routes/chat.py` | — |
| P2 — Scroll-up no frontend | `chat/page.tsx` detecta topo do scroll → `?before=<oldestId>&limit=50` → prepend com ancoragem de scroll; guard anti-duplicação; para em `has_more_before=false` | SP-181 | `apps/web/src/app/(app)/chat/page.tsx` | P1 |

**Gates de fase (paginação):**
- SP-180/SP-181 `must` → unit de service + integração ponta-a-ponta (route → service → repo → DB).
- INV-22/INV-23 → teste de integração com Postgres real, nunca mock.
- E2E Playwright: scroll ao topo carrega histórico sem duplicar (opcional, adiciona quando a suíte de chat for tocada).
- Sem PR sem referência a SP-180/SP-181 no body.

**Divergências vs. `app_plan.md`:** a carga inicial de `GET /chat/messages` deixa de ser "últimas N do histórico" e passa a "últimas N do dia corrente" — registrada aqui; sem mudança de schema de BD (só o envelope de resposta ganha `has_more_before`).

---

## 10. Edição total no `/day` + registro retroativo (SP-182..SP-185)

> **Contexto:** o Bloco 7 entregou edição inline limitada — macros de itens do catálogo canônico (TBCA/USDA) são "não editáveis" (SP-35) e não há edição de metadados — e o registro só existe via chat, sempre no dia corrente (`local_today`). A v1.15 da spec (SP-182..185) fecha os dois buracos: override de macros canônicos por clone, edição de qualquer campo no `/day` e registro em dia passado aberto (chat e `/day`). Decisões em ADR-014.

**Ordem de execução:**

| Etapa | Entrega | SPs | Arquivos | Depende de |
|-------|---------|-----|----------|-----------|
| R1 — Override canônico | Clone de fact `TBCA_2023`/`USDA_FDC` → `manual` (`created_by=user`) ao editar macros no `/day`; nunca muta o fact compartilhado | SP-182, INV-24 | `app/services/nutrient_fact_propagation.py` (ou serviço novo de clone), `app/api/routes/nutrient_facts.py`, `app/api/routes/records.py`, `apps/web/src/app/(app)/day/edit-forms.tsx` | — |
| R2 — Edição de metadados | PATCH de `detected_name`/`meal_slot`/`occurred_at`/`quantity`/`unit` nos 4 tipos + forms no `/day` | SP-183 | `app/api/routes/records.py`, `app/schemas/*`, `apps/web/src/app/(app)/day/edit-forms.tsx` | — |
| R3 — Registro retroativo via chat | Envelope da LLM ganha `target_date`; `MessageProcessor` resolve `day_log` por data (reusa `DayLogRepository.get_or_create`) | SP-184 | `app/services/message_processor.py`, `app/services/chat.py`, `app/integrations/anthropic/`, `app/schemas/llm.py` | — |
| R4 — Registro retroativo via `/day` | Form de adição em `/day/[data]` (dia aberto) com endpoints de criação estruturada (sem LLM) | SP-185 | `app/api/routes/*`, `apps/web/src/app/(app)/day/*` | R1, R2 |

**Gates de fase (edição/registro retroativo):**
- SP-182..185 `must` → unit de service + integração ponta-a-ponta (route → service → repo → DB).
- INV-24/INV-25 → integração com Postgres real. INV-24 via teste que edita item TBCA e verifica que o row do catálogo permanece intacto.
- Dia fechado → 409 `conflict_closed_day`; data futura → `validation_error`; verificados em chat e `/day`.
- Sem PR sem referência a SP-182..185 no body.

**Divergências vs. `app_plan.md`:** edição de fact canônico deixa de ser proibida (SP-35) — mas via clone por usuário, não mutação in-place. Registro deixa de ser "sempre hoje" e passa a aceitar data passada aberta.

---

## Histórico

- **2026-07-15** — v1.0. Plano inicial. Fase 0 marcada concluída.
- **2026-08-14** — v1.1. Módulo de treino (SP-120..127 núcleo + SP-170..179 expansão da v1.13 da spec): mapeamento SP→arquivos no mapa §1 e nova seção §8 com ordem de execução (E1..E6) e gates. Corresponde à spec v1.13 (§3.13 inalterado + nova §3.16).
- **2026-09-04** — v1.2. Paginação do chat por dia (SP-180/SP-181): mapeamento SP→arquivos no mapa §1 e nova seção §9 com ordem de execução (P1..P2) e gates. Corresponde à spec v1.14; decisões em ADR-013.
- **2026-09-05** — v1.3. Edição total no `/day` + registro retroativo (SP-182..185): mapeamento SP→arquivos no mapa §1 e nova seção §10 (etapas R1..R4 + gates). Corresponde à spec v1.15 (§3.13 inalterado + nova §3.17). Decisões em ADR-014.
