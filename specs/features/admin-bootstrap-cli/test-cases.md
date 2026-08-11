# Casos de Teste — Bootstrap de admin via CLI

> **Rastreabilidade**: Const. §18/§24, ADR-001 · CLI: `apps/api/app/cli/main.py`.
> **Tests existentes**: [Implementação não localizada] — nenhum `tests/test_cli*.py` dedicado; cobertura indireta via `conftest.py` (envs hardcoded) e via `apps/api/tests/test_auth.py` (login do admin default).

## Cobertura alvo

- **Unitários (alvo)**: `_bootstrap_admin` (idempotência, hash Argon2id, sem password em retorno), `hash_password` (params fixos), `Commands` via `typer.testing.CliRunner`.
- **Integração (alvo)**: `python -m app.cli bootstrap` em DB real (Postgres 16 service, igual ao jobs `api` do CI).
- **E2E manual (existente)**: Primeiro deploy provisiona admin via `bootstrap.sh`.

---

## Testes Unitários (alvo pendente)

> [Implementação não localizada] — adicionar `apps/api/tests/test_cli_bootstrap.py`. <!-- TODO: criar test_cli_bootstrap.py -->

### TC-U-001 — `bootstrap` cria user em DB vazio
- **Módulo**: `apps/api/app/cli/main.py::_bootstrap_admin`
- **Entrada**: `email="admin@example.com"`, `password="adminadmin"`, DB sem `User` com esse email.
- **Saída esperada**: retorna `(str(user.id), True)`; row persistida com `email="admin@example.com"` e `password_hash` começando `$argon2id$`.
- **Tipo**: Happy path

### TC-U-002 — `bootstrap` idempotente em user existente
- **Pré-condições**: DB tem `User(email="admin@example.com", password_hash="$argon2id$蒿...")`.
- **Entrada**: chamar `_bootstrap_admin("admin@example.com", "novasenha")`.
- **Saída esperada**: retorna `(existing_id, False)`; `password_hash` **não** trocado (SELECT, sem UPDATE).
- **Tipo**: Edge case (idempotência)

### TC-U-003 — `bootstrap` lowercases email
- **Entrada**: `email="Admin@Example.com"`.
- **Saída esperada**: `_bootstrap_admin` chama `users.get_by_email("admin@example.com")`; se criando, persiste `email="admin@example.com"`.
- **Tipo**: Edge case (normalização)

### TC-U-004 — `bootstrap` com `DEFAULT_ADMIN_PASSWORD` vazio aborta
- **Setup**: `Settings.default_admin_password = ""` (default).
- **Comando**: `python -m app.cli bootstrap` via `typer.testing.CliRunner`.
- **Saída esperada**: exit code 1; stderr contém "DEFAULT_ADMIN_PASSWORD não definido; abortando."; nenhum INSERT no DB.
- **Tipo**: Error case

### TC-U-005 — `bootstrap` com `DEFAULT_ADMIN_EMAIL` vazio aborta (ordem primeiro)
- **Setup**: `Settings.default_admin_email = ""` e `default_admin_password` setado.
- **Saída esperada**: stderr menciona `DEFAULT_ADMIN_EMAIL` (check primeiro); exit 1; nenhum INSERT.
- **Tipo**: Error case

### TC-U-006 — `bootstrap` nunca loga senha
- **Pré-condições**: capture stdout/stderr + log handler.
- **Passos**: roda `bootstrap` feliz path.
- **Resultado esperado**: stdout só `[bootstrap] created user_id=<uuid>`; log estruturado `extra={"event":"cli_bootstrap","user_id":...}` (sem `password`/`password_hash`).
- **Tipo**: Conformidade Const. §19

### TC-U-007 — `hash_password` produz Argon2id com params da Const.
- **Módulo**: `apps/api/app/core/security.py::hash_password`
- **Entrada**: `"adminadmin"`.
- **Saída esperada**: string começando `$argon2id$v=19$m=65536,t=3,p=2$`.
- **Tipo**: Conformidade ADR-001

### TC-U-008 — `needs_rehash` detecta hash antigo
- **Entrada**: hash Argon2 com `memory_cost=32768` (antes do upgrade).
- **Saída esperada**: `needs_rehash(hash) == True` → auth re-hash opportunistically.
- **Tipo**: Edge case

### TC-U-009 — `seed-nutrition` idempotente
- **Entrada**: DB já contém `nutrient_facts` com `canonical_name='arroz_branco_cozido'`. Rerodar `seed-nutrition` com CSV atualizado (kcal 124→130).
- **Saída esperada**: row atualizada; `inserted=0, updated>=1`; nenhum `source != 'TBCA_2023'` é tocado.
- **Tipo**: Idempotência

### TC-U-010 — `version` exibe build
- **Comando**: `python -m app.cli version`.
- **Saída esperada**: stdout `my-registers-api 0.0.0`.
- **Tipo**: Happy path

---

## Testes de Integração

