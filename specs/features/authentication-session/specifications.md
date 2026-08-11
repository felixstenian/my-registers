# Especificações Técnicas — Autenticação e sessão

> **Fontes**: `apps/api/app/api/routes/auth.py`, `apps/api/app/services/auth.py`, `apps/api/app/core/security.py`, `apps/api/app/core/rate_limit.py`, `apps/api/app/api/deps.py`, `apps/api/app/models/refresh_token.py`, `apps/web/src/proxy.ts`.

## Escopo técnico

Cobre o pipeline de sessão do backend (login/refresh/logout/me) e o proxy client-side do Next.js. Não cobre criação de usuário nem reset de senha — ver [`admin-bootstrap-cli`](../admin-bootstrap-cli/).

## Endpoints / Interface

### `POST /auth/login`

- **Auth**: pública (mas sujeita a rate limits).
- **Body** (`LoginRequest`, [`app/schemas/auth.py`](../../../apps/api/app/schemas/auth.py)):
  ```json
  { "email": "user@example.com", "password": "adminadmin" }
  ```
- **Sucesso**: `204 No Content` + `Set-Cookie: access_token=<JWT>`, `Set-Cookie: refresh_token=<opaque>`.
- **Erro `invalid_credentials`**: `401`
  ```json
  { "detail": "invalid credentials", "code": "invalid_credentials" }
  ```
  (email inexistente e senha errada devolvem exatamente o mesmo shape).
- **Erro `rate_limited`**: `429`
  ```json
  { "detail": "too many attempts from ip", "code": "rate_limited" }
  ```
- **Efeitos colaterais**:
  - `ip_limiter.record(ip)` **antes** de tentar autenticar (contabiliza a tentativa).
  - Se autenticação falhar: `email_limiter.record(email_key)` (só falhas incrementam contador de email).
  - Se `needs_rehash(user.password_hash)`: atualiza `users.password_hash`.

### `POST /auth/refresh`

- **Auth**: cookie `refresh_token` obrigatório.
- **Body**: vazio.
- **Sucesso**: `204` + novo par de cookies.
- **Erros**: `401 {code: "invalid_refresh"}` quando: cookie ausente, hash inválido, token expirado, user inativo, **ou reuso de token já revogado**. Neste último, `revoke_family(user_id)` roda antes do commit — invalida todos os refreshes ativos daquele usuário.
- **Efeito colateral**: refresh usado marcado com `revoked_at` e `replaced_by = novo_refresh.id`.

### `POST /auth/logout`

- **Auth**: cookie `refresh_token` opcional (idempotente).
- **Sucesso**: `204` + cookies limpos (`Max-Age=0`).
- **Se refresh presente e ativo**: revoga (marca `revoked_at`).
- **Se refresh ausente ou já revogado**: silencioso (limpa cookies mesmo assim).

### `GET /auth/me`

- **Auth**: `access_token` válido (via `Depends(get_current_user)`).
- **Sucesso**: `200` + `UserMe` (id, email, display_name, timezone, is_active, created_at). **Nunca** inclui `password_hash`.
- **Erro**: `401` com `code=unauthorized` se cookie ausente ou JWT inválido/expirado.

## Modelo de dados

### `users`

Modelo: [`apps/api/app/models/user.py`](../../../apps/api/app/models/user.py)

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | UUID | PK |
| `email` | `CITEXT UNIQUE NOT NULL` | Case-insensitive (`felix@x.com` == `Felix@X.com`) |
| `password_hash` | text | Argon2id ("$argon2id$...") |
| `display_name` | text NULL | Livre |
| `timezone` | text NOT NULL DEFAULT `'America/Sao_Paulo'` | Base do "dia local" (SP-92) |
| `weight_kg`, `height_cm`, `birthdate`, `sex` | numeric/date/char(1) | Perfil (SP-61) |
| `is_active` | bool NOT NULL DEFAULT true | Desativar sem deletar |

### `refresh_tokens`

