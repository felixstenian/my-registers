# Configurando a VPS no DigitalOcean

Passo a passo do zero até o app rodando com HTTPS. Sinônimo prático de
`docs/deploy.md`, com cliques da UI da DO e comandos concretos. Se algo
divergir do que a UI mostrar (a DO mexe no visual às vezes), o roteiro
lógico continua o mesmo.

**Custo estimado no MVP:** ~$18/mês (droplet $12 + $6 de reserva). Zero
custo de egress porque MinIO fica na mesma máquina.

---

## Pré-requisitos

- Conta na DigitalOcean com meio de pagamento verificado.
- Domínio registrado (Registro.br, Namecheap, Cloudflare Registrar…).
  Vamos apontar o DNS pra DO.
- Uma chave SSH local. Se não tiver:
  ```bash
  ssh-keygen -t ed25519 -C "felix-my-registers" -f ~/.ssh/id_ed25519_droplet
  # sem passphrase se for pra CI; com passphrase se for uso pessoal.
  ```
- Chave da Anthropic (`sk-ant-…`) e sua senha de admin decidida.

---

## 1. Criar o droplet

1. Menu esquerdo → **Create** → **Droplets**.
2. **Choose an image:** aba *Distributions* → **Ubuntu 24.04 (LTS) x64**.
3. **Choose Size:**
   - *Droplet Type:* **Basic**.
   - *CPU options:* **Regular (Disk: SSD)**.
   - Plano recomendado: **$12/mo (2 vCPU, 2 GB RAM, 60 GB SSD)**.
     - 4 GB só vale se você planeja rodar Sonnet com muitas imagens em
       paralelo — no MVP de 1 usuário, 2 GB basta.
4. **Choose a datacenter region:** *NYC3* ou *SFO3* costuma ter latência
   melhor pra Anthropic. *São Paulo (SFO2 / SGP1 não; a região BR é
   pequena)*. Se latência do usuário BR importa mais que da LLM, use
   *NYC3*.
5. **Authentication:** *SSH Key*.
   - Se ainda não subiu sua chave: **New SSH Key** → cole o conteúdo de
     `~/.ssh/id_ed25519_droplet.pub` → dá um nome (`macbook-felix`).
   - Marque a chave.
6. **Hostname:** `registers-prod` (ou o que preferir).
7. **Tags:** `mvp`, `app`. (Ajuda a filtrar depois.)
8. **Backups (opcional):** +20% do custo mensal. Se quiser dormir mais
   tranquilo, marque. Nossos scripts já fazem backup lógico, então é
   redundante mas não atrapalha.
9. **Create Droplet.** Espera ~1 min.

Anota o **IPv4** que aparecer (algo tipo `165.227.192.15`).

---

## 2. (Opcional) Reserved IP

Se quiser trocar o droplet no futuro sem trocar de IP:

1. Menu → **Networking** → **Reserved IPs** → **Assign Reserved IP**.
2. Escolhe a região do droplet e associa ao `registers-prod`.
3. **Custa $0/mês enquanto está associado a um droplet ativo.**

Use esse IP no DNS em vez do IP direto. Se você não vai trocar de droplet
nos próximos meses, pode pular.

---

## 3. Apontar o DNS

Duas opções:

### Opção A — DNS na própria DigitalOcean (mais simples)

1. Menu → **Networking** → **Domains** → **Add Domain**.
2. Adiciona seu domínio (ex.: `app.exemplo.com` — pode ser subdomínio).
   Se for domínio raiz, aponte-o para os nameservers da DO (ver §3.5 na
   UI): `ns1.digitalocean.com`, `ns2`, `ns3`. Feito no registrar do
   domínio.
3. Dentro do domínio na DO, cria:
   - Registro **A** — hostname `@` (ou o subdomínio) → droplet ou
     reserved IP.
   - (Opcional) Registro **AAAA** se seu droplet tem IPv6.

### Opção B — DNS externo (Cloudflare, Registro.br, etc.)

Adiciona um registro `A` no seu provedor:
- **Type:** A
- **Name:** `app` (para `app.exemplo.com`) ou `@` (para o raiz)
- **Value:** IP do droplet
- **TTL:** 300 (5 min é OK enquanto testa)

**Se usar Cloudflare, DESLIGUE o proxy (nuvenzinha cinza, não laranja)**
até a app subir com HTTPS certo. Cookies `Secure; SameSite=Lax` +
Cloudflare cache dão dor de cabeça no primeiro deploy.

### Verificar

Espera 1-5 min e:
```bash
dig +short A app.seudominio.com
# Deve devolver o IP da VPS.
```

---

## 4. Primeiro acesso SSH

