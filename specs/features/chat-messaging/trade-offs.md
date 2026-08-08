# Trade-offs — Chat e mensagens

## Decisão 1 — BackgroundTask do FastAPI (in-process) vs. Celery/RQ

### Contexto

Pós-202, precisamos rodar o pipeline (LLM + dispatch + recompute + formatter) sem bloquear o request. Opções vão de "in-process, no mesmo Python worker" até "queue + separate workers".

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — `fastapi.BackgroundTasks` (escolhida) | Zero deps; roda no mesmo processo após response | Se processo morre entre POST e processing, assistant nunca chega |
| B — Celery/RQ + Redis | Retry automático; observabilidade | +2 componentes (broker, worker); config nginx; monitoring |
| C — Postgres LISTEN/NOTIFY | Sem Redis | Ainda precisa worker separado |

### Decisão tomada

**Opção A.** MVP single-VPS single-user; usuário reenvia se travar.

### Consequências

- **Positivas**: código trivial; deploy simples; sem novos componentes.
- **Negativas**: sem retry se processo morre. Assistant simplesmente não chega — user reenvia.
- **Mitigação futura**: monitorar rate de "mensagens user sem assistant" > 30 min. Se relevante em multi-user, migrar para Celery/RQ.

---

## Decisão 2 — 202 Accepted + polling GET vs. streaming SSE

### Contexto

Streaming (SSE) daria "assistente digitando" UX. Polling é mais simples e igualmente aceitável em MVP.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — 202 + polling (escolhida, SP-10) | Simplíssimo; funciona com Nginx padrão; testes triviais | Latência percebida = total |
| B — SSE | UX melhor | Nginx buffering; workarounds; complexidade |
| C — Websocket | Interativo | Reconnect logic; monitoring; MVP não precisa |

### Decisão tomada

**Opção A.** SP-10 codifica.

### Consequências

- **Positivas**: HTTP/1.1 padrão; browser retry-friendly; testes com `httpx` simples.
- **Negativas**: 4-8s de "processando..." percebido pelo usuário. Aceito.

---

## Decisão 3 — Sem cursor devolve MAIS RECENTES, não as antigas

### Contexto

Pagination cursor típica: sem cursor = do início. Mas UX de chat é "vi o mais recente primeiro".

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Sem cursor devolve top-N recentes (escolhida) | UX correta; app abre com contexto | Regressão silenciosa se alguém "corrigir" |
| B — Sem cursor = do início | Padrão convencional | UX ruim — user vê mensagem 1 de 200 ao abrir |

### Decisão tomada

**Opção A.** Teste `test_list_no_anchor_returns_most_recent_not_oldest` protege.

### Consequências

- **Positivas**: UX consistente.
- **Negativas**: "aparente inconsistência" para dev novo — teste explícito documenta.

---

## Decisão 4 — `Cache-Control: no-store` obrigatório no GET

### Contexto

Bug histórico: polling da mesma URL era cacheado por Chrome/Safari; assistant não aparecia até refresh.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — `no-store` em todo GET /chat/messages (escolhida) | Correção definitiva | Sem cache; polling é o único jeito |
| B — Cursor variando por request (ex.: incluir timestamp) | Cache "por URL" ineficaz | Complexidade sem ganho |
| C — Deixar navegador decidir | Simples | Bug volta |

### Decisão tomada

**Opção A.** Header explícito em `list_messages`.

### Consequências

- **Positivas**: bug fixed.
- **Negativas**: polling um pouco mais custoso (sem 304). Aceito.

---

## Decisão 5 — `raw_llm_response` como JSONB opaco

### Contexto

Auditoria + debug do pipeline exige guardar payload da LLM + dispatch metadata. Poderia ser tabela normalizada ou JSONB.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — JSONB opaco em `messages` (escolhida) | Flexível; sem migration por evolução | Sem constraint; queries por campo interno são strings |
| B — Colunas dedicadas por campo | Type-safe | Explosão de colunas; migration por SP novo |
| C — Tabela separada `llm_dispatches` | Normalizado | Overhead de JOIN; sem valor MVP |

### Decisão tomada

**Opção A.** JSONB inclui `envelope` + `dispatch` metadata (ex.: `nutrient_fact_id` do SP-33).

### Consequências

- **Positivas**: adicionar SP novo com dispatch metadata é trivial.
- **Negativas**: sem type safety no shape; auditoria informal.

---

## Decisão 6 — Commit explícito antes de `add_task`

### Contexto

FastAPI docs indicam que BackgroundTask roda após response mas com sessão da dep já commitada. Mas experiência prática mostra edge cases (exception path, custom deps).

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — `await session.commit()` explícito antes de agendar (escolhida) | Zero risco de race; explícito | Latência extra ~5-10ms |
| B — Deixar dep manejar commit | Idiomático | Race window potencial em edge cases |

