# Fix — MinIO `NoSuchBucket` em prod (upload de imagem retorna 500)

**Sintoma:** `POST /api/media` retorna `500 Internal Server Error` em produção. Frontend mostra erro genérico ao anexar imagem no chat.

**Causa raiz:** o bucket `registers-media` **nunca foi criado** em produção. O `docker-compose.production.yml` sobe o MinIO daemon, mas — diferente do `docker-compose.local.yml` — não tem serviço `minio-init` que roda `mc mb registers-media` no boot. Quando `MediaService.upload` chama `put_object`, o MinIO responde `NoSuchBucket`; boto3 propaga a exception e a API converte em 500.

Mesma classe de bug do seed TBCA vazio: bootstrap idempotente não coberto em prod.

---

## 1. Diagnóstico (confirma antes de agir)

Na VPS:

```bash
cd ~/my-registers

# 1a. Logs recentes da API — procura NoSuchBucket ou traceback do boto3
docker compose -f docker-compose.production.yml --env-file .env.production \
  logs --tail=100 api | grep -iE "traceback|nosuchbucket|error" | head -20

# 1b. Lista buckets do MinIO. Extrai só as 2 vars que precisamos
#     (evita o bug do `source .env.production` quando alguma senha tem `!`
#     — o bash trata `!` como history expansion e falha).
export MINIO_ROOT_USER=$(grep '^MINIO_ROOT_USER=' .env.production | cut -d= -f2-)
export MINIO_ROOT_PASSWORD=$(grep '^MINIO_ROOT_PASSWORD=' .env.production | cut -d= -f2-)

docker compose -f docker-compose.production.yml --env-file .env.production \
  exec -T minio sh -c "
    mc alias set local http://localhost:9000 '$MINIO_ROOT_USER' '$MINIO_ROOT_PASSWORD' &&
    mc ls local/
  "
```

**Alternativa: carregar `.env.production` inteiro sem quebrar em `!`:**

```bash
# `+H` desliga history expansion antes do source.
set +H && set -a && source .env.production && set +a
```

**Interpretação:**

- Se **1a mostra `NoSuchBucket`** e **1b não lista `registers-media`** → bucket não existe. Segue §2.
- Se **1b já lista `registers-media/`** (mesmo com `0B` — bucket vazio é normal, ninguém subiu foto ainda) → bucket existe. Bug é outro. **Segue direto pra §5.**
- Se **1a não mostra nada relevante** → provoca upload de novo (anexa foto no chat + envia) e roda 1a de novo com `logs -f`.

---

## 2. Fix imediato — criar bucket via `mc` (1 min, sem restart)

Ainda na VPS, com `.env.production` já carregado no shell (do passo 1b):

```bash
docker compose -f docker-compose.production.yml --env-file .env.production \
  exec -T minio sh -c "
    mc alias set local http://localhost:9000 '$MINIO_ROOT_USER' '$MINIO_ROOT_PASSWORD' &&
    mc mb -p local/registers-media &&
    mc anonymous set none local/registers-media &&
    mc ls local/
  "
```

**Esperado:**
```
Bucket created successfully `local/registers-media`.
Access permission for `local/registers-media` is set to `none`
[YYYY-MM-DD HH:MM:SS UTC] registers-media/
```

Notas:
- `mc mb -p` é idempotente com o `-p` (`--path-create`), mas o `mc mb` sem `-p` também não falha se o bucket já existir. Se preferir explícito: `(mc mb -p local/registers-media || true)`.
- `mc anonymous set none` garante que o bucket **não** seja público (só acessa quem tem credenciais). Nossa app usa presigned URLs; nunca queremos leitura anônima.

Após o `mc mb`, o upload volta a funcionar **sem restart de container** — a próxima chamada `put_object` acha o bucket.

---

## 3. Smoke test (30s)

No browser em produção:

1. Login → chat.
2. Anexa uma foto qualquer no compositor.
3. Envia.

**Esperado:** upload passa (sem erro no console/toast), mensagem aparece no histórico com a foto renderizada via URL assinada.

Se ainda falhar, cheque logs em tempo real enquanto tenta de novo:

```bash
docker compose -f docker-compose.production.yml --env-file .env.production \
  logs -f --tail=20 api
```

---

## 4. Fix estrutural (próximo PR)

O `mc mb` manual resolve **este deploy**, mas o problema volta em qualquer VPS nova. Fix definitivo é adicionar serviço `minio-init` em `docker-compose.production.yml` copiando o padrão do local:

```yaml
minio-init:
  image: minio/mc:latest
  depends_on:
    minio:
      condition: service_healthy
  entrypoint: >
    /bin/sh -c "
    mc alias set local http://minio:9000 $$MINIO_ROOT_USER $$MINIO_ROOT_PASSWORD &&
    (mc mb -p local/registers-media || true) &&
    mc anonymous set none local/registers-media
    "
  environment:
    MINIO_ROOT_USER: ${MINIO_ROOT_USER}
    MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
  networks: [internal]
  restart: "no"
```

Roda uma vez ao subir; idempotente. Análogo ao que `scripts/bootstrap.sh` faz para migrations + admin + seed TBCA.

Quando abrir esse PR, aproveitar pra:
- Confirmar que o restart do stack em prod já com o bucket existente NÃO causa problema (deve passar direto).
- Mencionar no CHANGELOG como "infra: bucket MinIO criado automaticamente no boot".

---

## 5. Se `mc ls` já listava `registers-media/` (bug diferente)

Se a lista mostra o bucket (mesmo com `0B` — bucket vazio é normal, ninguém enviou foto ainda em prod), a causa é outra. Investigue **na ordem** abaixo — a primeira que falhar é a raiz.

