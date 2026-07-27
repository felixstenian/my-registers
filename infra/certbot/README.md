# Certbot — emissão inicial e renovação

Const. §14 / app_plan §14.6. Runbook do TLS na VPS.

## Pré-requisitos

- DNS `A/AAAA` de `${DOMAIN}` apontando pra VPS já resolvendo.
- Porta 80 e 443 abertas no firewall (`ufw allow 80 && ufw allow 443`).
- `.env.production` já preenchido com `DOMAIN=` e `LETSENCRYPT_EMAIL=`.

## Emissão pela 1ª vez (staging → prod)

O Nginx precisa estar servindo `/.well-known/acme-challenge/` na porta 80
**antes** do certbot. Como o `conf.d/app.conf` referencia
`/etc/letsencrypt/live/${DOMAIN}/fullchain.pem` (que ainda não existe),
o container quebra. Solução: subir num modo temporário só com o Nginx +
uma config mínima HTTP.

> ⚠️ **Armadilha do entrypoint em daemon-mode.**
>
> O serviço `certbot` do compose declara um `entrypoint` custom que roda
> um loop `while :; do certbot renew; sleep 12h; done` — perfeito pra
> renovação automática, mas **ignora silenciosamente qualquer comando
> que você passar via `run`**. Sem `--entrypoint certbot`, o comando
> `certonly` da primeira emissão é descartado e o container só executa
> o loop de renovação (que não faz nada porque não tem cert ainda).
>
> **Solução:** passe `--entrypoint certbot` em toda invocação `run`,
> como nos comandos abaixo. Isso substitui o entrypoint só naquela
> execução; o daemon continua funcionando pro renew automático.

Passo a passo (uma vez só na vida da VPS):

```bash
# 1. Ir para o repositório
cd ~/my-registers

# 2. Substituir a config real por uma placeholder HTTP-only
cp infra/nginx/conf.d/app.conf infra/nginx/conf.d/app.conf.bak
cat > infra/nginx/conf.d/app.conf <<'EOF'
server {
  listen 80;
  server_name ${DOMAIN};
  location /.well-known/acme-challenge/ { root /var/www/certbot; }
  location / { return 200 "ok"; }
}
EOF

# 3. Substituir ${DOMAIN} manualmente (o nginx não expande env vars
#    fora da diretiva `set`; use `envsubst` ou o sed abaixo):
sed -i "s|\${DOMAIN}|$DOMAIN|g" infra/nginx/conf.d/app.conf

# 4. Subir SÓ o nginx e o volume compartilhado
docker compose -f docker-compose.production.yml --env-file .env.production \
  up -d nginx

# 5. Testar (staging Let's Encrypt primeiro — não bate rate limit)
docker compose -f docker-compose.production.yml --env-file .env.production run --rm \
  --entrypoint certbot certbot \
  certonly --webroot -w /var/www/certbot \
  --staging --agree-tos --no-eff-email \
  -m "$LETSENCRYPT_EMAIL" -d "$DOMAIN"

# Se voltou "Successfully received certificate" na staging, apaga
# o cert de teste e emite o REAL (sem --staging):
docker compose -f docker-compose.production.yml --env-file .env.production run --rm \
  --entrypoint certbot certbot \
  delete --cert-name "$DOMAIN"

docker compose -f docker-compose.production.yml --env-file .env.production run --rm \
  --entrypoint certbot certbot \
  certonly --webroot -w /var/www/certbot \
  --agree-tos --no-eff-email \
  -m "$LETSENCRYPT_EMAIL" -d "$DOMAIN"

# 6. Restaurar a config real (com HTTPS)
mv infra/nginx/conf.d/app.conf.bak infra/nginx/conf.d/app.conf
sed -i "s|\${DOMAIN}|$DOMAIN|g" infra/nginx/conf.d/app.conf

# 7. Recarregar
docker compose -f docker-compose.production.yml --env-file .env.production restart nginx
```

## Renovação

O container `certbot` do compose loopa `certbot renew --webroot` a cada
12h. Como Let's Encrypt emite certs válidos por 90 dias e o Certbot só
renova quando restam < 30, na prática renova ~ a cada 60 dias.

Para checar manualmente:

```bash
docker compose -f docker-compose.production.yml --env-file .env.production \
  exec certbot certbot certificates
```

Para forçar renovação (ex.: rotação de chave) — atenção ao
`--entrypoint certbot` explicando acima:

```bash
docker compose -f docker-compose.production.yml --env-file .env.production run --rm \
  --entrypoint certbot certbot \
  renew --force-renewal --webroot -w /var/www/certbot
docker compose -f docker-compose.production.yml --env-file .env.production restart nginx
```

## Debug comum

- **Certbot "silencioso" — container só imprime `Created` e sai sem output.**
  Você esqueceu de `--entrypoint certbot` no `run`. O entrypoint daemon
  descartou seu `certonly` e rodou o loop de renew. Ver aviso acima.
- **`Connection refused`** no acme-challenge → nginx caiu ou porta 80
  não está aberta no firewall.
- **`too many failed authorizations`** → você bateu rate limit no
  staging. Espere 1h ou use `--dry-run`.
- **`unauthorized`** → DNS não propagou ainda. `dig +short A $DOMAIN`
  deve retornar o IP da VPS.
- **`cannot load certificate ... No such file or directory`** no nginx
  após restaurar a config real → o cert real não foi emitido (só o
  staging), ou o staging foi mantido e não deletado antes do prod.
  Confira com `openssl s_client -connect $DOMAIN:443 -servername $DOMAIN
  </dev/null 2>/dev/null | openssl x509 -noout -issuer` — se aparecer
  "Fake LE" no issuer, reemita o real (delete staging + certonly sem
  `--staging`).