### Decisão tomada

**Opção A.**

### Consequências

- **Positivas**: worker sempre enxerga a mensagem.
- **Negativas**: latência de POST sobe ~5-10ms. Aceito.

---

## Decisão 7 — `unknown_media` genérico (não distingue "não existe" vs. "não é seu")

### Contexto

Const. §21: isolamento por user. Vazar existência para outro user é infosec bad practice.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Erro genérico único (escolhida) | Sem enumeração cross-user | User debug menos claro em edge case |
| B — Distinguir "not_found" vs. "not_owned" | Debug fácil | Vazamento de existência |

### Decisão tomada

**Opção A.**

### Consequências

- **Positivas**: pentester não enumera IDs de outros users.
- **Negativas**: mensagem menos precisa. Aceito (MVP single-user).

---

## Decisão 8 — Sem retry automático quando assistant não chega

### Contexto

Se processo morre (deploy, OOM, restart) entre POST e assistant, mensagem user persiste mas assistant não. User precisa reenviar.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Aceitar; user reenvia (escolhida) | Simplíssimo | UX ruim em edge case |
| B — Detectar "user messages sem assistant após N min" e retry | Robust | Precisa scheduler; complexidade |
| C — Alertar usuário no UI | Compromisso | Ainda precisa detecção |

### Decisão tomada

**Opção A.**

### Consequências

- **Positivas**: código mínimo.
- **Negativas**: em incidente de deploy, algumas mensagens ficam "no vazio". Aceito no MVP.

---

## Decisão 9 — Cascade delete de messages ao deletar user, SET NULL em day_log

### Contexto

FKs no `Message` model:

- `user_id ON DELETE CASCADE` — user vai embora, mensagens vão junto (single-user, ~= account deletion).
- `day_log_id ON DELETE SET NULL` — se dia é deletado (migração), mensagem sobrevive como registro histórico.

### Justificativa

- User delete = data deletion legítima; deve levar tudo.
- Day delete não é operação de usuário; migration/manutenção. Preservar msg como histórico.

### Consequências

- Consumers de `messages` podem receber `day_log_id=NULL` — precisam tratar.

---

## Dívida técnica conhecida

| Item | Impacto | Prioridade |
|---|---|---|
| Sem retry se processo morre no meio do processing | Médio (UX) | Média; monitorar frequência |
| `raw_llm_response` sem shape validado | Baixo | Baixa; JSONB tolera |
| Polling constante mesmo sem mensagens novas | Baixo (custo servidor) | Baixa; SSE resolve mas é overkill |
| `nutrient_fact_id` hardcoded pra `log_nutrition_label` (não generalizado) | Baixo | Baixa; refactor se surgir 2º caso |
| `message_processor.py` com 1274 linhas — Deus-classe | Médio (manutenibilidade) | Média; split por intent futuro |
| Presigned URL sem cache — regenerada a cada GET | Baixo | Baixa; cache 30s se virar hot path |

## Riscos identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| Deploy no meio de processing → assistant perdida | Baixa (rare) | Baixo (user reenvia) | Aceito; monitorar rate |
| Anthropic + MinIO em conjunto → latência > 30s | Média (foto grande) | Médio (SP-14 fallback) | Compressão de imagem em `anthropic-integration` |
| Concorrência: user manda 5 msgs em 5s | Média | Baixo | Cada uma vira msg + task independente; recompute idempotente |
| Cursor UUID não é temporal (v4) → paginação inconsistente | Baixa (`created_at` é fallback) | Baixo | UUID v7 se surgir problema; hoje ordenação ASC por `created_at` |
| `day_log_id=NULL` em message quebra código downstream | Baixa | Médio | Testes; consumers checam |
| MinIO presigned URL expira antes do render (URL cacheada em image cache) | Baixa | Baixo | 1h TTL é folgado |
| BackgroundTask não roda por bug de FastAPI (exception no `add_task`) | Baixa | Alto (assistant never comes) | Try/except em `add_task` + fallback log |

## Alternativas para pós-MVP

- **Streaming SSE** — melhor UX de "assistant digitando".
- **Celery/RQ + Redis** — se escalar pra multi-user.
- **Message threading** (`replies_to_message_id`) — permite conversas paralelas.
- **Cursor por timestamp explícito** — mais robusto que UUID.
- **Compressão de `raw_llm_response`** (zstd) se DB crescer.
- **Purge de `raw_llm_response` após N dias** — reduzir footprint; audit externo (S3 archive).
- **Websocket bidirecional** — pode habilitar push de outros dispositivos.
