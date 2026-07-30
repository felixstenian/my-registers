# Trade-offs — Treino estruturado (Bloco 3)

> **Rastreabilidade**: SP-120..SP-127, ADR-011 (`research.md`) · Bloco 3 (T-B301..T-B308) em [`tasks.md`](../../001-mvp-registro-diario/tasks.md). Status: **`documented-only`** — ADR-011 aceita; implementação pendente desde v1.2/v1.6.

## Decisão 1 — Coexistência com `log_activity` via consolidação (ADR-011)

### Contexto
SP-120..127 introduzem modelo hierárquico (sessão → exercício → séries) que é fundamentalmente mais granular que `activity_records` flat atual. Como integrar sem alterar snapshot/semanal?

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Coexistir + consolidar em 1 `activity_record` no encerramento (SP-126)** (escolhida) | Snapshot/semanal agnósticos; baixa superfície de impacto; detalhamento no histórico (SP-121/127) | Dados duplicados (séries + `activity_record`); unlink INV-13 |
| B — Substituir `log_activity` por sessão para tudo | Unificação | Overhead pra cardio ("corri 40 min" não precisa de 3 tabelas) |
| C — Duas tabelas separadas sem consolidação | Stats granulares por séries | Snapshot/semanal precisaria ler duas fontes (quebra INV-1 — fonte única `kcal_out`) |
| D — Consolidação em tempo real (a cada série) | Atualização instantânea | Disparar `recompute` por série é caro; dado parcial não faz sentido |

### Decisão tomada
**Opção A** — ADR-011 accepted. Implementação T-B301..T-B304/T-B306. Justificativa: snapshot agnóstico < impacto mínimo; MVP-de-treino herda calculadora existente.

### Consequências
- Positivas: snapshot/semanal sem mudança; `activity_records` continua única fonte de `kcal_out` (INV-1 preservado); correções/deleções existentes continuam válidas.
- Negativas / dívida técnica:INV-13 (unlink); sessões órfãs possíveis; MET fixo aproximado.

---

## Decisão 2 — Estado conversacional 100% no banco (sem memória LLM)

### Contexto
LLM precisa saber "sessão atual ativa" e "último exercício" a cada mensagem. Avaliava-se memória de conversa vs consulta DB.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Lookup DB em cada handler** (escolhida) | Multi-device consistente; idempotente; INV-1 fácil de testar (mock LLM não "lembra") | 1+ query por intent; complexidade no service |
| B — Memória de conversa (Anthropic messages array) |latência reduz | LLM "lembra" errado entre dias; difícil reset |
| C — Cache Redis state | Rápida lookup | Infra adicional (single VPS evita) |

### Decisão tomada
**Opção A** — Consulta ao DB no handler. Index parcial `(user_id WHERE status='active')` faz lookup barato. INS-1 garante determinismo mesmo com LLM mock.

### Consequências
- Positivas: multi-device; reset por commit consiste; mock LLM em tests funciona.
- Negativas: 5+ queries em uma sessão longa; desprezível devido à escala single-user.

---

## Decisão 3 — Consolidação no encerramento (não a cada série)

### Contexto
`activity_record.kcal_burned` final só faz sentido quando sessão completa.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — `consolidate_to_activity` em `end_session` + `_handle_close_day`** (escolhida) | Snapshot só muda quando faz sentido; 1 recompute por sessão | Latência até encerramento pra ver kcal |
| B — Recompute a cada `log_set` | Atualização real-time | Disparar `recompute` por série é caro; dado parcial enganador |
| C — Stream events → batch | Event-sourced | Quebra INV-4 (snapshots from-scratch); complexo |

### Decisão tomada
**Opção A** — Encerramento é o momento natural (SP-124/SP-125). ADR-011 explicita.

### Consequências
- Positivas: snapshot consistente; menos churn.
- Negativas: usuário vê "calorias estimadas" só ao final (aceito).

---

## Decisão 4 — MET fixo por `workout_type`

### Contexto
`kcal = MET × weight × horas`. MET real varia muito por carga/descanso/perfil. Como estimar?

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — MET hardcoded por `workout_type`** (escolhida) | Simples; reproduzível; OK p/ MVP | Aproximação grosseira |
| B — Lookup MET por exercício + intensidade | Precision | Database MET; complexo |
| C — Fórmula "volume total × densidade" (peso × reps × sets) | Modela esforço real | Fora do escopo MVP sem normativas |
| D — LLM estima | — | Violado INV-1 (Art. II) — LLM não calcula |

### Decisão tomada
**Opção A** — MET fixo: `push`/`pull`/`upper` = 5.0; `legs`/`lower` = 6.0; `full_body` = 5.5. Justificativa: ADR-011 aceita aproximação pra MVP; refinamento é feature pós-MVP ("volume × densidade").

