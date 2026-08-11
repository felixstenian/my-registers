# Trade-offs — Pipeline CI/CD (Fase 10)

> **Rastreabilidade**: ADR-012 (`research.md`) — escolha GitHub Actions sobre Webhook/Watchtower/ArgoCD/Compose-pull/leave-as-is. Implementação em PR #34. Decisões restantes registradas inline neste arquivo.

## Decisão 1 — GitHub Actions em vez de alternativas (ADR-012)

### Contexto
MVP entregue sem pipeline (Fase 9). Avaliava-se adotar CD quando gatilhos disparassem (segundo dev, freq >2/semana, esquecimento de teste local).

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — GitHub Actions em 2 etapas (CI em PR + deploy SSH em merge)** (escolhida) | Grátis em repo público; auditável (`gh run list`); SSH já no workflow manual; sem novo daemon | Dependência GitHub pra deploy; manual mantido como fallback |
| B — Webhook + agente na VPS | Sem GitHub como(origem 但是 deploy) | Daemon receptor novo; autenticar payload; retries |
| C — Watchtower (polla registry) | Elegante | Requer build+push no CI pra GHCR × 2 imagens ~450 MB por merge; cresce storage |
| D — ArgoCD/Flux (GitOps) | Industry standard | Requer Kubernetes — viola ADR de single-VPS |
| E — Docker compose `pull` remoto via context | Sem build local | Docker daemon exposto — fricção de segurança |
| F — Deixar manual indefinidamente | Zero custo infra | Quebra na 1ª vez que 2º dev entra; risco de esquecer teste local |

### Decisão tomada
**Opção A** — registrado em ADR-012. Justificativa: aproveita SSH já no playbook; GitHub Actions free tier cabe; rollback via `git`.

### Consequências
- Positivas: deploy auditável; CI gate; rollback git-native; zero daemon novo.
- Negativas: dependência GitHub (fallback manual em `docs/deploy.md` §14.5).

---

## Decisão 2 — Dois workflows separados (`ci.yml` + `deploy.yml`)

### Contexto
Poderia ser um workflow único com jobs dependentes (`deploy` dependendo `ci`).

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Dois workflows** (`ci.yml` em PR; `deploy.yml` via `workflow_run`) (escolhida) | Escopos separados; CI em PR (com secrets/mocks); deploy só em main success | Configuração duas vezes;`workflow_run` filter manual necessário |
| B — Workflow único com job `deploy` dependente de `ci` | Simples, 1 arquivo | Em PR, CI roda mas não deve deploy; jobs depend no PR gatilho são diferentes de push |
| C — 1 workflow + conditions por branch | Single file | Lógica condicional complexa |

### Decisão tomada
**Opção A** — `ci.yml` em PR/push para `main`/`dev`; `deploy.yml` em `workflow_run` completed success branch main + filter `conclusion == 'success'` (workflow_run dispara mesmo em CI fail). Implementação: `.github/workflows/{ci,deploy}.yml`.

### Consequências
- Positivas: clean separation; CI pode testar coisas que deploy não depende.
- Negativas: filter `conclusion` no deploy.yml é necessário — workflow_run dispara em qualquer conclusão.

---

## Decisão 3 — `workflow_run` filter via `if` explícito

### Contexto
`on: workflow_run` types `[completed]` dispara independente de success/failure. Avaliava-se confiar só em CI gate ou filter explícito.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — `if: github.event.workflow_run.conclusion == 'success'`** (escolhida) | Defesa em profundidade; garante não deploy em CI fail | Condição simples YAML |
| B — Confiar em gate (CI fail impede complote) | Sem código | Sem defesa em depth; se `ci.yml` for mutado pra pular steps, deploy dispara |
| C — Re-run `ci` no deploy | Verificação dupla | Custo + tempo |

### Decisão tomada
**Opção A** — filter explicit; mesmo se CI handler mutado, deploy não roda sem success. Implementação: `deploy.yml:30`.

### Consequências
- Positivas: defense in depth; segura em mutações acidentais de CI.
- Negativas: nenhuma.

---

## Decisão 4 — Chave SSH `command="..."` restrita (não shell)

### Contexto
Runner precisa SSH na VPS. Avaliava-se chave comum vs restringida a 1 command.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — `command="$DEPLOY_CMD",restrictions` em `authorized_keys`** (escolhida) | Mesmo vazada, só faz deploy fixo; sem shell | Deploy command fixo; trocar exige `authorized_keys` update |
| B — Chave shell normal | Flexibilidade (Runner decide command) | Vazar = shell na VPS |
| C — Runner monta `command` SSH e envia | Dinâmico | Bypass possível se creds vazadas; restringe menos |

