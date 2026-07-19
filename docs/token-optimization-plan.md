# Plano de redução de tokens

Documento vivo. Serve como norte para tarefas de otimização de custo Anthropic
nas Fases 6+; deve ser revisado depois que qualquer item Tier 1 for implementado
(as estimativas mudam quando a linha de base muda).

## Snapshot do consumo atual

Cada `POST /chat/messages` dispara **1 call** para `messages.create` (mais até
2 semantic retries em `ValidationError`). O prompt inclui:

- **System prompt** (`system_v2.md`) — ~2.5 KB, marcado `cache_control: ephemeral`.
- **Tool schema** (`record_intent`) — ~2.5 KB, marcado `cache_control: ephemeral`.
- **User content** — texto (dezenas de tokens) + **até 4 imagens em base64** —
  cada imagem de 4-8 MB vira ~5-11K tokens *pra Anthropic contar* (a SDK cobra
  por dimensão da imagem, não por bytes de base64; ainda assim é o driver
  dominante).
- **Assistant tool_use response** — ~300-800 tokens output.

Ordem de magnitude típica por mensagem:

| Tipo | Input tokens | Output tokens |
|---|---|---|
| Texto puro | ~5K (só cache) | ~200-500 |
| Texto + 1 foto | ~6-10K | ~300-800 |
| Texto + 4 fotos | ~15-40K | ~500-1000 |
| Retry semântico | +tudo acima × N | idem |

Onde o cache **funciona**: system + tool schema (~5K tokens) ficam em cache
ephemeral (5 min TTL), reduzindo custo em ~90% desse pedaço nas mensagens
seguidas. Onde **não funciona**: imagens (não são cacheáveis) e texto novo
do usuário.

## Tier 1 — Fazer nas próximas fases (alto impacto, baixo esforço)

### 1. Confirmar que o prompt caching está *realmente* dando cache hit

Adicionar log estruturado do `response.usage` incluindo
`cache_creation_input_tokens` e `cache_read_input_tokens` (a SDK expõe).
Métrica: **cache hit rate diário deve ficar > 80%**. Se estiver baixo, o
`cache_control` pode estar no bloco errado ou o payload mudou entre turnos
(whitespace, ordem de chaves no tool schema).

**Onde tocar:** `AnthropicClient.call_record_intent` — logar `usage` no INFO
depois de cada call, com `event="anthropic_usage"` e campos separados.

### 2. Compressão de imagem server-side antes do base64

Hoje o `MessageProcessor._load_media` puxa os bytes crus do MinIO e passa
direto. Reencodar com **Pillow** para JPEG qualidade 75 + longest-side 1024px
reduz o tamanho da imagem em 5-15× sem perda perceptível para reconhecimento
de comida/rótulo. Um único hook em `AnthropicClient._build_user_content` ou
já no `_load_media`.

**Ganho:** ~70-90% menos tokens em mensagens com foto.

**Onde tocar:** `AnthropicClient._build_user_content` — para cada imagem,
`Image.open(BytesIO(data))` → `.thumbnail((1024, 1024))` → `.save(buf, "JPEG",
quality=75)` → base64 do buf. Preservar `image/jpeg` como `media_type`.

### 3. Roteamento por complexidade: Haiku vs Sonnet

`settings.anthropic_fallback_model` já existe (`claude-haiku-4-5`). Regra
simples: **texto puro → Haiku**, **qualquer imagem → Sonnet**. Haiku custa
~4× menos por token e é suficiente para classificar `log_water/log_beverage/
set_profile/log_food` sem foto.

**Onde tocar:** `AnthropicClient.call_record_intent` — heurística que troca
`model` antes do call se `not images and len(user_text or "") < 500`. Log
qual modelo foi usado em cada request para poder medir depois.

### 4. Reduzir semantic retries de 2 → 1

Hoje: 1 chamada inicial + até 2 retries de validação = 3 chamadas no pior
caso. Com o prompt reforçado nas Fases 3-5 e o schema estrito, o segundo
retry raramente adiciona valor. Passar para **1 retry** economiza 33% no
pior caso.

**Onde tocar:** default `max_semantic_retries=1` em
`AnthropicClient.call_record_intent`. Se `validation_exhausted` aumentar em
logs após rollout, revertemos.

## Tier 2 — Nas próximas fases (médio impacto, esforço médio)

### 5. Enxugar o system prompt

O `system_v2.md` tem 18 regras (~2.5 KB). Provavelmente 30% é redundância ou
reforço supérfluo agora que temos:

- Aliases pt-BR de `activity_type` no backend (regra 6a fica menor).
- `set_profile` e `kcal_burned_reported` bem descritos no JSON schema.
- Prompt caching cobre o custo do prompt em ~90% das mensagens.