```bash
ssh -i ~/.ssh/id_ed25519_droplet root@165.227.192.15
```

Aceita o fingerprint na primeira vez. Se você fez tudo certo na §1,
entra direto.

Dentro do droplet:

```bash
# Confirma que é Ubuntu 24.04
lsb_release -a

# Atualiza tudo
apt-get update && apt-get upgrade -y
```

---

## 5. Endurecer o SSH

Ainda como `root`:

```bash
# 5.1 Cria usuário sem privilégios
useradd -m -s /bin/bash felix
usermod -aG sudo felix

# 5.2 Copia a chave SSH do root pro felix
mkdir -p /home/felix/.ssh
cp /root/.ssh/authorized_keys /home/felix/.ssh/
chown -R felix:felix /home/felix/.ssh
chmod 700 /home/felix/.ssh
chmod 600 /home/felix/.ssh/authorized_keys

# 5.3 Sudo sem senha (opcional, mas prático — só se você é o único
#     admin. Alternativa: define senha com `passwd felix`.)
echo 'felix ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/felix
chmod 440 /etc/sudoers.d/felix

# 5.4 Desabilita login root e senha via SSH
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart ssh
```

**Testa em outro terminal** (não fecha esse ainda):
```bash
ssh -i ~/.ssh/id_ed25519_droplet felix@165.227.192.15
sudo -n whoami   # deve responder "root"
```

Se funcionou, fecha a sessão do `root`. **Se não funcionou, corrige antes
de fechar — se travar, tem o "Console droplet" na UI da DO como último
recurso.**

---

## 6. Firewall (UFW)

Como `felix`:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
# Confirma:
sudo ufw status verbose
```

Nada mais além disso. Postgres (5432) e MinIO (9000/9001) ficam **só na
rede interna do Docker**, não expostas ao público.

---

## 7. fail2ban

```bash
sudo apt-get install -y fail2ban
sudo systemctl enable --now fail2ban
sudo fail2ban-client status sshd
```

Config default já banna IPs após 5 tentativas SSH em 10 min. Suficiente
pro MVP.

---

## 8. Instalar Docker

Segue o script oficial da Docker (mais confiável que o `docker.io` do
apt do Ubuntu):

```bash
# Adiciona repo oficial
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Adiciona felix ao grupo docker (evita sudo em cada comando)
sudo usermod -aG docker felix

# Precisa recarregar a sessão pra pegar o novo grupo:
exit
```

Reconecta:
```bash
ssh -i ~/.ssh/id_ed25519_droplet felix@165.227.192.15
docker --version           # deve rodar sem sudo
docker compose version
```

---

## 9. Atualizações automáticas do kernel

```bash
sudo apt-get install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades   # marca "yes"
```

Config já vem com upgrades de segurança automáticos. Não vai reiniciar
sozinho — se um kernel novo pedir reboot, o arquivo
`/var/run/reboot-required` fica lá até você `sudo reboot`.

---

## 10. Clonar o repo + rodar

```bash
cd ~
git clone https://github.com/felixstenian/my-registers.git
cd my-registers
cp .env.production.example .env.production
nano .env.production      # ou vim, code-server, o que quiser
chmod 600 .env.production
```

Preenche **tudo** que tem `change-me` (senhas fortes com
`openssl rand -base64 24` são um bom padrão).

Alguns pontos que confundem:
- **`DOMAIN`**: só o hostname, sem `https://`, sem `/`. Ex.:
  `app.seudominio.com`.
- **`DATABASE_URL`**: use o hostname `postgres` (é o service do compose,
  não `localhost`).
- **`S3_ENDPOINT`**: `http://minio:9000` (idem).
- **`COOKIE_DOMAIN`**: mesmo valor de `DOMAIN`.
- **`ALLOWED_ORIGINS`**: `https://<DOMAIN>` (com `https://`, sem trailing
  slash).
- **`JWT_SECRET`**: `openssl rand -base64 48`.

---

## 11. Emitir o certificado TLS

Segue exatamente `infra/certbot/README.md`. Nginx expande `${DOMAIN}`
automaticamente no boot (envsubst da imagem oficial), então não precisa
`sed`. Resumo:

