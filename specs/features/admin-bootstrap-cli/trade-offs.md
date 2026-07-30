# Trade-offs — Bootstrap de admin via CLI

> **Rastreabilidade**: Const. §18/§24, ADR-001 · Implementação: `apps/api/app/cli/main.py`, `scripts/bootstrap.sh`. Não há ADR específica para o CLI — decisões registradas inline na Constituição e neste arquivo.

## Decisão 1 — CLI standalone (sem endpoint HTTP) para cadastro/reset

### Contexto
Const. §18 proíbe endpoints HTTP de cadastro/reset. Avaliava-se seguir só CLI vs adicionar endpoint interno com IP allowlist.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — CLI exclusivo, operador com SSH** (escolhida) | Zero superfície de ataque HTTP; bloqueia enumeração/brute-force; single-user MVP cabe | Reset exige SSH + conhecimento; sem automatização self-service |
| B — Endpoint HTTP `/admin/create` com IP allowlist | Automatizável por script | IP spoofing / X-Forwarded-For forge; superfície ativo de ataque |
| C — Web admin UI (só super-admin) | Conveniente | Viol direto Const. §18; código extra de UI de admin |

### Decisão tomada
**Opção A** — CLI no `python -m app.cli`; operador SSH-only. Implementação: `cli/main.py`, Const. §18.

### Consequências
- Positivas: defesa em profundidade; email/password enumeramento indisponível.
- Negativas / dívida técnica: `reset-password`/`create-admin` postponidos; reset atual via SSH ad-hoc.

---

## Decisão 2 — Typer em vez de argparse/click puro

### Contexto
CLI que precisa aceitar `bootstrap`/`seed-nutrition`/`version`. Codebase já é pydantic-heavy.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Typer** (escolhida) | Type-hints; auto-help; commands declarativos; integra pydantic-ish | Dep extra (small) |
| B — `argparse` stdlib | Zero deps | Boilerplate maior; help manual |
| C — Click | Robustez; API madura | Menor integração com type-hints; mais verboso que Typer |

### Decisão tomada
**Opção A** — Typer com `@app.command()`. Justificativa: DX + coerência com `pydantic-settings`.

### Consequências
- Positivas: código curto (96 linhas); commands bem declarados.
- Negativas: 1 dep runtime (`typer` + `click` transitiva); leve bundle extra no container API (~2 MB).

---

## Decisão 3 — Idempotência via lookup (sem `--force`, sem upsert SQL)

### Contexto
`bootstrap` roda a cada deploy; precisa não sobrescrever senha se user já existe. Avaliava-se `INSERT ... ON CONFLICT DO NOTHING` ou flag `--force`.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — `get_by_email` → se None, `create` + commit** (escolhida) | Simples; controlado; não altera senha nunca | 2 queries no path novo (SELECT + INSERT) |
| B — `INSERT ... ON CONFLICT DO NOTHING` | 1 query | Menos legível em SQLAlchemy; não retorna `created vs already_exists` sem extra check |
| C — Flag `--force` para sobrescrever | Conveniente | Risco de uso acidental; senha permanente sobrescrita em deploys |

### Decisão tomada
**Opção A** — `_bootstrap_admin` faz lookup, branch. Implementação: `cli/main.py:24-32`.

### Consequências
- Positivas: sem flag perigosa; teste isolado fácil (mocka repo).
- Negativas: 2 queries no criação; desprezível (uma vez por deploy); race condition potencial resolvido por CITEXT unique constraint (segundo INSERT falha).

---

## Decisão 4 — `lower()` no caller apesar de `CITEXT`

### Contexto
DB tem `email CITEXT unique`; lookup por default é case-insensitive. Avaliava-se confiar só no DB ou lower no código.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — `lower()` no caller** (escolhida) | Garante match mesmo se env variar; defensivo | 1 byte extra de código; redundante se CITEXT funcionar |
| B — Confiança em CITEXT | Passa ao DB | Surpresas se DB migrar para `Text` no futuro |

### Decisão tomada
**Opção A** — `settings.default_admin_email.lower()` no passo para `_bootstrap_admin`. Implementação: `cli/main.py:54`.

### Consequências
- Positivas: garantia dupla; valor persistido sempre lowercase (semансы case divergentes em DB).
- Negativas: nenhuma significativa.

---

## Decisão 5 — Argon2id params hardcoded (Const. §15)

