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
  certbot certonly --webroot -w /var/www/certbot \
  --staging --agree-tos --no-eff-email \
  -m "$LETSENCRYPT_EMAIL" -d "$DOMAIN"

# Se voltou "Successfully received certificate" na staging, rode a prod:
docker compose -f docker-compose.production.yml --env-file .env.production run --rm \
  certbot certonly --webroot -w /var/www/certbot \
  --force-renewal --agree-tos --no-eff-email \
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

Para forçar renovação (ex.: rotação de chave):

```bash
docker compose -f docker-compose.production.yml --env-file .env.production run --rm \
  certbot renew --force-renewal --webroot -w /var/www/certbot
docker compose -f docker-compose.production.yml --env-file .env.production restart nginx
```

## Debug comum

- **`Connection refused`** no acme-challenge → nginx caiu ou porta 80
  não está aberta no firewall.
- **`too many failed authorizations`** → você bateu rate limit no
  staging. Espere 1h ou use `--dry-run`.
- **`unauthorized`** → DNS não propagou ainda. `dig +short A $DOMAIN`
  deve retornar o IP da VPS.
