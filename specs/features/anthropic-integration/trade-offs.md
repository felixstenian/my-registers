# Trade-offs — Integração Anthropic

## Decisão 1 — LLM só via `tool_use` forçado (INV-9, Const. §7)

### Contexto

Alternativa comum: pedir "responda em JSON" no prompt e parsear. Anthropic suporta múltiplos formatos: texto livre, JSON structured output, tool_use.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — `tool_use` forçado (`tool_choice={type:tool, name:record_intent}`) (escolhida) | Schema declarativo; SDK valida estrutura; API garante bloco tool_use presente | 1 chamada devolve N blocos (assistant pode misturar text + tool_use) |
| B — Structured output (JSON schema) | Um único formato | Menos batalha-testado; SDK menos maduro |
| C — Texto livre + parsing | Zero coupling | Regex frágil; hallucination de JSON incorreto; sem validação |

### Decisão tomada

**Opção A.** Const. §7 codifica como regra: "texto livre da LLM (fora de tool_use.input) é descartado".

### Consequências

- **Positivas**: contract limpo; testabilidade alta (fake devolve tool_use estruturado); INV-9 audita.
- **Negativas**: mais tokens (tool schema é enviado em cada request; mitigado por cache ephemeral).

---

## Decisão 2 — Retry semântico limitado a 1

### Contexto

Se `LLMEnvelope.model_validate` falha (LLM emitiu `confidence=1.5` ou intent inválido), podemos: (a) desistir, (b) tentar N vezes, (c) tentar 1 vez com feedback.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — 1 retry (default) (escolhida) | 2 chamadas no pior caso; latência limitada | Alguns erros ficam sem correção |
| B — 2 retries (padrão anterior) | Chance maior de sucesso | Fase 5 mostrou ganho marginal; latência dobra |
| C — 0 retries | Latência mínima | Perde correções triviais que 1 retry resolveria |

### Decisão tomada

**Opção A.** Comment do código: "Fase 5 mostrou que o segundo retry raramente resolve".

### Consequências

- **Positivas**: latência P99 ≤ 20s cumprida; UX previsível.
- **Negativas**: alguns envelopes ficariam válidos com 2 retries; aceito — usuário reformula.

---

## Decisão 3 — `_clean_content_for_retry` remove metadata do SDK

### Contexto

Bug histórico: SDK Anthropic anexa `caller` em blocos `tool_use` da resposta. Se enviarmos essa resposta de volta como `assistant` no retry, Haiku 4.5 retorna HTTP 400 ("unexpected field 'caller'"). Bug documentado no CHANGELOG (`c4fa31e`).

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Função dedicada que copia só campos permitidos (escolhida) | Correção cirúrgica | Precisa manter lista de campos válidos |
| B — Modificar SDK / reportar bug | "Correto" | Depende de release; nossa dependência de SDK atualizada |
| C — Ignorar (deixar SDK fazer round-trip) | Simples | Reproduce bug |

### Decisão tomada

**Opção A.** Função `_clean_content_for_retry` copia apenas `{type, id, name, input}` para `tool_use` e `{type, text}` para `text`.

### Consequências

- **Positivas**: bug resolvido.
- **Negativas**: se SDK mudar formato dos blocos (Anthropic adiciona campo novo em `tool_use.input`), precisamos atualizar função.

---

## Decisão 4 — Roteamento Sonnet vs Haiku por heurística simples

### Contexto

Chamadas de intent podem custar 5-11K input tokens com foto vs. ~1K sem. Haiku é ~4× mais barato mas menos preciso.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Foto→Sonnet; texto curto→Haiku; texto longo→Sonnet (escolhida) | Simplíssimo; heurística grosseira mas efetiva | Threshold arbitrário (500 chars) |
| B — Sempre Sonnet | Melhor qualidade | Custo 4× maior |
| C — Sempre Haiku | Barato | Visão do Haiku ainda não madura para OCR de rótulo (SP-30) |
| D — Roteamento adaptativo (ML) | Otimizado | Overkill para MVP single-user |

### Decisão tomada

**Opção A.** Ligado como "Tier 1.3" do plano de otimização.

### Consequências

- **Positivas**: ~40% dos calls sem foto viram Haiku → economia significativa.
- **Negativas**: se prompt mudar e Haiku começar a falhar mais em texto simples, aumenta rate de retry.

---

## Decisão 5 — Cache ephemeral do Anthropic

### Contexto

Cada chamada carrega o system prompt (~500 tokens) e o tool schema (~800 tokens). Cache reduz esses ao mínimo (~100 tokens) em chamadas subsequentes.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Cache em `system` + `tools` (escolhida) | Ativos automaticamente; TTL ~5 min | Depende da Anthropic manter feature |
| B — Sem cache | Simples | Custo alto em sessões longas |
| C — Cache também em conversation (histórico) | Máximo hit rate | Complexidade em invalidação; conversa nossa é curta |

### Decisão tomada

**Opção A.** `cache_control={"type": "ephemeral"}` em system + tool schema.

### Consequências

- **Positivas**: usuário mandando 5 mensagens em 5 min → 4 delas viram cache hit no system.
- **Negativas**: se Anthropic depreciar cache ephemeral, precisamos revisitar.

---

## Decisão 6 — Compressão de imagem via Pillow (best-effort)

### Contexto