### Decisão tomada
**Opção A** — public key prefixada por `command="$DEPLOY_CMD",no-port-forwarding,no-x11-forwarding,no-agent-forwarding,no-pty`. Runner só envia `true` (placeholder); VPS executa o fixo. Implementação: `docs/deploy.md` §14.2.

### Consequências
- Positivas: vazamento de secret = força deploy só do head atual; sem acesso arbitrário.
- Negativas: mudar `DEPLOY_CMD` exige edit `authorized_keys` manual; `bootstrap.sh` path fixo.

---

## Decisão 5 — Sem registry; build local na VPS

### Contexto
GHCR + pull era opção comum para Watchtower. Build local é `--build` no compose.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Build local `docker compose --build api web`** (escolhida) | Zero storage registry; zero push CI build step; código fonte na VPS | CPU da VPS durante build; build blocka deploy até completar |
| B — GHCR + pull na VPS | Build no runner; VPS só pull (mais rápido) | Storage registry growth; 2 imagens ~450 MB/merge; CI build+push extra |
| C — Tar imgage scp manual | Sem registry | Process manual; não integra com deploy.yml |

### Decisão tomada
**Opção A** — VPS builds `api`/`web` no deploy. Justificativa: ADR-012 trade-off; build 2-3 min em single-dev aceitável.

### Consequências
- Positivas: zero registry maintenance; custo zero; rollback é git-native.
- Negativas: janela de indisponibilidade parcial durante build (`up -d --build` rebuilda antes de restartar); recomenda-se rebuild seletivo.

---

## Decisão 6 — Rebuild seletivo (`up -d --build api web`), não all

### Contexto
`docker compose up -d --build` pode rebuild todas as services ou só `api`+`web`. Avaliava-se all vs seletivo.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — `--build api web`** (escolhida) | DB/MinIO/nginx/certbot intactos; minimiza downtime; requeue DB não necessário | Comando explícito; esquecer adicionar nova service futuro |
| B — `--build` (all) | Não esquece de nada | Maiores janelas indisponibilidade; DB restart desnecessário |
| C — Build `web` only | Menor scope | API altera frequentemente; ficar para trás |

### Decisão tomada
**Opção A** — Comand `DEPLOY_CMD` menciona `--build api web` explicit. Implementação: `docs/deploy.md` §14.2.

### Consequências
- Positivas: postgres sem restart → snapshot sessions sobrevivem; minio sem restart → uploads não broken.
- Negativas:.Configuração novo service (`web`Next 16 etc) exige update do `DEPLOY_CMD` — manual SSH.

---

## Decisão 7 — Smoke em HTTPS público, não healthcheck interno

### Contexto
Pós-deploy, validar saúde. Avaliava-se `docker compose healthcheck` ou curl HTTPS público.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — `curl https://$DEPLOY_DOMAIN/api/health` 12×5s** (escolhida) | Expõe falhas de nginx/certbot/DNS/proxy; verdade total | Depende de TLS saudável; falso negativo por DNS/Domínio rotacionando |
| B — `docker inspect health` na VPS via SSH | Interno à VPS; não depende de TLS | Falso positivo: compose saudável mas nginx caiu |
| C — Ping network interno | Sem dependência externa | Não valida estado da API real |

### Decisão tomada
**Opção A** — smoke HTTPS público pós-deploy. Justificativa: acusar nginx quebrou / TLS expirado / proxy config errado.

### Consequências
- Positivas: denuncia falhas além da VPS-internal.
- Negativas: `DEPLOY_DOMAIN` em `variables` precisa bater com DNS atualizado;pendente DNS propagação pode dar smoke fail mesmo infra OK.

---

## Decisão 8 — Concorrência: cancel CI progress (true) / deploy serial (false)

### Contexto
PRs frequentes geram runs redundantes; deploys simultâneos podem quebrar estado.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — CI `cancel-in-progress: true`; deploy `false`** (escolhida) | CI enxuto; deploy garantido sem concorrência | Deploy serial pode ter 2 do-backlog se 2 merges rápidos |
| B — Upload ambos `true` | Mais em CI | Deploy cancelado mid-flight pode deixar estado inconsistente |
| C — Ambos `false` | Todos os rodam | CI custa em minutes em spam push |

### Decisão tomada
**Opção A** — `ci-${{ github.ref }}` cancel-progress (economia); `deploy-production` sem cancel (consistência).

### Consequências
- Positivas: CI enxuto, deploy serial.
- Negativas: segunds merges saem serializados; não é problem em single-dev.

---

## Decisão 9 — Sem E2E Playwright no CI

