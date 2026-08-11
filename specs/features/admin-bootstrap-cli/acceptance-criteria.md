# Critérios de Aceitação — Bootstrap de admin via CLI

> **Rastreabilidade**: Const. §18/§24, ADR-001 · Contratos: [`requirements.md`](./requirements.md), [`specifications.md`](./specifications.md).

## AC-001 — `bootstrap` cria admin a partir do env (T-107)

**Dado que** `DEFAULT_ADMIN_EMAIL` e `DEFAULT_ADMIN_PASSWORD` estão setados no env e o DB está vazio,
**Quando** `python -m app.cli bootstrap` executa,
**Então** cria um `User` com `email=<email lower>` e `password_hash=Argon2id(password)`; faz `session.commit()`; stdout mostra `[bootstrap] created user_id=<uuid>`.

**Dado que** o usuário já existe com o mesmo email,
**Quando** `bootstrap` executa,
**Então** `UserRepository.get_by_email` retorna a row; `password_hash` **não** é sobrescrito; stdout `[bootstrap] already_exists user_id=<uuid>`.

**Notas de validação:**
- Implementação: `apps/api/app/cli/main.py:24-32, 35-61`.

---

## AC-002 — Senha nunca logada (Const. §19)

**Dado que** `bootstrap` executa com sucesso,
**Quando** inspeciona stdout e log estruturado,
**Então** apenas `[bootstrap] {action} user_id={id}` aparece em stdout e `extra={"event":"cli_bootstrap","user_id":...}` em logs; `password`/`password_hash` não são impressos.

**Dado que** `bootstrap` falha por env ausente,
**Quando** stderr é capturado,
**Então** mensagem menciona apenas `DEFAULT_ADMIN_*  não definido`; senha não trafega.

**Notas de validação:**
- Implementação: `_bootstrap_admin` não retorna/exibe `password`; `typer.echo` só printa `action`+`user_id`.

---

## AC-003 — Envs ausentes abortam (T-107)

**Dado que** `DEFAULT_ADMIN_EMAIL` está vazio,
**Quando** `bootstrap` executa,
**Então** stderr `DEFAULT_ADMIN_EMAIL não definido; abortando.` + exit 1.

**Dado que** `DEFAULT_ADMIN_PASSWORD` está vazio (default `""`),
**Quando** `bootstrap` executa,
**Então** stderr `DEFAULT_ADMIN_PASSWORD não definido; abortando.` + exit 1.

**Dado que** ambos ausentes,
**Quando** `bootstrap` executa,
**Então** o check de `default_admin_email` dispara primeiro (ordem no código); exit 1.

---

## AC-004 — Hash Argon2id conforme Constituição §15

**Dado que** `bootstrap` cria um user,
**Quando** insere `password_hash` no DB,
**Então** a string segue formato `$argon2id$...` com `time_cost=3, memory_cost=64MB, parallelism=2` (parâmetros fixos pela Const. e ADR-001).

**Dado que** `authenticate(email, password)` (feature `authentication-session`) é chamada com senha correta,
**Quando** `verify_password` valida,
**Então** retorna `True`.

**Dado que** params do Argon2 mudam (e.g., `time_cost=4` upgrade),
**Quando** `verify_password` valida com hash velho,
**Então** `needs_rehash()` retorna `True` e login opportunistically re-hash (A).

---

## AC-005 — Email lowercased (RNF-009)

**Dado que** env tem `DEFAULT_ADMIN_EMAIL=Admin@Example.com`,
**Quando** `bootstrap` executa,
**Então** chama `_bootstrap_admin("admin@example.com", password)` (lower foi aplicado no caller); `email` persistida é lowercase.

**Dado que** DB já tem `admin@example.com` (lowercase) e env tem `Admin@Example.com`,
**Quando** `bootstrap` executa,
**Então** idempotência match (gracias ao `lower()` + CITEXT).

---

## AC-006 — Idempotência em deploy subsequente

**Dado que** `bootstrap.sh` roda em cada deploy (via Actions ou manual) E DB tem o admin default,
**Quando** `bootstrap` executa,
**Então** `get_by_email` retorna user existente; senha inalterada; `already_exists`; exit 0.

**Dado que** deploy ocorre em DB ainda sem admin,
**Quando** `bootstrap` executa pela primeira vez,
**Então** user é criado; próximo deploy respeitará idempotência.

---

## AC-007 — Scripts/bootstrap.sh valda `.env.production` (T-905)

**Dado que** `bootstrap.sh .env.production` executa,
**Quando** init,
**Então** valida que `.env.production` existe e tem as vars obrigatórias; aborta se validator falhar (prevenir config drift).

**Dado que** validation passa,
**Quando** script procede,
**Então** roda `alembic upgrade head` + `python -m app.cli bootstrap` em ordem; runtime da API (`uv run uvicorn`) iniciado depois via `docker compose up`.

