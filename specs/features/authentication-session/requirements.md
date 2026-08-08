# Requisitos — Autenticação e sessão

> **Rastreabilidade**: SP-01..SP-06 em [`specs/001-mvp-registro-diario/spec.md §3.1`](../../001-mvp-registro-diario/spec.md#31-autenticação-e-sessão) · Constituição Art. V §15-21 · Invariantes INV-6, INV-7.

## Visão geral

Autenticação por email/senha em app privada single-user. Login emite par de tokens: **access** stateless (JWT HS256, 15min) e **refresh** opaco persistido (14d), ambos em cookies `HttpOnly; SameSite=Lax`. Rotação obrigatória do refresh a cada uso; reuso de refresh revogado invalida a família inteira (Const. §17). **Nunca** existirão endpoints de cadastro público, reset, ou "esqueci minha senha" — criação e reset de admin são exclusivos da CLI (Const. §18, feature [`admin-bootstrap-cli`](../admin-bootstrap-cli/)).

## Requisitos funcionais

| ID | Requisito | SP | Prioridade |
|---|---|---|---|
| RF-001 | Login com email + senha via `POST /auth/login` retorna 204 + cookies `access_token` (15min) e `refresh_token` (14d), ambos `HttpOnly; SameSite=Lax`; UI redireciona para `/chat`. | SP-01 | Must Have |
| RF-002 | Credenciais inválidas → 401 `{code: "invalid_credentials"}`, indistinguível entre "email inexistente" e "senha errada". | SP-02 | Must Have |
| RF-003 | 10 falhas de login no mesmo email em 15 min → 429 mesmo com senha correta; 5 tentativas/min por IP → 429 independente do email. | SP-02 | Must Have |
| RF-004 | `POST /auth/refresh` revoga o refresh usado e emite novo par (rotação); marca `replaced_by` no antigo. | SP-03 | Must Have |
| RF-005 | Reuso de refresh já revogado → invalida **toda a família** (todos os refresh ativos do user) e força novo login. | SP-03, INV-6 | Must Have |
| RF-006 | `POST /auth/logout` revoga o refresh atual e limpa cookies (`Max-Age=0`), 204. | SP-04 | Must Have |
| RF-007 | `POST /auth/register`, `POST /auth/forgot-password`, `POST /auth/reset-password` retornam 404 sem hint. | SP-05, Const. §18 | Must Have |
| RF-008 | Qualquer request para rota protegida sem `access_token` válido → 401 JSON (`{code: "unauthorized"}`); frontend redireciona para `/login?next=<pathname>`. | SP-06 | Must Have |
| RF-009 | `GET /auth/me` (com cookie válido) retorna dados do usuário sem incluir `password_hash`. | SP-06 | Must Have |
| RF-010 | Ao logar com senha usando algoritmo/params desatualizados, rehash idempotente atualiza `password_hash` no DB. | Const. §19 | Should Have |
| RF-011 | Frontend proxy (`apps/web/src/proxy.ts`) protege prefixos `/chat`, `/day`, `/days`, `/weekly` pela presença do cookie; se logado e visitar `/login`, redireciona para `/chat`. | SP-06 | Must Have |

## Requisitos não funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | Senhas hasheadas com **Argon2id** (default do `argon2-cffi`); `needs_rehash` detecta downgrades. | Segurança |
| RNF-002 | Refresh **nunca** volta como plaintext após criação — só uma vez, para colocar no cookie; storage é SHA-256 hash (`hash_refresh_token`). | Segurança |
| RNF-003 | JWT HS256 com `settings.jwt_secret`; TTL curto (`jwt_access_ttl_seconds`, default 900s / 15min). | Segurança |
| RNF-004 | Cookies em produção: `Secure=true`, `SameSite=Lax`, `HttpOnly=true`, `path=/`. | Segurança |
| RNF-005 | Nenhum log ou resposta HTTP contém `password_hash`, refresh plaintext ou tokens JWT. | Segurança (INV-7) |
| RNF-006 | Latência de login P95 ≤ 300ms (Argon2 domina; verificação em conexão local). | Performance |
| RNF-007 | Rate limiting em memória via `get_ip_limiter()`/`get_email_fail_limiter()`; reset explícito entre testes. | Confiabilidade |
| RNF-008 | Email é `CITEXT` no Postgres — comparação case-insensitive nativa (evita bug de "Felix@..." vs "felix@..."). | Correção |

## Restrições e premissas

- **Single-user**: admin default é semeado por `pnpm db:bootstrap` (ver [`admin-bootstrap-cli`](../admin-bootstrap-cli/)); MVP não suporta múltiplos usuários.
- **Sem cadastro público**: qualquer requisição a endpoints hipotéticos (`/auth/register`, `/auth/forgot-password`, `/auth/reset-password`) devolve 404 sem hint — nem 405, nem 403.
- **JWT stateless**: access token não é verificado contra DB; se `jwt_secret` mudar em produção, todos os accesses ativos são invalidados. Refresh continua válido (pode gerar novo access).
- **Rate limiting em memória**: reinício da API zera contadores. Aceito para single-VPS single-user; em multi-instância exigiria backend externo (Redis) — fora do MVP.
- **`sid` no JWT**: encoding inclui `sid=str(refresh_row.id)` para amarrar o access ao refresh de origem (útil para revoke posterior; ainda não usado para auth).
- **Rotação `SameSite=Lax`**: cookies acompanham navegação top-level; POSTs cross-origin não os enviam (mitigação CSRF barata).

## Dependências

**Depende de:**
- `argon2-cffi` para hashing.
- `python-jose` para JWT HS256.
- Postgres com extensão `citext`.
- [`admin-bootstrap-cli`](../admin-bootstrap-cli/) — cria o admin default idempotente.

**Requerido por:**
- **Todas** as demais features do backend — toda rota exceto `/health`, `/auth/login` e `/auth/refresh` chama `Depends(get_current_user)`.
- [`chat-messaging`](../chat-messaging/) — dispara `POST /chat/messages`.
- Frontend `apps/web/src/proxy.ts` — leitura da presença do cookie decide redirect.