Modelo: [`apps/api/app/models/refresh_token.py`](../../../apps/api/app/models/refresh_token.py)

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | UUID | PK |
| `user_id` | UUID FK users(id) ON DELETE CASCADE | Owner |
| `token_hash` | text UNIQUE NOT NULL | SHA-256 do refresh plaintext |
| `issued_at`, `expires_at` | timestamptz | Ciclo de vida |
| `revoked_at` | timestamptz NULL | Marca revogação (rotação ou logout ou família invalidada) |
| `replaced_by` | UUID FK refresh_tokens(id) NULL | Aponta pro token novo emitido na rotação (audit chain) |
| `user_agent` | text NULL | Header do request |
| `ip` | inet NULL | IP do cliente na emissão |

**Índice**: `ix_refresh_tokens_user_expires (user_id, expires_at)` — para varredura eficiente de família ativa.

## Fluxo de dados

### Login bem-sucedido

```
POST /auth/login {email, password}
  ├─ ip_limiter.is_blocked(ip)?             → 429 se sim
  ├─ email_limiter.is_blocked(email)?       → 429 se sim
  ├─ ip_limiter.record(ip)
  ├─ AuthService.login(email, password, ua, ip):
  │     ├─ user = UserRepository.get_by_email(email)
  │     ├─ if user is None or not is_active → UnauthorizedError(invalid_credentials)
  │     ├─ if not verify_password(password, hash) → UnauthorizedError(invalid_credentials)
  │     ├─ if needs_rehash(hash) → update_password_hash(user, hash_password(password))
  │     └─ _issue_pair(user, ua, ip):
  │           ├─ refresh_plain = generate_refresh_token()   (secrets.token_urlsafe)
  │           ├─ INSERT refresh_tokens { hash=SHA-256(refresh_plain), user, exp=+14d, ua, ip }
  │           ├─ (access, exp) = encode_access_token(sub=user.id, sid=refresh_row.id)
  │           └─ return IssuedSession(user, access, refresh_plain, ...)
  ├─ Set-Cookie access_token/refresh_token (HttpOnly, Secure=env, SameSite=Lax)
  └─ 204 No Content
```

### Refresh + detecção de reuso

```
POST /auth/refresh (cookie refresh_token)
  ├─ token_hash = SHA-256(refresh_plain)
  ├─ token = RefreshTokenRepository.get_by_hash(token_hash)
  ├─ if token is None → UnauthorizedError(invalid_refresh)
  ├─ if token.revoked_at IS NOT NULL:                   # SP-03 / INV-6
  │     ├─ RefreshTokenRepository.revoke_family(token.user_id)
  │     ├─ session.commit()                             # antes do raise, pra não perder revoke
  │     └─ UnauthorizedError(invalid_refresh)           # força relogin
  ├─ if token.expires_at ≤ now → UnauthorizedError(invalid_refresh)
  ├─ user = UserRepository.get_by_id(token.user_id)
  ├─ if user is None or not is_active → UnauthorizedError(invalid_refresh)
  ├─ new_session = _issue_pair(...)
  ├─ new_row = RefreshTokenRepository.get_by_hash(hash(new_session.refresh_token))
  ├─ RefreshTokenRepository.revoke(token, replaced_by=new_row.id)
  └─ 204 + novo par
```

### Route protection

```
Cliente → GET /chat (browser)
  ├─ Next middleware (proxy.ts):
  │     ├─ pathname ∈ ['/chat', '/day', '/days', '/weekly']
  │     ├─ has(access_token)? → NextResponse.next()
  │     └─ else → 302 /login?next=/chat
  ├─ Backend /api/*:
  │     └─ Depends(get_current_user):
  │           ├─ decode_access_token(cookie) → payload
  │           ├─ if None → 401 unauthorized
  │           ├─ user = get_by_id(payload.sub)
  │           └─ if user None or not is_active → 401 unauthorized
```

## Regras de negócio

