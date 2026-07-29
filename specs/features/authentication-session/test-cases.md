# Casos de Teste — Autenticação e sessão

> Todos em `apps/api/tests/test_auth.py` (integração com Postgres real via `httpx.AsyncClient` + fixture `admin_user`).
> Suite completa: `uv run pytest tests/test_auth.py`.

---

## Testes de integração (contra Postgres + endpoints reais)

### TC-I-001 — Login com sucesso seta cookies e devolve 204

- **Arquivo**: `test_auth.py::test_login_success_sets_cookies_and_204`
- **Setup**: `admin_user` fixture (email `admin@example.com`, senha `adminadmin`, `is_active=true`)
- **Ação**: `POST /auth/login {email, password}`
- **Verificar**:
  - Status 204
  - `Set-Cookie: access_token=...; HttpOnly; SameSite=Lax; Max-Age=900; Path=/`
  - `Set-Cookie: refresh_token=...; HttpOnly; SameSite=Lax; Max-Age=1209600; Path=/`
- **SP**: SP-01

### TC-I-002 — Case-insensitive email

- **Arquivo**: `test_login_case_insensitive_email`
- **Ação**: login com `email='ADMIN@Example.COM'`
- **Verificar**: 204 + cookies (mesmo comportamento do TC-I-001)
- **SP**: SP-01, robustez do `CITEXT`

### TC-I-003 — Senha errada devolve 401 genérico

- **Arquivo**: `test_login_invalid_password_returns_401_generic`
- **Ação**: login com email válido + senha errada
- **Verificar**: 401 `{"code": "invalid_credentials"}`
- **SP**: SP-02

### TC-I-004 — Email inexistente devolve 401 genérico

- **Arquivo**: `test_login_unknown_email_returns_401_generic`
- **Ação**: login com email que não existe
- **Verificar**: mesma resposta do TC-I-003 (indistinguível)
- **SP**: SP-02

### TC-I-005 — Rate limit por IP

- **Arquivo**: `test_login_rate_limited_by_ip`
- **Ação**: 6 requests do mesmo IP em <60s (5 falhas + tentativa)
- **Verificar**: 6ª → 429 `{"code": "rate_limited"}`, mesmo com credenciais corretas
- **SP**: SP-02
- **Setup**: fixture reseta limiters entre testes

### TC-I-006 — Rate limit por email (falhas)

- **Arquivo**: `test_login_rate_limited_by_email_failures`
- **Ação**: 10 falhas seguidas para `admin@example.com`, 11ª com senha correta
- **Verificar**: 11ª → 429 `{"code": "rate_limited"}`
- **SP**: SP-02

### TC-I-007 — Rotação de refresh

- **Arquivo**: `test_refresh_rotates_and_revokes_old`
- **Fluxo**: login → capture `T1` → `POST /auth/refresh` com `T1`
- **Verificar**:
  - 204 + novo par
  - No DB: `T1.revoked_at != NULL`, `T1.replaced_by = T2.id`
  - `T2.revoked_at IS NULL`
- **SP**: SP-03

### TC-I-008 — Reuso de refresh revogado invalida família

- **Arquivo**: `test_refresh_reuse_of_revoked_token_invalidates_family`
- **Fluxo**: login → refresh (T1→T2) → tentar usar T1 de novo
- **Verificar**:
  - Segunda tentativa com T1 → 401 `{"code": "invalid_refresh"}`
  - Todos os refresh tokens do user agora com `revoked_at != NULL` (incluindo T2)
  - Tentativa subsequente com T2 → 401 também
- **SP**: SP-03, INV-6

### TC-I-009 — Logout revoga refresh + limpa cookies

- **Arquivo**: `test_logout_clears_cookies_and_revokes_refresh`
- **Fluxo**: login → `POST /auth/logout` com cookie
- **Verificar**:
  - 204
  - Set-Cookie limpando `access_token` e `refresh_token` (Max-Age=0)
  - `refresh_tokens.revoked_at != NULL`
  - Nova tentativa de refresh com o mesmo token → 401
- **SP**: SP-04

### TC-I-010 — Endpoints públicos hipotéticos retornam 404

- **Arquivo**: `test_forbidden_public_endpoints_return_404` (parametrizado)
- **Paths testados**: `/auth/register`, `/auth/forgot-password`, `/auth/reset-password`
- **Verificar**: 404 sem hint (nem 405 nem 403)
- **SP**: SP-05

### TC-I-011 — `/auth/me` sem cookie → 401

- **Arquivo**: `test_me_without_cookie_returns_401`
- **Ação**: `GET /auth/me` sem headers
- **Verificar**: 401 `{"code": "unauthorized"}`
- **SP**: SP-06

