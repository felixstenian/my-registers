# Trade-offs — Autenticação e sessão

## Decisão 1 — Access stateless + Refresh stateful com rotação obrigatória

### Contexto

Dois extremos possíveis: (a) tudo stateless (JWT longo, sem revogação real) ou (b) tudo stateful (session cookie que lookupa DB por request). Escolhemos híbrido.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Access JWT curto (15min) + Refresh opaco 14d rotativo (escolhida) | Sem DB call por request de negócio; revogação real via refresh; detecção de reuso | 2 tokens a gerenciar; refresh rotation adiciona uma request extra a cada 15min |
| B — Só session cookie stateful | Simples; revogação trivial | DB lookup por request; chat polling amplifica load |
| C — Só JWT long-lived (sem refresh) | Zero state | Sem revogação real; roubo de token = sessão para sempre |

### Decisão tomada

**Opção A.** JWT HS256 15min + refresh 14d rotativo (`generate_refresh_token()` opaco, hasheado SHA-256).

### Consequências

- **Positivas**: latência baixa em endpoints de negócio; revogação granular (`revoke`, `revoke_family`); trilha auditável em `refresh_tokens.replaced_by`.
- **Negativas**: complexidade extra em `AuthService.refresh` (validação de expiração, reuso, family); teste de rotação exige orquestração de 3 estados (T1 ativo, T1 revogado, T2 ativo).

---

## Decisão 2 — Reuso de refresh revogado invalida FAMÍLIA (INV-6, Const. §17)

### Contexto

Se atacante rouba refresh `T_n` e usa antes do usuário rotacionar, o atacante fica com `T_n+1` legítimo e usuário sem sessão. Como detectar?

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Reuso de token revogado → invalida todos os ativos do user (escolhida) | Detecção real de roubo; falha segura | Falso-positivo: race condition de 2 refreshes simultâneos derruba sessão legítima |
| B — Reuso invalida só o token específico | Menos disruptivo | Não detecta roubo — atacante persiste |
| C — Aceitar reuso silenciosamente | Simplíssimo | Sem segurança |

### Decisão tomada

**Opção A.** Documentada como INV-6.

### Consequências

- **Positivas**: qualquer replay de refresh dispara auto-defesa; usuário legítimo relogar é custo baixo (14d TTL na maioria dos casos).
- **Negativas**: race condition (mesmo usuário abrindo 2 abas com refresh próximo do TTL) pode disparar `revoke_family` — desloga tudo. **Rara em single-user** (uma aba ativa), mas possível.
- **Mitigação futura**: window de tolerância pós-rotação (segundos) que aceita o T anterior sem alarme. Não implementado no MVP.

---

## Decisão 3 — Rate limit em memória (não Redis)

### Contexto

`SlidingWindowLimiter` guarda janelas por IP e por email na memória do processo Python.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — In-memory (escolhida) | Zero deps; sem latência extra; simplicíssimo | Restart zera; multi-instância vaza |
| B — Redis | Persiste restart; multi-instância consistente | Nova dep, nova falha, novo runbook |
| C — Postgres (tabela `rate_limit_log`) | Sem nova dep | Latência extra por request de login (pequeno mas real) |

### Decisão tomada

**Opção A.** MVP é single-VPS single-user.

### Consequências

- **Positivas**: código trivial; testes isolam trocando fixture do limiter; sem gerenciamento operacional.
- **Negativas**: se atacante nota que API caiu e voltou (restart), pode retomar tentativas. Aceito.
- **Migração futura**: mudança para Redis é trocar 1 implementação atrás de `get_ip_limiter()` — não vaza pro caller.

---

## Decisão 4 — Sem endpoints HTTP de cadastro/reset (Const. §18)

### Contexto

App privada. Bootstrap do admin default acontece via CLI (`app.cli bootstrap`, feature [`admin-bootstrap-cli`](../admin-bootstrap-cli/)). Reset de senha via `app.cli reset-password` rodado por humano com SSH.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Sem endpoints HTTP (escolhida) | Superfície de ataque nula; sem risco de leak de token de reset por email/SMS | Reset exige SSH (custo pra dono do app) |
| B — Reset por email link | UX moderno | Dependência SMTP; risco de leak; complexidade extra que não paga em single-user |
| C — Endpoints protegidos com role admin | Consistente com padrões web | Cria um sistema RBAC pra 1 role |

### Decisão tomada

**Opção A.** `POST /auth/register`, `/auth/forgot-password`, `/auth/reset-password` retornam 404 sem hint (default FastAPI).

### Consequências

- **Positivas**: superfície minimalíssima; não precisa configurar SMTP; testes explicitamente asseguram (`test_forbidden_public_endpoints_return_404`).
- **Negativas**: dono do app precisa SSH pra resetar senha (aceito).
- **Bloqueio explícito**: se alguém tentar adicionar futuramente, `test_forbidden_public_endpoints_return_404` quebra.

