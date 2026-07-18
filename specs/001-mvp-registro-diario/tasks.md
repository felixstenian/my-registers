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

## Fase 2 — Mensagens e upload de mídia ✅

Meta: usuário envia mensagem por chat com texto e/ou fotos; backend persiste sem chamar LLM ainda (mock).

Status: **done** (branch `feat/fase-2-messages-media`). 36 testes verdes (SP-10, SP-11, SP-12, SP-92 + SP-01..06 da Fase 1); lint verde.

- [x] **T-201** — Migration `0002_chat_and_media.py`: `day_logs` (UNIQUE user_id+log_date, trigger `set_updated_at`), `messages` (GIN em `raw_llm_response`, `(user_id, created_at DESC)`), `media` (UNIQUE `storage_key`), `message_media` n:n. Models correspondentes.
- [x] **T-202** — `integrations/storage/minio.py`: boto3 S3v4, `put_object` e `presigned_get_url` em thread pool (`asyncio.to_thread`), `make_storage_key(uid, ext)` gera `users/{uid}/media/{yyyy}/{mm}/{uuid}.{ext}`. `S3_PUBLIC_BASE_URL` opcional troca host da URL assinada em prod (MinIO interno + Nginx público).
- [x] **T-203** — `POST /media` (multipart): allowlist `image/jpeg|png|webp`, size ≤ 8MB, decode probe com Pillow (rejeita corpo não-imagem via `verify()`), SHA-256, persiste com `status='uploaded'`, `width`/`height`. Const. §22.
- [x] **T-204** — `DayLogRepository.get_or_create` idempotente com `INSERT ... ON CONFLICT DO NOTHING`. `ChatService.post_user_message` valida ownership dos `media_ids` (Const. §21) e usa `ZoneInfo(user.timezone)` para SP-92. `list_messages` paginada por `after`/`before` com âncoras que respeitam a ordem cronológica.
- [x] **T-205** — `POST /chat/messages` → 202 `{message_id, status:"processing"}`; `GET /chat/messages?after=<id>&before=<id>&limit=<n>` com URLs assinadas na resposta.
- [x] **T-206** — Página `/chat` no frontend: lista mensagens (auto-scroll), textarea + input file (accept `image/*`, cap 4 arquivos), upload em paralelo → POST mensagem, **polling `after=<lastId>` a cada 1.5s com cap 30s** (para quando a assistant response chegar na Fase 3).
- [x] **T-207** — 18 novos testes de integração (`test_media.py` + `test_chat.py`): upload happy path (PNG/JPEG), MIME não suportado, imagem falsa, arquivo grande, auth requerida; envio 202, empty message rejeitada, link com 2 mídias, limite de 4, isolamento cross-user (Const. §21), listagem cronológica, `after`, `before`, URLs de mídia; SP-92 cria e reutiliza `day_log` da data local do usuário. `FakeStorage` em memória substitui MinIO via `dependency_overrides`.

**Gate Fase 2 — cumprido:** mensagens persistem, mídia sobe pro MinIO com URL assinada, chat funcional sem LLM. Const. §21-22 verificadas.

---

## Fase 3 — Integração Anthropic ✅

Meta: LLM interpreta mensagens, devolve JSON validado por Pydantic, sem persistir registros nutricionais ainda (LabelCatalogService/MealService vêm na Fase 4).

Status: **done** (branch `feat/fase-3-anthropic-integration`). 51 testes verdes (15 novos de LLM cobrindo SP-13, SP-14, INV-9); lint verde.