Fotos grandes (rótulo com resolução alta) custam 5-11K input tokens. Compressão reduz para 500-1500.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Pillow local + fallback bytes originais (escolhida) | Economiza tokens; falha graciosa | Perda de qualidade em OCR de rótulo pequeno |
| B — Enviar sempre original | Melhor qualidade | Custo alto; latência de upload maior |
| C — Serviço externo (Cloudinary) | Otimizado | Dependência extra |

### Decisão tomada

**Opção A.** 1024px + JPEG q=75. Se Pillow falhar (imagem exótica), envia original.

### Consequências

- **Positivas**: 5-15× redução de tamanho; OCR ainda funciona (SP-30..35 aceita).
- **Negativas**: rótulos de fonte pequena podem ficar borrados. Aceito — usuário reenvia se necessário.

---

## Decisão 7 — Prompts como arquivos em disco versionados

### Contexto

Onde manter os prompts do system role?

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — `prompts/*.md` versionados (escolhida) | Diff no git; testes reusam; sem hardcode | Precisa de bootstrap de path; `@lru_cache` |
| B — Constantes Python | Simples | Diff em Python é ruim para prompts longos |
| C — DB (`llm_prompts` table) | Rotável em runtime | Overkill; migration complica |

### Decisão tomada

**Opção A.** Arquivos em `apps/api/app/integrations/anthropic/prompts/`.

### Consequências

- **Positivas**: mudança de prompt é PR isolado; `PROMPT_VERSION` codifica versão.
- **Negativas**: rotação em runtime exige restart do processo (aceito — MVP não precisa).

---

## Decisão 8 — Sem streaming (SP-10)

### Contexto

Anthropic suporta `stream=True` (SSE) — assistant text é enviada em chunks conforme LLM gera.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Sem streaming; polling (escolhida) | Simples; funciona com Nginx padrão | Latência percebida = total |
| B — Streaming SSE | UX melhor (usuário vê palavras aparecendo) | Nginx buffering; workaround complexo; MVP não precisa |

### Decisão tomada

**Opção A.** SP-10 explicitamente pede polling; SSE é "fora do escopo do MVP".

### Consequências

- **Positivas**: infraestrutura simples.
- **Negativas**: usuário vê "processando..." por 6s+ — UX aceito no MVP.

---

## Decisão 9 — Result object nunca levanta para o caller

### Contexto

Erros de rede, timeout, validation. Poderíamos deixar exception propagar.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Result com `error: str \| None` (escolhida) | Caller sempre sabe o que fazer; sem try/except spread | Precisa checar `error` explicitamente |
| B — Exception por erro | Idiomatic | Caller precisa try/except em cada uso |

### Decisão tomada

**Opção A.** `LLMCallResult(error='anthropic_timeout')` etc.

### Consequências

- **Positivas**: `MessageProcessor` código linear; se `result.error is not None` → fallback SP-14.
- **Negativas**: developer pode esquecer de checar `error`; testes forçam coverage.

---

## Dívida técnica conhecida

| Item | Impacto | Prioridade |
|---|---|---|
| Threshold 500 chars é arbitrário; nunca calibrado | Baixo | Baixa |
| `raw_llm_response` gravado em `messages`, sem rotação | Baixo (single-user) | Baixa |
| Sem métricas de rate de erro por tipo (`no_tool_use`, `validation_exhausted`) — só logs | Médio | Média (adicionar prometheus counters em observabilidade v2) |
| Sem A/B de prompts (`system_v2` vs `system_v3`) — só troca via env | Baixo (MVP) | Baixa |
| Timeouts hardcoded (60s SDK, sem override por config) | Baixo | Baixa |
| `_clean_content_for_retry` acopla à shape do SDK — mudança quebra silenciosamente | Alto | Média; teste de regressão obrigatório |
| Retry semântico só cobre `ValidationError`; `no_tool_use` não retenta | Baixo | Baixa; comportamento aceito |

## Riscos identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| Anthropic depreca cache ephemeral | Baixa | Médio (custo sobe) | Aceito; migração para próximo produto de cache |
| Sonnet 4.7 muda calibração de `confidence` (threshold 0.5 vira "quase tudo needs_confirmation") | Média | Médio (UX degrada) | Monitorar; recalibrar `LOW_CONFIDENCE_THRESHOLD` em [`food-logging`](../food-logging/) |
| Novo modelo rejeita tool_use em novos payloads | Baixa | Alto (feature quebra) | Testes de regressão com fixtures; cache TTL curto dá tempo de detectar |
| API key vaza (git, log, resposta HTTP) | Baixa (`.gitignore` cobre) | Crítico | Rotacionar imediatamente; grep pré-commit |
| Modelo devolve payload MUITO grande (100k tokens output) | Muito baixa (`max_tokens=1024`) | Baixo | Config já limita |
| SDK Anthropic breaking change (major version) | Média (upgrade forçado) | Alto | Testes E2E antes de bump; pin de major no `pyproject.toml` |
| Prompt Injection via user_text | Média | Baixo (backend calcula tudo; INV-1 protege) | Nada sensível a manipular via LLM |

## Alternativas para pós-MVP

- **Streaming SSE** — melhoria de UX para respostas longas.
- **Fine-tuning ou Prompt caching persistente** — se Anthropic oferecer, adotar.
- **Multi-provider fallback** (Anthropic → OpenAI → local Llama) — resiliência; overkill hoje.
- **Prompt A/B testing** com métricas por versão.
- **Tool schema versionado** — evolução com backward-compat.
- **Persistência do cache token** — pré-warmup de cache ao acordar processo.
- **Batch API** para narrativas semanais atrasadas — se custo virar problema.
