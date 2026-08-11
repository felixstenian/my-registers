# Especificações Técnicas — Bootstrap de admin via CLI

> **Rastreabilidade**: Const. §18/§24, ADR-001 · Implementação: `apps/api/app/cli/main.py` (96 linhas), `apps/api/app/core/config.py`, `apps/api/app/core/security.py`, `apps/api/app/repositories/user.py`, `scripts/bootstrap.sh`.

## Escopo técnico

CLI Typer exposto por `python -m app.cli` em `apps/api`. 3 comandos implementados: `bootstrap` (criação idempotente do admin default), `seed-nutrition` (catálogo TBCA), `version` (build string). Sem servidor HTTP; não integra com FastAPI runtime — é standalone Python async com `SessionLocal` direto. Senha nunca trafega em logs.

## Interface — commands

### `python -m app.cli bootstrap` (T-105/T-107)
```bash
DEFAULT_ADMIN_EMAIL=admin@example.com \
DEFAULT_ADMIN_PASSWORD=<secret> \
uv run python -m app.cli bootstrap
```
Saída stdout:
- Criado: `[bootstrap] created user_id=<uuid>`
- Já existia: `[bootstrap] already_exists user_id=<uuid>`
Saída stderr em falta:
- `DEFAULT_ADMIN_EMAIL não definido; abortando.` → exit 1
- `DEFAULT_ADMIN_PASSWORD não definido; abortando.` → exit 1

Log estruturado (não em stdout): `logger.info("bootstrap_admin", extra={"event":"cli_bootstrap","user_id":...})`.

### `python -m app.cli seed-nutrition` (T-403)
```bash
uv run python -m app.cli seed-nutrition
# → [seed-nutrition] inserted=N updated=M
```
Popula `nutrient_facts` a partir de `seed_tbca.csv` (BR alimentos comuns). Idempotente: rodar 2x mantém mesmo estado final; não toca em entradas `source='label_ocr'` ou `'user_manual'`.

### `python -m app.cli version`
```
my-registers-api 0.0.0
```

## Modelo de dados — entidade `User`

```python
# apps/api/app/models/user.py
class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("sex IN ('m','f','o','n')", name="ck_users_sex"),)
    email: Mapped[str]          # CITEXT, unique, nullable=False
    password_hash: Mapped[str]  # Text, nullable=False  (Argon2id)
    display_name: Mapped[str|None]
    timezone: Mapped[str]       # "America/Sao_Paulo" default
    weight_kg/height_cm/birthdate/sex: Mapped[...]  # nullable profile fields
    is_active: Mapped[bool]     # default true
```
`CITEXT` torna o email case-insensitive no Postgres; o CLI ainda `lower()` antes do lookup por convenção.

## Interface — internos

### `_bootstrap_admin(email, password) -> tuple[str, bool]`
```python
async def _bootstrap_admin(email: str, password: str) -> tuple[str, bool]:
    async with SessionLocal() as session:
        users = UserRepository(session)
        existing = await users.get_by_email(email)
        if existing is not None:
            return str(existing.id), False  # idempotente
        user = await users.create(
            email=email,
            password_hash=hash_password(password),  # Argon2id
        )
        await session.commit()
        return str(user.id), True
```

### `UserRepository.get_by_email` / `.create`
- `get_by_email(email)`: `SELECT WHERE email = ?` via `select(User)`; retorna `None` se não há.
- `create(email, password_hash, display_name=None)`: `session.add(User(...))` + `flush()` => retorna instância com `id` populado.

### `hash_password(plain) -> str` (Argon2id)
```python
_hasher = PasswordHasher(time_cost=3, memory_cost=64*1024, parallelism=2)
def hash_password(plain: str) -> str:
    return _hasher.hash(plain)
```
Atributos fixos pela Constituição §15-17 e ADR-001; `verify_password`/`needs_rehash` no mesmo modulo.

### Settings (`apps/api/app/core/config.py`)
```python
class Settings(BaseSettings):
    default_admin_email: str = "admin@example.com"
    default_admin_password: str = ""   # força explicitação do env
    # ... mais dezenas de vars
```

## Fluxo de dados

### Bootstrap (deploy / dev initial)
1. Operador/CI provisiona `.env.production` (via SSH manual; **never** GitHub Actions edits) com `DEFAULT_ADMIN_EMAIL`/`DEFAULT_ADMIN_PASSWORD`.
2. `scripts/bootstrap.sh .env.production` carga env → `alembic upgrade head` (cria tables `users` se faltantes).
3. `python -m app.cli bootstrap` chama `get_settings()`. `pydantic-settings` lê envs.
4. Validação: se `default_admin_email` ou `default_admin_password` vazios → exit 1.
5. `asyncio.run(_bootstrap_admin(email.lower(), password))`:
   - `SessionLocal()` abre DB session.
   - `UserRepository.get_by_email(email)` — se existir, retorna `(id, False)` (idempotente).
   - Senão: `users.create(...)` com `hash_password(password)`; `session.commit()`; retorna `(id, True)`.
6. Log estruturado `cli_bootstrap` event; stdout `[bootstrap] {action} user_id={id}`.
7. **Senha nunca** entra em log/extra/stdout.

