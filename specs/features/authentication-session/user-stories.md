# Histórias de Usuário — Autenticação e sessão

## Personas

- **Felix (P1) — usuário único**: acessa em desktop (Chrome/Safari) e mobile (iOS/Android). Tolerância baixa para relogar; espera sessão viver dias.
- **Atacante (não persona, ator adversário)**: força bruta, roubo de sessão, replay de refresh.

---

### US-001 — Login em app privado

**Como** Felix,
**Quero** entrar com email + senha em `/login`,
**Para que** eu acesse `/chat`, `/day`, `/weekly` sem precisar autenticar em cada request.

**Critérios de aceitação resumidos:**
- [ ] Sucesso → 204 + cookies `access_token` (15min) e `refresh_token` (14d) `HttpOnly`.
- [ ] Redireciona pra `/chat` ou `?next=<pathname>`.
- [ ] Senha errada → 401 genérico, sem hint entre "email não existe" e "senha errada".

**Cobertura**: SP-01, SP-02.

---

### US-002 — Sessão longa sem relogar

**Como** Felix,
**Quero** permanecer logado por 14 dias sem digitar senha,
**Para que** eu abra o app no celular pela manhã e não precise autenticar.

**Critérios de aceitação resumidos:**
- [ ] Cookie de refresh expira em 14 dias por padrão (`REFRESH_TTL_SECONDS=1209600`).
- [ ] Quando access expira (15min), próximo request chama `POST /auth/refresh` que emite novo par.
- [ ] Refresh rotação: antigo é marcado `revoked_at` + `replaced_by = novo.id`.

**Cobertura**: SP-01, SP-03.

---

### US-003 — Sair sem deixar rastro válido

**Como** Felix,
**Quero** fazer logout e ter certeza que o refresh não pode ser reutilizado,
**Para que** um browser esquecido não vire vetor de acesso.

**Critérios de aceitação resumidos:**
- [ ] `POST /auth/logout` revoga refresh + limpa cookies (`Max-Age=0`).
- [ ] Chamada sem cookie continua sendo 204 (idempotente).
- [ ] Tentar refresh depois → 401 `invalid_refresh`.

**Cobertura**: SP-04.

---

### US-004 — Ficar protegido de força bruta

**Como** Felix,
**Quero** que múltiplas tentativas erradas contra o meu email travem por 15 min,
**Para que** um atacante não descubra minha senha por brute force.

**Critérios de aceitação resumidos:**
- [ ] 10 falhas de senha no mesmo email em 15 min → 429 `rate_limited` mesmo com senha correta subsequente.
- [ ] 5 tentativas/min por IP → 429 independente do email tentado.
- [ ] Após janela expirar, contadores são limpos e login volta a aceitar.

**Cobertura**: SP-02.

---

### US-005 — Detectar refresh vazado

**Como** Felix,
**Quero** que uso de refresh já rotacionado dispare invalidação total de sessões,
**Para que** um atacante com refresh roubado não consiga continuar logado enquanto eu estou logado normalmente.

**Critérios de aceitação resumidos:**
- [ ] Reuso de refresh revogado → `revoke_family(user_id)`: todos os refreshes ativos do user marcados `revoked_at`.
- [ ] Ambos (eu e atacante) sou forçados a relogar.
- [ ] Nenhum indicador para o atacante (401 genérico `invalid_refresh`).

**Cobertura**: SP-03, INV-6.

---

### US-006 — Falha de acesso amigável no frontend

**Como** Felix,
**Quero** que ao expirar sessão eu seja levado ao `/login?next=<meu pathname>`,
**Para que** ao logar de novo eu volte pra onde estava.

**Critérios de aceitação resumidos:**
- [ ] `proxy.ts` cobre `/chat`, `/day`, `/days`, `/weekly`.
- [ ] Sem cookie → 302 `/login?next=<pathname>`.
- [ ] Com cookie e visitar `/login` → 302 `/chat`.
- [ ] `/api/*` sem cookie → 401 JSON, frontend axios trata.

**Cobertura**: SP-06.

---

### US-007 — Não existir superfície pública de cadastro

**Como** operador do app privado,
**Quero** que ninguém consiga se cadastrar via HTTP (nem tentar reset de senha),
**Para que** o app permaneça single-user por design.

**Critérios de aceitação resumidos:**
- [ ] `POST /auth/register` → 404 sem hint (sem 405 ou 403 revelar existência).
- [ ] `POST /auth/forgot-password` → 404.
- [ ] `POST /auth/reset-password` → 404.
- [ ] Não existem essas rotas no OpenAPI (`/docs`).

**Cobertura**: SP-05, Const. §18.

---

### US-008 — Nunca vazar senha

**Como** Felix (e como auditor de segurança),
**Quero** garantia de que `password_hash` nunca sai em resposta HTTP nem em log,
**Para que** um bug de UI/log não exponha o hash.

**Critérios de aceitação resumidos:**
- [ ] `GET /auth/me` devolve `UserMe` schema sem `password_hash`.
- [ ] Logs de erro não incluem senha nem hash (verificado por teste).
- [ ] Cookie corrompido → 401 sem eco do cookie.

**Cobertura**: SP-06, INV-7.