```bash
# Backup do template real
cp infra/nginx/templates/app.conf.template infra/nginx/templates/app.conf.template.bak

# Placeholder HTTP-only pra Let's Encrypt validar
cat > infra/nginx/templates/app.conf.template <<'EOF'
server {
  listen 80;
  server_name ${DOMAIN};
  location /.well-known/acme-challenge/ { root /var/www/certbot; }
  location / { return 200 "ok"; }
}
EOF

# Sobe SÓ o nginx (envsubst roda no boot com ${DOMAIN} do env)
docker compose -f docker-compose.production.yml --env-file .env.production up -d nginx

# Testa em staging (não bate rate limit real)
DOMAIN=$(grep ^DOMAIN= .env.production | cut -d= -f2)
LETSENCRYPT_EMAIL=$(grep ^LETSENCRYPT_EMAIL= .env.production | cut -d= -f2)

docker compose -f docker-compose.production.yml --env-file .env.production run --rm \
  --entrypoint certbot certbot \
  certonly --webroot -w /var/www/certbot \
  --staging --agree-tos --no-eff-email \
  -m "$LETSENCRYPT_EMAIL" -d "$DOMAIN"

# Se "Successfully received certificate" na staging, apaga o cert
# de teste e emite o REAL (sem --staging):
docker compose -f docker-compose.production.yml --env-file .env.production run --rm \
  --entrypoint certbot certbot \
  delete --cert-name "$DOMAIN"

docker compose -f docker-compose.production.yml --env-file .env.production run --rm \
  --entrypoint certbot certbot \
  certonly --webroot -w /var/www/certbot \
  --agree-tos --no-eff-email \
  -m "$LETSENCRYPT_EMAIL" -d "$DOMAIN"

# Restaura o template real (com HTTPS)
mv infra/nginx/templates/app.conf.template.bak infra/nginx/templates/app.conf.template

# Recria nginx (envsubst só roda no boot — `nginx -s reload` sozinho
# não pega mudança de template)
docker compose -f docker-compose.production.yml --env-file .env.production up -d --force-recreate nginx
```

---

## 12. Bootstrap (migrations + admin)

```bash
./scripts/bootstrap.sh .env.production
```

Rola até "OK. Suba os serviços com…". Se der erro, o output mostra qual
step falhou (migração ou bootstrap CLI).

---

## 13. Subir os serviços

```bash
docker compose -f docker-compose.production.yml --env-file .env.production up -d
```

Espera ~30s e:

```bash
docker compose -f docker-compose.production.yml --env-file .env.production ps
```

Todos devem estar `Up (healthy)` (exceto `minio-init` que sai depois de
criar o bucket — status `Exited (0)` é OK).

Testa de fora:
```bash
curl -I https://app.seudominio.com/
# HTTP/2 200
# strict-transport-security: max-age=31536000; includeSubDomains
# x-frame-options: DENY

curl -fsS https://app.seudominio.com/api/health
# {"status":"ok"}
```

Abre no browser: `https://app.seudominio.com/login`. Loga com o admin
default (`DEFAULT_ADMIN_EMAIL` / `DEFAULT_ADMIN_PASSWORD` do `.env`).

---

## 14. Cron de backup

```bash
sudo crontab -e -u felix
```

Adiciona:

```
0 3 * * * /home/felix/my-registers/scripts/backup-postgres.sh >> /var/log/registers-backup.log 2>&1
0 4 * * * /home/felix/my-registers/scripts/backup-minio.sh   >> /var/log/registers-backup.log 2>&1
```

Se quiser off-VPS (recomendado), configure `rclone` para B2/S3 e defina
`RCLONE_REMOTE` no ambiente do cron:

```
RCLONE_REMOTE=b2:registers-backups-felix
0 3 * * * /home/felix/my-registers/scripts/backup-postgres.sh >> /var/log/registers-backup.log 2>&1
0 4 * * * /home/felix/my-registers/scripts/backup-minio.sh   >> /var/log/registers-backup.log 2>&1
```

Testa manualmente pra ver se sobe rápido:
```bash
sudo mkdir -p /var/backups/pg /var/backups/minio
sudo chown felix:felix /var/backups/pg /var/backups/minio
./scripts/backup-postgres.sh
ls -lh /var/backups/pg/
```

---

## 15. Health check externo (healthchecks.io)

1. Cria conta grátis em https://healthchecks.io.
2. **Add check** → nome `registers-prod` → schedule `*/5 * * * *` →
   grace time 3 min.
3. Copia o UUID do ping URL.

Na VPS:
```bash
sudo crontab -e -u felix
```

Adiciona:
```
*/5 * * * * curl -fsS --max-time 15 https://app.seudominio.com/api/health > /dev/null && curl -fsS --max-time 10 https://hc-ping.com/SEU-UUID-AQUI > /dev/null
```

Em 10 min, healthchecks.io deve mostrar o check como *"up"*. Se cair
por > 5 min, você recebe email/Telegram/Discord (configura na UI da
healthchecks).

---

## 16. Snapshot da DO (opcional, muito recomendado após primeiro boot)

Depois que tá tudo funcionando:

