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
my-registers-nginx-1    Up (healthy)
my-registers-api-1      Up (healthy)
my-registers-web-1      Up
my-registers-postgres-1 Up (healthy)
my-registers-minio-1    Up (healthy)
my-registers-certbot-1  Up
```

Testes de fumaça:
- `curl -I https://$DOMAIN/` → 200 + `Strict-Transport-Security` presente.
- `curl -fsS https://$DOMAIN/api/health` → `{"status":"ok"}`.
- Login manual pelo browser em `https://$DOMAIN/login` com o admin default.

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
| `infra/nginx/` (config) | `exec nginx nginx -s reload` (ou restart se mudou volume/binding) |
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

# 4. Logs sem stack traces recentes?
docker compose -f docker-compose.production.yml --env-file .env.production logs --since=2m api web | grep -iE "traceback|error " | head -10
```

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
      Referrer-Policy, Permissions-Policy — `infra/nginx/conf.d/app.conf`.
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