### 5.1 Log real da API

Antes de qualquer hipótese, provoca o erro de novo e captura a exception exata:

```bash
# Terminal 1: log em tempo real
docker compose -f docker-compose.production.yml --env-file .env.production \
  logs -f --tail=20 api

# Terminal 2 (ou browser): tenta o upload de novo — anexa foto no chat, envia.
```

Procure no terminal 1 a linha com `botocore.exceptions.ClientError` ou similar. Padrões esperados:

| Erro no log | Causa | Ver seção |
|--|--|--|
| `An error occurred (InvalidAccessKeyId)` | `S3_ACCESS_KEY` não bate com `MINIO_ROOT_USER` | §5.2 |
| `An error occurred (SignatureDoesNotMatch)` | `S3_SECRET_KEY` não bate com `MINIO_ROOT_PASSWORD` | §5.2 |
| `An error occurred (AccessDenied)` | User autenticou mas não tem permissão | §5.2 |
| `An error occurred (NoSuchBucket)` | Bucket sumiu entre 1b e o upload (raro) | §2 |
| `Could not connect to the endpoint URL` / timeout | `S3_ENDPOINT` errado | §5.3 |
| `413 Request Entity Too Large` (nginx, não API) | `client_max_body_size` no nginx | §5.4 |

### 5.2 Credenciais MinIO divergem entre app e daemon

O app autentica com `S3_ACCESS_KEY`/`S3_SECRET_KEY`; o MinIO daemon é iniciado com `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD`. Em produção, como não criamos users secundários no MinIO, os dois pares **precisam ser idênticos**.

```bash
grep -E "^(S3_ACCESS_KEY|S3_SECRET_KEY|MINIO_ROOT_USER|MINIO_ROOT_PASSWORD)=" .env.production
```

Regras:
- `S3_ACCESS_KEY == MINIO_ROOT_USER`
- `S3_SECRET_KEY == MINIO_ROOT_PASSWORD`

Se alguma diferir, fix idempotente via `sed` (não depende de `source`, então imune ao problema do `!`):

```bash
# Backup rápido
cp .env.production .env.production.bak

# Copia ROOT_* → S3_*
sed -i "s|^S3_ACCESS_KEY=.*|S3_ACCESS_KEY=$(grep '^MINIO_ROOT_USER=' .env.production | cut -d= -f2-)|" .env.production
sed -i "s|^S3_SECRET_KEY=.*|S3_SECRET_KEY=$(grep '^MINIO_ROOT_PASSWORD=' .env.production | cut -d= -f2-)|" .env.production

# Confere
grep -E "^(S3_ACCESS_KEY|S3_SECRET_KEY|MINIO_ROOT_USER|MINIO_ROOT_PASSWORD)=" .env.production
```

**Recria só o container API pra pegar o env novo:**

```bash
docker compose -f docker-compose.production.yml --env-file .env.production \
  up -d --force-recreate api
```

Aguarda ~30s (healthcheck da API tem `interval: 15s + retries: 6`) e testa o upload de novo.

> **Nota sobre senha do MinIO com caracteres especiais.** MinIO aceita `!`, `@`, `#` etc., mas **evita** usar `%` (URL-encoding em alguns SDKs) e `+`/`/` em base64. Se estiver gerando senha nova, usa só `[A-Za-z0-9]`: `openssl rand -base64 24 | tr -d '/+=' | head -c 24`.

### 5.3 Endpoint errado

`S3_ENDPOINT` no `.env.production` **precisa** ser `http://minio:9000` (nome do service do compose). Nunca `localhost` — a API está em outro container.

```bash
grep '^S3_ENDPOINT=' .env.production
```

Esperado: `S3_ENDPOINT=http://minio:9000`. Se estiver `localhost` ou o IP do host, corrige:

```bash
sed -i 's|^S3_ENDPOINT=.*|S3_ENDPOINT=http://minio:9000|' .env.production
docker compose -f docker-compose.production.yml --env-file .env.production \
  up -d --force-recreate api
```

### 5.4 Nginx com `client_max_body_size` pequeno

Nesse caso o status **não é 500 da API** — é `413 Request Entity Too Large` **do nginx** (antes da request sequer chegar na API). Se você viu 413 em vez de 500, edita `infra/nginx/conf.d/app.conf` e garante que o bloco `server` de HTTPS tem:

```nginx
server {
  listen 443 ssl;
  # ...
  client_max_body_size 15m;   # 4 fotos × 8 MB + margem
  # ...
}
```

Reload sem downtime:

```bash
docker compose -f docker-compose.production.yml --env-file .env.production \
  exec nginx nginx -s reload
```

---

## Apêndice — carregar `.env.production` no shell da VPS

O `source .env.production` do bash falha se **qualquer valor** contém `!` seguido de espaço/caractere identificador — bash interpreta como history expansion. Sintoma típico:

```
5pPH38!: command not found
```

Duas soluções:

**A. Desabilita history expansion antes:**

```bash
set +H && set -a && source .env.production && set +a
```

**B. Extrai só as vars que você precisa (mais seguro):**

```bash
export MINIO_ROOT_USER=$(grep '^MINIO_ROOT_USER=' .env.production | cut -d= -f2-)
export MINIO_ROOT_PASSWORD=$(grep '^MINIO_ROOT_PASSWORD=' .env.production | cut -d= -f2-)
```

Nunca use `cat .env.production | while read line; do export "$line"; done` — quebra em qualquer valor com espaço, `=` embutido, quotes, etc.