### TC-I-012 — `/auth/me` com cookie válido → user (sem hash)

- **Arquivo**: `test_me_with_valid_cookie_returns_user`
- **Fluxo**: login → `GET /auth/me`
- **Verificar**: 200; body tem `{id, email, display_name, timezone, is_active, created_at}`; **não** tem `password_hash`
- **SP**: SP-06

### TC-I-013 — Cookie adulterado → 401 sem eco

- **Arquivo**: `test_me_with_tampered_cookie_returns_401`
- **Ação**: modificar payload JWT sem re-assinar; enviar como cookie
- **Verificar**: 401 sem stack trace, sem eco do payload
- **SP**: SP-06, INV-7

### TC-I-014 — Password nunca vaza em resposta

- **Arquivo**: `test_password_never_in_response`
- **Ação**: percorrer respostas de login/refresh/me/logout
- **Verificar**: strings `password`, `password_hash`, `argon2` **não** aparecem em nenhuma resposta (exceto cookies `Set-Cookie`)
- **SP**: INV-7

### TC-I-015 — `/auth/me` nunca vaza `password_hash`

- **Arquivo**: `test_me_never_returns_password_hash`
- **Ação**: pegar resposta de `GET /auth/me`
- **Verificar**: chave `password_hash` ausente
- **SP**: INV-7

---

## Testes unitários (a criar / potenciais gaps)

Estes cobrem `app/core/security.py` isoladamente — parte da suíte pode já estar em `test_auth.py` mas ganhariam de ser separados:

### TC-U-001 — `hash_password + verify_password` roundtrip

- Hash de string qualquer, verify contra hash → True.
- Verify com senha errada → False.

### TC-U-002 — `needs_rehash` detecta downgrade

- Passar hash em formato antigo (bcrypt fake, ou params obsoletos) → True.
- Passar hash Argon2id atual → False.

### TC-U-003 — `encode/decode_access_token` roundtrip

- Encode com sub/sid → decode devolve `{sub, sid, exp}` correto.
- Decode com JWT expirado → `None` (não exception).
- Decode com JWT adulterado → `None`.

### TC-U-004 — `generate_refresh_token` produz strings únicas e URL-safe

- N gerações → todos únicos.
- `re.match(r'^[A-Za-z0-9_-]+$', token)` para cada.

### TC-U-005 — `hash_refresh_token` é determinístico

- Mesma entrada → mesmo output.
- Comparação com igualdade estrita ok.

---

## E2E manuais

### TC-E-001 — Login → navegação → logout → tentar rota protegida

- **Persona**: Felix (browser Chrome)
- **Passos**: `/login`, submeter, ver redirect para `/chat`, clicar `/weekly`, clicar botão "Sair" (dispara logout), tentar acessar `/chat` de novo
- **Resultado esperado**: última tentativa redireciona para `/login`

### TC-E-002 — Expiração de access, refresh automático

- **Passos**: login, esperar 15 min (ou forçar `JWT_ACCESS_TTL_SECONDS=10` em dev), fazer request para `/api/*`
- **Resultado esperado**: axios recebe 401, chama `/auth/refresh`, retry com novo access — usuário não percebe

### TC-E-003 — Expiração de refresh, redirect forçado

- **Passos**: `REFRESH_TTL_SECONDS=60` em dev, esperar 61s, tentar refresh
- **Resultado esperado**: 401 `invalid_refresh`, frontend redireciona para `/login`

### TC-E-004 — Refresh vazado (simulação de ataque)

- **Passos**: login em browser A → capturar cookies → colar em browser B → refresh em A (rotaciona) → refresh em B com token antigo
- **Resultado esperado**: refresh em B falha; refresh em A também passa a falhar (família invalidada); ambos precisam relogar

---

## Testes de regressão críticos

- **`test_refresh_reuse_of_revoked_token_invalidates_family`** — se a lógica de commit-antes-do-raise (linhas 79-82 de `services/auth.py`) regredir, a revogação da família some junto com o rollback do dependency.
- **`test_password_never_in_response`** — garante que expansão futura do `UserMe` ou de outros schemas não vaze hash.
- **`test_forbidden_public_endpoints_return_404`** — se alguém acidentalmente adicionar `POST /auth/register` como wrapper de admin, esse teste quebra imediatamente.

## Como rodar

```bash
cd apps/api

# suite completa (Postgres precisa estar rodando: pnpm infra:up):
uv run pytest tests/test_auth.py -v

# um teste específico:
uv run pytest tests/test_auth.py::test_refresh_reuse_of_revoked_token_invalidates_family -v

# com coverage no service:
uv run pytest tests/test_auth.py --cov=app/services/auth --cov=app/core/security --cov-report=term-missing
```
