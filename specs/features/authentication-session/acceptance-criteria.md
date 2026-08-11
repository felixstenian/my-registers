# Critérios de Aceitação — Autenticação e sessão

## AC-001 — Login válido emite par de cookies (SP-01)

**Dado que** admin existe (`admin@example.com` / `adminadmin`) e `is_active=true`
**Quando** `POST /auth/login` com body `{"email": "admin@example.com", "password": "adminadmin"}`
**Então** resposta é `204 No Content`
**E** header `Set-Cookie` contém `access_token=...; HttpOnly; SameSite=Lax; Max-Age=900; Path=/`
**E** header `Set-Cookie` contém `refresh_token=...; HttpOnly; SameSite=Lax; Max-Age=1209600; Path=/`
**E** em produção, cookies também têm `Secure` (`COOKIE_SECURE=true`).

**Notas de validação:**
- `test_auth.py::test_login_success_sets_cookies_and_204`.

---

## AC-002 — Email é case-insensitive (SP-01)

**Dado que** `users.email = 'admin@example.com'` (via `CITEXT`)
**Quando** login com `email='Admin@Example.COM'`
**Então** login sucede exatamente igual ao AC-001.

**Notas**:
- Router faz `email_key = payload.email.lower()` antes do lookup.
- `CITEXT` também garantiria isso mesmo sem `.lower()`, mas belt-and-suspenders.
- `test_auth.py::test_login_case_insensitive_email`.

---

## AC-003 — Credencial inválida devolve 401 genérico (SP-02)

**Dado que** admin existe
**Quando** login com senha errada **OU** email inexistente
**Então** resposta em **ambos os casos** é:
```
401
{"detail": "invalid credentials", "code": "invalid_credentials"}
```
**E** nenhum campo revela qual dos dois foi o motivo.

**Notas**:
- `test_login_invalid_password_returns_401_generic`, `test_login_unknown_email_returns_401_generic`.

---

## AC-004 — Rate limit por IP (SP-02)

**Dado que** 5 requests foram feitas do mesmo IP em < 60s (independente de sucesso)
**Quando** 6ª tentativa do mesmo IP
**Então** 429 `{"code": "rate_limited", "detail": "too many attempts from ip"}`
**E** mesmo com senha correta.

**Notas**:
- `test_auth.py::test_login_rate_limited_by_ip`.
- Reset ocorre após ~60s.

---

## AC-005 — Rate limit por email nas falhas (SP-02)

**Dado que** 10 tentativas falhas foram registradas para `admin@example.com` em 15 min
**Quando** 11ª tentativa com senha correta
**Então** 429 `{"code": "rate_limited", "detail": "too many failed attempts for email"}`.

**Notas**:
- Só falhas incrementam contador (login sucesso não).
- Contador por IP roda em paralelo.
- `test_auth.py::test_login_rate_limited_by_email_failures`.

---

## AC-006 — Rotação de refresh (SP-03)

**Dado que** login emitiu refresh `T1`
**Quando** `POST /auth/refresh` com cookie `refresh_token=T1`
**Então** 204 + novos cookies (novo access + novo refresh `T2`).
**E** no DB, linha do `T1` tem `revoked_at != NULL` e `replaced_by = id_de_T2`.
**E** próxima tentativa de usar `T1` → 401 + `revoke_family` (ver AC-007).

**Notas**:
- `test_auth.py::test_refresh_rotates_and_revokes_old`.

---

## AC-007 — Reuso de refresh revogado invalida família (SP-03, INV-6)

**Dado que** login emitiu `T1`, refresh rotacionou para `T2` (T1 agora revogado)
**Quando** alguém tenta usar `T1` **de novo**
**Então** resposta é 401 `{"code": "invalid_refresh"}`
**E** todos os refreshes do user (incluindo o `T2` legítimo) ficam `revoked_at != NULL`
**E** próximo `POST /auth/refresh` com `T2` também falha.

**Notas**:
- `revoke_family` roda antes do `raise` para não ser perdido no rollback do `get_session`.
- `test_auth.py::test_refresh_reuse_of_revoked_token_invalidates_family`.

---

## AC-008 — Logout revoga refresh + limpa cookies (SP-04)

**Dado que** login emitiu par de cookies
**Quando** `POST /auth/logout` com cookie refresh
**Então** 204
**E** cookies limpos (`Max-Age=0` em Set-Cookie)
**E** `refresh_tokens.revoked_at != NULL` no DB
**E** próxima tentativa de refresh com o mesmo → 401.