1. Menu → seu droplet → **Snapshots** → **Take Snapshot**.
2. Nome: `registers-prod-clean-YYYYMMDD`.
3. Custa $0.06/GB/mês (~$4/mês pra um droplet de 60GB). Você mantém dois
   ou três históricos e apaga os antigos.

Um snapshot = restore de 5 min se algo der muito errado. Vale a pena.

---

## 17. Deploy de nova versão

Depois de mergear PRs, na VPS:

```bash
cd ~/my-registers
git fetch origin
git checkout main
git reset --hard origin/main

./scripts/bootstrap.sh .env.production  # se tiver migration nova

docker compose -f docker-compose.production.yml --env-file .env.production build api web
docker compose -f docker-compose.production.yml --env-file .env.production up -d api web

# Log em tempo real
docker compose -f docker-compose.production.yml --env-file .env.production logs -f api
```

Rollback simples: `git checkout <hash-anterior> && ./scripts/bootstrap.sh
&& up -d`.

---

## 18. Custo total

- Droplet $12/mês (2 vCPU / 2 GB RAM / 60 GB SSD)
- Reserved IP $0 (associado)
- Snapshots $0.06/GB/mês (~$4 se 60GB usado com 1 snapshot)
- Backups automáticos DO $2.40/mês (20% do droplet)
- **Total: $12-18/mês** dependendo do que você marcar

Off-VPS (rclone → B2 Backblaze): ~$0.005/GB/mês. Se seus dumps ficam
~200 MB, é $0.001/mês. Vale muito a pena.

---

## 19. Radiografia rápida (script de saúde)

Depois de subir, rode a qualquer momento pra ver como a VPS está indo:

```bash
./scripts/vps-check.sh
```

O script faz um dashboard em <5s cobrindo:

- **Capacidade** — CPU load, RAM (com swap), disco raiz + footprint do Docker.
- **Containers** — estado + health de nginx, api, web, postgres, minio, certbot.
- **Endpoints** — `GET /api/health` no localhost e via `$DOMAIN` público.
- **Backups** — idade e tamanho do último dump do Postgres e do último
  espelho do MinIO. Alarme se > 30h; falha se > 48h.
- **TLS** — dias até expirar o cert (alerta em 14d, falha em 5d).
- **LLM (últimas 24h)** — quantas mensagens caíram no fallback
  "Não consegui interpretar…". Ajuda a pegar regressões cedo.

Saída colorida com `✓ / ! / ✗`, exit code `0`/`1`/`2` (bom pra plugar em
healthchecks.io como check secundário, ou usar num cron semanal).

Thresholds configuráveis via env (ex.: `MEM_WARN_PCT=90 ./scripts/vps-check.sh`).

Sinais que valem upgrade do droplet:
- **CPU load** com WARN sustentado por > 1 semana.
- **Memória RAM** em WARN + swap ativo.
- **Disco** em WARN e crescendo mais que 5% ao mês (fotos acumulando).

Se aparecer, considera pular pro plano $18/mês (2 vCPU / 2 GB) ou
$24/mês (2 vCPU / 4 GB). Resize a quente na DO leva ~5 min.

---

## 20. Debug do primeiro deploy

Se `https://app.seudominio.com` não abrir:

```bash
# 1. Nginx tá up?
docker compose -f docker-compose.production.yml --env-file .env.production ps nginx

# 2. Consegue bater na API interna?
docker compose -f docker-compose.production.yml --env-file .env.production exec nginx \
  wget -qO- http://api:8000/health

# 3. Logs do Nginx (últimas 50 linhas)
docker compose -f docker-compose.production.yml --env-file .env.production logs --tail=50 nginx

# 4. Logs da API
docker compose -f docker-compose.production.yml --env-file .env.production logs --tail=100 api

# 5. Firewall ok?
sudo ufw status
```

Erros comuns:
- **`upstream 'api' not found`**: Docker DNS não subiu ainda. Reinicia
  o Nginx: `docker compose ... restart nginx`.
- **502 Bad Gateway**: API não respondeu no tempo. Ver se `api` está
  `healthy`, e checa logs.
- **Certificado inválido no browser**: você usou staging por acidente.
  Rode o passo 11 de novo sem `--staging`.
- **Cookie não persiste (login não guarda sessão)**: `COOKIE_DOMAIN`
  está errado, ou `COOKIE_SECURE=true` mas você tá em `http://`
  ainda (verifica que abriu com `https`).

---

## 21. Referências

- Runbook geral (não-DO): `docs/deploy.md`.
- Certbot: `infra/certbot/README.md`.
- Compose de produção: `docker-compose.production.yml`.
- Checklist §16 de segurança: `docs/deploy.md` §12.
- Script de saúde: `scripts/vps-check.sh`.