- [x] **T-301** — `app/integrations/anthropic/client.py`: `AsyncAnthropic` com timeout 60s, `max_retries=2` (delega retries 5xx/429 pro SDK), extract `tool_use` block. `MinioStorage.get_object` adicionado para download da mídia; base64 feito no cliente. Const. Art. II.
- [x] **T-302** — `app/schemas/llm.py` com `LLMEnvelope` (`extra=forbid`) + `FoodItemIn`, `WaterIn`, `BeverageIn`, `ActivityIn`, `CorrectionIn`, `DeletionIn`, `NutritionLabelIn` (com validator do `per_serving`). Prompt `system_v2.md` (18 regras) + `tool_schema.py`. `cache_control: ephemeral` no system + tool para prompt caching.
- [x] **T-303** — `tool_choice={"type":"tool","name":"record_intent"}` força o uso. Retry semântico: no `ValidationError`, envia `assistant` (response) + `user` com o erro Pydantic para até 2 tentativas antes de virar `validation_exhausted`. INV-9: bloco não-`tool_use` → `no_tool_use` (também é erro).
- [x] **T-304** — `app/services/intent_dispatcher.py`: `clarify`/`unknown` → `DispatchResult` com content. `log_food`/`log_water`/... → `IntentNotImplemented(intent)`. Enum desconhecido cai em `unknown`.
- [x] **T-305** — `MessageProcessor` + `run_processor_in_background`. Injeção do `session_factory` como dep FastAPI (evita reutilizar `SessionLocal` do módulo em testes com loops diferentes). Handler comita **antes** de agendar a task (BackgroundTasks rodam antes do cleanup da dep de sessão). Persiste `raw_llm_response` completo + tokens + `llm_intent`/`llm_model`/`llm_prompt_version`.
- [x] **T-306** — `tests/test_llm_flow.py`: 15 casos com `FakeAnthropicClient` injetado. Cobre SP-13 (clarify com pergunta amigável, não cria negócio), SP-14 (timeout, 500, 429, `no_tool_use`, `validation_exhausted` → assistant "não consegui" + `raw_llm_response.error` preservado), intents estruturados → `NotImplemented` amigável, mídia é baixada e forwardada em base64, fluxo end-to-end via `GET /chat/messages`. `no_queued_result` é sentinela para testes que não exercem LLM (não polui `test_chat.py`).

**Gate Fase 3 — cumprido:** LLM responde no chat com clarify/unknown; sem persistir registros; fluxo de retry semântico e fallback de erro cobertos.

---

## Fase 4 — Registro de alimentos ✅

Meta: `log_food` cria registros nutricionais com cálculos determinísticos do backend.

Status: **done** (branch `feat/fase-4-food-registry`). 79 testes verdes (28 novos cobrindo SP-20..SP-26 + INV-1 + INV-4 + INV-10); lint verde.

- [x] **T-401** — Migration `0003_food_catalog_snapshots.py`: `food_records` (FK RESTRICT em day_log_id), `food_items` (macros/micros materializados), `nutrient_facts` (aliases GIN + canonical_name index), `daily_snapshots` (UNIQUE day_log_id + version), `audit_events` (JSONB before/after, GIN opcional futuro). Triggers `set_updated_at` reutilizados.
- [x] **T-402** — `integrations/nutrition/`: `NutritionCatalog` Protocol + `LocalTBCACatalog` com precedência (marca exata > TBCA > label_ocr > manual > verified_by_user > mais recente). `normalize_name` remove acentos + slug + singulariza plurais BR simples.
- [x] **T-403** — `seed_tbca.csv` com 31 alimentos BR (arroz, feijão preto/carioca, frango peito/coxa, ovo, pão francês/integral, banana, maçã, laranja, mamão, batata, mandioca, tomate, alface, brócolis, queijo, iogurte, carne, salmão, azeite/óleo…). CLI `python -m app.cli seed-nutrition` idempotente.
- [x] **T-404** — `services/nutrition_calculator.py`: `compute(hit, grams, ml)` puro. `per_100g` × grams/100; `per_100ml` × ml/100; sem hit → zeros com `reasons`. Cobertura 100% via `test_nutrition_calculator.py` (10 casos unit).
- [x] **T-405** — `MealService.create_from_llm`: uma `food_record` por envelope; para cada `FoodItemIn` lookup no catálogo, cálculo determinístico, persist `food_items` com materialização. Flag `needs_confirmation=True` se `confidence<0.5` ou sem catálogo. Grava `audit_events(actor='llm', action='create', after={meal_slot, occurred_at, item_ids})`.
- [x] **T-406** — `DailyRecomputeService.recompute(day_log_id)`: SUM sobre `food_items` vivos + JOIN em `food_records` vivos. Upsert em `daily_snapshots` por UNIQUE(day_log_id) com `version = c.version + 1` em conflito. `execution_options(populate_existing=True)` no RETURNING para forçar refresh do identity map (senão a 2ª recompute do mesmo dia devolve o snapshot cacheado da 1ª). Warnings agregam itens sem catálogo + `needs_confirmation`.
- [x] **T-407** — `MessageProcessor._handle_log_food` chama `MealService` → `DailyRecompute` → cria assistant message com resumo factual dos itens + totais + aviso legal (Const. Art. VII §26 antecipado). `IntentDispatcher` deixa de listar `log_food` como estruturado. Fluxo end-to-end coberto em `test_log_food_flow.py`.
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