### TC-I-001 — `bootstrap` em Postgres real (CI job api replica)
- **Pré-condições**: Postgres 16 service (como CI), `DATABASE_URL` aponta para DB, `alembic upgrade head` rodou (tabela `users` existe).
- **Passos**:
  1. Set `DEFAULT_ADMIN_EMAIL=admin@example.com`, `DEFAULT_ADMIN_PASSWORD=adminadmin`.
  2. `uv run python -m app.cli bootstrap`.
  3. Verifica: `User` row existe na tabela `users`; `password_hash` começa `$argon2id$`.
- **Resultado esperado**: created; stdout `[bootstrap] created user_id=<uuid>`.

### TC-I-002 — `bootstrap` 2x em sequência mostra `already_exists`
- **Passos**: do TC-I-001, rodar `bootstrap` novamente sem mudar env.
- **Resultado esperado**: `already_exists` no stdout; `User.password_hash` não mudou (assert via SELECT antes/depois).
- **Tipo**: Idempotência

### TC-I-003 — Login após bootstrap (SP-01 chain)
- **Poós** TC-I-001: `POST /auth/login { email, password }`.
- **Resultado esperado**: 204 + cookies; UTC distingue de feature `authentication-session`.

### TC-I-004 — `scripts/bootstrap.sh .env.production` em VPS dry-run
- **Passos** (em staging/non-prod env): set `.env` válido; rodar `bash scripts/bootstrap.sh .envтест`.
- **Resultado esperado**: validate `.env` → `alembic upgrade head` → `python -m app.cli bootstrap` em ordem; exit 0; admin disponível.

### TC-I-005 — `bootstrap.sh` aborta em `.env` ausente/inválido
- **Passos**: rodar `bootstrap.sh` sem `.env.production` (ou arquivo incompleto).
- **Resultado esperado**: stderr + exit 1 antes de chamar Alembic/CLI.

### TC-I-006 — `POST /auth/register` retorna 404 (Const. §18, SP-05)
- **Passos**: `curl -X POST $API/auth/register -d '{"email":"x","password":"y"}'`.
- **Resultado esperado**: 404; sem body informativo (no hint).
- **Tipo**: Conformidade (existente em `test_auth.py`)

### TC-I-007 — Roteamento do `auth.py` só tem 4 rotas
- **Passos**: introspectar FastAPI app routes.
- **Resultado esperado**: `/auth/login`, `/auth/logout`, `/auth/refresh`, `/auth/me` apenas; sem `register`/`forgot`/`reset`.

---

## Testes E2E (manuais)

### TC-E-001 — Primeiro deploy provisiona admin
- **Persona**: Felix (operador primeiro deploy).
- **Passos**:
  1. Provisionar VPS + `.env.production` com `DEFAULT_ADMIN_*`.
  2. `bash scripts/bootstrap.sh .env.production`.
  3. Subir `docker compose ... up -d`.
  4. Browser: `https://$DOMAIN/login` com email/senha do env.
- **Resultado esperado**: login funciona; redireciona pra `/chat`.

### TC-E-002 — Deploy subsequente (CD) não quebra admin
- **Passos**: deploy subsequente via GitHub Actions `deploy.yml`.
- **Resultado esperado**: `bootstrap.sh` roda idempotente; admin hook from env já existe; senha atual preservada; login continua funcionando.

### TC-E-003 — Troca de senha admin (workaround atual, sem CLI reset-password)
- **Passos** Felix atualmente faz:
  1. SSH na VPS.
  2. `docker compose exec api python -c "..."` ou `uv run python -c "...": from app.repositories.user import ...; update_password_hash(...)`.
- **Resultado esperado**: novo `password_hash` persistido; login com nova senha funciona.
- **Notas**: gap — TX de produto `reset-password` command listada em US-004.

---

## Testes de Regressão

Casos críticos a manter a cada release:

- **R-001** (Const. §19): stdout/log nunca contém `password`/`password_hash`.
- **R-002** (T-107): `bootstrap` idempotente — senha não sobrescrita em user existente.
- **R-003** (Const. §18 + SP-05): `/auth/register`, `/forgot-password`, `/reset-password` respondem 404 sem hint.
- **R-004** (ADR-001): `password_hash` sempre `$argon2id$v=19$m=65536,t=3,p=2$...`.
- **R-005** (T-107): `bootstrap` exit 1 quando `DEFAULT_ADMIN_*` vazio.
- **R-006** (Const. §24): runtime da API nunca roda migrations — `bootstrap.sh` é o único canal.
- **R-007** (T-905): `bootstrap.sh` valida `.env.production` antes de rodar.
- **R-008** (RNF-009): email lowercased + CITEXT unique garantem match case-insensitive.
- **R-009** (T-403): `seed-nutrition` idempotente; não toca em `source != 'TBCA_2023'`.
- **R-010** (Const. §15): `PasswordHasher(time=3, mem=64*1024, par=2)` params fixos; `needs_rehash` detecta upgrade opportunistic.