# Histórias de Usuário — Bootstrap de admin via CLI

> **Rastreabilidade**: Const. §18/§24, ADR-001 · Persona única: Felix (dev/operador).

## Personas

- **Felix (operador primeiro deploy)**: precisa ter um admin no DB antes de fazer o primeiro login.
- **Felix (operador deploy subsequente)**: precisa que `bootstrap` não quebre em DB já populado.
- **Felix (em reset)**: esqueceu a senha do admin e quer trocar via SSH sem expor por HTTP.

---

### US-001 — Provisionar o admin default no primeiro deploy
**Como** Felix (operador primeiro deploy),
**Quero** rodar um comando CLI que cria o admin do env sem variantes,
**Para que** eu faça o primeiro login em `/login` sem cadastrar via HTTP (que não existe).

**Critérios de Aceitação resumidos:**
- [ ] `DEFAULT_ADMIN_EMAIL`/`DEFAULT_ADMIN_PASSWORD` no env.
- [ ] `python -m app.cli bootstrap` cria `User` com hash Argon2id.
- [ ] Senha nunca aparece em stdout ou log.
- [ ] Após bootstrap, `POST /auth/login` resolve.

**Notas:**
- Fonte: T-105/T-107, Const. §24. `scripts/bootstrap.sh` automatiza.

---

### US-002 — Rerodar bootstrap sem quebrar admin existente
**Como** Felix (operador deploy subsequente),
**Quero** rodar `bootstrap` em cada deploy sem sobrescrever meu admin,
**Para que** minha senha atual continue válida depois de um `git pull`.

**Critérios de Aceitação resumidos:**
- [ ] `get_by_email(existing.email)` short-circuits e retorna id.
- [ ] `password_hash` não é sobrescrito.
- [ ] Stdout `already_exists`.

**Notas:**
- Fonte: T-107 idempotência.

---

### US-003 — Falhar explicitamente se envs ausentes
**Como** Felix (operador),
**Quero** que bootstrap aborte com mensagem clara se `DEFAULT_ADMIN_PASSWORD` está vazio,
**Para que** eu não continue deploy com admin invisível.

**Critérios de Aceitação resumidos:**
- [ ] Password/email vazios → exit 1 + mensagem em stderr.

**Notas:**
- Fonte: T-107. `default_admin_password=""` no config é default; força explicitação.

---

### US-004 — Resetar minha própria senha sem endpoint HTTP
**Como** Felix (em reset),
**Quero** um comando CLI para trocar a senha do admin,
**Para que** eu não expor `POST /auth/reset-password` na web.

**Critérios de Aceitação resumidos:**
- [ ] `python -m app.cli reset-password` troca hash Argon2id idempotente.
- [ ] Senha antiga nunca logada; senha nova não persistida em migration/code.

**Notas:**
- **Status: [Implementação não localizada]** — Const. §18 menciona; atualmente reset exige SSH ad-hoc via Python/SQL.

---

### US-005 — Criar admin adicional no futuro (multi-user)
**Como** Felix (operador),
**Quero** um comando CLI `create-admin` (sem endpoint HTTP),
**Para que** eu possa dar acesso a alguém sem expor signup na web.

**Critérios de Aceitação resumidos:**
- [ ] `python -m app.cli create-admin <email> <password>` cria novo user ativo.
- [ ] Bootstrap mantém o default.

**Notas:**
- **Status: [Implementação não localizada]** — Const. §18 menciona; MVP single-user.

---

### US-006 — Popular catálogo nutricional no deploy
**Como** Felix (operador),
**Quero** rodar `seed-nutrition` para upsert do catálogo TBCA,
**Para que** registros de alimentos usem valores BR atualizados.

**Critérios de Aceitação resumidos:**
- [ ] `python -m app.cli seed-nutrition` lê `seed_tbca.csv`.
- [ ] Idempotente: atualiza valores existentes; não duplica.
- [ ] Não mexe em `source != 'TBCA_2023'`.

**Notas:**
- Fonte: T-403. Documentado no CHANGELOG v1.2.0 (seed TBCA enriquecido).

---

### US-007 — Ver versão da API sem rodar server
**Como** Felix (operador),
**Quero** checar a versão do build sem subir uvicorn,
**Para que** eu valide deploy rapidamente.

**Critérios de Aceitação resumidos:**
- [ ] `python -m app.cli version` → `my-registers-api 0.0.0`.

**Notas:**
- [Inferido do código]

---

### US-008 — Garantir ausência de endpoints de cadastro/reset via HTTP
**Como** Felix (segurança),
**Quero** que `POST /auth/register`, `/auth/forgot-password`, `/auth/reset-password` retornem 404 sem hint,
**Para que** atacante que varre rotas não descubra que cadastramento existe.

**Critérios de Aceitação resumidos:**
- [ ] Roteamento do `auth.py` só tem `/login`, `/logout`, `/refresh`, `/me`.
- [ ] 404 sem body informativo.

**Notas:**
- Fonte: SP-05, Const. §18. Testado em `apps/api/tests/test_auth.py`.