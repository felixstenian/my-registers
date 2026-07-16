# Tasks — MVP: Registro Diário por Chat com IA

**Feature ID:** 001-mvp-registro-diario
**Depende de:** [`spec.md`](spec.md), [`plan.md`](plan.md), [`../../.specify/memory/constitution.md`](../../.specify/memory/constitution.md)

---

## Regras deste documento

- Cada tarefa tem ID `T-XXX` estável.
- Uma tarefa é **atômica**: entrega em ≤ 1 dia, em 1 PR pequeno.
- Cada tarefa referencia: os `SP-XX` que atende, arquivos-chave a criar/modificar, dependências (`blocked_by`), e critério de aceite.
- Status: `todo` · `in_progress` · `done` · `blocked` · `deferred`.
- Ordem de execução respeita fases da `plan.md` §2 e dependências explícitas.

Convenção de tamanho: **S** (≤ 2h) · **M** (½ dia) · **L** (1 dia).

---

## Fase 0 — Fundação ✅

Status: **done** (commit `87b8382`).

- [x] **T-000** — Monorepo, Dockerfiles, docker-compose local, esqueleto FastAPI + Next.js, `/health`, Alembic init, Pydantic Settings, logging JSON, Typer CLI placeholder. (M) — `must` de infra; não cobre SP diretamente mas destrava as demais fases.

---

## Fase 1 — Autenticação e bootstrap do admin ✅

Meta: usuário admin cria sessão via `/auth/login`, permanece autenticado via cookies, faz logout. Bootstrap idempotente pela CLI.

Status: **done** (branch `feat/fase-1-auth-bootstrap`). 18 testes verdes (SP-01..SP-06 + INV-6, INV-7); lint verde.

- [x] **T-101** — Migration Alembic inicial (extensões `pgcrypto`, `citext` + tabelas `users`, `refresh_tokens`). (S) — pré-requisito para SP-01 a SP-06. Arquivos: `apps/api/alembic/versions/0001_users_and_refresh_tokens.py`, `app/models/user.py`, `app/models/refresh_token.py`, trigger `set_updated_at`.
- [x] **T-102** — `app/core/security.py`: hash Argon2id, verify, JWT encode/decode HS256. (S) — atende Const. §15-16. Rehash oportunístico via `needs_rehash`. Refresh opaco 32B + SHA-256.
- [x] **T-103** — `app/services/auth.py` + `app/repositories/user.py` + `refresh_token.py`. Fluxo login, refresh, logout com rotação e detecção de reuso (SP-03). (M) — cobre SP-01, SP-03, SP-04. Commit explícito antes de raise no reuso para não perder revogação da família no rollback.
- [x] **T-104** — Rate limiting no login: 5/min/IP e 10/15min/email (SP-02). (S) — `app/core/rate_limit.py` sliding-window in-memory com lock. Reset via `reset_login_limiters()` para testes.
- [x] **T-105** — `app/api/routes/auth.py` com dependências FastAPI para cookie access + refresh. Handlers para `/login`, `/logout`, `/refresh`, `/me`. (M) — `app/api/deps.py` com `get_current_user`, `get_client_ip` (respeitando `X-Forwarded-For`), `get_session`.
- [x] **T-106** — Ausência de `/register` e `/forgot-password` provada por teste (SP-05). Coberto em `tests/test_auth.py::test_forbidden_public_endpoints_return_404`.
- [x] **T-107** — CLI `python -m app.cli bootstrap` real: cria admin idempotente lendo `DEFAULT_ADMIN_EMAIL`/`DEFAULT_ADMIN_PASSWORD`. Nunca ecoa a senha (Const. §19).
- [x] **T-108** — Middleware Next.js protegendo rotas `(app)/*` via cookie access. Redirect para `/login`. `apps/web/src/middleware.ts` mais rewrite `/api/*` → backend em `next.config.mjs`.
- [x] **T-109** — Página `/login` no frontend (`(auth)/login/page.tsx`) + layout protegido `(app)/layout.tsx` que faz SSR de `/auth/me` + botão logout + placeholder `/chat`.
- [x] **T-110** — Testes de integração: SP-01, SP-02, SP-03, SP-04, SP-05, SP-06 + INV-7. Fixtures em `tests/conftest.py` com DB de teste `registers_test` (migrations em subprocess para isolar `asyncio.run` do env.py), TRUNCATE entre casos, reset de rate limiter.

**Gate Fase 1 — cumprido:** todos SP-01 a SP-06 verdes; Const. §15-19 e §21 verificadas; próximo PR merge para `dev`.

---

## Fase 2 — Mensagens e upload de mídia

Meta: usuário envia mensagem por chat com texto e/ou fotos; backend persiste sem chamar LLM ainda (mock).

