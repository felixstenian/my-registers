# Requisitos — Bootstrap de admin via CLI

> **Rastreabilidade**: Constituição Art. V §18 e Art. VI §24 em [`.specify/memory/constitution.md`](../../.specify/memory/constitution.md) · ADR-001 (Argon2id + JWT) · Implementação: `apps/api/app/cli/main.py` (commands `bootstrap`, `seed-nutrition`, `version`), `apps/api/app/core/config.py` (`default_admin_*`), `apps/api/app/core/security.py::hash_password`, `apps/api/app/repositories/user.py`, `scripts/bootstrap.sh`. Fase 1 (T-105/T-107) concluída; `reset-password`/`create-admin` ainda **não implementados** (§18 menciona como referência).

## Visão geral

Comando CLI `python -m app.cli bootstrap` cria o usuário admin default a partir de variáveis de ambiente (`DEFAULT_ADMIN_EMAIL`/`DEFAULT_ADMIN_PASSWORD`), aplicando Argon2id e nunca ecoando a senha. Idempotente: executar 2x não sobrescreve o usuário. Complementarmente, `seed-nutrition` popula o catálogo TBCA e `version` exibe build. Reflete Arts. V §18 (sem endpoints HTTP de cadastro/reset) e VI §24 (bootstrap CLI idempotente); a senha nunca vem do runtime da API nem é lida de migration.

## Requisitos funcionais

| ID | Requisito | Fonte | Prioridade |
|---|---|---|---|
| RF-001 | `python -m app.cli bootstrap` lê `DEFAULT_ADMIN_EMAIL` e `DEFAULT_ADMIN_PASSWORD` do ambiente; aplica Argon2id via `hash_password()`; persiste `User({email, password_hash})`; commit. | Const. §24, T-107 | Must Have |
| RF-002 | Idempotência: se já existe `User` com o email, **não** sobrescreve; retorna id existente e registra `already_exists`. | T-107 | Must Have |
| RF-003 | Email é normalizado para lowercase antes do lookup (`settings.default_admin_email.lower()`). | [Inferido do código] | Must Have |
| RF-004 | Falta de `DEFAULT_ADMIN_EMAIL` ou `DEFAULT_ADMIN_PASSWORD` aborta com exit 1 e mensagem em stderr ("... não definido; abortando."). | T-107 | Must Have |
| RF-005 | Senha **nunca** ecoada em stdout nem logs (Const. §19); stdout contém apenas `[bootstrap] {created|already_exists} user_id={uuid}`. | Const. §19 | Must Have |
| RF-006 | Log estruturado via `logger.info("bootstrap_admin", extra={"event": "cli_bootstrap", "user_id": ...})`. | [Inferido do código] | Should Have |
| RF-007 | `python -m app.cli seed-nutrition` popula/atualiza `nutrient_facts` a partir de `seed_tbca.csv` (idempotente; não toca em rótulos OCR/manuais). | T-403 | Should Have |
| RF-008 | `python -m app.cli version` exibe `my-registers-api 0.0.0`. | [Inferido do código] | Could Have |
| RF-009 | `scripts/bootstrap.sh` (Fase 9) chama `alembic upgrade head` + `python -m app.cli bootstrap` idempotentes; valida `.env.production` antes de rodar. Runtime da API **não** roda migrations (INV: Art. VI §24 — runtime never migrations). | T-905 | Must Have |
| RF-010 | `POST /auth/register`, `/auth/forgot-password`, `/auth/reset-password` **MUST NOT** existir — respondem 404 sem hint. | Const. §18, SP-05 | Must Have |
| RF-011 | `python -m app.cli reset-password` — reset de senha do admin via CLI. | Const. §18 | Could Have |
| RF-012 | `python -m app.cli create-admin` — criação de admin adicional via CLI. | Const. §18 | Could Have |

> **Status RF-011/RF-012**: [Implementação não localizada] — A Constituição §18 menciona `create-admin`/`reset-password` como referência, mas só `bootstrap` está implementado em `apps/api/app/cli/main.py`. O admin default é único (`admin@example.com / adminadmin` no dev); reset atualmente requer SSH manual no banco.