1. **Email é case-insensitive**: `LoginRequest` aceita `EmailStr`, e o router chama `.lower()` antes de `get_by_email`. `users.email` é `CITEXT` no schema.
2. **Erro genérico em qualquer falha de auth**: `invalid_credentials` para email inexistente, senha errada, user inativo — indistinguível.
3. **Rate limit é aplicado antes** da verificação: mesmo com senha correta, um email bloqueado devolve `rate_limited`. Isso é intencional (SP-02).
4. **Rate limit por IP conta toda tentativa**; **rate limit por email só falhas**. Combinado, mitiga brute force distribuído e concentrado.
5. **Rotação obrigatória**: nunca reaproveitamos um refresh — ao ser trocado, é revogado com `replaced_by` apontando pro novo. Cadeia auditável.
6. **Família = todos os refreshes ativos do usuário**. `revoke_family(user_id)` marca `revoked_at=NOW()` em todos com `revoked_at IS NULL`.
7. **Logout é idempotente**: sem cookie → 204 direto. Cookie inválido → 204 direto. Cookie válido → revoke + 204.
8. **Access token é stateless**: sem chamada ao DB para verificar (só `decode_access_token` + `get_by_id` para pegar o `User`). O `sid` (session id) é o `refresh_tokens.id` de origem; hoje é meramente informativo.
9. **`GET /auth/me` nunca vaza `password_hash`**: `UserMe` schema não tem esse campo. Adição futura ao User exige rechecar `UserMe`.
10. **Proxy do frontend é heurística**: só checa presença do cookie. A validação real é backend-side; se o cookie estiver corrompido ou expirado, backend devolve 401 e o axios client aciona redirect (não coberto por este spec).

## Configurações e variáveis de ambiente

| Variável | Descrição | Padrão | Obrigatória |
|---|---|---|---|
| `JWT_SECRET` | Segredo HS256. Rotacionar invalida todos os accesses. | — | Sim |
| `JWT_ACCESS_TTL_SECONDS` | TTL do JWT. | `900` (15min) | Não |
| `REFRESH_TTL_SECONDS` | TTL do refresh. | `1209600` (14d) | Não |
| `COOKIE_SECURE` | `true` em produção (HTTPS). | `false` em dev | Sim (prod) |
| `COOKIE_SAMESITE` | `lax` (default). | `lax` | Não |
| `DEFAULT_ADMIN_EMAIL`, `DEFAULT_ADMIN_PASSWORD`, `DEFAULT_ADMIN_TIMEZONE` | Usados por `app.cli bootstrap` — ver [`admin-bootstrap-cli`](../admin-bootstrap-cli/). | `admin@example.com` / `adminadmin` / `America/Sao_Paulo` | Não |

## Referências de implementação

- **Rotas**: [`app/api/routes/auth.py`](../../../apps/api/app/api/routes/auth.py).
- **Service**: [`app/services/auth.py`](../../../apps/api/app/services/auth.py) (`AuthService`, `IssuedSession`).
- **Security**: [`app/core/security.py`](../../../apps/api/app/core/security.py) (`hash_password`, `verify_password`, `needs_rehash`, `encode_access_token`, `decode_access_token`, `generate_refresh_token`, `hash_refresh_token`).
- **Rate limit**: [`app/core/rate_limit.py`](../../../apps/api/app/core/rate_limit.py) (`get_ip_limiter`, `get_email_fail_limiter`).
- **Deps**: [`app/api/deps.py`](../../../apps/api/app/api/deps.py) (`ACCESS_COOKIE`, `REFRESH_COOKIE`, `get_current_user`, `get_client_ip`, `get_user_agent`).
- **Modelos**: [`app/models/user.py`](../../../apps/api/app/models/user.py), [`app/models/refresh_token.py`](../../../apps/api/app/models/refresh_token.py).
- **Schemas**: [`app/schemas/auth.py`](../../../apps/api/app/schemas/auth.py).
- **Frontend proxy**: [`apps/web/src/proxy.ts`](../../../apps/web/src/proxy.ts).
- **Testes**: [`apps/api/tests/test_auth.py`](../../../apps/api/tests/test_auth.py) (16 casos, ver `test-cases.md`).