Meta: chegar em **1.5 KB** eliminando duplicação. Ganho pequeno em bytes,
mas ainda vale para o *primeiro* miss do cache do dia.

### 6. Dedupe por hash de conteúdo

Se o usuário reenviar exatamente a mesma mensagem (texto + mesma `media_id`),
a mesma resposta já está persistida em `messages.raw_llm_response`. Um
lookup em `messages` no `MessageProcessor.process` antes do call — se
identidade bater dentro de N minutos, reaproveita. Custo: ~zero em código;
ganho: casos de duplo-clique, refresh acidental, retry manual do usuário.

**Onde tocar:** `MessageProcessor.process` — SHA-256 sobre `(user_id, text,
sorted(media_ids))` → check em `messages.raw_llm_response` cujo hash bata e
`created_at > now() - interval '5 minutes'`.

### 7. Log persistente de tokens por request

`Message.tokens_input`/`tokens_output` já existe. Falta uma view/report:

```sql
SELECT
    date_trunc('day', created_at) AS day,
    llm_model,
    llm_intent,
    count(*) AS n_messages,
    sum(tokens_input) AS in_total,
    sum(tokens_output) AS out_total,
    avg(tokens_input) AS in_avg
FROM messages
WHERE role = 'assistant' AND llm_model IS NOT NULL
GROUP BY 1, 2, 3
ORDER BY 1 DESC;
```

Se o custo mensal virar previsível, dá pra tomar decisão sobre Tier 3.

## Tier 3 — Depois do MVP (alto retorno, exige mais código)

### 8. Fast-path local para padrões simples (bypass LLM)

Casos que não precisam de LLM porque a mensagem é 100% estruturada:

- `"peso 65 kg"` / `"peso: 65"` → `set_profile` direto.
- `"500 ml de água"` / `"250ml agua"` → `log_water` direto.
- `"corri 40 min moderado"` (sem foto) → `log_activity` com
  `activity_type=cardio_run`.

Um `LocalIntentClassifier` com regex + normalize testa em `< 1ms`. Se match
com alta confiança, pula a chamada Anthropic completamente e economiza ~5-10K
tokens por mensagem. Se não bate, fluxo atual segue.

**Ganho estimado: 30-50% das mensagens não chegam na LLM.**

Complexidade: manter os regex sincronizados com o prompt vira dívida. Só
depois que a distribuição de intents estabilizar (Tier 2.7 traz esse dado).

### 9. Batch classification para histórico

Se implementar `query_day`/`weekly_summary` (Fases 7/8), evitar mandar o dia
inteiro pro LLM. Em vez disso, calcular totais no backend (que é o que já
fazemos por INV-1) e mandar só o resumo compacto para a LLM gerar narrativa
— não a lista bruta.

## Métricas para acompanhar

Colocar num painel simples (Grafana no futuro ou SQL manual por ora):

1. **Cache hit rate** (`cache_read / (cache_read + cache_creation)` diário).
2. **Tokens/mensagem** — média, p50, p95, p99, por `llm_intent` e `llm_model`.
3. **% de mensagens com retry semântico** — indicador da qualidade do prompt.
4. **Distribuição por modelo** — Sonnet vs Haiku após o roteamento do Tier 1.3.
5. **Custo estimado por dia** — usar preços da tabela oficial da Anthropic;
   um cronjob que consolida `messages` do dia.

## Estimativa de ganho combinado

Uma mensagem média (texto + 1 foto) hoje: ~7-8K input, ~500 output tokens.

- Tier 1.2 (compressão imagem): −60% no input de foto → ~3-4K input.
- Tier 1.3 (Haiku para texto puro): −75% de custo em ~30-40% das mensagens.
- Tier 1.4 (1 retry): −33% no pior caso, ~5% na média (retries são raros).
- Tier 3.8 (fast-path local): elimina ~30-50% das chamadas.

**Combinado, dá para chegar em ~50-70% de redução de custo mensal** sem
regressão de qualidade — o driver principal sempre é imagem, e o Tier 1.2
sozinho já resolve muito.

## Ordem de execução sugerida

1. **Antes de qualquer otimização**: Tier 1.1 (medir cache hit rate) + Tier
   2.7 (query SQL diária). Sem baseline, otimizar é chute.
2. **Semana 1**: Tier 1.2 (compressão imagem). Alto ROI, código isolado.
3. **Semana 2**: Tier 1.3 (roteamento por modelo) + Tier 1.4 (menos retries).
4. **Depois do MVP**: Tier 2.5 e 2.6, e só então Tier 3 se o custo ainda
   estiver alto.

## Histórico

- **2026-07-18** — v1.0. Plano inicial após Fases 3-5 concluídas.