### Consequências
- Positivas: 1 cálculo determinístico; teste fácil.
- Negativas: para musculação intensa de pk, 5.0 MET pode ser sub-estimado; aceito.

---

## Decisão 5 — `weight_kg` do perfil (sem default)

### Contexto
Fórmula kcal precisa do peso do usuário. Avaliava-se default e não bloquear.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Sem `weight_kg` no perfil → `kcal_burned=NULL` + warning** (escolhida) | Treino persiste; usuário define depois; sem fricção | kcal fica pendente |
| B — Bloquear sessão até preencher perfil | Sem pendências | UX má; perfil é opcional na spec |
| C — Default 70 kg generic | Funciona | Generic wrong; kcal skew |

### Decisão tomada
**Opção A** — `warning 'weight_kg_required_for_kcal'`; treino persiste. Implementação T-B304.

### Consequências
- Positivas: usuário nunca perde dados por perfil incompleto.
- Negativas: snapshot tem `kcal_burned=NULL` em treino; ajusta ao preencher perfil (possible follow-up).

---

## Decisão 6 — INV-13 unlink bidirectional (delete não propaga)

### Contexto
Após consolidação, `activity_record` e `workout_sessions/exercises/sets` coexistem com link FK. Apagar um deve propagar?

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Unlink: delete não propaga** (escolhida) | Simples; histórico de séries preservado | Consistência requer recompute manual (fora MVP) |
| B — Cascade delete em ambos | Consistente | Perder dados detalhados |
| C — Trigger automático recompute | Eventual consistência | Over-engineering pra single-user MVP |

### Decisão tomada
**Opção A** — INV-13 explicita unlink bidirectional; ADR-011 assume dívida técnica aceitável.

### Consequências
- Positivas: histórico preservado após apagar `activity_record`.
- Negativas / dívida técnica: se usuário apaga cardio genérico (correção), treino consolidado permanece; recompute manual pra refletir. Feature futura se incomodar.

---

## Decisão 7 — Parser pt-BR pela LLM (backend só valida)

### Contexto
"20 kg da barra + 20 kg de cada lado" → 60. Parser estruturado vs LLM NLP?

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — LLM faz NLP, payload Pydantic validado** (escolhida) | Reproduzível; backend determinístico (INV-1); flexível | Edge cases LLM; seed de cache para PR |
| B — Regex/parser próprio | Totalmente deterministic | Frágil pt-BR; refresh de sinônimos interminável |
| C — Tool/function calling múltiplas | Fine-grained | Latência alta; complexidade |

### Decisão tomada
**Opção A** — LLM collated via `tool_use` JSON payload; backend `weight_kg > 0` `reps > 0`. Se ambíguo → `clarify`.

### Consequências
- Positivas: regras vocab free; backend mantém INV-1.
- Negativas: dependência LLM para aceitar "20 kg só a barra"; LLM deixa vazio/ambíguo → backend rejeita.

---

## Decisão 8 — Antecipar `CALC_METHOD_LABEL_PT['workout_session']` no frontend

### Contexto
Bloco 6 (`daily-detail-view`) já adicionou label `'sessão de treino'` para `calc_method='workout_session'` em `types.ts`, mesmo sem implementação. Decisão: deixar vazio placeholder ou já incluir？

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Antecipada em Bloco 6** (escolhida) | Sem regressão visual quando implementado; UI já mostra "sessão de treino" | Códigoче for feature não-existente |
| B — Adicionar só quando Bloco 3 implementado | Sem código morto | Risco de mostrar "workout_session" cru ao user |

### Decisão tomada
**Opção A** — `types.ts:137` já tem `'sessão de treino'` (commit Bloco 6); backend não emite `calc_method='workout_session'` hoje, então não aparece anyway. Zero UX impact; prontidão.

### Consequências
- Positivas: zero regressão quando Bloco 3 implementar.
- Negativas: cruft slight (uma entrada em dict, aceitável).

---

## Decisão 9 — 5 intents fora de `_STRUCTURED_INTENTS`

### Contexto
Meal/water/beverage/activity compartilham pipeline genérico em `_STRUCTURED_INTENTS`. Avaliava-se reaproveitar vs handlers dedicated.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Handlers dedicated (5 `_handle_workout_*`)** (escolhida) | Cada handler tem fluxo próprio (estado/recuperação histórico); isolado | Boilerplate; dispatcher deve explicitar |
| B — Reuso de pipeline genérico | Menos boilerplate | Pipeline não comporta lookup histórico + 2-step consolidar |
| C — Um handler só switch | Conciso | Switch case legibility |

### Decisão tomada
**Opção A** — 5 handlers dedicated; rotear fora de `_STRUCTURED_INTENTS`. T-B305.

### Consequências
- Positivas: lógica isolada; testável sem acoplar meal flow.
- Negativas: 5 funções similares; commentário no `_STRUCTURED_INTENTS` sobre eles (documentação inline).

---

## Decisão 10 — T-B308 frontend opcional