### Contexto
ADR-001 fixa Argon2id `time=3, memory=64MB, parallelism=2`. Avaliava-se settings-driven ou hardcoded.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Hardcoded em `security.py`** (escolhida) | Imutável sem code change + revisão; segurança em primeiro | Upgrade requer release + `needs_rehash()` opportunistic |
| B — Settings-driven | Tunavel por env; ajuste operacional risco: degraded params em prod |
| C — Const valores dinâmicos por env | Flexível | Mesmo risco que B |

### Decisão tomada
**Opção A** — `_hasher = PasswordHasher(time_cost=3, memory_cost=64*1024, parallelism=2)` hardcoded. Justificativa: ajuste de hash é decisão de segurança, não operacional; code review叮嘱 params.

### Consequências
- Positivas: param fixos auditáveis; upgrade Argon-version via `needs_rehash()` opportunistically em login.
- Negativas / dívida técnica: upgrade da lib Argon2 pode broken old hashes — `needs_rehash()` cobre; test em CI.

---

## Decisão 6 — Senha nunca em log/stdout (Const. §19)

### Contexto
Bootstrap lida com plaintext senha via env. Avaliava-se logar evento com info útil vs estrito.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Stdout só action + user_id; log extra {event, user_id}** (escolhida) | Compliant Const. §19; senha nunca persiste | Debug menos contextual sem password hash (aceito) |
| B — Log password_hash (não plaintext) | Debuggable | Pode vazar via `kubectl logs`/journald |
| C — Log diff de derniers hashes | Auditoria | Hashes são secretias se database leak |

### Decisão tomada
**Opção A** — CLI só echoa `action` + `user_id`; log structured `event`+`user_id` (no `password_hash`/`password`). Implementação: `cli/main.py:57-61`.

### Consequências
- Positivas: comply Const. §19; zero leaker de senha.
- Negativas: debug de bootstrap precisa outras técnicas (state do DB).

---

## Decisão 7 — `scripts/bootstrap.sh` compartilhado entre Actions e manual

### Contexto
Deploy Actions (Fase 10) executa `command="...bootstrap.sh .env.production..."`. Deploy manual (GitHub outage) precisa do mesmo caminho.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Mesmo `bootstrap.sh` chamado em ambos** (escolhida) | Single source of truth; fallback sem desvio | Validação `.env` funciona igual; integrado em código |
| B — Script Actions-only + script manual separado | Isolar | Duplicação; drift |
| C — `docker compose run api alembic + bootstrap` | Containerizado sempre | Runtime da API podia correr migrations — viola Const. §24 se mal configurado |

### Decisão tomada
**Opção A** — `scripts/bootstrap.sh` é idempotente e utilizado em todos canais. ADR-012 consequência; `docs/deploy.md` §14.5 explica fallback.

### Consequências
- Positivas: drift zero; consulta a um arquivo para debug.
- Negativas: `bootstrap.sh` precisa manter separateness entre Actions env (no GitHub) e VPS env (no `.env.production`).

---

## Decisão 8 — `alembic upgrade head` ANTES do bootstrap

### Contexto
Runtime da API não corre migrations (Const. §24); bootstrap precisa tabela `users` pra inserir.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — `alembic upgrade head` no `bootstrap.sh` antes de CLI** (escolhida) | Garante schema pronto; explicit no deploy | Sequência obrigatória; esquecer quebra bootstrap |
| B — CLI chama `alembic upgrade` internamente | One-shot | Runtime acoplamento; CLI não deveria manusear migrations |
| C — Init container Docker com Alembic | K8s pattern | Compose `depends_on` healthcheck já cobre; extra complex for single-VPS |

### Decisão tomada
**Opção A** — `bootstrap.sh` chama `alembic upgrade head` antesde `python -m app.cli bootstrap`. Implementação: `scripts/bootstrap.sh` (T-905).

### Consequências
- Positivas: separação clara; CLI não sabe de migrations.
- Negativas: ordem obrigatória documentada (deploy runbook §14).

---

## Decisão 9 — `reset-password`/`create-admin` postponidos

### Contexto
Const. §18 menciona `app.cli create-admin` e `app.cli reset-password` como referência; só `bootstrap` foi implementado. Avaliava-se adicionar agora.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Só `bootstrap` para MVP single-user** (escolhida) | Escopo minimal; reset via SSH ad hoc | Spec §18 tem explicit referência; gap documentado |
| B — Implementar `reset-password` grudados agora | Compliant com plano Const. §18 spec | Trabalho extra; outliers sim funcionalmente, sem demanda real |
| C — `create-admin` (multi-user) agora | Escalar | MVP é single-user; spec Art. V §20 "única conta" |

