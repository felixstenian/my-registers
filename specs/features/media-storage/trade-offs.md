# Trade-offs — Storage de mídia

## Decisão 1 — Decode probe via `PIL.Image.verify()` (Const. §22)

### Contexto

Um arquivo renomeado (PDF → .jpg) ou bytes corrompidos teriam MIME correto mas não seriam imagem. Sem probe, chegaria à Anthropic causando erro opaco no processamento.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — `PIL.Image.verify()` + segundo open para size (escolhida) | Prova que bytes são imagem real; captura dimensões | Dois `Image.open` (comportamento de `verify()` consome stream) |
| B — `filetype` library (magic bytes apenas) | Simples | Não prova decodificabilidade completa |
| C — Sem probe (confiar no MIME) | Zero overhead | Falha tardia na Anthropic; difícil debug |

### Decisão tomada

**Opção A.** Const. §22 codifica explicitamente "decode probe".

### Consequências

- **Positivas**: segurança garantida antes do I/O para MinIO.
- **Negativas**: dois `Image.open` por upload (ambos sobre BytesIO em memória — custo negligível para imagens ≤ 8MB).

---

## Decisão 2 — boto3 em `asyncio.to_thread` (não aiobotocore)

### Contexto

FastAPI usa asyncio; boto3 é síncrono e bloquearia o event loop se chamado diretamente.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — `asyncio.to_thread(boto3_call)` (escolhida) | boto3 oficial; bem testado; sem dep extra | Thread pool overhead por request |
| B — `aiobotocore` (async native S3) | Async nativo | Dep extra; menos madura; API diferente de boto3 |
| C — `aiofiles` + boto3 híbrido | — | Não resolve o problema |

### Decisão tomada

**Opção A.** Padrão amplamente usado para I/O síncrono em asyncio. Thread pool do Python é adequado para I/O-bound.

### Consequências

- **Positivas**: sem dep extra; sem risco de incompatibilidade.
- **Negativas**: ~1ms de overhead de thread switching por request. Irrelevante para upload de imagem.

---

## Decisão 3 — Presigned URL gerada por demanda (não armazenada)

### Contexto

Poderíamos armazenar a URL em `media.presigned_url` e regenerar periodicamente.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Gerar por request de `GET /chat/messages` (escolhida) | Sempre fresca; simples | 1 chamada boto3/media por GET |
| B — Armazenar URL com TTL | Menos boto3 calls | URL pode expirar; requer job de renovação |
| C — URL pública permanente | Zero custo de geração | Exposição pública da imagem |

### Decisão tomada

**Opção A.** Fotos são privadas; URL efêmera é a abordagem correta.

### Consequências

- **Positivas**: sem job de renovação; sem URL vazada.
- **Negativas**: N calls boto3 para N medias em 1 GET. Com 4 medias por mensagem e 50 mensagens, são 200 calls. Mitigação: `asyncio.to_thread` paraleliza se necessário.

---

## Decisão 4 — Reescrita de host para `S3_PUBLIC_BASE_URL`

### Contexto

Em produção, MinIO está em Docker network interna. Presigned URL gerada tem `http://minio:9000/...` — inacessível pelo browser.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Trocar scheme+netloc, preservar path+query (escolhida) | Assinatura S3 continua válida (depende de path+query, não host) | Hack sutil; quebra se S3 exigir host na assinatura |
| B — Configurar MinIO com MINIO_DOMAIN público | Elegante; nativo | Requer TLS no MinIO; config de DNS |
| C — Proxy no Nginx que repassa para MinIO interno | URL pública limpa | Proxy adicional; latência |

### Decisão tomada

**Opção A.** MinIO S3v4 assina baseado em path+query, não host. Funciona. ADR não foi escrito mas comportamento foi validado em produção (CHANGELOG v1.0.0).

### Consequências

- **Positivas**: zero config extra de DNS/TLS no MinIO.
- **Negativas**: depende de S3 signature v4 não incluir host no scope. Se Anthropic/AWS mudar comportamento, quebra silenciosamente — teste E2E de URL reescrita é obrigatório.

---

## Decisão 5 — Compressão na camada Anthropic, não no MediaService

