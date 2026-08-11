# Histórias de Usuário — Pipeline CI/CD (Fase 10)

> **Rastreabilidade**: ADR-012 · Persona única: Felix (dev/operador).

## Personas

- **Felix (dev)**: quer feedback automático de qualidade em cada PR sem rodar tudo localmente.
- **Felix (operador)**: quer deploys auditáveis que rodem sem intervenção manual pós-merge.
- **Felix (em incidente)**: precisa pausar/reverter quando deploy quebra produção.

---

### US-001 — Validação automática em PR (CI)
**Como** Felix (dev),
**Quero** que cada PR rode lint + typecheck + build + testes automaticamente,
**Para que** eu mergeie com confiança sem depender da minha memória de rodar local.

**Critérios de Aceitação resumidos:**
- [ ] `ci.yml` dispara em `pull_request` para `dev`/`main`.
- [ ] Jobs `api` e `web` em paralelo.
- [ ] Branch protection bloqueia merge sem CI verde (após T-1003).
- [ ] Tanto verde como falha ficam visíveis no PR.

**Notas:**
- Fonte: ADR-012, T-1001/T-1002.

---

### US-002 — Aprovar PR sem doar duplicar work
**Como** Felix (dev),
**Quero** que um push novo no mesmo PR cancele o run anterior,
**Para que** eu não espere 2 runs idênticos acabarem.

**Critérios de Aceitação resumidos:**
- [ ] `concurrency.group=ci-${{ github.ref }}` com `cancel-in-progress: true`.

**Notas:**
- Fonte: T-1001.

---

### US-003 — Deploy automático pós-merge (CD)
**Como** Felix (operador),
**Quero** que mergear em `main` dispare deploy pra VPS sem intervenção,
**Para que** eu foque em codar e não em rodar `git pull && docker compose up` na mão.

**Critérios de Aceitação resumidos:**
- [ ] `deploy.yml` dispara ao `ci.yml` completar com sucesso em `main`.
- [ ] SSH na VPS roda `bootstrap.sh + docker compose --build api web`.
- [ ] Deployment aparece na aba Deployments do GitHub.

**Notas:**
- Fonte: ADR-012, T-1005.

---

### US-004 — Smoke test garante saúde pós-deploy
**Como** Felix (operador),
**Quero** que o pipeline verifique que `/api/health` responde 200,
**Para que** eu saiba que o deploy pegou e a API está viva.

**Critérios de Aceitação resumidos:**
- [ ] 12 tentativas × 5s em `https://$DEPLOY_DOMAIN/api/health`.
- [ ] 200 no primeiro hit → run verde.
- [ ] 60s sem 200 → run vermelho; containers permanecem de pé.

**Notas:**
- Fonte: T-1007. Rollback continua manual.

---

### US-005 — Segredos de negócio nunca saem da VPS
**Como** Felix (operador),
**Quero** que `ANTHROPIC_API_KEY` e `POSTGRES_PASSWORD` não cheguem ao GitHub,
**Para que** um leak do GitHub Actions não exponha minha chave de LLM/DB.

**Critérios de Aceitação resumidos:**
- [ ] Secret único no Actions: `DEPLOY_SSH_KEY`.
- [ ] `deploy.yml` nunca edita `.env.production`.
- [ ] Variáveis `DEPLOY_HOST`/`DEPLOY_DOMAIN` são não-sensíveis.

**Notas:**
- Fonte: ADR-012.

---

### US-006 — Chave SSH só faz deploy (sem shell)
**Como** Felix (operador),
**Quero** que a chave deploy-only só rode o comando de deploy,
**Para que** mesmo se ela vazar, atacante só consiga forçar um deploy do estado atual do repo.

**Critérios de Aceitação resumidos:**
- [ ] `command="..."` prefixa a public key no `authorized_keys`.
- [ ] Restrições `no-port-forwarding,no-x11-forwarding,no-agent-forwarding,no-pty`.
- [ ] Shell interativo recusa (roda o deploy e desconecta).

**Notas:**
- Fonte: T-1004, `docs/deploy.md` §14.2.

---

### US-007 — Rollback por `git revert`
**Como** Felix (em incidente),
**Quero** reverter um deploy quebrado com `git revert + push`,
**Para que** eu recupere produção em segundos sem navegar em UIs.

**Critérios de Aceitação resumidos:**
- [ ] `git revert <hash>` + `git push origin main`.
- [ ] Pipeline reroda com o hash anterior.
- [ ] Migration destrutiva requires `alembic downgrade -1` primeiro.

**Notas:**
- Fonte: `docs/deploy.md` §14.4. Sem workflow dedicado.

---

### US-008 — Debugar deploy que falhou
**Como** Felix (em incidente),
**Quero** ver logs do deploy pelo `gh` CLI,
**Para que** eu entenda o que deu errado.

**Critérios de Aceitação resumidos:**
- [ ] `gh run list --workflow=deploy.yml --limit 10`.
- [ ] `gh run view --log`.
- [ ] Mentions: `curl -sSI https://$DOMAIN/api/health` e `docker compose ps`.

**Notas:**
- Fonte: `docs/deploy.md` §14.3.

---

### US-009 — Pausar CD quando GitHub/Actions cair
**Como** Felix (em incidente),
**Quero** deployar manualmente quando GitHub Actions está fora do ar,
**Para que** o fato do GitHub cair não bloqueie uma hotfix crítica.

**Critérios de Aceitação resumidos:**
- [ ] Docs em `deploy.md` §14.5 explicam via manual (`git pull && bootstrap.sh && docker compose up -d --build`).
- [ ] `scripts/bootstrap.sh` é idêntico ao que o Actions roda.

**Notas:**
- Fonte: `docs/deploy.md` §14.5.

---

### US-010 — Custo mensal previsível
**Como** Felix (dev),
**Quero** que o pipeline caiba no free tier do GitHub Actions,
**Para que** eu não tenha surpresa no fim do mês.

**Critérios de Aceitação resumidos:**
- [ ] Cada run CI ~2-3 min; deploy ~1-2 min.
- [ ] Cancel-in-progress no CI evita desperdício.
- [ ] 2000 min/mês grátis em repo private cobre ~100 runs mês.

**Notas:**
- Fonte: ADR-012 consequências. Repo atualmente público (ilimitado em actions).