**Notas de validação:**
- Runtime da API nunca roda migrations (Const. §24); migrations são passo explícito do `bootstrap.sh`.

---

## AC-008 — `seed-nutrition` idempotente (T-403)

**Dado que** CSV já foi importado em algum deploy anterior,
**Quando** `python -m app.cli seed-nutrition` roda novamente,
**Então** atualiza valores nutricionais (upsert) sem duplicar; não toca em `source='label_ocr'` ou `'user_manual'` (somente bancos TBCA).

**Dado que** CSV muda valor (ex.: arroz 124→130 kcal/100g),
**Quando** `seed-nutrition` roda,
**Então** `updated` count reflete a mudança; idempotente.stringValue

---

## AC-009 — Sem endpoints HTTP de cadastro/reset (Const. §18, SP-05)

**Dado que** cliente envia `POST /auth/register` (ou `/forgot-password`, `/reset-password`),
**Quando** FastAPI router resolve,
**Então** retorna 404 sem body/hint que sugira o endpoint.

**Dado que** `apps/api/app/api/routes/auth.py` é inspecionado,
**Quando** lista rotas,
**Então** somente `/login`, `/logout`, `/refresh`, `/me` presentes.

---

## AC-010 — `reset-password` via CLI — pendente (Const. §18)

**Dado que** Felix esqueceu senha do admin,
**Quando** tenta `python -m app.cli reset-password`,
**Então** ([Implementação não localizada]) comando não existe; retorno erro do Typer (`No such command 'reset-password'`).

> **Status**:-gap conhecido; reset atualmente exige SSH + `python -m app.cli` ad-hoc via `UserRepository.update_password_hash`.

---

## AC-011 — `create-admin` adicional — pendente (Const. §18)

**Dado que** precisa criar segundo admin,
**Quando** tenta `python -m app.cli create-admin <email> <password>`,
**Então** ([Implementação não localizada]) comando não existe.

> **Status**: gap conhecido; MVP é single-user.

---

## AC-012 — Login após bootstrap (SP-01)

**Dado que** `bootstrap` foi executado em DB vazio,
**Quando** cliente envia `POST /auth/login { email: <admin email>, password: <admin password> }`,
**Então** resposta 204 + cookies `access_token` + `refresh_token` (feature `authentication-session`).

---

## Cenários de Borda

| Cenário | Comportamento Esperado |
|---|---|
| Email existe com case diferente (`Admin@Example.com` em env vs `admin@example.com` no DB) | `lower()` no caller + `CITEXT` no DB devem match; idempotente `already_exists`. |
| Password com caracteres especiais (`$@#`) | Argon2id lida; `hash_password` aceita qualquer str; secrets no env não sofrem escape problems se quoting shell correto. |
| DB indisponível (Postgres fora) | `SessionLocal()` falha em abrir; exception propagada; exit não-zero (não 1 explicitamente — future: handle claro). |
| `alembic upgrade head` antes falha (migration quebrada) | `bootstrap.sh` aborta; `bootstrap` CLI não roda; deploy falha; containers antigos intactos. |
| `bootstrap` chamado sem `.env` sourceado | `get_settings()` carrega defaults → `default_admin_password=""` → exit 1. |
| Hash gerado com Argon2 params antigos após upgrade de lib | `needs_rehash()` true; login opportunistically re-hash via `auth.py`. |
| Pydantic-settings invalida type (ex.: email número em vez de str) | Não há validator; Settings aceita str livre; próximo passo lower(input); falha em `hash_password`? não - aceita qualquer str. |
| `bootstrap` rodado por usuário não-DB-owner | depende de `DATABASE_URL`; falha em `commit` se sem permissão; exception propagada. |
| 2 deploys paralelos tentam `bootstrap` simultâneo | Race: 2x `get_by_email` retorna None; 2x `create(email)` falha no segundo por unique constraint (CITEXT unique); primeiro vence; segundo exception + exit não-zero. |
| `hash_password` com senha empty após passar check | Note: `if not default_admin_password` short-circuits empty, então nunca chega ao Argon2. |
| Pytest fixtures resetam DB entre tests | `conftest.py` seta `DEFAULT_ADMIN_EMAIL=admin@example.com`, `PASSWORD=adminadmin` e rodam bootstrap indireto por fixtures (`async def create_user(...)`). |

## Critérios de Não-Funcionalidade

| Critério | Threshold |
|---|---|
| Tempo de `bootstrap` em DB ready | < 1s (1 query SELECT + INSERT + commit) |
| Stdout nunca contém password | 0 ocorrências |
| Log nunca contém password_hash | 0 ocorrências (aloa só `user_id`) |
| Idempotência | 2x execução = mesmo estado final |
| Argon2id params | Fixos em `time=3, mem=64MB, par=2` |
| HTTP endpoints de registro/reset | 0 (404 sem hint) |
| Tamanho do CLI | < 100 linhas (96 atual) |
| Dep runtime CLI | `typer` (pequena); shared com FastAPI utilities |