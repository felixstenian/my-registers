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

## [Unreleased]

### Adicionado
- **SP-160..SP-169** — Edição inline de registros no `/day`: formulários expansíveis (`<details>`) para food items, água, bebidas e atividades. PATCH endpoints com recompute de snapshot + auditoria. Propagação de `nutrient_fact` (INV-14) para itens em dias abertos. E2E tests no Playwright.

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
