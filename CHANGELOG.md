# Changelog

Todas as mudanças notáveis do projeto serão documentadas aqui.

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versionamento segue [SemVer](https://semver.org/lang/pt-BR/).

Categorias:
- **Adicionado** — funcionalidade nova.
- **Modificado** — mudança em funcionalidade existente.
- **Corrigido** — bugfix.
- **Removido** — feature retirada.
- **Segurança** — vulnerabilidade tratada.
- **Documentação** — spec, ADR, runbook, README.
- **Infra** — CI/CD, Docker, deploy, observabilidade.

Cada release tem tag Git `vX.Y.Z` e uma entrada correspondente em [GitHub Releases](https://github.com/felixstenian/my-registers/releases).

---

## [1.7.0] — 2026-09-09

Bloco 9 — edição total no `/day` e registro retroativo (SP-182..SP-185, INV-24/INV-25). Correções de estabilidade no E2E/CI e bump de segurança em dependência do backend.

### Adicionado
- **#89 — SP-182..SP-185 — edição total no `/day` + registro retroativo** — Spec §3.17 / plan §10 / ADR-014. SP-182/INV-24: `POST /records/food-items/{id}/clone-fact` clona fact canônico (TBCA/USDA) para `manual` por usuário — override de macros sem nunca mutar o catálogo compartilhado. SP-183: PATCH de metadados (`detected_name`, `meal_slot`, `occurred_at`, `quantity`/`unit`) nos 4 tipos de registro. SP-184: registro retroativo via chat (`LLMEnvelope.target_date`). SP-185/INV-25: `StructuredRegistrationService` + endpoints de criação estruturada (`POST /records/{food,water,beverage,activity}`) + formulário `DailyAddForm` em `/day/[date]` (apenas dias abertos). Frontend: override canônico + edição de nome nos edit-forms. Cobertura em `tests/test_edit_total_retroactive.py` (INV-24, INV-25, SP-182..185). ([#89](https://github.com/felixstenian/my-registers/pull/89)).

### Corrigido
- **Race do poll do chat com resposta rápida do worker** — Se o worker commitava a assistant antes do `loadInitial()` terminar, o poll (ancorado na última mensagem) nunca a via como nova: `revalidateKey` não bumpava, o typing indicator rodava até o cap de 60s e a barra de totais ficava stale. `performSend` agora bumpa o `revalidateKey` direto quando a última mensagem carregada já é a assistant. (commit `2ca41e0`, via [#89](https://github.com/felixstenian/my-registers/pull/89)).
- **Flake de auth no E2E — `/test/reset` com admin de id estável** — O reset deletava e recriava o admin com UUID novo a cada teste; requests em voo do teste anterior (fetch server-side do Next, que sobrevive ao teardown do browser) inseriam `refresh_tokens`/`day_logs` com o id antigo → FK violation 500 em `/auth/login` e `/days/today`, derrubando testes aleatórios (redirect loops, `user not active`). O reset agora faz upsert por email (`ON CONFLICT DO UPDATE`), resetando senha/perfil sem trocar o `user_id`. (commit `2ca41e0`, via [#89](https://github.com/felixstenian/my-registers/pull/89)).
- **E2E: strict-mode nos headers do `/day` + flake do apt do google-chrome no CI** — `getByText('Almoço'/'Atividade', { exact: true })` colidia com `<option>`s do `DailyAddForm` (strict mode violation); locators escopados ao `header span.font-semibold`. CI: o repo `google-chrome` pré-instalado no runner `ubuntu-24.04` falhava com "Hash Sum mismatch" durante o `apt-get update` do `playwright install-deps`; a source é removida antes da instalação (o Playwright instala o próprio Chromium). (commit `11b5bc9`, via [#89](https://github.com/felixstenian/my-registers/pull/89)).

### Segurança
- **#87 — Dependabot (uv): bump cryptography 49.0.0 → 50.0.0** — Atualização do grupo `uv` em `apps/api`. ([#87](https://github.com/felixstenian/my-registers/pull/87)).

### Documentação
- **#88 — spec(001): SP-182..SP-185 — edição total no `/day` + registro retroativo** — spec v1.15 (§3.17) + invariantes INV-24 (fato canônico imutável por usuário) e INV-25 (registro retroativo respeita dia fechado/futuro); decisões em ADR-014. ([#88](https://github.com/felixstenian/my-registers/pull/88)).
- **#85 — spec(001): SP-180 SP-181 — paginação do chat por dia (Bloco 8)** — SDD da paginação do histórico do chat; especificado, ainda não implementado. ([#85](https://github.com/felixstenian/my-registers/pull/85)).

### Deploy
Deploy automático via `deploy.yml` ao mergear em `main`; nenhuma migration nova nem operação manual na VPS necessária.

---

## [1.6.1] — 2026-09-04

Manutenção de dependências e segurança do frontend. Sem mudança funcional.

### Segurança
- **#84 - bump do grupo npm_and_yarn (next, postcss, nanoid)** - Dependabot atualiza em 2 diretórios (raiz e `apps/web`): `next` 16.2.10→16.2.11, `postcss` 8.4.49→8.5.23 e `nanoid` 3.3.16→3.3.18, resolvendo 34 vulnerabilidades (20 high, 14 moderate). ([#84](https://github.com/felixstenian/my-registers/pull/84)).
- **#78 - configuração do Dependabot** - Adiciona `.github/dependabot.yml` (ecossistema `npm`, grupo `npm_and_yarn`, raiz + `apps/web`). ([#78](https://github.com/felixstenian/my-registers/pull/78)).
- **#79 - SECURITY.md** - Adiciona política de segurança e canal de relato de vulnerabilidades. ([#79](https://github.com/felixstenian/my-registers/pull/79)).

### Deploy
Deploy automático via `deploy.yml` ao mergear em `main`; nenhuma operação manual na VPS necessária.

---

## [1.6.0] — 2026-08-18

Melhoria da navegação mobile. Correção da configuração do setup de testes e2e. Atualização e edição da documentação sobre a feature de workouts.

### Adicionado
- **#63  - SP-NM-01..07 - header sticky + bottom tab bar mobile** - Mobile: menu primario sempre ao alcance — bottom tab bar (Chat · Hoje · Semana) com aria-current, hit-target 48px e safe-area. Header: sticky top-0 + colapso em <md (nav inline e email ocultos); root min-h-dvh. /chat: 100vh -> 100dvh + reserva de espaco p/ a barra — composer e disclaimer (Art. VII 26) nunca ficam cobertos. Desktop: inalterado (nav inline no header, sem barra). ([#63](https://github.com/felixstenian/my-registers/pull/63)).

### Corrigido
- **#64 - endurece login flake e setup Playwright (P1-P6)** - Endurece o setup E2E do apps/web e o flake de hidratação do login no Next dev (testes de auth/FE-03). Flake de hidratação: loginViaForm agora aguarda a hidratação React (__reactProps/__reactFiber) antes do click em "Entrar"; timeouts de navegação pós-login em 15000ms (router.replace lento no Next dev sob carga). Aplicado em auth.spec.ts e nos 7 testes de login de error-handling.spec.ts. P1 — chat.spec.ts: Promise.race entre "typing indicator visível" e /registrei/i já renderizado. P2 — novo e2e/global-setup.ts: checa /health + /login com AbortSignal.timeout(5000) e instruções ./scripts/e2e-bootstrap.sh. P3 — módulos compartilhados e2e/support/chat.ts (postChat/waitForAssistant) e types.ts; seed.ts/test.ts/inline-edit.spec.ts refatorados. P4 — error-handling.spec.ts: revalidação determinística do DayTotalsBar via envelope log_food + expect.poll com contador de aborts. P5 — navigation-mobile.spec.ts: profiles Pixel 7/Desktop Chrome derivados sem defaultBrowserType. P6 — constants.ts com API_BASE/WEB_BASE via env (defaults 8001/3001); baseURL derivado. ([#64](https://github.com/felixstenian/my-registers/pull/64)).


### Documentação
- **#62 - spec(003): SP-NM-01..07 - navegacao mobile (spec + plan + tasks)** SDD para a navegação mobile (header sticky + bottom tab bar), fechando o fluxo spec: -> plan: -> tasks: nesta branch. ([#62](https://github.com/felixstenian/my-registers/pull/62)).
- **#65 - SP-170..SP-179 - módulo de treino (workout module) + renumeração INV** - Formaliza no spec canônico a expansão do cliente de treino como módulo de produto e resolve a colisão de numeração de invariantes descoberta entre workout (§3.13 v1.6) e PWA/SW (§3.13 v1.7). 2. Nova §3.16 — Módulo de treino (SP-170..SP-179). Estende §3.13 (núcleo SP-120..127 inalterado, may). SPs must/should, pós-MVP: -> SP-170 /workouts (abas Ativos/Inativos/Histórico) -> SP-171 cadastro de treino por texto (template de exemplo + LLM) -> SP-172 status ativo/inativo -> SP-173 chat de treino dedicado — mesmo pool de messages com via='workout' (decisão fixada: Opção A), header com atividades/kcal do dia, botões Cadastrar/Iniciar/Finalizar treino -> SP-174 registro por imagem (título/atividade/intensidade/kcal) -> SP-175 edição de peso/séries/kcal via chat e /day (reconsolida se encerrada) -> SP-176 seção de treinos no /day (should) -> SP-177 histórico paginado -> SP-178 fluxo guiado com botões + "Ir para o próximo exercício" -> SP-179 cronômetro + tempo registrado. ([#65](https://github.com/felixstenian/my-registers/pull/65)).
- **#66 - SP-170..SP-179 - módulo de treino (E1..E6 + gates)** - Atualiza specs/001-mvp-registro-diario/plan.md (HOW) para a expansão de treino como módulo — spec v1.13 (§3.16), SP-170..SP-179. Mapa SP → arquivos (§1): -> SP-120..SP-127 — núcleo hierárquico (sessão → exercício → séries), app/services/workout.py + models/repository + MessageProcessor/IntentDispatcher. -> SP-170..SP-179 — módulo: workout_templates, rotas /workouts/*, apps/web/src/app/(app)/workouts/*, filtro messages.via (SP-173), seção/edição no /day. ([#66](https://github.com/felixstenian/my-registers/pull/66)).
- **#67 - SP-170..SP-179 - T-B309..T-B328 módulo de treino** - Adiciona as tarefas atômicas do módulo de treino (spec §3.16, plan §8 E1..E6) ao Bloco 3 de specs/001-mvp-registro-diario/tasks.md: T-B309..T-B328 (20 tarefas). ([#67](https://github.com/felixstenian/my-registers/pull/67)).


---

## [1.5.0] — 2026-08-14

Correção de dados legados (itens com `kcal=0`) + reseed do catálogo TBCA + endurecimento de deploy e sessão. Formaliza o hotfix aplicado em prod em 2026-08-13 (schema drift), que havia sido documentado como "v1.4.1" mas nunca recebeu tag/release.

### Adicionado
- **Backfill de itens legados + reseed do catálogo (CLI)** — Novos comandos `python -m app.cli reseed-catalog` e `python -m app.cli backfill-zeroed [--include-closed]` via `CatalogBackfillService` (`apps/api/app/services/catalog_backfill.py`). O banco foi seedado de uma **versão antiga** do `seed_tbca.csv` (35 fatos; o CSV atual tem 65): no momento do registro o lookup perdia e itens persistiam com `kcal=0`/`catalog_ref_id=NULL`. **Não há drift de `canonical_name`** — `seed.py` normaliza nomes no ingest (`brocolis_cozido`→`brocoll_cozido`) e o lookup normaliza a query; a hipótese inicial de renomear nomes foi descartada porque quebraria o matching. O `reseed-catalog` re-roda `seed_from_csv` (upsert idempotente) inserindo os fatos faltantes; o `backfill-zeroed` religa itens zerados ao catálogo, preenche `grams`/`ml` a partir do `serving_grams` quando ausentes (`is_estimate=true`), recomputa macros via `NutritionCalculator` (Art. II §5/§10), grava `audit_events` (`action='correct'`, `actor='user'` — Art. III §11) e recomputa o snapshot por dia (Art. III §10). Dias fechados são pulados por padrão (INV-5, Art. VIII §28); `--include-closed` corrige histórico de forma explícita. Runbook em `docs/catalog-backfill-runbook.md` + 7 testes novos. ([#60](https://github.com/felixstenian/my-registers/pull/60)).

### Corrigido
- **Schema drift por deploy sem migrations (incidente 2026-08-13)** — O Bloco 5 adicionou `NutrientFact.created_by` ao model, mas a migration `0008_nutrient_facts_created_by` nunca foi aplicada na VPS (deploy manual via `git pull && docker compose up -d` sem passar por `bootstrap.sh`). Todo registro de comida/bebida — cujo lookup faz `SELECT nutrient_facts.created_by` (`local_tbca.py`) — estourava `UndefinedColumnError`, e o catch-all `background_processor_failed` convertia o erro no fallback genérico: assistant message "Não consegui interpretar sua mensagem agora" com `llm_intent="unknown"`/`llm_confidence=NULL`. Água continuou funcionando porque o path dela não consulta `nutrient_facts`. Diagnóstico: sintoma **água OK + comida/bebida falhando = schema drift, NÃO falha de LLM** (canário em `docs/deploy.md` §10.2). Fix operacional: `./scripts/bootstrap.sh .env.production` na VPS (aplica 0008/0009/0010 + re-seed TBCA). Hardening: `bootstrap.sh` agora loga `alembic current` pós-upgrade; `docs/deploy.md` §10.1/§10.2/§14 deixa migrations obrigatórias em todo deploy (manual ou via CD). Observação: este hotfix foi documentado como "v1.4.1" em `AGENTS.md`/CHANGELOG mas **nunca recebeu tag/release**; v1.5.0 o formaliza. ([#58](https://github.com/felixstenian/my-registers/pull/58)).
- **#57 — Deploy com `git fetch` + `git reset --hard origin/main`** — O `command="..."` restrito no SSH do CD usava `git pull`, que aborta com "Your local changes would be overwritten by merge" se a working tree da VPS tiver edição não commitada. Troca por `git fetch origin && git reset --hard origin/main` (a app vive no git; segredos no `.env.production`), alinhando `deploy.yml`, `docs/deploy.md` §14 e `pos-deploy-macros-fix.md`. ([#57](https://github.com/felixstenian/my-registers/pull/57)).
- **#59 — Refresh de sessão com single-flight no `api-client` (FE-05)** — Refresh concorrente de sessão deduplicado: múltiplas chamadas simultâneas esperam a mesma promise em vez de disparar N refreshes paralelos (evita corrida na rotação do refresh token). Cobertura E2E em `e2e/session.spec.ts`. ([#59](https://github.com/felixstenian/my-registers/pull/59)).

### Documentação
- **#58 — Runbook do hotfix schema drift** — `docs/hotfix-schema-drift-v1.4.1.md` com o passo a passo do incidente; `docs/deploy.md` §10.1/§10.2/§14 tornam migrations obrigatórias em todo deploy e documentam o canário `alembic current` + `UndefinedColumnError`. ([#58](https://github.com/felixstenian/my-registers/pull/58)).
- **Runbook de backfill** — `docs/catalog-backfill-runbook.md`: backup → `reseed-catalog` → `backfill-zeroed` → revisão de itens `unresolved` → decisão sobre dias fechados → validação. ([#60](https://github.com/felixstenian/my-registers/pull/60)).

### Deploy
Backend `api` ganha 2 comandos CLI (reseed + backfill); `web` ganha o single-flight de sessão; `deploy.yml` e o `command="..."` da VPS passam a usar `git fetch + reset --hard`. Em VPS existente:

```bash
cd ~/my-registers
git fetch origin && git reset --hard origin/main
./scripts/bootstrap.sh .env.production          # migrations + seed (obrigatório)
docker compose -f docker-compose.production.yml --env-file .env.production up -d --build api web
```

Correção de dados (obrigatório para quem tem itens zerados): seguir `docs/catalog-backfill-runbook.md` — `python -m app.cli reseed-catalog` e depois `python -m app.cli backfill-zeroed`, revisando os itens `unresolved`.

---

## [1.4.0] — 2026-08-12

Terceira onda pós-MVP: fecha a visão item-a-item do dia (Blocos 5/6/7), adiciona navegação temporal e valida o golden path end-to-end com Playwright. Dois hotfixes de prod (#37, #41) finalmente formalizados em release.

### Adicionado
- **Bloco 5 — Recuperação de itens sem catálogo (SP-140..SP-142)** — Quando a LLM classifica `no_catalog_hit`, a assistant message traz prompt claro com 3 CTAs por item (`Cadastrar manual` · `Foto do rótulo` · `Descartar`). Form manual cria `nutrient_fact` sem foto; `promote_food_item_id` no `POST /chat/messages` promove item legacy para o novo catálogo. Fluxo de confirmação legado removido. Spec §3.14 ([#38](https://github.com/felixstenian/my-registers/pull/38)); implementação [#45](https://github.com/felixstenian/my-registers/pull/45)).
- **Bloco 6 — Visão detalhada do dia (SP-150..SP-154)** — Nova rota `/day/[date]` que lista item-por-item (food, água, bebidas, atividades) com macros + micros, totais do dia, badge de dia fechado. Revive parcialmente o T-409 (records item-a-item) que ficou fora do MVP. Spec §3.15 ([#40](https://github.com/felixstenian/my-registers/pull/40)); implementação [#43](https://github.com/felixstenian/my-registers/pull/43)).
- **SP-155 — Navegação temporal no `/day`** — Botões prev/next, date picker e link a partir do `/weekly`. Fecha o loop de acesso: antes só se chegava em dias passados digitando URL. [#44](https://github.com/felixstenian/my-registers/pull/44).
- **Bloco 7 — Edição inline de registros no `/day` (SP-160..SP-169)** — Formulários expansíveis (`<details>`) para corrigir food items (grams/ml/quantity), água (volume_ml), bebidas (volume_ml) e atividades (duration_min) direto na página. PATCH endpoints `PATCH /records/{food|water|beverage|activity}/{id}` com recompute de snapshot (Art. III §10) + auditoria (`action='correct'`, `actor='user'`). Propagação de `nutrient_fact` (INV-14) para itens em dias abertos quando o catálogo é atualizado — usuário corrige valor lido da foto do rótulo sem voltar ao chat. E2E tests no Playwright. Spec [#54](https://github.com/felixstenian/my-registers/pull/54)); implementação [#55](https://github.com/felixstenian/my-registers/pull/55)).
- **Testes E2E — autenticação & sessão (SP-01, SP-02, SP-03, SP-04, SP-06)** — Playwright cobrindo login, sessão persistente, logout, redirect 401, refresh de sessão. [#51](https://github.com/felixstenian/my-registers/pull/51)).
- **Testes E2E — chat-messaging (TC-E-001..TC-E-004)** — Envio de texto, upload de mídia, polling de resposta, renderização de assistant message. [#53](https://github.com/felixstenian/my-registers/pull/53)).
- **Testes do CLI bootstrap (TC-U-001..010, TC-I-001..003)** — 11 unitários (incl. helpers hash/verify Argon2id) + 3 integração com Postgres real. [#52](https://github.com/felixstenian/my-registers/pull/52)).
- **Testes E2E golden path — 5 specs + CI job** — Login → registrar refeição → ver dia → encerrar dia → semana → dia passado read-only. `TestAnthropicClient` HTTP-controlável responde de fila enfileirada pelo Playwright (zero custo, zero flake por variação de LLM, alinhado à Art. II). Job `e2e` adicionado ao `ci.yml`. [#48](https://github.com/felixstenian/my-registers/pull/48)).

### Corrigido
- **#37 — Macros zerados em prod** — `scripts/bootstrap.sh` só chamava `python -m app.cli bootstrap` (cria admin), nunca `seed-nutrition`. Em prod `nutrient_facts` ficava vazio, `MealService.create_from_llm` fazia lookup vazio, `NutritionCalculator.compute(hit=None)` devolvia zeros e itens persistiam com `kcal=0`/`catalog_ref_id=NULL`. Fix: `bootstrap.sh` agora chama `seed-nutrition` após `bootstrap` (ambos idempotentes); todo deploy garante catálogo populado. [#37](https://github.com/felixstenian/my-registers/pull/37)).
- **#37 / Bloco 5 — Confirmar item sem catálogo** — O hotfix #37 (pós-v1.3.0) havia introduzido `POST /records/food-items/{id}/confirm` + `PendingItemsModal.tsx` para desmarcar `needs_confirmation` quando o item só tinha `quantity`. O Bloco 5 (SP-140..142, esta release) **reformulou** o fluxo: o modal, o endpoint, a intent LLM `confirm_items` e o `ConfirmationService` foram removidos em favor dos 3 CTAs card recovery (`Cadastrar manual` · `Foto do rótulo` · `Descartar`). `PATCH /food-items/{id}` mantém o bônus introduzido pelo #37 de sempre tentar lookup pelo `normalized_name` para promover itens legados presos com `catalog_ref_id=NULL`/`kcal=0` (com otimização em dev: se `catalog_ref_id` já existir, busca por ID direto em vez de lookup por nome). [#37](https://github.com/felixstenian/my-registers/pull/37) + [#45](https://github.com/felixstenian/my-registers/pull/45)).
- **#41 — Imagens do chat bloqueadas por CSP + host interno do MinIO** — URL assinada gerada pelo MinIO vinha `http://minio:9000/...` (host da rede docker interna, inatingível pelo browser) e mesmo se fosse, `img-src 'self'` bloqueava o host. Fix estrutural: nginx `location /media/` faz proxy interno para `http://minio:9000/` com `Cache-Control private, max-age=3600` (aproveita o expiry de 1h da URL assinada). Nova var de env `S3_PUBLIC_BASE_URL` reescreve o host da URL assinada de `minio:9000` para o domínio público, mantendo assinatura. Zero mudança de CSP. [#41](https://github.com/felixstenian/my-registers/pull/41)).
- **#46 — Encerrar dia passado quando ainda aberto** — Botão "Encerrar dia" só aparecia em `/day` para o dia atual; usuário que esqueceu de encerrar um dia anterior não tinha como resolver retroativamente pela UI. Fix: o botão aparece em qualquer dia com `status='open'`. ([#46](https://github.com/felixstenian/my-registers/pull/46)).
- **#50 — Hardening do `api-client` (FE-01..FE-05)** — `api()` envolve `fetch` em try/catch (`network_error` com `status=0`), feedback de erro visível, proteção contra open-redirect no redirect pós-login, redirect 401 automático para `/login`, `DayNavigator` não stale de datas inválidas. E2E de cobertura. ([#50](https://github.com/felixstenian/my-registers/pull/50)).
- **#49 — Restaura ESLint (flat config) no web e no CI** — `next lint` foi removido no Next.js 16; o script `lint` falhava ("Invalid project directory provided") e o job `web` do CI silenciava. Fix: ESLint flat config + step `lint` no job `web`. ([#49](https://github.com/felixstenian/my-registers/pull/49)).

### Removido
- **Fluxo de "confirmação de item" (Bloco 5)** — Endpoint `POST /records/food-items/{id}/confirm`, modal `PendingItemsModal.tsx`, intent LLM `confirm_items`, `ConfirmationService` e componente `ConfirmItemButton` no `/day`. Motivador: sobreposição semântica confusa — item sem catálogo não precisa de "confirmação", precisa de **ação** (cadastrar valores OU descartar). O campo `needs_confirmation` permanece no schema (evita migration) mas o backend nunca mais o seta como `true`; o frontend usa `has_catalog` como único sinal. Estes artefatos haviam sido introduzidos pelo hotfix #37 em prod após v1.3.0 (sem tag/release formal); v1.4.0 formaliza a remoção. ([#45](https://github.com/felixstenian/my-registers/pull/45); ver spec §3.14 "Decisão de escopo (revisão 2026-07-28)").

### Documentação
- **#47 — Índice + specs por feature (23 features, 161 artefatos)** — Nova pasta `specs/features/` como visão reindexada por feature do produto, sem alterar o spec-kit contratual em `specs/001-mvp-registro-diario/`. Cada feature tem 7 artefatos (`requirements.md`, `specifications.md`, `user-stories.md`, `acceptance-criteria.md`, `test-cases.md`, `architecture.md`, `trade-offs.md`). `INDEX.md` no topo. ([#47](https://github.com/felixstenian/my-registers/pull/47)).
- **#39 — Sync do hotfix #37 + CHANGELOG v1.3.0 para dev** — Traz `dev` em par com `main` pós-v1.3.0 + checklist pós-deploy do hotfix em `docs/pos-deploy-macros-fix.md`. ([#39](https://github.com/felixstenian/my-registers/pull/39)).

### Infra
- **D-02 — nginx com `envsubst` nativo** — Substitui `sed 's|\${DOMAIN}|...|g'` manual (que exigia intervenção do operador a cada `git pull` de mudança em `app.conf`) pelo `envsubst` nativo da imagem `nginx:*-alpine`. Infra reproduzível. ([#42](https://github.com/felixstenian/my-registers/pull/42)).

### Deploy
Atualiza `web` (Blocos 5/6/7 + navegação temporal + hardening), `api` (PATCH endpoints + confirm + promote_food_item_id) e `nginx` (template envsubst já em prod via #41 e #42). Em VPS existente:

```bash
cd ~/my-registers
git pull
docker compose -f docker-compose.production.yml --env-file .env.production up -d --build api web nginx
# rodar seed-nutrition uma vez garante catálogo dos deploys anteriores (idempotente):
docker compose -f docker-compose.production.yml --env-file .env.production exec api python -m app.cli seed-nutrition
```

Após esta release, o **deploy automático via `deploy.yml`** é plenamente operacional desde que T-1003 (branch protection em `main`) e T-1004 (chave SSH deploy-only na VPS) estejam configurados conforme `docs/deploy.md` §14.2.

---

## [1.3.0] — 2026-07-27

Segunda onda pós-MVP: fecha a cauda funcional (encerrar dia + semanal) e liga o pipeline CI/CD.

### Adicionado
- **T-704** — Botão "Encerrar dia" na barra de totais do chat + modal com resumo pós-fechamento (narrativa da LLM + totais finais). Trata SP-101 idempotente ([#31](https://github.com/felixstenian/my-registers/pull/31)).
- **T-804** — Página `/weekly` com tabela cronológica dos últimos 7 dias fechados, grid de totais + médias, narrativa LLM, banner `insufficient_history`, estado vazio amigável ([#31](https://github.com/felixstenian/my-registers/pull/31)).
- Link "Semana" no header do layout protegido ([#31](https://github.com/felixstenian/my-registers/pull/31)).

### Infra
- **Fase 10 (T-1001, T-1002, T-1005, T-1006, T-1007)** — Pipeline CI/CD via GitHub Actions ([#34](https://github.com/felixstenian/my-registers/pull/34)):
  - `.github/workflows/ci.yml` — jobs `api` (Postgres 16 service + ruff + pytest) e `web` (typecheck + build + verify:sw), em paralelo, em cada PR e push em `main`.
  - `.github/workflows/deploy.yml` — SSH deploy pós-CI verde em `main`, com smoke test em `/api/health`.
- Config manual (T-1003 branch protection + T-1004 chave SSH deploy-only) documentada em `docs/fase-10-setup.md` e `docs/deploy.md` §14, pendente de execução via UI/SSH.

### Corrigido
- **Testes de catálogo TBCA** — 15 asserts em 8 arquivos hardcoded valores antigos de `arroz_branco_cozido` (124→130), `peito_de_frango_grelhado` (159→165) e `leite_integral` (61→57). Bug encontrado pelo próprio CI da Fase 10; sem CI teria virado dessincronia silenciosa entre seed e testes ([#34](https://github.com/felixstenian/my-registers/pull/34)).

### Documentação
- **D-01** — `infra/certbot/README.md` documenta armadilha do entrypoint daemon do certbot (silencia comandos `run` sem `--entrypoint certbot`) + fluxo staging→delete→prod atualizado ([#32](https://github.com/felixstenian/my-registers/pull/32)).
- **D-03** — `CLAUDE.md` atualizado para refletir estado real (Fases 0-9 em prod, Blocos 1/2/4, MVP em `myregister.felix.dev.br`). Descrição de `apps/web` inclui Next 16 + Serwist + distinção `NEXT_PUBLIC_API_URL` vs `INTERNAL_API_URL` ([#32](https://github.com/felixstenian/my-registers/pull/32)).
- **D-04** — Nova seção em `docs/pwa.md` sobre cache do SW segurando ícones/manifest após deploy, com regra explícita que iOS só atualiza com reinstalar ([#32](https://github.com/felixstenian/my-registers/pull/32)).
- `docs/deploy.md` §14 — Documentação completa da Fase 10: fluxo, setup de chave deploy-only, secrets/variables, branch protection, debug, rollback ([#34](https://github.com/felixstenian/my-registers/pull/34)).
- `tasks.md` — T-408, T-410, T-908 marcadas concluídas; T-409 delimitada como "totals via `DayTotalsBar` entregues, tela `/days/[date]` opcional" ([#33](https://github.com/felixstenian/my-registers/pull/33)).

### Deploy
Rebuild seletivo — só `web`. Backend (`api`), Postgres e MinIO ficam intactos.

```bash
cd ~/my-registers
git pull
docker compose -f docker-compose.production.yml --env-file .env.production up -d --build web
```

Após esta release, seguindo o setup de `docs/fase-10-setup.md`, o **próximo release será deploy automático** via `deploy.yml`.

---

## [1.2.0] — 2026-07-27

Adiciona seed TBCA enriquecido + specs registradas para próximas features + docs de deploy.

### Modificado
- **Seed TBCA enriquecido** — adiciona itens comuns brasileiros faltantes (pão francês, tapioca, açaí, queijo prato, requeijão, peito de peru, etc.) e atualiza valores nutricionais de 3 itens conforme fonte TBCA mais recente: arroz_branco_cozido (124→130 kcal/100g), peito_de_frango_grelhado (159→165), leite_integral (61→57 kcal/100ml) ([#11](https://github.com/felixstenian/my-registers/pull/11)).

### Documentação
- **PWA/spec** — Spec `SP-128..SP-135` (Bloco 4 PWA) integrada ao `spec.md` ([#26](https://github.com/felixstenian/my-registers/pull/26)).
- **Workout tracking spec (pós-MVP)** — SP-120..SP-127 registrados como Bloco 3 para implementação futura ([#21](https://github.com/felixstenian/my-registers/pull/21)).
- **CI/CD spec (Fase 10)** — ADR-012 registrada; escolha GitHub Actions vs alternativas ([#22](https://github.com/felixstenian/my-registers/pull/22)).
- **Deploy runbook** — `docs/deploy.md` §10.1 (tabela de escopo de rebuild) e §10.2 (verificação pós-deploy) ([#29](https://github.com/felixstenian/my-registers/pull/29)).

---

## [1.1.0] — 2026-07-27

PWA básico — my-registers vira app instalável com shell offline.

### Adicionado
- **Bloco 4 PWA (SP-128..SP-135)** — Manifest, service worker via Serwist, 4 tamanhos de ícone, meta tags iOS, página `/offline`, toast de update, botão "Instalar" no header ([#27](https://github.com/felixstenian/my-registers/pull/27)).
- **INV-11** — Service worker nunca cacheia respostas de `/api/*` (dados de negócio sempre do DB conforme Art. III §10). Garantido por `verify-sw.mjs` no CI ([#27](https://github.com/felixstenian/my-registers/pull/27)).

### Modificado
- Build do web passa a usar `--webpack` (Serwist ainda não suporta Turbopack — issue [serwist/serwist#54](https://github.com/serwist/serwist/issues/54)) ([#27](https://github.com/felixstenian/my-registers/pull/27)).

### Documentação
- `docs/pwa.md` — Guia completo de instalação por plataforma (iOS Safari, Android Chrome, Desktop), diagnóstico, arquivos-chave ([#27](https://github.com/felixstenian/my-registers/pull/27)).

---

## [1.0.0] — 2026-07-27

Primeira release em produção. MVP end-to-end funcional em `https://myregister.felix.dev.br`.

### Adicionado

**Fases 0-9 do MVP:**
- **Fase 0** — Bootstrap monorepo pnpm + FastAPI + Next.js + Docker + Alembic + CI local.
- **Fase 1** — Autenticação (Argon2id + JWT curto + refresh opaco rotacionado) + CLI de bootstrap idempotente do admin.
- **Fase 2** — Mensagens + upload de mídia via MinIO (S3-compat), pipeline de chat com polling.
- **Fase 3** — Integração Anthropic (Sonnet 4.6 + Haiku 4.5 fallback) via `tool_use` forçado + retry semântico.
- **Fase 4** — Registro de alimentos (LocalTBCACatalog + MealService + DailyRecomputeService).
- **Fase 4.b** — Leitura de tabela nutricional via foto de rótulo.
- **Fase 5** — Hidratação, bebidas calóricas, atividade física.
- **Fase 6** — Correções + exclusões (soft-delete com audit).
- **Fase 7** — Encerramento de dia + relatório do dia (narrativa LLM).
- **Fase 8** — Relatório semanal (últimos 7 dias fechados).
- **Fase 9** — Hardening + runbook de deploy (nginx, certbot, backups, VPS DigitalOcean).

**Blocos pós-MVP entregues:**
- **Bloco 1** — Composer/envio (Enter envia, Shift+Enter quebra, drop de arquivos, cap 8 MB).
- **Bloco 2** — Renderização estruturada de assistant messages (tabelas markdown, `DayTotalsBar`, `PendingItemsModal`).

**Infra:**
- `docker-compose.production.yml` com healthchecks + log rotation.
- Nginx com HSTS 1 ano, CSP, OCSP stapling.
- Certbot com renovação automática (loop de 12h).
- Scripts `backup-postgres.sh` + `backup-minio.sh` (retenção 14d + rclone opcional).
- Script `vps-check.sh` de radiografia rápida.

**Documentação:**
- `docs/deploy.md` — runbook genérico (13 seções).
- `docs/vps-digitalocean.md` — passo a passo DigitalOcean (21 seções).
- `.env.production.example` — template completo.

### Corrigido (hotfixes durante o deploy inicial)
- **#24** — Build de produção quebrava com Next 16 (`useSearchParams` sem Suspense em `/login`; `middleware.ts` deprecated → `proxy.ts`).
- **#25** — Server component do layout protegido chamava `fetch('/api/auth/me')` no Node com URL relativa → `ERR_INVALID_URL`. Fix: variável `INTERNAL_API_URL` separada da `NEXT_PUBLIC_API_URL`.
- Retry semântico da Anthropic rejeitado com HTTP 400 pelo Haiku 4.5 quando payload de tool_result estava malformado ([`c4fa31e`](https://github.com/felixstenian/my-registers/commit/c4fa31e)).
- `IntentDispatcher` propagava `NotFoundError` em `_handle_query_day` ([`3643526`](https://github.com/felixstenian/my-registers/commit/3643526)).

---

## Notas gerais

- **Versionamento**: SemVer sobre a superfície pública (endpoints `/api/*`, contratos de LLM, migrations irreversíveis). Mudanças em UI/UX ou docs contam como MINOR se adicionam capacidade, PATCH se corrigem.
- **Cada release em `main`** deve ter uma tag `vX.Y.Z` e entrada em [GitHub Releases](https://github.com/felixstenian/my-registers/releases). O `deploy.yml` da Fase 10 dispara o deploy automatizado ao mergear em `main` (a partir de v1.3.0, após config manual).
- **Cauda pendente do MVP** (`tasks.md`): T-B408 (splash iOS, adiado por asset). Feature specs registradas para futura implementação: Bloco 3 (workout tracking).