---

## Decisão 5 — Erro genérico `invalid_credentials` para qualquer falha pré-token

### Contexto

Diferenciar "email não existe" de "senha errada" ajudaria enumerar users. App privado single-user: enumeração é irrelevante (só existe um user). Mas mantém a política para consistência.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Sempre `invalid_credentials` (escolhida) | Zero enumeração; código simples | Timing attack teórico (Argon2 x no-op) |
| B — 401 diferente pra "email não existe" | Debug fácil | Enumera user |
| C — Falso hash quando email não existe (verify contra hash dummy) | Timing constante | Complexidade que não paga em single-user |

### Decisão tomada

**Opção A.** Constante `invalid_credentials`.

### Consequências

- **Positivas**: político-security limpo, teste simples.
- **Negativas**: timing attack teórico. Em single-user com só 1 email, irrelevante.

---

## Decisão 6 — JWT HS256 (não RS256/EdDSA)

### Contexto

HS256 é HMAC com chave simétrica. Assinatura e verificação usam a mesma `jwt_secret`.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — HS256 (escolhida) | 1 secret, simples, rápido | Verificação exige o mesmo secret (não delegável a clientes) |
| B — RS256 | Verificação por chave pública | Cerimônia de key rotation, keypair overhead |
| C — EdDSA | Modernidade | Suporte de libs menos maduro (2026-07); ganho marginal |

### Decisão tomada

**Opção A.** Single service verifica JWTs; simetria não incomoda.

### Consequências

- **Positivas**: config trivial, código minimal.
- **Negativas**: rotacionar `jwt_secret` invalida todos os accesses vivos — usuário legítimo precisa refresh (single request, silencioso).

---

## Dívida técnica conhecida

| Item | Impacto | Prioridade |
|---|---|---|
| Sem janela de tolerância na rotação (race condition pode invalidar família legítima) | Baixo em single-user | Baixa; monitorar; adicionar `graceful_window_seconds` se acontecer |
| Rate limit em memória não persiste restart | Baixo (single-VPS) | Baixa; Redis quando escalar |
| Sem CSRF token adicional além de SameSite=Lax | Baixo (app privado + Lax) | Baixa |
| Timing attack teórico em `invalid_credentials` | Zero prático (single email) | Muito baixa |
| Sem métrica de `revoke_family` disparado — sinal de ataque perdido | Médio (observabilidade) | Média; adicionar counter em logs |
| `sid` no JWT não é usado em nenhum lugar hoje | Zero | Zero (deixar pra expansão futura) |
| Middleware `proxy.ts` só checa presença de cookie — se dev commitar rota nova sem prefixo listado, fica pública no client (mas backend continua protegido) | Médio (UX confuso) | Média; adicionar teste E2E de coverage de rotas |

## Riscos identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| `jwt_secret` vazado em git/log | Baixa (`.gitignore` cobre `.env`) | Crítico — todas as sessões forjáveis | Rotacionar imediatamente; usuário faz refresh natural; script `scripts/vps-check.sh` alerta `.env` desprotegido |
| Argon2 params ficam obsoletos | Média (5+ anos) | Baixo (`needs_rehash` corrige on-login) | Nenhuma ação até `argon2-cffi` recomendar upgrade |
| Refresh vazado por XSS no frontend | Baixa (cookies HttpOnly) | Alto | HttpOnly + CSP (via Nginx) — ver `infra/nginx/`. XSS que passa cookies pra atacante é falha crítica; testar CSP |
| Login mass-scan pela rede pública (bot que sabe do `/auth/login`) | Média | Baixo (rate limit) | Nginx rate limit adicional na frente (ver `infra/nginx/`) |
| Sessão presa após rotação do `jwt_secret` | Certa se rotacionar sem plano | Baixo (1 refresh silencioso) | Documentar como "expected" no runbook de rotação |
| Ataque de reuse concorrente de 2 refreshes | Baixa em single-user | Médio (relogin forçado) | Aceito; graceful window fica pra multi-user |

## Alternativas para pós-MVP

- **CSRF token**: adicionar double-submit cookie ou header customizado se abrir a app para uso público.
- **Passkeys / WebAuthn**: eliminar senha; possível em single-user (device do usuário registrado como authenticator).
- **Multi-factor (TOTP)**: exigir TOTP no login (`otp_secret` em `users`).
- **Refresh window graceful**: aceitar refresh anterior por N segundos após rotação para tolerar race de abas.
- **Métricas de segurança**: contador de `revoke_family` disparados por semana; alertar se > 0.
- **Refresh device binding**: gravar fingerprint de device em `refresh_tokens.device_hash`; rejeitar refresh de device diferente do de emissão.
