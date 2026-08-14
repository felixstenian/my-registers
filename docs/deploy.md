# Runbook de deploy — MVP em VPS única

Cobre T-901..T-907 da Fase 9. Objetivo: subir e manter o MVP em uma VPS Linux
com HTTPS, backups e monitoramento externo, com risco baixo de dowtime.

Constituição §31 (dev em Docker) **não** se aplica em produção — em prod
tudo roda em containers, incluindo backend e frontend.

## 1. Provisionar VPS

- Ubuntu 24.04 LTS, 2 vCPU / 4 GB RAM / 40 GB SSD (mínimo). Kernel default.
- Firewall (UFW):
  ```bash
  sudo ufw allow OpenSSH
  sudo ufw allow 80
  sudo ufw allow 443
  sudo ufw enable
  ```
- `fail2ban` instalado com defaults (SSH bruteforce ban).
- Docker Engine + Compose plugin (via apt oficial da Docker, não a versão do Ubuntu):
  ```bash
  # https://docs.docker.com/engine/install/ubuntu/
  ```
- Usuário sem root para operar (`useradd -m felix -s /bin/bash && usermod -aG docker felix`).
  Deploy pela conta `felix`, `sudo` só para operações de sistema.

## 2. Configurar DNS

- Registro `A` de `${DOMAIN}` apontando pro IP da VPS.
- **Sem** proxy Cloudflare (por enquanto — cookies `Secure; SameSite=Lax`
  funcionam melhor sem CDN intermediando).
- `dig +short A app.exemplo.com` deve retornar o IP em < 1 min de espera.

## 3. Clonar repo + secrets

```bash
cd ~
git clone https://github.com/felixstenian/my-registers.git
cd my-registers
cp .env.production.example .env.production
$EDITOR .env.production    # preencher tudo (§14.1 do app_plan)
chmod 600 .env.production
```

## 4. Emitir cert TLS (primeira vez)

Ver `infra/certbot/README.md`. Resumo:

```bash
# Sobe só o nginx com config placeholder + valida via Let's Encrypt staging.
# Depois substitui pela config real e recarrega.
```

## 5. Bootstrap (migrations + admin)

```bash
./scripts/bootstrap.sh .env.production
```

Idempotente — pode rodar quantas vezes quiser. Migrations vão até o head
atual; admin é criado se não existir, atualizado se as vars mudarem.

## 6. Subir os serviços

```bash
docker compose -f docker-compose.production.yml --env-file .env.production up -d
```

Estado esperado após ~30s (usando `docker compose ps`):
```
NAME              STATUS
my-registers-nginx-1        Up (healthy)
my-registers-api-1          Up (healthy)
my-registers-web-1          Up
my-registers-postgres-1     Up (healthy)
my-registers-minio-1        Up (healthy)
my-registers-minio-init-1   Exited (0)     # roda uma vez e sai — normal
my-registers-certbot-1      Up
```

> ⚠️ **`minio-init` precisa aparecer** — é o serviço que cria o bucket
> `registers-media` no primeiro boot. Se você deployar com um compose
> antigo que não tem esse service, o upload de imagem quebra com
> `NoSuchBucket` (Internal Server Error). Fix manual em
> `docs/fix-minio-bucket-prod.md`.

> ⚠️ **`S3_PUBLIC_BASE_URL` no `.env.production` precisa apontar pra
> `https://$DOMAIN/media`** — sem isso, as URLs de imagem geradas ficam
> em `http://minio:9000/...` (host interno, inatingível pelo browser),
> disparando `blocked:csp` no console. O nginx tem `location /media/`
> que faz proxy interno. Ver `.env.production.example` e
> `infra/nginx/conf.d/app.conf`.

Testes de fumaça:
- `curl -I https://$DOMAIN/` → 200 + `Strict-Transport-Security` presente.
- `curl -fsS https://$DOMAIN/api/health` → `{"status":"ok"}`.
- Login manual pelo browser em `https://$DOMAIN/login` com o admin default.
- **Upload de imagem**: no chat, anexa uma foto e envia. A mensagem deve exibir a imagem renderizada (não broken image). Ver `docs/fix-minio-bucket-prod.md` se falhar.

## 7. Backups (cron do host)

```bash
sudo crontab -e -u felix
```
```
# 03:00 dump completo do Postgres
0 3 * * * /home/felix/my-registers/scripts/backup-postgres.sh >> /var/log/registers-backup.log 2>&1
# 04:00 espelhamento MinIO
0 4 * * * /home/felix/my-registers/scripts/backup-minio.sh   >> /var/log/registers-backup.log 2>&1
```

Off-VPS opcional (recomendado):
```bash
export RCLONE_REMOTE="b2:registers-backups"    # configure rclone antes
```
Ambos os scripts respeitam essa var e replicam pra remote se setada.