### Decisão tomada
**Opção A** — `bootstrap` único implemented. Justificativa: Art. V §20 ("UP única conta"); gap aceito; reset fallback via SSH ad-hoc.

### Consequências
- Positivas: menos código, menos bugs no MVP.
- Negativas / dívida técnica: gap documentado; se senha perdida, recovery via SSH manual. Tarefa posterior (Fase 11.x?).

---

## Decisão 10 — `default_admin_password=""` default força explicitação

### Contexto
Settings pydantic-settings default `""` para `default_admin_password`. Avaliava-se defaultar `adminadmin` ou força explicit.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Default `""` que força empty check** (escolhida) | Defesa em profundidade; nada silenciosamente instala senha fraca | Operador precisa sempre setar env (pequeno friction) |
| B — Default `adminadmin` (conveniência dev) | Zero config em dev | Perigo se deploy prod esquecer — senha fraca em prod |
| C — Sem default (raise em Settings) | Explícito começando | Erros de config ainda più misterioso |

### Decisão tomada
**Opção A** — `default_admin_password: str = ""` e check no `bootstrap` command: `if not settings.default_admin_password: exit 1`. `.env.example` documenta `adminadmin` para dev. Implementação: `cli/main.py:49-51`, `config.py:38`.

### Consequências
- Positivas: deploy prodcliffe nunca usa senha default; solid deploy-time guard.
- Negativas: Operationalmental precisa setar env (documented clearly).

---

## Dívida técnica conhecida

| Item | Impacto | Prioridade |
|---|---|---|
| `reset-password` não implementado (Const. §18 menciona) | Reset atual via SSH ad hoc; multi-step manual | Média — pendente demanda/uso |
| `create-admin` não implementado | Multi-user indisp. (single-user MVP) | Baixa |
| Sem `tests/test_cli_bootstrap.py` dedicado | Cobertura via `test_auth.py` indireta; regressão só pega em auth flow | Média — adicionar Vitest-like para Typer CliRunner |
| `bootstrap` sem handle explícito para DB exception (Postgres down) | Exit code é da exception stacktrace (não 1 explicito) | Baixa — message é legível, mas não ergonomic |
| Race condition entre 2 bootstraps paralelos (raro em deploy serializado) | 2º INSERT falha unique CITEXT → stacktrace | Baixa — `deploy.yml` já serializa |
| `version` command hardcoded `0.0.0` (não lê `pyproject.toml`) | Versão não acompanha release automatic | Baixa — futuro: usar `importlib.metadata` |
| `seed-nutrition` path relativo ao CSV (`app/integrations/nutrition/seed_tbca.csv`) | Se rodar de fora de `apps/api` cwd, path não resolve | Baixa — usualmente rodado em `cd apps/api` |

## Riscos identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| Senha esquecida sem `reset-password` command | Média | Médio | SSH ad-hoc via `docker compose exec api python -c "..."`; documentado |
| `bootstrap` rodado sem `.env` sourceado | Média | Baixo | Check `not default_admin_password` captura; exit 1 |
| Postgres indisponível no bootstrap | Baixa | Alto | `bootstrap.sh` valida antes; exception legível; deploy aborta |
| 2 deploys concorrentemente tentam bootstrap | Baixa (deploy.yml serializa) | Baixo | CITEXT unique constraint garante 1 vence; 2º falha |
| Argon2 lib upgrade breaks old hashes | Baixa | Alto | `needs_rehash()` opportunistic em login (feature `authentication-session`) |
| `DEFAULT_ADMIN_PASSWORD` exposto em `.env.production` com perms erradas | Baixa | Alto | VPS perms `chmod 600`; nunca no git; never no GitHub |
| CI fixtures (`admin@example.com/adminadmin`) viram hardcoded em testes | Alta | Baixo | Convenção dev; nada vulnerável (cred dev não-prod) |
| `bootstrap` executado por usuário sem perm DB write | Baixa | Médio | Exception na `session.commit()` propagada; legada a operador |
| `seed-nutrition` roda em prod com CSV alterado (valores sync drift) | Média | Baixo | Idempotente — re-run atualiza; periódico após TBCA refresh |