- [ ] **T-201** — Migration para `day_logs`, `messages`, `media`, `message_media`. (S) — Arquivos: `alembic/versions/0002_*.py`, models correspondentes.
- [ ] **T-202** — `app/integrations/storage/minio.py`: cliente boto3 com endpoint MinIO, PUT via `storage_key = users/{uid}/media/{yyyy}/{mm}/{uuid}.{ext}`, URL assinada de download. (M) — pré-requisito para SP-11.
- [ ] **T-203** — `POST /media` endpoint: valida MIME server-side, size ≤ 8MB, Pillow decode probe, upload MinIO, insere linha em `media`. (M) — SP-11 (parte). `blocked_by: T-201, T-202`. Const. §22.
- [ ] **T-204** — `app/services/chat.py` + repositório de mensagens. Cria `messages` + `message_media`, garante `day_logs` para timezone do usuário (SP-92). (M) — SP-10, SP-11, SP-12, SP-92.
- [ ] **T-205** — `POST /chat/messages` + `GET /chat/messages?after=<id>&limit=`. (M) — SP-10 (retorno 202), SP-12 paginação. `blocked_by: T-204`.
- [ ] **T-206** — Página `/chat` no frontend: lista mensagens, drop de imagens (react-dropzone), envio via mutation, polling a cada 1.5s por assistant response (com cap 30s). (L) — SP-10, SP-11, SP-14 (parte). `blocked_by: T-205`.
- [ ] **T-207** — Testes: SP-10, SP-11, SP-12, SP-92. (M) — gate.

**Gate Fase 2:** mensagens persistem, mídia sobe pro MinIO com URL assinada, chat funcional sem LLM. Const. §21-22 verificadas.

---

## Fase 3 — Integração Anthropic

Meta: LLM interpreta mensagens, devolve JSON validado por Pydantic, sem persistir registros nutricionais ainda (LabelCatalogService/MealService vêm na Fase 4).

- [ ] **T-301** — `app/integrations/anthropic/client.py`: wrapper da SDK oficial com timeout 60s, retries 2 em 5xx/429, download de mídia do MinIO e conversão base64. (M) — Const. Art. II.
- [ ] **T-302** — `app/integrations/anthropic/prompts/system_v2.md` + `app/schemas/llm.py` (`LLMEnvelope`, `FoodItemIn`, `WaterIn`, `BeverageIn`, `ActivityIn`, `CorrectionIn`, `DeletionIn`, `NutritionLabelIn`). Prompt caching ativo. (M) — Const. §7. Ver `app_plan.md` §8.
- [ ] **T-303** — Chamada com `tool_use` obrigatório e retry semântico (2 tentativas com feedback do erro Pydantic). (M) — Const. §7. `blocked_by: T-301, T-302`.
- [ ] **T-304** — `IntentDispatcher` esqueleto: recebe `LLMEnvelope`, roteia para services por `intent`. Fase 3 conecta apenas `clarify` e `unknown` (responde ao chat), `log_food` etc. levantam `NotImplementedError`. (S) — SP-13, SP-14.
- [ ] **T-305** — `BackgroundTasks.process_user_message`: baixa mídia, chama Anthropic, valida, dispatcher, cria `messages(role='assistant')` com `narrative`. Grava `raw_llm_response`, tokens. (M) — cobre SP-13, SP-14. `blocked_by: T-303, T-304`.
- [ ] **T-306** — Testes com fixtures de resposta Anthropic (não chama API real). SP-13, SP-14, INV-9. (M) — gate.

**Gate Fase 3:** LLM responde no chat com clarify/unknown; sem persistir registros; fluxo de retry semântico coberto.

---

## Fase 4 — Registro de alimentos

Meta: `log_food` cria registros nutricionais com cálculos determinísticos do backend.

- [ ] **T-401** — Migration `food_records`, `food_items`, `nutrient_facts`, `daily_snapshots`, `audit_events`. (M) — Arquivos: `alembic/versions/0003_*.py`.
- [ ] **T-402** — `app/integrations/nutrition/catalog.py` (protocol) + `LocalTBCACatalog` + normalização de nome. (M) — SP-35 (parcial).
- [ ] **T-403** — CSV seed TBCA (~50-100 itens iniciais) + `app.cli seed-nutrition`. (M) — pré-requisito para SP-20.
- [ ] **T-404** — `app/services/nutrition_calculator.py`: computa kcal/macros/micros por item deterministicamente. (S) — INV-1. Cobertura mínima 90%. `blocked_by: T-402`.
- [ ] **T-405** — `app/services/meal.py`: `MealService.create_from_llm(envelope, message_id)`. Cria `food_records`+`food_items`, chama calculator, grava `audit_events`. (M) — SP-20, SP-23 (parte), SP-24. `blocked_by: T-404`.
- [ ] **T-406** — `app/services/daily_recompute.py`: recompute from-scratch, escreve `daily_snapshots` incrementando `version`. (M) — INV-4, SP-90 (parte). `blocked_by: T-401`.
- [ ] **T-407** — Ligar dispatcher: `log_food` → `MealService`. Após: sempre recompute. (S) — `blocked_by: T-405, T-406`.
- [ ] **T-408** — `GET /days/today`, `GET /days/{date}` (só leitura no MVP). (S) — SP-90, SP-91. `blocked_by: T-406`.
- [ ] **T-409** — Frontend `DayTable`: renderiza totals + records. Fetch em polling e após confirmação do assistente. (M) — SP-90 UI. `blocked_by: T-408`.
- [ ] **T-410** — Testes: SP-20 a SP-26, INV-1, SP-90, SP-91, SP-92 (foco em timezone). (M) — gate.