## Requisitos não funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | Hash Argon2id com params fixos `time_cost=3, memory_cost=64MB, parallelism=2` (Constituição §15) — via `argon2.PasswordHasher`. | Segurança |
| RNF-002 | CLI é exclusivo canal de criação/reset de usuário (sem endpoint HTTP). Invocação por humano com SSH na VPS. | Segurança |
| RNF-003 | Senha lida do environment (`pydantic-settings`) — não de migration nem hardcoded. `default_admin_password` default `""` (vazio) força omissão explícita. | Segurança |
| RNF-004 | `typer` framework — commands declarativos; `add_completion=False`, `no_args_is_help=True`. | DX |
| RNF-005 | `pydantic-settings` valida tipos e injeta envs; `default_admin_email` default `"admin@example.com"` (conveniência dev; `.env.example` documenta). | Reprodutibilidade |
| RNF-006 | Interna async via `asyncio.run(_bootstrap_admin(...))`; tipo `async with SessionLocal()`. | Corretude |
| RNF-007 | Não há teste automatizado para o CLI `bootstrap` no `apps/api/tests/` (testado indiretamente via `conftest` que aplica envs hardcoded `admin@example.com / adminadmin` em fixtures). | — (gap) |
| RNF-008 | `scripts/bootstrap.sh` shared entre deploy Actions e deploy manual (A); valida `.env.production` para evitar config drift. | Operacional |
| RNF-009 | `User.email` é `CITEXT` (case-insensitive unique); ainda assim `bootstrap` lower-cases o email no lookup. | Corretude |
| RNF-010 | `apps/api/.env.example` documenta `DEFAULT_ADMIN_EMAIL=admin@example.com` + `DEFAULT_ADMIN_PASSWORD=adminadmin` — defaults de dev; em prod são valores reais. | DX |

## Restrições e premissas

- **Constituição Art. V §18 e Art. VI §24 inegociáveis**: nunca endpoint HTTP de cadastro/reset; bootstrap CLI idempotente.
- **Senha nunca em migration** — ADR-001/Const. §24 proíbe; admin default vem do env lido no deploy.
- **Runtime da API não roda migrations** — `bootstrap.sh` asdispara em passo explícito antes de subir `api`; deploy nunca atalhos via app runtime.
- **`reset-password`/`create-admin` ainda não implementados** — gap conhecido; reset atualmente exige SSH + SQL/Python ad-hoc.
- **Padrão dev**: `admin@example.com / adminadmin` (em `conftest.py` e `.env.example`); **em prod** são valores reais via `.env.production` (secrets, não no GitHub).
- **Single-user MVP**: User model tem campo `is_active` boolean; não há role `admin`/`user` (Art. V §20 — única conta).
- **`bootstrap` não tem flag de força** — impossível sobrescrever; para trocar a senha via CLI futuro `reset-password` é necessário.

## Dependências

**Depende de:**
- [`authentication-session`](../authentication-session/requirements.md) — senha normalizada Argon2id (`security::hash_password`); SP-01 (login) assume admin já criado via bootstrap.
- **ADR-001** (`research.md`) — escolha Argon2id + JWT + refresh opaco.
- `alembic` (runtime CLI迁移 cascata) — para `bootstrap.sh`.
- `app/integrations/nutrition/seed.py::seed_from_csv` — para `seed-nutrition`.
- `pydantic-settings` + `app/core/config.py::get_settings` — para ler `default_admin_*`.
- **Fase 10 (CI/CD)** — `scripts/bootstrap.sh` é o mesmo rodado pelo GitHub Actions deploy (`deploy-pipeline-ci-cd`).

**Requerido por:**
- [`authentication-session`](../authentication-session/requirements.md) — preciso de admin no DB antes do primeiro login.
- [`deploy-pipeline-ci-cd`](../deploy-pipeline-ci-cd/requirements.md) — deploy scripts chamam `bootstrap.sh`.
- Toda feature que assume usuário autenticado (chat, /day, /weekly, records) — indireto via SP-01.