### Contexto
ADR-012 não incluiu E2E. Avaliava-se custo/benefício.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Só unit + integration + smoke** (escolhida) | CI barato/macio; mantém invariantes (INV-11 via `verify:sw`) | Bugs de regressão visual só pegam em prod |
| B — Playwright em CI | Captura regressões visuais | Setup: ~5-10 min/run; browser installs; maint 1 spec p/ feature |
| C — Cypress | Igual B | Idem B |

### Decisão tomada
**Opção A** — Unit + integration + smoke. Reabrir quando E2E valer o custo (2º dev, mais features).

### Consequências
- Positivas: CI ~3 min/run; sem browser install.
- Negativas / dívida técnica: regressões visuais só pegas em produção; documentado em ADR-012.

---

## Decisão 10 — Rollback via `git revert`, sem workflow dedicado

### Contexto
Pode-se ter workflow `rollback.yml` que faz `git revert` automático.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — `git revert + push` manual** (escolhida) | Simples; git-native; pipeline reroda com hash anterior | Operador precisa de laptop; sem atalho |
| B — Workflow `rollback.yml` | Botão "rollback" UI | Workflow reversão é tão complexo quanto forward; migração implícitas |
| C — `git reset + push -f` | Vai exato hash anterior | Force-push quebra linear history (branch protection); perde histórico |

### Decisão tomada
**Opção A** — `git revert + push origin main`. Pipeline reroda, smoke valida rollback. Migration destrutiva requer `alembic downgrade -1` manual SSH.

### Consequências
- Positivas: sem workflow extra; linear history preservado.
- Negativas: rollback manual migration-intensive requer double-step.

---

## Dívida técnica conhecida

| Item | Impacto | Prioridade |
|---|---|---|
| **T-1003 (branch protection) pendente config manual** | Merge sem CI verde possível até operador configurar UI | Alta — único gap pendente da Fase 10 |
| **T-1004 (chave SSH deploy-only) pendente setup VPS** | `deploy.yml` falha no SSH até setup | Alta — CD não eficaz sem isso |
| Actions não pinados em SHA (somente `@v4`/`@v5`) | Supply-chain: se action major version atualizada com breaking implicit, CI quebra silencioso | Média |
| `ssh-keyscan` sem TOFU rigoroso (aceita fingerprint na 1ª run) | MITM teórico se DNS/VPS spoofed | Baixa (HTTPS prod; runner efêmero) |
| Sem E2E/Playwright | Regressões visuais só pegas em produção | Média (revisitar em 2º dev) |
| Sem cache de deps do Docker (layer cache) | Build local mais lento que registry rebuild | Baixa |
| Build local usa CPU/VPS durante deploy | Latência ~10-30s na API durante rebuild web | Baixa (single-user; aceitável) |
| `bootstrap.sh` roda migrations mesmo deploy fail-safe (sem testar rollback path) | Alembic down em migration não-reversível requer manual | Baixa |
| Sem notificação Slack/email pós-deploy fail | Operador só vê se checkar GitHub manualmente | Baixa (single-dev; GitHub emails default on) |

## Riscos identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| T-1003/T-1004 nunca configurados | Média (operação pendente) | Alto (CD não effektiv; merge sem CI gate) | Documentado `docs/deploy.md` §14.2; PR #34 ready |
| GitHub Actions outage bloqueia hotfix deploy | Baixa | Médio | `docs/deploy.md` §14.5 via manual imperativo |
| `DEPLOY_DOMAIN` DNS ainda não propagation | Baixa | Baixo (smoke fail falso) | Operador ajusta variable; rerun |
| `DEPLOY_SSH_KEY` vazada | Baixa | Baixo (vazamento só força deploy do HEAD atual) | `command="..."` restringido; rotação SSH keygen novo |
| Migration destrutiva em main without test | Baixa | Alto (rollback trava) | `alembic downgrade -1` manual; revisar migration antes de merge |
| CIedo falso positivo (Tests pulados) | Baixa | Médio | `uv run pytest -q` executa all 226 tests; ruff check bloqueia |
| `bootstrap.sh` falha em prod (e.g., catalog seed quebra) | Baixa | Alto (deploy fail mid-migration) | `git revert` rollback; migrations testadas localmente antes |
| VPS sem disk pra build | Baixa | Alto (deploy fail) | Monitorar `df` via `vps-check.sh`; backups 14d retenção |
| Smoke em HTTPS pós-deploy return 403/502 se nginx config errado | Baixa | Médio | Deploy bloqueado; operador corrige nginx e re-push |
| `cancel-in-progress: false` em deploy acumula 2 deploys seriais | Baixa | Baixo | Single-dev; acceptável |