**Gate Fase 4:** registrar alimento por texto funciona ponta-a-ponta; snapshot atualiza; tabela renderiza. Const. §5-6, §10.

---

## Fase 4.b — Leitura de tabela nutricional

Meta: cadastrar produtos via foto de rótulo; opcionalmente registrar consumo na mesma mensagem.

- [ ] **T-421** — Migration acrescentando `barcode`, `label_media_id`, `verified_by_user` a `nutrient_facts`; source enum recebe `label_ocr`. (S) — SP-30, SP-35.
- [ ] **T-422** — Atualizar prompt para v2 + schema `NutritionLabelIn` (regras 16-18 do plano §8.3). (S) — SP-30 a SP-32. Ver `app_plan.md` §8.
- [ ] **T-423** — `app/services/label_catalog.py`: `upsert_from_label`. Normaliza `per_serving` → `per_100g|ml` deterministicamente. Nunca sobrescreve `TBCA_2023`. Bloqueia sem `serving_size_*` se `basis='per_serving'`. (M) — SP-30, SP-32, SP-35. `blocked_by: T-421`.
- [ ] **T-424** — `IntentDispatcher` roteia `log_nutrition_label`. Se `also_consumed` presente: chama `MealService` reusando `catalog_ref_id`. (S) — SP-31. `blocked_by: T-423, T-405`.
- [ ] **T-425** — `PATCH /nutrient-facts/{id}` para confirmar/editar valores, seta `verified_by_user=true`. (S) — SP-33.
- [ ] **T-426** — Frontend: cartão de confirmação inline no chat com botão "Confirmar" que chama `PATCH`. (M) — SP-33 UI. `blocked_by: T-425`.
- [ ] **T-427** — Testes: SP-30 a SP-35, precedência de lookup, `warnings` com micros ausentes (SP-34). (M) — gate.

**Gate Fase 4.b:** upload de foto de rótulo cadastra produto reutilizável; consumo opcional funciona; precedência TBCA > label_ocr enforced.

---

## Fase 5 — Hidratação e atividades

Meta: registrar água, outros líquidos e atividades; snapshot inclui todos.

- [ ] **T-501** — Migration `water_records`, `beverage_records`, `activity_records`. (S)
- [ ] **T-502** — `HydrationService.create_from_llm` + validação anti-dupla-contagem (rejeita `log_water` com `kcal>0`). (M) — SP-40, SP-41, SP-42, INV-2. `blocked_by: T-501`.
- [ ] **T-503** — `BeverageService.create_from_llm` reusando `NutritionCalculator` para macros do catálogo. (M) — SP-50, SP-51, SP-52, INV-3. `blocked_by: T-501, T-404`.
- [ ] **T-504** — Tabela seed de METs por `activity_type`/`intensity` + `ActivityCalculator.compute(activity, user)`. (M) — SP-60, SP-62, SP-63, SP-64.
- [ ] **T-505** — `ActivityService.create_from_llm`. Se `users.weight_kg` for null, retorna intent de esclarecimento sem persistir. (M) — SP-61. `blocked_by: T-504`.
- [ ] **T-506** — Estender `DailyRecomputeService` para incluir água, líquidos, kcal_out. (S) — SP-90. `blocked_by: T-406, T-502, T-503, T-505`.
- [ ] **T-507** — Ligar dispatcher: `log_water`, `log_beverage`, `log_activity`. (S)
- [ ] **T-508** — Testes: SP-40 a SP-64, INV-2, INV-3. (M) — gate.

**Gate Fase 5:** os três novos tipos de registro funcionam; snapshot completo. Const. Art. IV verificada por teste.

---

## Fase 6 — Correções e remoções

Meta: usuário corrige e remove registros por chat com auditoria completa.