### Contexto

Imagens grandes custam tokens. Comprimir no upload economizaria storage e download posterior.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Comprimir só ao enviar para Anthropic (escolhida) | MediaService agnóstico sobre destino; rótulo OCR pode precisar qualidade alta | Download de bytes originais sempre |
| B — Comprimir no upload | Storage e download menores | Perde qualidade original; rótulo OCR pode degradar |
| C — Armazenar ambas (original + comprimida) | Flexibilidade | Complexidade; storage 2x |

### Decisão tomada

**Opção A.** Separação de responsabilidades clara. `AnthropicClient._compress_image` faz Pillow 1024px JPEG q=75 — ver [`anthropic-integration`](../anthropic-integration/).

### Consequências

- **Positivas**: storage preserva original; compressão é para-Anthropic-only.
- **Negativas**: `get_object` sempre baixa original (~8MB worst case) para comprimir na memória. Aceitável — FastAPI processa em thread.

---

## Decisão 6 — MIME allowlist restrita (`jpeg, png, webp`)

### Contexto

Anthropic suporta JPEG, PNG, GIF, WEBP. Poderíamos aceitar GIF.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — `{jpeg, png, webp}` (escolhida) | Simples; GIF animado é edge case | Rejeita GIF que Anthropic aceitaria |
| B — `{jpeg, png, gif, webp}` | Mais compatível | GIF animado pode criar comportamento inesperado na LLM |

### Decisão tomada

**Opção A.** GIF não é caso de uso de foto de prato/rótulo. Pode ser adicionado se surgir demanda.

### Consequências

- **Positivas**: set mínimo e seguro.
- **Negativas**: user com GIF estático recebe 422. Edge case aceito.

---

## Dívida técnica conhecida

| Item | Impacto | Prioridade |
|---|---|---|
| N calls boto3 por message em `GET /chat/messages` (1 por media) | Médio se mensagem tem muitas medias | Média; batch ou cache de URL futuro |
| `asyncio.to_thread` para `get_object` em `MessageProcessor` — não paralelizado | Médio (fotos sequenciais) | Média; `asyncio.gather` para múltiplas mídias |
| Sem GC de objetos orphaned no MinIO (upload OK, DB falhou) | Baixo (raro) | Baixa; cron de reconciliação futuro |
| Presigned URL TTL hardcoded (3600s) — não configurável | Baixo | Baixa |
| Sem backup de MinIO integrado no CI | Médio (ops) | Média; `scripts/backup-minio.sh` existe mas não automatizado em Fase 10 |
| `status='failed'` nunca setado hoje (transação desfaz tudo) | Baixo | Baixa; preparatório para retry futuro |

## Riscos identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| MinIO indisponível durante upload | Baixa (single-VPS) | Alto (upload falha) | Retry no cliente; healthcheck do MinIO no CI |
| Reescrita de host quebra assinatura S3 em versão futura do MinIO | Baixa | Alto (URLs inacessíveis) | Teste E2E de URL em staging antes de release |
| Pillow `verify()` rejeita WEBP animado válido | Média | Baixo (usuário recebe 422) | Testar com WEBP animado; adicionar tratamento se necessário |
| Decode probe lento para imagem grande (8MB) | Baixa (síncrono em request thread) | Baixo (~50ms) | Aceitável; alternativa: `to_thread` para probe também |
| Objetos orphaned no MinIO (upload OK, Postgres falhou) | Baixa | Baixo (storage waste) | Cron de reconciliação no futuro |

## Alternativas para pós-MVP

- **`asyncio.gather` para múltiplas presigned URLs** em `GET /chat/messages` — paralelizar N calls.
- **Cache de presigned URL por 55min** — evitar N calls; invalidar ao `DELETE /media` (se existir).
- **GIF na allowlist** — se surgir caso de uso real.
- **Cron de GC** de objetos orphaned no MinIO.
- **Compressão no upload** opcional (accept quality=high vs. quality=fast) para salvar storage.
- **Streaming upload** para arquivos grandes — hoje carrega tudo em memória (`file.read()`).
- **CDN na frente do MinIO** — para distribuir fotos sem carga no MinIO.