### Contexto
Backend em markdown das sessões já é renderizável pelo `AssistantContent`. Avaliava-se fazer UI customizada já no MVP-de-treino.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Backend primeiro, T-B308 opcional/melhoria** (escolhida) | Ship mais rápido; markdown é legível; User foca em core | Sem destaque visual; sem `WorkoutHistoryCard` |
| B — UI customizada no PR Bloco 3 | UX melhor desde dia 1 | Mais código; 2 entregas acopladas |
| C — Componente reusable para fitness apps | Zero escopo | Over-engineering |

### Decisão tomada
**Opção A** — T-B308 marcado opcional; `message_formatter.compose_workout_*` em markdown resolveleit عبر `AssistantContent` existente. Melhorias visuais aguardam demanda real.

### Consequências
- Positivas: escopo menor; ship incremental.
- Negativas: sem "PR ambar"/"série atual verde" até futuro; markdown identifica por textual.

---

## Decisão 11 — Sessões órfãs aceitas

### Contexto
Usuário pode iniciar sessão e nunca encerrar, nem fechar dia (dia continua aberto por dias/semanas).

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Aceitar; SP-125 cobre caso mais comum (close day)** (escolhida) | Sem cron/monitor; MVP simples | Sessões `status='active'` continuamILITIES |
| B — Cron fecha sessões >24h | Realística | Infra nova (cron); contratempo UX (user volta e treino fechado) |
| C — LLM avisa continuamente | UX | Ruído |

### Decisão tomada
**Opção A** — spec aceita; index parcial permite manutenção futura; SP-125 cobre padrão single-user. Documentado em ADR-011.

### Consequências
- Positivas: zero overhead.
- Negativas / dívida técnica: lookup `status='active'` pode retornar sessão velha; necessária comparação `started_at` adicional quando Bloco 3 implementado.

---

## Dívida técnica conhecida

| Item | Impacto | Prioridade |
|---|---|---|
| Bloco 3 inteiro não implementado | Feature não disponível | Alta — spec aceita (v1.2/v1.6); aguarda priorização pós-Fase 10 |
| `reset-password`/`create-admin` inline (sem CLI direct) | Não relacionado a Bloco 3; gap operacional (feature `admin-bootstrap-cli`) | Média |
| MET fixo sub-estimado para musculação intensa | kcal_burned baixista | Baixa (refinamento futuro) |
| Sessões órfãs aceitas sem recharge | Acumulação de sessões `active` sem dono de contexto | Baixa |
| `clarify` no parser LLM sem fluxo guidance de fallback | Pode ficar repetitivo | Baixa |
| `WorkoutHistoryCard`/destaque visual (T-B308) postergado | UX "ok" mas sem blink PR | Baixa |
| Sem cron de housekeeping sobre `workout_*` | Tabelas podem crescer | Baixa (single-user MVP) |
| Auditoria gap se(sessão acaba sem mutar `activity_record`)? | Audit cobre só mutações; consulta SP-127 não audita | Baixa |
| `apps/api/tests/test_workout.py` inexistente — cobertura 0% | Bloco não implementado | Alta — criar junto com implementação |

## Riscos identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| Bloco 3 nunca implementado | Média | Médio | Spec aceita; backlog priorizado; revisitar em planning |
| Race condition 2 `start` simultâneos | Baixa (deploy serial access HTTP) | Médio | Index parcial `(user_id WHERE status='active')` + unique; service detecta |
| LLM parser errado: "só a barra" interpretado como vazio | Média | Baixo | Backend validar `weight_kg>0`; LLM `clarify` se None |
| MET fixo vira "production-true" e nunca melanja | Alta | Médio | Documentado como Aproximação (ADR-011); feature pós-MVP |
| INV-13 unlink irrita user: "apaguei treino, kcal não recalculou" | Média | Médio | UX explica (recompute manual fora MVP); feature future |
| Snapshot de dia anterior não mostra treino | Baixa | Médio | SP-125 garante encerra + consolidate ANTES do close; if user nunca faz close, aceito |
| LLM emite `intent=workout_start` para "corri 40 min" (overlap cardio) | Média | Médio | Prompt rule 19 explicita; LLM modo ambíguo → clarify |
| Histórico fuzzy match retorna falso-positive ("supino reto" casa "supino reto máquina" incorreto) | Média | Baixo | Review das rules de `normalized_name`; refinamento incremental |
| migration destrutivo (cria tabelas) em prod sem rollback path | Baixa | Alto | Alembic downgrade -1 testado em staging antes de prod |
| `weight_kg` mudou no perfil between sessões → PR histórico afeta? | Baixa | Baixo | Histórico é "peso que MEEDI no exercício" (de workout_sets); perfil é apenas para cálculo de kcal consolidado |
| Auditoria reproduz sessão toda em delete | Média | Baixo | INV-10 registrou create; recompute não restore |