**Notas**:
- Sem cookie → 204 direto (idempotente).
- `test_auth.py::test_logout_clears_cookies_and_revokes_refresh`.

---

## AC-009 — Endpoints de cadastro/reset retornam 404 sem hint (SP-05)

**Para cada** um de: `POST /auth/register`, `POST /auth/forgot-password`, `POST /auth/reset-password`
**Quando** request enviado com qualquer body
**Então** 404 `{"detail": "Not Found"}` (padrão FastAPI para rota inexistente)
**E** OpenAPI (`/docs` e `/openapi.json`) não lista essas rotas.

**Notas**:
- `test_auth.py::test_forbidden_public_endpoints_return_404` (parametrizado).

---

## AC-010 — Rota protegida sem cookie → 401 JSON (SP-06)

**Dado que** `GET /auth/me` **sem** cookie
**Então** resposta 401 `{"detail": "...", "code": "unauthorized"}`
**E** nenhum eco do request.

**Notas**:
- `test_auth.py::test_me_without_cookie_returns_401`.

---

## AC-011 — Cookie válido decodifica e devolve usuário (SP-06)

**Dado que** cookie access válido (JWT HS256 assinado com `settings.jwt_secret`)
**Quando** `GET /auth/me`
**Então** 200 com body `{ id, email, display_name, timezone, is_active, created_at }`
**E** **sem** `password_hash`.

**Notas**:
- `test_auth.py::test_me_with_valid_cookie_returns_user`.
- `test_auth.py::test_me_never_returns_password_hash` (regressão explícita de INV-7).

---

## AC-012 — Cookie adulterado → 401 (SP-06, INV-7)

**Dado que** cookie access modificado (payload alterado sem re-assinatura)
**Quando** `GET /auth/me`
**Então** 401 `unauthorized`, **sem** stack trace ou eco do payload.

**Notas**:
- `jose.decode` levanta `JWTError`, capturado por `decode_access_token` → retorna `None`.
- `test_auth.py::test_me_with_tampered_cookie_returns_401`.

---

## AC-013 — Frontend redireciona sem cookie (SP-06)

**Dado que** browser sem cookie navega para `/chat`
**Quando** `proxy.ts` middleware roda
**Então** 302 redirect para `/login?next=/chat`.

**Dado que** browser com cookie navega para `/login`
**Então** 302 redirect para `/chat`.

**Notas**:
- Middleware só olha presença do cookie; validação real é backend.
- `matcher: ['/chat/:path*', '/day/:path*', '/days/:path*', '/weekly/:path*', '/login']`.

---

## AC-014 — Password nunca retorna em nenhuma resposta (INV-7)

**Dado que** um teste percorre todas as rotas com log de resposta
**Então** nenhuma resposta contém `password_hash`, `password`, ou refresh plaintext (exceto no `Set-Cookie` no login/refresh — esperado).

**Notas**:
- `test_auth.py::test_password_never_in_response`.

---

## Cenários de borda

| Cenário | Comportamento esperado |
|---|---|
| Login em user com `is_active=false` | 401 `invalid_credentials` (indistinguível de senha errada). |
| Refresh com cookie ausente | 401 `invalid_refresh`. |
| Refresh de user cujo `is_active` virou `false` depois | 401 `invalid_refresh`. |
| Logout duas vezes seguidas | Ambas 204 (idempotente). |
| Rate limit ativo, senha correta | 429 (rate limit ganha do login). |
| Two-simultaneous-refresh race (mesmo T1 usado 2x concorrente) | Um ganha (rotação), outro cai em `revoked_at != NULL` → `revoke_family`. |
| Server restart | Rate limits em memória são zerados; refresh tokens persistem. |
| `jwt_secret` rotacionado | Todos os access ativos invalidados na hora; refresh continua e emite novos. |

## Critérios de não-funcionalidade

| Critério | Threshold | Fonte |
|---|---|---|
| Latência login P95 | ≤ 300ms (Argon2 domina) | RNF-006 |
| Login rate limit IP | 5 tentativas / 60s | SP-02 |
| Login rate limit email | 10 falhas / 15 min | SP-02 |
| TTL access JWT | 900s (15min) | RNF-003 |
| TTL refresh | 1209600s (14d) | RNF-003 |
| Cookies (prod) | `HttpOnly + Secure + SameSite=Lax + Path=/` | RNF-004 |
| Hash de senha | Argon2id (não Argon2i/d puros) | RNF-001 |
| Storage do refresh | SHA-256 hash | RNF-002 |