## 8. Rotação de logs

Já está no `docker-compose.production.yml` (`json-file` com `max-size=10m,
max-file=5`). Nada mais a fazer — logs viram cyclíc automaticamente.

## 9. Health check externo (T-906)

Cria uma conta grátis em [healthchecks.io](https://healthchecks.io) e
adiciona um cronjob que faz ping da URL `/health`:

```bash
sudo crontab -e -u felix
```
```
# cada 5 min: bate no /health e pinga healthchecks
*/5 * * * * curl -fsS https://$DOMAIN/api/health > /dev/null && curl -fsS -m 10 --retry 3 https://hc-ping.com/SEU-UUID > /dev/null
```

Se o backend cair, healthchecks.io alerta por email/Telegram em 10 min.

**Complementar com o script local `scripts/vps-check.sh`:** roda em <5s e
cobre load/RAM/disco/containers/backups/TLS/fallbacks do LLM. Bom pra
`crontab` semanal ou pra dar `./scripts/vps-check.sh` no SSH sempre que
quiser um radar rápido do estado da VPS.

## 10. Deploy de novas versões

```bash
cd ~/my-registers
git fetch origin
git checkout main
git pull

# Bootstrap (só corre migrations pendentes)
./scripts/bootstrap.sh .env.production

# Rebuild + up com zero-downtime pra web e api (nginx segura o tráfego)
docker compose -f docker-compose.production.yml --env-file .env.production build api web
docker compose -f docker-compose.production.yml --env-file .env.production up -d api web
```

Rollback: `git checkout <hash-anterior>` + repetir. Se a migration for
irreversível, primeiro rode `alembic downgrade -1` (ver
`apps/api/alembic/versions/*.py::downgrade()`).

### 10.1 O que rebuildar em cada deploy

Nem todo PR mexe em todo serviço. Rebuildar tudo custa tempo e reinicia
containers sem necessidade. Use a tabela abaixo pra decidir escopo:

| O que mudou no PR | O que rebuildar |
|--|--|
| Só `apps/web/` | `up -d --build web` |
| Só `apps/api/` (sem migration) | `up -d --build api` |
| `apps/api/` **com** migration nova | `./scripts/bootstrap.sh .env.production` + `up -d --build api` |
| `docker-compose.production.yml` | `up -d` (recria containers afetados; adicione `--build` se `build:` mudou) |
| `infra/nginx/templates/*.template` | `up -d --force-recreate nginx` (envsubst só roda no boot — reload sozinho não pega mudança de template) |
| `infra/nginx/conf.d/*.conf` ou `nginx.conf` | `exec nginx nginx -s reload` (mudança direta em config renderizada) |
| `.env.production` | `up -d --force-recreate <service>` (nomear os que consomem a var) |
| Sem certeza / múltiplas áreas | `up -d --build` sem nome — rebuilda tudo. Custa tempo mas nunca deixa serviço com imagem stale. |

**Como confirmar escopo antes do deploy** (do host, após `git fetch origin`):

```bash
# Diff em arquivos que mudam a imagem web:
git diff --stat HEAD..origin/main -- apps/web/ next.config.mjs docker-compose.production.yml

# Diff em arquivos que mudam a imagem api:
git diff --stat HEAD..origin/main -- apps/api/ docker-compose.production.yml

# Existe migration nova?
git diff --name-only HEAD..origin/main -- apps/api/alembic/versions/
```

Vazio nos três = deploy pode ser só docs/spec, provavelmente `git pull`
sem `up -d` já basta.

> **Migrations são obrigatórias em TODO deploy, não só quando o PR traz
> migration nova.** `bootstrap.sh` é idempotente e roda `alembic upgrade
> head` — executá-lo sempre cobre o caso de o PR mexer no model SQLAlchemy
> sem migration dedicada (o `--autogenerate` nem sempre detecta) ou de
> uma migration pendente que ficou pra trás.
>
> **Failure mode conhecido (2026-08-13, fix v1.4.1):** o bloco-5 adicionou
> `NutrientFact.created_by` no model sem aplicar a migration 0008 na VPS.
> Todo registro de comida/bebida (que faz `SELECT nutrient_facts.created_by`)
> estourou `UndefinedColumnError`. O erro cai no fallback genérico e vira
> `llm_intent="unknown"` com `llm_confidence=NULL` — ou seja, registros de
> comida/bebida **pareciam falha de LLM mas eram schema drift**. Água
> continuou funcionando porque o path dela não consulta `nutrient_facts`.

### 10.2 Verificação pós-deploy

Após qualquer `up -d`, uma bateria rápida de checks:

```bash
# 1. Todos os containers healthy?
docker compose -f docker-compose.production.yml --env-file .env.production ps
# Coluna STATUS: espera "Up X seconds (healthy)" em todos.

# 2. Endpoint público OK?
curl -sSI https://$DOMAIN/api/health | head -3
# Espera HTTP/2 200.

# 3. Web serve rota protegida sem quebrar?
curl -sSI https://$DOMAIN/login | head -3

# 4. Migrations no head esperado?
docker compose -f docker-compose.production.yml --env-file .env.production run --rm api alembic current
# Espera a última revisão de apps/api/alembic/versions/ (hoje: 0010_propagate_action).

# 5. Logs sem stack traces recentes?
docker compose -f docker-compose.production.yml --env-file .env.production logs --since=2m api web | grep -iE "traceback|error |UndefinedColumnError" | head -10
```

**Canário rápido de schema drift:** mande uma mensagem de comida ou bebida
(ex.: "140g de feijão com 60g de arroz") no chat e confira se o registro
persiste com macros. Registro de água funcionar e comida/bebida falharem
com "Não consegui interpretar" é assinatura de schema drift (ver §10.1),
não de falha de LLM.

Se um container ficar em `Restarting` por mais de 30s, `logs <serviço>`
mostra o motivo real — a maioria das vezes é config errada em
`.env.production` ou cert ausente.

## 11. Restore de um dia ruim

```bash
# Snapshot pre-restore por precaução
./scripts/backup-postgres.sh
# Restaura o dump escolhido
./scripts/restore-postgres.sh /var/backups/pg/registers-YYYYMMDD-HHMM.dump
```

## 12. Checklist §16 (segurança)

Cobrir antes de considerar o MVP "em produção".

- [x] Senhas com Argon2id (`time_cost=3`, `memory_cost=64MB`, `parallelism=2`) — Fase 1.
- [x] `JWT_SECRET` fora do repo, `chmod 600` no host.
- [x] `.env.production` fora do repo; segredos nunca em log (Const. §19).
- [x] Cookies `HttpOnly; Secure; SameSite=Lax` — Fase 1.
- [x] Access token 15min + refresh 14d com rotação; reuso invalida família — Fase 1.
- [x] Sem cadastro/reset público (SP-05). Criação de user só pela CLI.
- [x] Rate limit login: 5/min/IP + 10/15min/email.
- [x] Validação server-side de MIME e ≤ 8MB no upload (SP-11).
- [x] Nginx: HSTS 1 ano, X-Content-Type-Options, X-Frame-Options DENY, CSP,
      Referrer-Policy, Permissions-Policy — `infra/nginx/templates/app.conf.template`.
- [x] TLSv1.2+ (nada de v1.0/1.1); ciphers `HIGH:!aNULL:!MD5`; OCSP stapling.
- [x] Postgres e MinIO sem porta pública (rede `internal` do compose).
- [x] `client_max_body_size 15m` no Nginx (4 fotos × 8MB + margem).
- [x] Migrations rodadas por script humano (`bootstrap.sh`), não pelo runtime.
- [x] Backups diários (postgres `-Fc` + minio `mc mirror`), retenção 14d local.
- [ ] Backups off-VPS via `RCLONE_REMOTE` (opcional mas recomendado).
- [ ] `fail2ban` ativo e monitorado.
- [ ] Kernel patches automáticos: `unattended-upgrades --dry-run` limpo.
- [ ] `docker system prune -a --volumes` mensal, agendado.
- [ ] Auditoria manual: `docker compose ... logs api | grep -E 'ERROR|CRITICAL'`
      semanalmente na 1ª sprint pós-deploy.

## 13. O que fica de fora do MVP

- Zero-downtime real com múltiplas réplicas + rolling update (§9.5 do plan).
- Métricas via Prometheus/Grafana (tem log JSON, dá para plugar depois).
- Redis pra rate-limit distribuído (por ora `in-memory` no processo).
- WAF/CDN na frente do Nginx.

Todos esperando o MVP validar o produto antes de investir em complexidade
extra (Const. §31 — YAGNI).

## 14. CI/CD (Fase 10 — GitHub Actions)

Registrado em **ADR-012** (`specs/001-mvp-registro-diario/research.md`).
Dois workflows em `.github/workflows/`:

- **`ci.yml`** — dispara em `pull_request` para `dev`/`main`. Dois jobs
  em paralelo:
  - `api`: Postgres 16 service + `uv sync` + `ruff check` + `ruff format
    --check` + `pytest -q`.
  - `web`: `pnpm install --frozen-lockfile` + `typecheck` + `build`
    (webpack) + `verify:sw` (garante INV-11).
- **`deploy.yml`** — dispara ao concluir `ci.yml` com sucesso em `main`.
  Faz SSH pra VPS usando chave restrita e roda smoke test em
  `https://$DEPLOY_DOMAIN/api/health`.

### 14.1 Fluxo de trabalho

```
feature branch → PR pra dev → ci.yml (bloqueante) → merge
release: dev → PR pra main → ci.yml → merge → deploy.yml → prod
```

Não há mais `git pull` + `docker compose up -d --build` manual — o
deploy é feito pelo próprio GitHub Actions ao mergear em `main`.

> **TODO deploy — manual ou via CD — passa por `./scripts/bootstrap.sh
> .env.production`** (que roda `alembic upgrade head`). O `DEPLOY_CMD` da
> §14.2 já a encadeia; a via manual de emergência (§14.5) também. Sem ela,
> o schema do banco fica pra trás do model SQLAlchemy e as falhas são
> silenciosas (ver failure mode do bloco-5 em §10.1).

### 14.2 Configuração da VPS (uma vez só)

**Chave SSH `deploy-only`:**

```bash
# No seu laptop (não na VPS):
ssh-keygen -t ed25519 -f ~/.ssh/deploy_myregisters -N "" -C "deploy-only"

# A public key vai pro authorized_keys da VPS com command="..." restringindo
# o que essa chave pode fazer. NÃO é uma chave shell normal — se você
# tentar `ssh -i deploy_myregisters felix@vps` interativamente, ele roda
# o comando de deploy e desconecta.
DEPLOY_CMD='cd ~/my-registers && git pull && ./scripts/bootstrap.sh .env.production && docker compose -f docker-compose.production.yml --env-file .env.production up -d --build api web'

# Na VPS, como usuário felix:
mkdir -p ~/.ssh && chmod 700 ~/.ssh
# Prepend `command="…",restrictions` ANTES da chave pública em authorized_keys:
echo "command=\"$DEPLOY_CMD\",no-port-forwarding,no-x11-forwarding,no-agent-forwarding,no-pty $(cat ~/.ssh/deploy_myregisters.pub)" \
  >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

**Segredos e variáveis no GitHub:**

Repo → Settings → Secrets and variables → Actions.

**Secrets** (criptografados; usados só pelo runner):
| Nome | Valor |
|--|--|
| `DEPLOY_SSH_KEY` | Conteúdo da **private key** (`~/.ssh/deploy_myregisters`, o arquivo sem `.pub`). |

**Variables** (visíveis em logs; ok pra dados não-sensíveis):
| Nome | Valor exemplo |
|--|--|
| `DEPLOY_HOST` | `myregister.felix.dev.br` (ou IP se DNS ainda não propagou) |
| `DEPLOY_DOMAIN` | `myregister.felix.dev.br` (usado no smoke test HTTPS) |

O `ANTHROPIC_API_KEY`, `POSTGRES_PASSWORD`, etc. **não** vão pro GitHub —
continuam só em `.env.production` na VPS. Rotação é operação manual no
host.

**Branch protection em `main`:**

Repo → Settings → Branches → Add rule → `main`:
- [x] Require a pull request before merging
- [x] Require status checks to pass before merging:
  - [x] `api (ruff + pytest)`
  - [x] `web (typecheck + build)`
- [x] Require branches to be up to date before merging
- [x] Require linear history (opcional; evita merge commits noise)
- [x] Do not allow bypassing the above settings

### 14.3 Debug de deploy que falhou

```bash
# Lista os últimos runs do deploy.yml:
gh run list --workflow=deploy.yml --limit 10

# Ver logs do último:
gh run view --log

# Se o smoke test falhou mas containers estão de pé, o app pode estar
# funcional — verifique manualmente:
curl -sSI https://$DOMAIN/api/health
docker compose -f docker-compose.production.yml --env-file .env.production ps
```

### 14.4 Rollback

Sem workflow dedicado (evita complexidade). Padrão git:

```bash
# No laptop, na branch main:
git revert <hash-que-quebrou>
git push origin main
# O deploy.yml roda de novo com o commit anterior.
```

Se o rollback também depende de banco (migration destrutiva), primeiro
`alembic downgrade -1` na VPS antes de mergear o revert.

### 14.5 Quando pausar o CD

Situações que exigem override manual:
- **GitHub Actions fora do ar** — deploy pela via tradicional na VPS:
  `git pull && ./scripts/bootstrap.sh && docker compose ... up -d --build`.
- **Mudança urgente em `.env.production`** (rotação de segredo) —
  editar no host, `docker compose ... up -d --force-recreate <service>`.
- **Migration não-reversível chegando com bug** — segure o merge em
  `main`, aplique correção em outro PR, mergeie o combo.

Não desabilite o `deploy.yml` — em vez disso feche a PR ou marque
com label `do-not-deploy` (comportamento não é impedido, mas sinaliza).