### Seed-nutrition (deploy)
1. CSV em `app/integrations/nutrition/seed_tbca.csv` (BR alimentos).
2. `python -m app.cli seed-nutrition` → `seed_from_csv(session)` Lê CSV → `upsert` por chave (`canonical_name`?); retorna `(inserted, updated)`.
3. Idempotente: segunda execução updates valores já presentes (ex.: arroz 124→130 kcal); não toca em `source != 'TBCA_2023'`.

### Deploy via Actions (Fase 10)
1. `deploy.yml` faz SSH → VPS executa `command="$DEPLOY_CMD"`.
2. `$DEPLOY_CMD = "cd ~/my-registers && git pull && ./scripts/bootstrap.sh .env.production && docker compose -f docker-compose.production.yml --env-file .env.production up -d --build api web"`.
3. `bootstrap.sh` dentro do `$DEPLOY_CMD` chama `alembic upgrade head` + `python -m app.cli bootstrap` (idempotente).
4. `api`/`web` reconstruídos (`--build api web`).

## Regras de negócio

1. **Idempotência do `bootstrap`**: lookup por email; se existe, retorna id sem reescrever; não há flag de override.
2. **Email lowercased** antes do lookup (`settings.default_admin_email.lower()`): garante match mesmo que env varie.
3. **Senha nunca em logs/stdout** (Const. §19): o CLI só echoa `action` + `user_id`; `password` é descartado após `hash_password`.
4. **Hash Argon2id** (Const. §15): PasswordHasher com `time=3, mem=64MB, par=2`.
5. **Senhas nunca em migration**: admin default é lido do env, não hardcoded. Migration só cria schema.
6. **Runtime da API não roda migrations**: `bootstrap.sh` chama `alembic upgrade head`; runtime da API nunca invoca migrations startup (Const. §24).
7. **Sem endpoint HTTP de register/reset/forgot-password** (Const. §18, SP-05): respondem 404 sem hint; proteção defesa em profundidade.
8. **CLI é standalone** (não depende do FastAPI app): abre `SessionLocal`, dry-run acessível sem iniciar uvicorn.
9. **`is_active` default true**: novo user via bootstrap é ativo por padrão (não há fluxo de ativação no MVP).
10. **`reset-password`/`create-admin` não implementados** — gap focado em MVP single-user; reset atual exige SSH + SQL ad-hoc.

## Configurações e variáveis de ambiente

| Variável | Descrição | Padrão | Obrigatória |
|---|---|---|---|
| `DEFAULT_ADMIN_EMAIL` | Email do admin default (ex.: `admin@example.com` em dev) | `admin@example.com` | Sim |
| `DEFAULT_ADMIN_PASSWORD` | Senha plaintext do admin (lida só no bootstrap; nunca persistida) | `""` (vazio → exit 1) | Sim |
| `LOG_LEVEL` | Nível de log do CLI (`INFO` default via `get_settings`) | `INFO` | Não |
| `LOG_FORMAT` | Formato de log do CLI | JSON ou plain | Não |
| `DATABASE_URL` | URL Postgres para `SessionLocal` | — | Sim |

`.env.example`: `DEFAULT_ADMIN_EMAIL=admin@example.com`, `DEFAULT_ADMIN_PASSWORD=adminadmin` (dev). `.env.production`: valores reais (secrets na VPS).

## Referências de implementação

- **CLI principal**: `apps/api/app/cli/main.py` (96 linhas) — typer `app`, `_bootstrap_admin`, `_seed_nutrition`, `bootstrap`, `seed-nutrition`, `version`.
- **CLI package**: `apps/api/app/cli/__init__.py` re-exports `cli_app`; `__main__.py` chama `app()` no `python -m app.cli`.
- **Config**: `apps/api/app/core/config.py` — `Settings.default_admin_email/password`.
- **Security**: `apps/api/app/core/security.py:29` (`hash_password` Argon2id) + `verify_password`/`needs_rehash` (mesmo módulo consumido na feature `authentication-session`).
- **Repository**: `apps/api/app/repositories/user.py` — `get_by_email`, `create`, `update_password_hash`.
- **Model**: `apps/api/app/models/user.py` — `User(email CITEXT unique, password_hash Text, ...)`.
- **Seed**: `app/integrations/nutrition/seed.py::seed_from_csv` + `seed_tbca.csv` (alimentos BR).
- **Bootstrap script**: `scripts/bootstrap.sh` (Fase 9 T-905) — invocado em deploy Actions E manual.
- **Docs/runbook**: `docs/deploy.md` §41 (`$EDITOR .env.production` referencia §14.1 do `app_plan.md`) + `docs/deploy.md` §83 ("Login manual pelo browser em https://$DOMAIN/login com o admin default").
- **Constituição**: `.specify/memory/constitution.md` Arts. V §18/§19, V §15-17, VI §24.
- **ADR**: ADR-001 (`research.md`) — escolha Argon2id + JWT.
- **Tasks Fase 1**: `tasks.md:28-...` (T-105/T-107); Fase 9 (T-905).
- **Pinagem**: `apps/api/pyproject.toml` lista `typer` como dep.
- **Env**: `apps/api/.env.example:18-19`, `apps/api/tests/conftest.py:29-30` (fixtures).
- **Tests**: [Implementação não localizada] — nenhum teste unit dedicado para `app.cli` em `apps/api/tests/`; cobertura indireta via `conftest` que finge envs. <!-- TODO: adicionar tests/test_cli_bootstrap.py -->