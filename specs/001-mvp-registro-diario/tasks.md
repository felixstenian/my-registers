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
- [x] **T-408** — `GET /days/today`, `GET /days/{date}` implementados em `app/api/routes/days.py:33` (today) e `:52` (by date). Ambos retornam `DaySnapshotOut` com `records` populados. SP-90/91/92 cobertos.
- [x] **T-409** — Frontend renderiza **totals** via `DayTotalsBar` (SP-116 do Bloco 2) — a barra do chat consome `GET /days/today` com revalidação por assinatura de nova assistant message e após confirmação de items pendentes. Renderização detalhada de `records` item-a-item numa página dedicada **não foi entregue no MVP** mas foi **revivida pelo Bloco 6** (log fechado): `/day` + `/day/[date]` entregam a visão item-a-item do dia (ver seção Bloco 6, SP-150..SP-155). O remark "opcional para o MVP" deixou de valer — a necessidade virou real após o bug do catálogo zerado em prod (#37), e a tarefa `T-409b` sugerida nesta avaliação foi materializada como Bloco 6.
- [x] **T-410** — Testes SP-90/91/92 cobertos em `tests/test_day_close_report.py::test_get_today_returns_empty_snapshot_when_no_records`, `::test_get_today_reflects_registered_food`, `::test_get_by_date_not_found_returns_404`, `::test_get_by_date_open_day_returns_status_open`, `::test_get_today_uses_user_timezone_not_utc`. SP-20..SP-26 cobertos em `tests/test_log_food_flow.py` + `tests/test_meal_service.py`. INV-1 (LLM não soma) coberto em `tests/test_nutrition_calculator.py` + integração do log_food que testa retornos determinísticos mesmo com LLM mentindo. Gate cumprido.
- [x] **T-411** — SP-24 chat-side (SP-24a): intent `confirm_items` + `ConfirmationService`. Feedback do teste manual do café-da-manhã mostrou loop de "confirmo esses itens" caindo em clarify ou re-registrando. Envelope aceita `scope='all'|'specific'` + `target_hints`; audit `action='confirm'` (migration 0006 acrescenta ao CHECK); não recomputa snapshot. Testes em `tests/test_confirm_items.py`. (M) — SP-24.

**Gate Fase 4 — cumprido:** registrar alimento por texto funciona ponta-a-ponta; snapshot atualiza; totais renderizam via `DayTotalsBar` (SP-116). Página `/days/[date]` detalhada foi conscientemente deixada de fora do MVP (ver T-409 acima). Const. §5-6, §10.

---

## Fase 4.b — Leitura de tabela nutricional ✅

Meta: cadastrar produtos via foto de rótulo; opcionalmente registrar consumo na mesma mensagem.

- [x] **T-421** — Migration acrescentando `barcode`, `label_media_id`, `verified_by_user` a `nutrient_facts`; source enum já inclui `label_ocr`. **Já entregue na Fase 4 (migration 0003)** — sem migration nova.
- [x] **T-422** — Prompt `system_v2.md` já traz regras 16-18 para `log_nutrition_label` + `NutritionLabelIn` no `app/schemas/llm.py`. **Já entregue na Fase 3**.
- [x] **T-423** — `app/services/label_catalog.py::LabelCatalogService.upsert_from_label`. Escala `per_serving` (via `serving_size_g|ml`) para `per_100g|ml` deterministicamente. Idempotência: mesmo `barcode` (ou `canonical_name`+`brand`) → UPDATE. `verified_by_user=true` nunca é rebaixado por reupload. Warning `micros_missing_for_product` quando Ca/Fe/K nulls (SP-34). (M) — SP-30, SP-32, SP-34.
- [x] **T-424** — `MessageProcessor._handle_nutrition_label`. Se `also_consumed` presente: `LabelCatalogService.register_consumption` cria `food_record` + `food_item` apontando pro fact recém-criado + dispara recompute. `IntentDispatcher._STRUCTURED_INTENTS` fica vazio. (M) — SP-31.
- [x] **T-425** — `PATCH /nutrient-facts/{id}` (`app/api/routes/nutrient_facts.py`). Rejeita fatos com `source='TBCA_2023'` ou `USDA_FDC` (não editáveis) com 422 `not_editable`. Sempre marca `verified_by_user=true`, mesmo sem valor novo (confirmação implícita). Audit event `action='update'`, `actor='user'`. (S) — SP-33.
- [x] **T-426** — Frontend: `MessageOut` expõe `nutrient_fact_id`; botão "Confirmar cadastro do produto" aparece só sob assistant messages com `llm_intent='log_nutrition_label'`. Após clique vira "Confirmado ✓" (state local; refresh mostra novos cards se houver). (S) — SP-33 UI.
- [x] **T-427** — `tests/test_label_catalog.py` (17 casos): upsert cria + idempotência por barcode + preserva `verified` no reupload; normalização `per_serving` 34g → per_100g; `per_serving` sem serving_size rejeitado no schema; `micros_missing_for_product` emitido/omisso; `also_consumed` cria food_record; `PATCH` marca verified + audit; PATCH rejeita TBCA/USDA; PATCH 404; precedência de lookup TBCA vs label_ocr; `MessageOut.nutrient_fact_id` populado só quando aplicável. (M) — gate.

**Gate Fase 4.b — cumprido:** upload de foto de rótulo cadastra produto reutilizável; consumo opcional funciona; precedência TBCA > label_ocr respeitada; usuário confirma via UI. Const. Art. II §5 (LLM só interpreta), §22 (audit), §35 (precedência).

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

## Fase 6 — Correções e remoções ✅

Meta: usuário corrige e remove registros por chat com auditoria completa.

Status: **done** (branch `feat/fase-6-corrections-deletions`). 154 testes verdes (17 novos cobrindo SP-70..82 + INV-4/5/10); lint verde.

- [x] **T-601** — `services/correction_matcher.py` (TargetMatcher, kind_hints, meal_slot_hints, score) + `services/correction.py` (CorrectionService). Matching por token overlap + qualificador. Recompute macros via Calculator se `grams`/`ml` mudou. `source` vira `user_corrected`. Audit `action='correct'` com before/after.
- [x] **T-602** — `services/deletion.py` (DeletionService). Soft delete via `deleted_at`. `apply_from_llm` usa matcher; `delete_by_id` para path REST direto. Idempotente (`already_deleted=True` no 2ª chamada). Audit `action='delete'`.
- [x] **T-603** — `MessageProcessor._handle_correction_or_deletion` roteia intent `correct_record`/`delete_record`. `AmbiguousTarget` → assistant clarify listando candidatos. `NoTargetFound` → clarify pedindo mais detalhes. `DayClosedError` → clarify explicando dia encerrado. Recompute automático pós-mutação.
- [x] **T-604** — `api/routes/records.py`: `DELETE /records/food-items|water|beverage|activity/{id}` (200 sempre, idempotente por SP-81); `PATCH /records/food-items/{id}` com update parcial + recompute + audit. 409 se dia closed; 404 se não achou.
- [x] **T-605** — `tests/test_corrections_deletions.py` (17 casos): matcher (unambiguous/ambiguous/qualified/no-target), CorrectionService (grams update recompute, audit trail, ambiguous no-op, closed day), DeletionService (soft delete + audit, closed day), REST endpoints (delete, idempotência, 409, PATCH recompute), INV-4 (snapshot recomputa após correction/deletion via chat), ambiguidade via chat vira clarify. Helper `_day_log` resolve pela timezone do user (não UTC) para casar com o `ChatService`.

**Gate Fase 6 — cumprido:** correções e exclusões seguras, com trilha de auditoria. Const. Art. III §11 e Art. VIII §28 verificadas.

---

## Fase 7 — Encerramento e relatório diário ✅

Meta: fechar o dia por chat, gerar narrative sobre totais calculados.

- [x] **T-701** — `POST /days/{date}/close` idempotente + recompute forçado + snapshot com `warnings` agregados (via `DayCloseService`). (M) — SP-100, SP-101, SP-102.
- [x] **T-702** — Geração de `narrative` via `AnthropicClient.call_narrative` alimentada por totais já calculados (segunda chamada, temperature=0.3, sem tool_use). `narrative` é armazenada em `daily_snapshots.narrative` (migration 0005) e o disclaimer é concatenado por `_with_disclaimer` no service. (M) — SP-103, SP-104, Const. §26.
- [x] **T-703** — Dispatcher `close_day` e `query_day` movidos para o `MessageProcessor` (fora do `IntentDispatcher` estruturado); chamam `DayCloseService.close_today` / `DayQueryService.get_today`. (S)
- [x] **T-704** — Frontend: botão "Encerrar dia" no `DayTotalsBar` (aparece só se `status='open'`; badge "Dia encerrado" quando `status='closed'`). Modal `CloseDayModal` em 4 fases (confirm → submitting → done | error). No estado `done`, renderiza os `totals` finais + `narrative` da LLM + contador de warnings + link "Ver semana". Idempotência SP-101 tratada com título "Este dia já estava encerrado" quando `was_already_closed=true`. (M)
- [x] **T-705** — `tests/test_day_close_report.py` (17 casos): SP-90 (empty + records), SP-91 (404 + open), SP-92 (timezone), SP-100 (close via chat), SP-101 (idempotência preserva `closed_at`/`snapshot_version`/`narrative`), SP-102 (recompute pré-close reflete records tardios), SP-103 (payload de totals sem IDs para a LLM), SP-104 (disclaimer sempre presente + fallback LLM + não-duplicação), INV-5 (correction/deletion bloqueados + leitura congelada), INV-10 (audit event `action='close'`), `query_day` via chat. (M) — gate.

**Gate Fase 7 — cumprido:** fechamento gera relatório correto e idempotente; dia fechado é imutável; UI de encerramento entregue em T-704. Const. Art. III §10 (INV-4), Art. VIII §28 (INV-5), §26 (disclaimer) e §22 (audit) verificadas.

---

## Fase 8 — Relatório semanal ✅

Meta: janela dos últimos 7 dias encerrados com totais, médias e narrative.

- [x] **T-801** — Migration `0007_weekly_reports.py`: `weekly_reports` com `totals`/`averages`/`per_day`/`warnings`/`snapshot_versions` JSONB, `UNIQUE(user_id, window_start, window_end)`, trigger `set_updated_at`. `window_start`/`window_end` nullable para permitir report transiente quando o usuário ainda não fechou nenhum dia. (S)
- [x] **T-802** — `WeeklyReportService.generate(user)`: seleciona até 7 dias fechados mais recentes, agrega totals/averages sobre `daily_snapshots`, ordena `per_day` ASC (SP-113), reusa row existente se `snapshot_versions` bater (SP-112), gera narrativa via `AnthropicClient.call_weekly_narrative` (T-802) e concatena disclaimer. Upsert por `(user_id, window_start, window_end)`. Sem dias fechados → devolve report transiente com warning `insufficient_history` (não persiste). (M) — SP-110, SP-111, SP-112, SP-113, INV-8.
- [x] **T-803** — `GET /weekly` + dispatcher `weekly_summary`. Rota registra a rota `weekly.router` no `main.py`; `MessageProcessor._handle_weekly_summary` roteia o intent para o `WeeklyReportService`. `IntentDispatcher` removeu `weekly_summary` de `_STRUCTURED_INTENTS`. (S)
- [x] **T-804** — Frontend `/weekly` (rota protegida no proxy) com: header + janela `window_start` a `window_end`; banner `insufficient_history` quando <7 dias fechados; grid "Totais da semana" e grid "Médias diárias"; tabela `per_day` ordenada ASC (SP-113) com colunas Dia/Cal.in/Cal.out/Saldo/P/C/G/Água; narrativa da LLM; disclaimer Art. VII §26. Link "Semana" adicionado ao header do `(app)/layout`. Fetch client-side pra evitar SSR obsoleto quando o usuário mudar sessão. Estado vazio (`days_included=0`) mostra CTA amigável. (M) — SP-113.
- [x] **T-805** — `tests/test_weekly_report.py` (14 casos): SP-110 (empty + <7 + 9→7), SP-111 (totais determinísticos + LLM lies ignoradas), SP-112 (2ª call reusa mesmo id + version bump quando snapshot muda), SP-113 (per_day ordenado ASC), INV-8 (open days ignorados), disclaimer sempre presente, endpoint `GET /weekly`, chat via intent `weekly_summary`, chat sem dias fechados, isolamento cross-user. (M) — gate.

**Gate Fase 8 — cumprido:** semanal funcional; agrega apenas dias fechados (INV-8); UI `/weekly` entregue em T-804. Const. Art. II §5 (LLM não soma), §10 (recompute), §26 (disclaimer), §30 (janela 7 dias).

---

## Fase 9 — Hardening e deploy ✅

Meta: sistema pronto para VPS com HTTPS, backups, e restart resiliente.

- [x] **T-901** — `docker-compose.production.yml`: nginx (portas 80/443), certbot loop de renovação, postgres/minio em rede interna, `minio-init` idempotente para bucket, `env_file: .env.production`, healthchecks em todos os serviços, `json-file` logs com rotação (`max-size=10m, max-file=5`). (S)
- [x] **T-902** — `infra/nginx/nginx.conf` + `conf.d/app.conf` com HSTS (1 ano), CSP mínimo para Next.js + Tailwind, X-Content-Type-Options, X-Frame-Options DENY, Referrer-Policy, Permissions-Policy, OCSP stapling, TLSv1.2+ com `HIGH:!aNULL:!MD5`, `client_max_body_size 15m`. (S)
- [x] **T-903** — `infra/certbot/README.md` com runbook de emissão inicial (staging → prod), instrução de placeholder HTTP pra 1ª emissão, comandos de renovação forçada e debug comum. (S)
- [x] **T-904** — `scripts/backup-postgres.sh` (pg_dump -Fc + retenção 14d + rclone opcional off-VPS), `scripts/backup-minio.sh` (mc mirror + retenção + rclone), `scripts/restore-postgres.sh` (destrutivo com confirmação de 5s + DRY_RUN flag). Chmod +x aplicado. (M)
- [x] **T-905** — `scripts/bootstrap.sh`: `alembic upgrade head` + `python -m app.cli bootstrap` idempotentes; valida `.env.production` antes de rodar. INV-6: runtime da API não roda migrations. (S)
- [x] **T-906** — Health check externo documentado em `docs/deploy.md` §9 (healthchecks.io + cron `*/5 * * * *` fazendo ping do `/api/health`). (S)
- [x] **T-907** — Checklist de segurança §16 completo em `docs/deploy.md` §12 (13 itens ✅ + 5 itens ainda para operador validar: rclone, fail2ban, unattended-upgrades, docker prune, auditoria de logs). `.gitignore` atualizado com `.env.production`. `.env.production.example` com todas as variáveis de §14.1 do plano. (M)
- [x] **T-908** — Deploy real executado em VPS DigitalOcean (Ubuntu 24.04, droplet Basic 2 vCPU / 2 GB) via runbook `docs/vps-digitalocean.md`. Domínio de produção: `myregister.felix.dev.br` (DNS na Vercel, subdomínio A pra IP do droplet). TLS Let's Encrypt emitido pós-hotfix D-01 (entrypoint certbot). Smoke test do cenário-âncora executado no browser (login → chat → registro → encerramento → semanal). Deploys posteriores: v1.1 (Bloco 4 PWA), v1.2 (seed TBCA + docs). Sessão de deploy inicial produziu 3 hotfixes rastreados (#24 build Next 16, #25 server-side fetch, config nginx/certbot manual em D-01).

**Gate Fase 9 — cumprido:** todos os artefatos de código, docs e o deploy real estão em produção. Const. §14 e Art. VI §24 verificados no campo.

---

## Fase 10 — CI/CD ✅ (parcial — aguarda config no GitHub e VPS)

Meta: eliminar o deploy manual + garantir que nenhum PR quebrado entre em `dev`/`main`. Decisão registrada em **ADR-012**: GitHub Actions em dois workflows separados. **Não bloqueia MVP** — sem sofrimento enquanto Felix for solo dev; começa a doer quando: (a) segundo colaborador entra, (b) frequência de deploy > 2/semana, ou (c) algum teste local for esquecido antes de mergear.

Pré-requisitos: T-908 concluído (VPS de produção rodando) e `docs/deploy.md` §10 funcionando manualmente end-to-end. **Ambos ✅.**

- [x] **T-1001** — `.github/workflows/ci.yml` job `api`: Postgres 16 como service (env `POSTGRES_USER=registers_app`, `POSTGRES_PASSWORD=dev_password`), health check via `pg_isready`. Steps: checkout, `setup-uv@v5` com cache, `uv python install 3.12`, `uv sync --frozen`, `uv run ruff check app tests`, `uv run ruff format --check app tests`, `uv run pytest -q`. `concurrency.group=ci-${{ github.ref }}` com `cancel-in-progress: true` (cancela runs antigos ao push). Cache do uv via `enable-cache: true`. Timeout 15 min. (S)
- [x] **T-1002** — `.github/workflows/ci.yml` job `web` em paralelo com `api`: `pnpm/action-setup@v4` (pin 10.12.1, casa com `packageManager` do `package.json`), `setup-node@v4` Node 20 + cache pnpm, `pnpm install --frozen-lockfile`, `pnpm --filter web typecheck`, `pnpm --filter web build` (webpack — Serwist ainda não suporta Turbopack) com env vars dummy pra passar no compile-time, `pnpm --filter web verify:sw` (INV-11). Timeout 15 min. (S)
- [ ] **T-1003** — Branch protection em `main`. **Config manual** via UI: Settings → Branches → Add rule → `main`, require status checks `api (ruff + pytest)` + `web (typecheck + build)`, require branches up-to-date, no direct pushes. Instruções detalhadas em `docs/deploy.md` §14.2. Aguarda operador acionar via UI. (S)
- [ ] **T-1004** — Chave SSH `deploy-only` na VPS. **Config manual** conforme `docs/deploy.md` §14.2: gerar par `ed25519` no laptop, prepend `command="..."` ao `~/.ssh/authorized_keys` do usuário `felix` com restrições `no-port-forwarding,no-x11-forwarding,no-agent-forwarding,no-pty`. Private key vai como GitHub Secret `DEPLOY_SSH_KEY`. Aguarda operador. (S)
- [x] **T-1005** — `.github/workflows/deploy.yml`: gatilho `workflow_run` em `ci` types `[completed]` branches `[main]`. Filtra por `github.event.workflow_run.conclusion == 'success'` (workflow_run dispara mesmo se ci falhou). Steps: `webfactory/ssh-agent@v0.9.0` com `DEPLOY_SSH_KEY`, `ssh-keyscan` do `DEPLOY_HOST` pra known_hosts, `ssh felix@$DEPLOY_HOST true` (dispara o command restringido). Timeout 10 min. `concurrency.group=deploy-production, cancel-in-progress=false` (um deploy por vez). `environment: production` com `url` — deploys aparecem na aba Deployments do GitHub. (M)
- [x] **T-1006** — `docs/deploy.md` §14 (novo, subsecões 14.1 a 14.5): fluxo `feature branch → PR dev → CI → merge; dev → PR main → CI → merge → deploy.yml → prod`; setup completo de chave SSH deploy-only na VPS + `authorized_keys` com `command="..."`; secrets/variables no GitHub (`DEPLOY_SSH_KEY` secret + `DEPLOY_HOST`/`DEPLOY_DOMAIN` variables); branch protection passo-a-passo; debug (`gh run list --workflow=deploy.yml`, `gh run view --log`); rollback via `git revert`; quando pausar o CD (GitHub Actions down, rotação de segredo, migration não-reversível). (S)
- [x] **T-1007** — Smoke test em `deploy.yml`: loop de 12 tentativas × 5s (60s total) batendo em `https://$DEPLOY_DOMAIN/api/health` com `curl -fsS --max-time 5`. Sai 0 no primeiro 200; sai 1 após 60s. Containers ficam de pé mesmo em fail — rollback manual pelo dev. (S)

**Gate Fase 10 — parcial (código pronto):** workflows `ci.yml` e `deploy.yml` em `.github/workflows/`; docs completa em `docs/deploy.md` §14. **Falta config no GitHub UI (T-1003) e na VPS (T-1004)** — não é possível fazer via commit. Depois disso, o próximo merge em `main` dispara deploy automatizado.

**Não incluído (fixado em ADR-012):**
- Testes E2E (Playwright) — carga de manutenção alta pra 1 dev.
- Signed commits gate.
- Preview environments por PR.
- Cache de imagens Docker no GHCR (build atual é ~2 min, aceitável).
- Watchtower / ArgoCD / GitOps sofisticado.

---

## Bloco 1 — Composer/envio (chat quality-of-life) ✅

Meta: melhorar UX do compositor de mensagens no `/chat`. Todas SPs `may` (pós-MVP), zero impacto no backend.

- [x] **T-B101** — SP-15: `Enter` envia, `Shift+Enter` quebra linha, tecla é ignorada durante envio em curso ou compositor vazio. Considera composição IME (`event.nativeEvent.isComposing`).
- [x] **T-B102** — SP-16: `capture="environment"` no `<input type="file">` para sugerir câmera traseira no mobile (ignorado em desktop, comportamento continua sendo file picker).
- [x] **T-B103** — SP-17: cap client-side de 4 anexos com feedback por nome. `mergeFiles(incoming, mode)` — `replace` para o input file, `append` para drop. Nomes excedentes listados em bloco de erro amigável.
- [x] **T-B104** — SP-18: erros por-arquivo (`file_too_large`, `invalid_image`, `unsupported_media_type`, `empty_upload`) traduzidos para pt-BR com o nome do arquivo. Batch de upload não aborta por causa de um item — anexos válidos continuam. Compositor não perde o texto digitado. Cap de 8 MB validado também no `mergeFiles` (client-side) para feedback imediato antes do upload.
- [x] **T-B105** — SP-19: drag-and-drop com feedback visual (borda tracejada + fundo), contador de dragenter/leave para evitar flicker. Aplica mesmas regras de MIME/cap.
- [x] **T-B106** — Lista de chips por arquivo com botão remover (`×`) e reset do `input.value` após seleção para permitir re-selecionar o mesmo arquivo.

**Gate Bloco 1 — cumprido:** `pnpm typecheck` verde; smoke manual (Felix) das cinco SPs.

---

## Bloco 2 — Renderização de assistant messages (SP-115..118) ✅

Meta: transformar as respostas do assistant em cards estruturados legíveis + barra fixa com totais do dia + confirmação inline de itens pendentes.

- [x] **T-B201** — SP-118: `app/services/message_formatter.py` com helpers `_fmt_int/_fmt_dec/_fmt_kcal/_fmt_g/_fmt_ml/_fmt_min` (pt-BR), `_table` (markdown 2-cols), `_daily_totals_table` (comum a todos os intents), `_warnings_block` (dedup preservando ordem). `compose_meal/water/beverage/activity` seguem a spec: cabeçalho pt-BR + 1ª tabela (só do registro atual) + 2ª tabela (`Total acumulado — DD/MM/YYYY`) + disclaimer + bloco de warnings opcional. `MessageProcessor._handle_registration` delega às novas funções passando `local_today(user.timezone)`. `≈` só aparece em linhas nutricionais quando pelo menos 1 item é estimativa ou precisa de confirmação; água/volume nunca recebem `≈`. `Líquidos Totais*` recebe asterisco quando `other_liquids_ml > 0`, com nota em rodapé.
- [x] **T-B202** — SP-115: `apps/web/src/app/(app)/chat/AssistantContent.tsx` — parser mínimo de markdown (bold + tabelas + parágrafos) que renderiza cada tabela como card com header destacado. Suporta detecção de células com `≈` (italic) e labels com `*` (amber accent). Sem dependência de biblioteca de markdown externa — bundle enxuto, dialeto controlado pelo backend.
- [x] **T-B203** — SP-116: `apps/web/src/app/(app)/chat/DayTotalsBar.tsx` — fixado acima da lista de mensagens; consome `GET /days/today`; revalida via prop `revalidateKey` incrementado pelo `page.tsx` a cada nova assistant message detectada pelo poll. Colapsa horizontalmente em telas pequenas (`overflow-x-auto`). Estado vazio quando `kcal_in=0` && sem líquidos. Badge de warnings clicável (`N itens precisam de confirmação`) dispara callback do pai.
- [x] **T-B204** — SP-117: `apps/web/src/app/(app)/chat/PendingItemsModal.tsx` — modal (overlay + trap) listando `food_items` com `needs_confirmation=true` puxados do `GET /days/today`. Botão **Confirmar** re-envia grams/ml/quantity atuais via `PATCH /records/food-items/{id}` (backend recomputa macros e limpa `needs_confirmation`); botão **Descartar** dispara `DELETE /records/food-items/{id}` (soft delete + recompute). Sinaliza `onChanged()` que revalida a barra de totais e fecha o modal.
- [x] **T-B205** — `tests/test_message_formatter.py` (18 casos): formatação pt-BR de int/dec/kcal/g/ml/min; `compose_meal` pt-BR do slot, agregação só de items da mensagem, `≈` presente/ausente conforme is_estimate/needs_confirmation, warnings depois do disclaimer, `Calorias Gastas`/`Saldo` só quando `kcal_out > 0`; `compose_water` sem `≈`; `compose_beverage` com linha `Volume` + `Líquidos Totais*`; `compose_activity` com `Duração` + hint `informado pelo dispositivo`; cabeçalho `Total acumulado — DD/MM/YYYY` da data local. Suíte completa em verde (226 tests).

**Gate Bloco 2 — cumprido:** assistant messages viraram cards de tabela pt-BR, barra fixa de totais reage a novas mensagens, itens pendentes confirmáveis inline sem sair do chat.

---

## Bloco 3 — Registro estruturado de treino (SP-120..SP-127) — pendente

Meta: rastrear treinos de força de forma granular (sessão → exercícios → séries), coexistindo com `log_activity`. Consolida em `activity_record` no encerramento. Ver seção 3.13 da spec e ADR-011.

**Todas `may` — implementação após Fase 9 concluída.** Não bloqueia MVP.

- [ ] **T-B301** — Migration nova: `workout_sessions` (id, user_id, day_log_id FK, workout_type enum, detected_name, started_at, ended_at nullable, status enum `active|ended`, end_reason enum), `workout_exercises` (id, session_id FK, name, normalized_name, sequence_index, started_at), `workout_sets` (id, exercise_id FK, sequence_index, weight_kg NUMERIC, reps INT, notes nullable). Índices: `(user_id, status)` parcial em session; `(normalized_name, user_id, ended_at DESC)` em exercise pra lookup histórico rápido. FK opcional `activity_records.workout_session_id`. (M) — SP-120, INV-15.
- [ ] **T-B302** — `Intent` enum ganha `workout_start`, `workout_add_exercise`, `workout_log_set`, `workout_end`, `workout_history`. Novos payloads `WorkoutStartIn`, `WorkoutExerciseIn`, `WorkoutSetIn`, `WorkoutEndIn`, `WorkoutHistoryQueryIn` em `app/schemas/llm.py`, tudo `_LenientBase`. Tool schema `record_intent` estendido. Prompt `system_v2.md` ganha regra 19 explicando os intents. (M) — SP-120..SP-127.
- [ ] **T-B303** — `app/services/workout.py::WorkoutService`: `start_session`, `add_exercise` (com lookup histórico + PR), `log_set`, `end_session`, `history`. Métodos autônomos, sem dependência do MessageProcessor — testáveis isoladamente. (L) — SP-120..SP-124, SP-127.
- [ ] **T-B304** — `WorkoutService.consolidate_to_activity`: cria `activity_record` com `activity_type='strength'`, `calc_method='workout_session'`, kcal via MET fixo × weight_kg × horas. Chamado por `end_session` (SP-124) e por `_handle_close_day` quando há sessão ativa (SP-125). (M) — SP-126, INV-17.
- [ ] **T-B305** — `MessageProcessor` ganha 5 handlers: `_handle_workout_start`, `_handle_workout_add_exercise`, `_handle_workout_log_set`, `_handle_workout_end`, `_handle_workout_history`. `IntentDispatcher` roteia os 5 diretamente (não passam pelo `_STRUCTURED_INTENTS`). Cada handler compõe assistant message via novo `message_formatter.compose_workout_*` — tabelas markdown pra consistência com SP-118. (M)
- [ ] **T-B306** — `_handle_close_day` chama `WorkoutService.end_session` **antes** do recompute quando há sessão ativa (SP-125). Ordem crítica: `activity_record` precisa estar persistido pra entrar no snapshot. (S)
- [ ] **T-B307** — Testes: `tests/test_workout.py` cobrindo SP-120 (start + auto-encerra anterior), SP-121 (lookup histórico + PR), SP-122 (parser de peso pt-BR + múltiplas séries em 1 msg), SP-123 (encerramento implícito de exercício), SP-124 (end explícito → consolidate), SP-125 (close_day auto-encerra), SP-126 (activity_record correto), SP-127 (history query), INV-15 (única sessão ativa), INV-16 (set no último exercício), INV-17 (delete de activity_record não apaga sessão). (L)
- [ ] **T-B308** — Frontend: renderização especial de assistant messages `workout_*` com destaque visual (peso PR em amber, série atual em verde). Novo `WorkoutHistoryCard` no chat. (M) — opcional, backend em markdown já é usável.

**Gate Bloco 3:** treino registrado por chat com histórico contextual; encerramento gera activity_record que aparece no snapshot; INV-15/16/17 verificadas.
## Bloco 4 — PWA básico (SP-128..SP-135) ✅ (parcial)

Meta: app instalável em iOS/Android/Desktop com shell offline. **Não** cobre offline de dados de negócio (contradiria INV-11), fila de mensagens (B-08) nem push (B-05). Zero mudança no backend.

Pré-requisitos: Fase 9 concluída (app em prod com HTTPS válido — PWA exige TLS pra instalar).

- [x] **T-B401** — `src/app/manifest.ts` com name, short_name (`my-reg`), icons (192/512/maskable), theme_color `#0f172a`, background_color `#0f172a`, display=standalone, start_url=/chat, scope=/, orientation=portrait, lang=pt-BR. (S)
- [x] **T-B402** — Ícones em `public/icons/`: `icon.svg` (source), `icon-192.png`, `icon-512.png`, `icon-512-maskable.png`, `apple-touch-icon.png` (180×180). Gerados via `sharp` a partir do SVG placeholder (mr em fundo `#0f172a`). Script inline; substituir por assets de design real depois. SP-131. (S)
- [x] **T-B403** — Meta tags iOS Safari + Viewport no root layout: `appleWebApp` da Metadata API do Next 15 (capable, status-bar-style, title), `formatDetection.telephone=false`, `apple-touch-icon`, `viewportFit=cover`, `themeColor`. SP-129. (XS)
- [x] **T-B404** — Service worker via **Serwist** em `src/app/sw.ts`: `NetworkOnly` para `/api/*` (INV-11), `NetworkFirst` com timeout 5s para HTML de rotas, `StaleWhileRevalidate` para `/_next/static/*`, `navigationPreload` on, `clientsClaim` on. Serwist injetado no `next.config.mjs` via `@serwist/next` (config `disable` em dev). Build usa `--webpack` porque Serwist ainda não suporta Turbopack. SP-130. (M)
- [x] **T-B405** — `src/app/offline/page.tsx` (server) + `OfflineRetryButton.tsx` (client) exibindo "Sem conexão" + aviso legal Art. VII §26 + botão que faz `window.location.reload()`. SP-135. (S)
- [x] **T-B406** — `src/app/sw-update-prompt.tsx` no root layout: escuta `updatefound` + `installed` state + `controllerchange`; toast fixo no rodapé com botão "Recarregar" que dispara `SKIP_WAITING` e recarrega quando o novo SW assume. SP-132. (M)
- [x] **T-B407** — `src/app/(app)/InstallButton.tsx` no header do layout protegido: escuta `beforeinstallprompt` (preventDefault + guarda o evento), botão que chama `.prompt()` e some após `appinstalled` OU quando já está em `display-mode: standalone`. Oculto em navegadores sem o evento (Safari/Firefox). SP-133. (S)
- [ ] **T-B408** — Splash iOS opcional (SP-134). **Adiado** — precisa 3 sizes de asset de design real; volta quando ícone final chegar. (S, opcional)
- [x] **T-B409** — `apps/web/scripts/verify-sw.mjs` roda em `pnpm --filter web verify:sw`: sanity checks estáticos de sw.ts (matcher /api/, NetworkOnly no handler, fallback /offline, listener SKIP_WAITING) + bundle contém /api/ e /offline. **Sem vitest** — evita adicionar framework de teste no web só por 1 assertion; Lighthouse PWA rodado manualmente conforme `docs/pwa.md` (gate ≥ 90 pendente de rodar em prod). (M)
- [x] **T-B410** — `docs/pwa.md` cobre instalação em iOS Safari (share → Adicionar à Tela de Início), Android Chrome (banner ou menu), Desktop (ícone na barra), diagnóstico, arquivos-chave, e como rodar Lighthouse. SP-133/135 documentados. (XS)

**Gate Bloco 4:** app é instalável em iOS + Android + Desktop com HTTPS; Lighthouse PWA ≥ 90 (rodar em prod após deploy); SW **não** cacheia respostas de `/api/*` (INV-11) — garantido por `verify-sw.mjs`; update flow visível quando nova versão sai. **T-B408 adiado** por depender de asset de design.

**Não inclui (por design):**
- Fila offline de mensagens (B-08 no backlog — envolve idempotência de envio + IndexedDB).
- Push notifications (B-05 no backlog — envolve VAPID + backend novo).
- Cache offline dos totais do dia (contradiz INV-11; se um dia formos fazer, precisa de estratégia estale-while-revalidate específica com invalidação por evento).
- Background Sync API (parte do B-08).

---

## Bloco 5 — Recuperação de itens sem catálogo (SP-140..SP-143) ✅

Meta: fechar o loop pra o usuário quando `catalog.lookup` devolve `None`, entregando **três botões clicáveis por item** direto no assistant message (Cadastrar manual, Foto do rótulo, Descartar). Remove o fluxo de "confirmação de item" que era redundante.

Status: **done** (spec #38 + feat #45, release v1.4.0). A remoção do fluxo de confirmação e a foto-do-rótulo com promoção (SP-143) foram entregues na mesma release — ver CHANGELOG v1.4.0.

Pré-requisitos:
- Fase 4.b (SP-30..35) concluída (LabelCatalogService disponível).

### Backend — cadastro manual (mantido do PR original)

- [x] **T-B501** — Composer de assistant message detecta warnings `no_catalog_hit` e anexa marcador `<!-- catalog-recovery: id1,id2 -->` + label "Sem catálogo para: **X**, **Y**". Frontend parseia. Adaptado à revisão v1.12 — remove texto sobre "descartar via chat" e "responda apaga" (vira botão). Testes em `test_message_formatter.py`. (S)
- [x] **T-B502** — **Não necessária** (CHECK já tinha `'manual'`).
- [x] **T-B503** — `POST /nutrient-facts/manual` com `ManualNutrientFactIn` + migration `0008_nutrient_facts_created_by`. Audit `create`. (M)
- [x] **T-B504** — `promote_food_item_id` no mesmo endpoint via `_try_promote_item`. Falha silenciosa com `promotion_warning`. (M)
- [x] **T-B505** — 11 testes em `tests/test_manual_nutrient_facts.py`. (L)
- [x] **T-B506** — `ManualCatalogForm.tsx` (modal client, form curto). (M)

### Backend — remoção do fluxo de confirmação

- [x] **T-B510** — Backend não seta mais `needs_confirmation=True`. Remover a lógica em `MealService._create_item` (`if confidence < LOW_CONFIDENCE_THRESHOLD or hit is None`) e no `BeverageService` equivalente. Campo continua no schema (nunca setado), retorno de API continua expondo (frontend ignora). Ajustar testes que hoje esperam `needs_confirmation=True` — passar a esperar `False`. (M)
- [x] **T-B511** — Deletar endpoint `POST /records/food-items/{id}/confirm` (hotfix #37) + `ConfirmationOut` schema. Testes em `test_corrections_deletions.py` (`test_confirm_food_item_*`, 4 casos) deletados. (S)
- [x] **T-B512** — Deletar `apps/api/app/services/confirmation.py` (`ConfirmationService`), remover import + branch `confirm_items` do `IntentDispatcher` + `MessageProcessor._handle_confirm_items`, remover intent do enum `Intent`, remover campos `confirmation`/`ConfirmationIn` do `LLMEnvelope` + `system_v2.md` prompt + `tool_schema.py`. `tests/test_confirm_items.py` deletado. Fluxo de correção via chat ("corrija X 100g") continua funcionando via intent `correct_record` (não tocado). (L)
- [x] **T-B513** — `message_formatter._warnings_block` (bloco "Confirma estes itens?") deletado. `_has_approx_food_items` continua usando warnings pra decidir `≈`. Teste `test_compose_meal_warnings_listed_after_disclaimer` deletado ou reformado. (S)

### Backend — foto do rótulo com promoção acoplada (SP-143)

- [x] **T-B520** — `POST /chat/messages` aceita novo campo opcional `promote_food_item_id: uuid`. Adiciona ao schema Pydantic + rota. Validação server-side de ownership no `ChatService.post_user_message` (silenciosamente descarta se falha — não bloqueia envio). Coluna nova em `messages` (nullable) ou armazenar em `raw_llm_response`? Decisão de plan: **armazenar em `raw_llm_response.metadata.promote_food_item_id`** pra evitar migration destrutiva. (M) — SP-143.
- [x] **T-B521** — `MessageProcessor._handle_log_nutrition_label` (fluxo Fase 4.b), depois de `LabelCatalogService.upsert_from_label` retornar sucesso: se `promote_food_item_id` está na mensagem E o item passa validação (ownership + não deletado + dia aberto), chama helper compartilhado com `_try_promote_item` do endpoint manual (extrair pra `app/services/promotion.py` ou similar). Falha silenciosa grava audit `action='promotion_failed'`. (M) — SP-143.
- [x] **T-B522** — Testes de integração em `tests/test_label_promotion.py` (6 casos): foto de rótulo válido + item válido → promoção completa; foto de rótulo válido + item de outro user → fact criado sem promoção; foto de rótulo válido + item deletado → idem; foto de rótulo válido + dia fechado → idem; foto que **não** é rótulo (LLM retorna clarify) → `promote_food_item_id` ignorado silenciosamente; foto de rótulo mas sem `promote_food_item_id` → comportamento original inalterado. (M)

### Frontend — remoção da UX de confirmação

- [x] **T-B530** — Deletar `apps/web/src/app/(app)/chat/PendingItemsModal.tsx`. Remover import + state + render do modal em `chat/page.tsx`. `DayTotalsBar.tsx` remove badge "N item precisa de confirmação" + prop `onPendingClick`. Interface `FoodItemRef.needs_confirmation` fica no tipo (backend ainda expõe), mas nenhum consumidor no frontend. (S)
- [x] **T-B531** — Deletar `apps/web/src/app/(app)/day/ConfirmItemButton.tsx`. Em `FoodItemRow.tsx`, remover badge "confirmar" (mantém apenas "sem catálogo" quando `has_catalog=false`). Cor amarela do badge some. (S)

### Frontend — 3 botões clicáveis no card recovery

- [x] **T-B540** — `AssistantContent.tsx` estende o parser + render do bloco `recovery` pra ter 3 botões por item (não só "Cadastrar"): **Cadastrar** (abre `ManualCatalogForm`, já feito), **Foto** (novo, ver T-B541), **Descartar** (novo, ver T-B542). Layout compacto — botões inline, ícones + label curto em mobile. (M) — SP-140.
- [x] **T-B541** — Novo componente `LabelPhotoUploader.tsx` (client). Botão dispara `<input type="file" accept="image/*" capture="environment">` (aproveita SP-16 pra câmera mobile). Ao selecionar: (1) POST `/media` pra subir; (2) POST `/chat/messages` com `text` mínimo ("foto do rótulo de {nome}"), `media_ids=[uploadedId]`, `promote_food_item_id={item.id}`. Sucesso → toast + `window.location.reload()` pra pegar novo assistant message. Erros de upload (SP-18) reusam mecânica existente (mensagens em pt-BR pra `file_too_large`, `invalid_image`). (M) — SP-143.
- [x] **T-B542** — Novo componente `DiscardItemButton.tsx` (client). Botão dispara `DELETE /records/food-items/{item.id}` diretamente (sem confirmação extra — item que ainda não gerou macros úteis pode ser deletado com 1 clique). Success → `window.location.reload()`. Erro exibe toast. (S)

### Docs

- [x] **T-B508** — Docs: spec §3.14 entregue em #38; UX autodescoberta documentada no CHANGELOG v1.4.0. (XS)

**Gate Bloco 5 revisado — objetivo:** usuário registra alimento fora do seed → assistant message mostra card com 3 botões por item. Clica Cadastrar → form curto + submit + item promovido + snapshot recalculado. Clica Foto → escolhe imagem → LLM lê rótulo + backend promove item automaticamente. Clica Descartar → item removido + snapshot recalculado. Nenhum fluxo de "confirmar" existe mais (endpoint, UI, intent LLM).

**Não inclui:**
- Migration destrutiva removendo `needs_confirmation` da coluna (adia).
- Delete de fact manual (adia).
- Sugestão automática de kcal pela LLM (viola Const. §5).
- Compartilhamento de facts entre users (single-user por design).

---

## Bloco 6 — Visão detalhada do dia (SP-150..SP-155) ✅

Meta: página `/day` que lista item-por-item do dia com macros + micros, permitindo o usuário validar cada registro. Fecha o loop de confiança que ficou aberto após o bug do catálogo vazio em prod (usuário via total zerado sem saber qual item estava sem catálogo).

Read-only na v1 — todas as mutações continuam via chat (mantém interface única de escrita). V2 pode ganhar ações inline.

Pré-requisitos: nenhum backend novo. `GET /days/today` e `GET /days/{date}` já entregam records completos (T-408 concluído). Reaproveita `CloseDayModal` (T-704) para o botão "Encerrar dia" no header.

Status: **done** (spec #40 + feat #43 + navegação temporal #44, release v1.4.0). Bloco 7 (edição inline) entregue separadamente — ver bloco seguinte.

- [x] **T-B601** — `apps/web/src/app/(app)/day/page.tsx` (server component) faz fetch de `GET /days/today` via `INTERNAL_API_URL` + delega renderização pra `DayView.tsx` (compartilhado com `/day/[date]`). `dynamic = 'force-dynamic'` porque records mudam a cada mensagem no chat. Header com data pt-BR + badge open/closed + `<CloseDayButton>` (novo client component que abre `CloseDayModal` reusado do chat; chama `useRouter().refresh()` pós-fechamento). SP-150. (M)
- [x] **T-B602** — `MealSection.tsx` (server) recebe records agrupados por meal_slot via `groupBySlot` em `DayView`. Ordem fixa `breakfast → lunch → snack → dinner → unspecified`; slots vazios retornam null. Grid 12-col: Item/Quantidade/Calorias/P/C/G/Fib. Kcal parcial da refeição no cabeçalho + horário do primeiro registro. SP-151. (M)
- [x] **T-B603** — `FoodItemRow.tsx` (server + `<details>` HTML nativo — zero JS extra). Grid 12-col matching o header do `MealSection`. Expansão revela sódio/cálcio/ferro/potássio + origem em pt-BR + confidence LLM (só quando `source='llm'`). Badges inline: "confirmar" (`needs_confirmation`) e "sem catálogo" (`has_catalog=false`). Valores zero renderizam `—` (formatters em `format.ts`). SP-152. (S)

  **Ajuste backend:** `_load_food` em `apps/api/app/services/day_query.py` estendido pra expor `fiber_g` + os 4 micros + `confidence` + `has_catalog` (booleano derivado de `catalog_ref_id`). Zero mudança de schema — `DayRecordsOut.food` já era `list[dict[str, Any]]`. 18 testes de `test_day_close_report.py` continuam verdes.

- [x] **T-B604** — `AuxiliarySections.tsx` exporta `HydrationSection` (horário + volume + total), `BeverageSection` (item/volume/kcal/P/C/G, badge confirmar), `ActivitySection` (nome + tipo pt-BR + duração + intensidade + kcal_out + método pt-BR). `ACTIVITY_TYPE_LABEL_PT` + `CALC_METHOD_LABEL_PT` + `SOURCE_LABEL_PT` em `types.ts` mapeiam enums → pt-BR. Cada seção some se sua lista estiver vazia. SP-153. (M)
- [x] **T-B605** — Link "Hoje" no header do `(app)/layout` entre "Chat" e "Semana" apontando pra `/day`. `proxy.ts` atualizado: `/day` e `/day/:path*` adicionados a `PROTECTED_PREFIXES` e `matcher`. SP-150. (XS)
- [x] **T-B606** — `apps/web/src/app/(app)/day/[date]/page.tsx` valida param contra `/^\d{4}-\d{2}-\d{2}$/` (rejeita path traversal + strings arbitrárias antes de bater na API); fetch de `GET /days/{date}`; 404 amigável ("Nenhum registro encontrado nesta data") + link "Voltar para hoje". Read-only: `allowClose={false}` passado pro `DayView` — botão Encerrar não aparece pra dias passados. SP-154. (S)
- [ ] **T-B607** — Testes: **adiado**. Web não tem framework de teste (vitest/jest) instalado — adicionar só pra 1 sanity de server component é overkill. Backend cobre o novo shape de `_load_food` via os 18 testes existentes de `test_day_close_report.py` (verificam `records.food[].items[]`). E2e manual: `pnpm dev`, cadastrar 3 itens no chat, abrir `/day`. Documentação separada fica pra próxima PR se necessário.
- [x] **T-B608** — Navegação temporal (SP-155): componente `DayNavigator.tsx` no header do `DayView` com botões **← Dia anterior**, **Próximo dia →** (escondido no dia atual), **Hoje** (escondido no dia atual) e input `<input type="date" max="{today}">` que submit navega pra `/day/[date]`. Aritmética de datas em `format.ts` (`addDays`, `todayLocalISO`). Página `/day/[date]` bloqueia data futura com componente `FutureDateNotice` antes de bater no backend. `WeeklyReportView.tsx` transforma coluna "Dia" da tabela `per_day` em `<Link href={`/day/${row.date}`}>`. (M) — SP-155. **Entregue em #44.**

**Gate Bloco 6 — cumprido:** `/day` mostra dia atual completo com refeições agrupadas, macros por item, expansão de micros e seções auxiliares. `/day/[date]` renderiza dias passados read-only, alcançável via setas prev/next, input date ou link da tabela do `/weekly` (T-B608). Botão "Encerrar dia" reaproveita `CloseDayModal` sem duplicação. Backend estendido sem quebrar testes existentes.

**Não inclui (por design):**
- Edição/deleção inline (v2 — hoje é via chat).
- Filtros/ordenação (só a ordem natural: meal_slot → occurred_at).
- Exportação CSV/PDF (feature B-06 do backlog).
- Gráficos ou comparação com dias anteriores (v2+).

---

## Bloco 7 — Edição inline de registros no `/day` (SP-160..SP-169) ✅

Meta: corrigir registros direto na página do dia, sem voltar ao chat. Restrito a dias abertos (Art. VIII); auditoria `action='correct'` `actor='user'`; snapshot recomputa do zero pós-mutação (Art. III §10).

Feature spec própria em `../002-edicao-inline-day/` (spec #54 + feat #55, release v1.4.0). Task IDs `T-B200`.. do spec-kit 002; todas entregues. Diferenças da implementação real vs. planejado:

Status: **done**.

- [x] **T-B200** — Refactor: `correction_ops.py` extraído a partir de `services/correction.py` (funções puras `apply_water_change`/`apply_beverage_change`/`apply_activity_change`), reusado pelos novos PATCH sem duplicar lógica do chat. Testes do chat permaneceram verdes. (S)
- [x] **T-B210** — `PATCH /records/water/{id}` — body `{volume_ml}`; ownership (Art. V §21), 404 se deletado/inexistente, 409 `conflict_closed_day` (INV-5), recompute + audit. (S) — SP-164.
- [x] **T-B211** — `PATCH /records/beverage/{id}` — body `{volume_ml}`; recompute macros via `NutritionCalculator` a partir do fact referenciado; beverage sem `catalog_ref_id` mantém macros (warning `no_catalog_hit`). (M) — SP-165.
- [x] **T-B212** — `PATCH /records/activity/{id}` — body `{duration_minutes?, intensity?, kcal_burned?}`; kcal explícito → `calc_method='user_manual'`; sem peso → warning `weight_kg_required_for_kcal`; `detected_name` não editável (400). (M) — SP-166.
- [x] **T-B220** — `services/nutrient_fact_propagation.py` (INV-14): PATCH em `nutrient_facts` propaga macros sobrescritos para todos os `food_items`/`beverage_records` de dias **abertos** referenciando o fact, recomputando cada snapshot; itens em dias fechados → `skipped` (INV-5). Response do PATCH expõe `propagated`/`propagation_skipped`. (M) — SP-163.
- [x] **T-B230** — Edição client-side: em vez das Server Actions planejadas, os forms reusam o hook `useEditForm` de `edit-forms.tsx` com `api()` do `api-client.ts` (padrão FE-04) + `router.refresh()` pós-sucesso (revalidar server components). (S) — SP-169.
- [x] **T-B231** — `EditFoodItemForm` dentro de `FoodItemRow` (`<details>`): inputs `grams`/`ml`/`quantity` e, quando `has_catalog && source ∈ {label_ocr, manual}`, inputs per-100g; fact TBCA/USDA mostra "não editável". Dia fechado desabilita inputs. (M) — SP-160, SP-161, SP-162, SP-167.
- [x] **T-B240** — `EditWaterForm`/`EditBeverageForm`/`EditActivityForm` em `AuxiliarySections.tsx` com mesmos padrões de dia fechado + loading/erro/a11y. (M) — SP-168.
- [x] **T-B250** — Testes: `tests/test_patches_*.py` (happy/404/409/isolation/audit/snapshot), `test_nutrient_fact_propagation.py` (INV-14, INV-5); E2E Playwright em `apps/web/e2e/inline-edit.spec.ts`. (S) — INV-1/4/5/10/14.

**Gate Bloco 7 — cumprido:** os quatro tipos de registro editáveis no `/day` com recompute + auditoria; propagação de `nutrient_fact` (INV-14) fecha o loop "contrário" (correção de rótulo reflete em dias abertos); E2E cobre o fluxo. Const. Art. III §10 e Art. VIII §28 verificadas.

**Não inclui (por design):**
- Mudança de `meal_slot`/horário por UI (v2).
- Reabertura de dia encerrado (B-04 do backlog).

---

## Backlog (pós-MVP, `may`)

- **B-01** — Persistência agregada de `sugars_g`, `added_sugars_g`, `saturated_fat_g`, `trans_fat_g`.
- **B-02** — Leitura de código de barras (client-side + LLM fallback).
- **B-03** — Integração Apple Health / Google Fit.
- **B-04** — Reabertura de dia encerrado com auditoria especial.
- **B-05** — Notificações (push/email/Telegram) sobre encerramento pendente.
- **B-06** — Exportação CSV/PDF do diário e semanal.
- **B-07** — Multi-usuário + cadastro público (envolve emenda constitucional).
- **B-08** — PWA offline **completo** (fila de mensagens em IndexedDB, envio idempotente, Background Sync). Complementa o Bloco 4 (instalabilidade + shell) com capacidade de trabalhar sem conexão.
- **B-09** — Migrar fila para RQ/Dramatiq quando >1 usuário concorrente.

---

## Histórico

- **2026-07-15** — v1.0. Estrutura inicial. Fase 0 marcada como done. Total: 47 tarefas ativas + 9 backlog.