## Fase 5 — Hidratação e atividades ✅

Meta: registrar água, outros líquidos e atividades; snapshot inclui todos.

Status: **done** (branch `feat/fase-5-hydration-beverage-activity`). 108 testes verdes (29 novos cobrindo SP-40..42, SP-50..52, SP-60..64, INV-2, INV-3); lint verde.

- [x] **T-501** — Migration `0004_hydration_beverage_activity.py`: `water_records` (schema **sem** kcal/macros — INV-2 estrutural), `beverage_records` (macros/micros materializados + FK opcional para nutrient_facts), `activity_records` (met_value, kcal_burned, calc_method). Triggers `set_updated_at` reutilizados.
- [x] **T-502** — `HydrationService.create_from_llm` — cria `water_records`. Análise defensiva do `user_text_summary` (com acentos removidos) contra café/leite/suco/refrigerante/álcool → `ValidationAppError(water_intent_rejected)`; MessageProcessor traduz em clarify (SP-41).
- [x] **T-503** — `BeverageService.create_from_llm` — `LocalTBCACatalog` + `NutritionCalculator` (per_100ml). Materializa kcal/macros/micros. `needs_confirmation` idem MealService. Adicionadas 4 bebidas ao `seed_tbca.csv` (café coado, leite integral, suco de laranja, refrigerante cola).
- [x] **T-504** — `ActivityCalculator` — tabela MET × intensidade para 7 tipos comuns (cardio_run/walk, bike, swim, strength, yoga, cardio genérico). `estimate_duration_from_distance` para SP-63. 11 casos unit cobrem SP-60/SP-64/SP-63.
- [x] **T-505** — `ActivityService.create_from_llm` — chama calculator; `WeightRequired` levantado se `users.weight_kg` null (SP-61). SP-62: strength com `unknown` intensity usa MET moderate no cálculo mas grava `unknown` no registro. SP-63: sem duration + com distance → estima por velocidade média.
- [x] **T-506** — `DailyRecomputeService` estende para agregar `water_ml` (WaterRecord), `other_liquids_ml` + kcal_in + macros (BeverageRecord), `kcal_out` (ActivityRecord). `kcal_balance = kcal_in - kcal_out`. Warnings agregam entidades por tabela (`entity` field). INV-2/INV-3 garantidos: água nunca em kcal_in, bebida calórica nunca em water_ml.
- [x] **T-507** — `MessageProcessor._handle_registration` unifica log_food/log_water/log_beverage/log_activity. `IntentDispatcher` deixa de listar os quatro como estruturados. `ValidationAppError`/`WeightRequired` viram assistant clarify amigáveis.
- [x] **T-508** — Testes: `test_activity_calculator.py` (11 unit), `test_hydration_beverage_activity.py` (10 integração), `test_log_liquids_activity_flow.py` (6 end-to-end incluindo mix de 4 registros num dia com kcal_in + kcal_out + water_ml + other_liquids_ml corretos).

**Gate Fase 5 — cumprido:** os três novos tipos de registro funcionam; snapshot completo. Const. Art. IV verificada por teste (INV-2/INV-3).

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