- [ ] **T-601** — `CorrectionService.apply(target_hint, changes, day)`: matching por `normalized_name` + qualificadores (meal_slot, hora). Retorna `AmbiguousTarget` se >1 match. (M) — SP-70, SP-71, SP-72.
- [ ] **T-602** — `IntentDispatcher.route_correction` e `route_deletion`. Assistente responde pedindo desambiguação se `AmbiguousTarget`. (M) — SP-71. `blocked_by: T-601`.
- [ ] **T-603** — Soft-delete em todos os services de registro + audit_events com `before`/`after`. Bloqueio em dias fechados (409). (M) — SP-73, SP-74, SP-80, SP-82, INV-5, INV-10.
- [ ] **T-604** — `DELETE /records/*/{id}` e `PATCH /records/food-items/{id}` idempotentes. (S) — SP-81. `blocked_by: T-603`.
- [ ] **T-605** — Testes: SP-70 a SP-82, INV-4, INV-5, INV-10. (M) — gate.

**Gate Fase 6:** correções e exclusões seguras, com trilha de auditoria. Const. Art. III §11 verificada.

---

## Fase 7 — Encerramento e relatório diário

Meta: fechar o dia por chat, gerar narrative sobre totais calculados.

- [ ] **T-701** — `POST /days/{date}/close` idempotente + recompute forçado + snapshot com `warnings` agregados. (M) — SP-100, SP-101, SP-102.
- [ ] **T-702** — Geração de `narrative` via LLM alimentada pelo snapshot já calculado (segunda chamada, temperature=0.3, sem tool_use). Concatena disclaimer. (M) — SP-103, SP-104, Const. §26.
- [ ] **T-703** — Dispatcher `close_day` → `POST /days/{today}/close`. (S)
- [ ] **T-704** — Frontend: botão "Encerrar dia" na barra do chat + tela de resumo pós-fechamento. (M)
- [ ] **T-705** — Testes: SP-100 a SP-104, INV-5. (M) — gate.

**Gate Fase 7:** fechamento gera relatório correto; dia fechado é imutável. Const. Art. VIII verificada.

---

## Fase 8 — Relatório semanal

Meta: janela dos últimos 7 dias encerrados com totais, médias e narrative.

- [ ] **T-801** — Migration `weekly_reports`. (S)
- [ ] **T-802** — `WeeklyReportService.generate(user)`: seleciona 7 dias fechados mais recentes, agrega SQL, gera narrative, upsert por `(user_id, window_start, window_end)`. (M) — SP-110, SP-111, SP-112, SP-113, INV-8.
- [ ] **T-803** — `GET /weekly` + dispatcher `weekly_summary`. (S)
- [ ] **T-804** — Frontend `/weekly` com tabela cronológica. (M) — SP-113.
- [ ] **T-805** — Testes: SP-110 a SP-113, INV-8. (M) — gate.

**Gate Fase 8:** semanal funcional; agrega apenas dias fechados.

---

## Fase 9 — Hardening e deploy

Meta: sistema pronto para VPS com HTTPS, backups, e restart resiliente.

- [ ] **T-901** — `docker-compose.production.yml` finalizado (§14 do plano). (S)
- [ ] **T-902** — `infra/nginx/nginx.conf` + `conf.d/app.conf` com HSTS/CSP. (S)
- [ ] **T-903** — Certbot webroot + cronjob de renovação. (S)
- [ ] **T-904** — `scripts/backup-postgres.sh`, `scripts/backup-minio.sh`, `scripts/restore-postgres.sh` testados em dry-run. (M)
- [ ] **T-905** — `scripts/bootstrap.sh` de deploy (migration + bootstrap idempotentes). (S)
- [ ] **T-906** — Health check externo (healthchecks.io) + doc. (S)
- [ ] **T-907** — Checklist de segurança §16 do plano executado; issues abertas para pendências. (M)
- [ ] **T-908** — Deploy real numa VPS de staging; smoke test manual do cenário-âncora. (L) — gate MVP.

**Gate Fase 9:** MVP em produção; §19 do plano (critérios de aceite) todos verdes.

---

## Backlog (pós-MVP, `may`)

- **B-01** — Persistência agregada de `sugars_g`, `added_sugars_g`, `saturated_fat_g`, `trans_fat_g`.
- **B-02** — Leitura de código de barras (client-side + LLM fallback).
- **B-03** — Integração Apple Health / Google Fit.
- **B-04** — Reabertura de dia encerrado com auditoria especial.
- **B-05** — Notificações (push/email/Telegram) sobre encerramento pendente.
- **B-06** — Exportação CSV/PDF do diário e semanal.
- **B-07** — Multi-usuário + cadastro público (envolve emenda constitucional).
- **B-08** — PWA offline com fila de mensagens.
- **B-09** — Migrar fila para RQ/Dramatiq quando >1 usuário concorrente.

---

## Histórico

- **2026-07-15** — v1.0. Estrutura inicial. Fase 0 marcada como done. Total: 47 tarefas ativas + 9 backlog.
