# Trade-offs — Módulo de Treino (Workout Module)

> **Rastreabilidade**: SP-120..SP-127, ADR-011 (`research.md`), Bloco 3 (T-B301..T-B308) em [`tasks.md`](../../001-mvp-registro-diario/tasks.md) · Expansão do cliente (SP-170..179 propostos), 2026-08-14. Status: **`documented-only`** — ADR-011 aceita; implementação pendente.

## Decisão 1 — Coexistência com `log_activity` via consolidação (ADR-011)

### Contexto
SP-120..127 introduzem modelo hierárquico (sessão → exercício → séries) mais granular que `activity_records` flat. Como integrar sem alterar snapshot/semanal?

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Coexistir + consolidar em 1 `activity_record` no encerramento (SP-126)** (escolhida) | Snapshot/semanal agnósticos; baixa superfície de impacto; detalhamento no histórico | Dados duplicados (séries + `activity_record`); unlink INV-17 |
| B — Substituir `log_activity` por sessão para tudo | Unificação | Overhead pra cardio ("corri 40 min" não precisa de 3 tabelas) |
| C — Duas tabelas separadas sem consolidação | Stats granulares por séries | Snapshot/semanal precisaria ler duas fontes (quebra INV-1) |
| D — Consolidação em tempo real (a cada série) | Atualização instantânea | Disparar `recompute` por série é caro; dado parcial não faz sentido |

### Decisão tomada
**Opção A** — ADR-011 accepted. Implementação T-B301..T-B304/T-B306.

### Consequências
- Positivas: snapshot/semanal sem mudança; `activity_records` única fonte de `kcal_out` (INV-1); correções/deleções existentes válidas.
- Negativas/dívida: INV-17 (unlink); sessões órfãs; MET fixo aproximado.

---

## Decisão 2 — Estado conversacional 100% no banco (sem memória LLM)

### Contexto
LLM precisa saber "sessão atual ativa", "último exercício" e "template guiado" a cada mensagem.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Lookup DB em cada handler** (escolhida) | Multi-device consistente; idempotente; INV-1 testável | 1+ query por intent |
| B — Memória de conversa (Anthropic messages array) | Latência reduzida | LLM "lembra" errado entre dias; difícil reset |
| C — Cache Redis state | Lookup rápida | Infra adicional (single VPS evita) |

### Decisão tomada
**Opção A**. Index parcial `(user_id WHERE status='active')` torna o lookup barato.

---

## Decisão 3 — Consolidação no encerramento (não a cada série)

### Contexto
`activity_record.kcal_burned` final só faz sentido quando a sessão completa.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — `consolidate_to_activity` em `end_session` + `_handle_close_day`** (escolhida) | Snapshot só muda quando faz sentido; 1 recompute por sessão | Latência até encerramento pra ver kcal |
| B — Recompute a cada `log_set` | Real-time | `recompute` por série caro; dado parcial enganador |
| C — Stream events → batch | Event-sourced | Quebra INV-4 (snapshots from-scratch) |

### Decisão tomada
**Opção A**. INV-20 adiciona reconsolidação **sob demanda** quando a sessão já encerrada é editada.

---

## Decisão 4 — kcal: reportada pelo usuário (INV-21) vs MET fixo

### Contexto
Cliente pediu calorias gastas "quando forem passadas" (texto/imagem/edição) entrando no resumo do dia. Como conciliar com MET fixo?

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — `kcal_burned_reported` como fonte quando informada; senão MET fixo por `workout_type`** (escolhida) | Respeita valor real do usuário/equipamento (esteira/pulso); fallback determinístico; INV-21 | Dados "dupla origem" (reportada vs estimada) precisam semântica clara no `calc_method` |
| B — Sempre MET fixo | Consistente | Ignora calorias que o usuário tem (ex.: foto de esteira) — cliente quer exibi-las |
| C — LLM calcula | — | Violado INV-1 (Art. II) |
| D — MET por exercício + intensidade | Preciso | Database MET; complexo |

### Decisão tomada
**Opção A**. `workout_sessions.kcal_burned_reported` persiste o valor informado; `consolidate_to_activity` usa reportada se existir (`met_value=NULL`), senão MET. `calc_method='workout_session'` permanece; origem via `met_value`/`kcal_burned_reported` em `notes`.

### Consequências
- Positivas: cliente vê kcal reais da atividade; fallback MET intacto.
- Negativas: dois caminhos de kcal na sessão — mitigado por INV-21 + labels de origem.

---

## Decisão 5 — `workout_templates`: entidade de catálogo separada

### Contexto
Cliente quer cadastrar treinos reutilizáveis (RF-015), com status ativo/inativo (RF-016) e fluxo guiado (RF-020). Onde viver?

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Tabela nova `workout_templates` + `workout_template_exercises`, sessões referenciam `template_id`** (escolhida) | Catálogo ≠ execução; histórico preservado (INV-20); lista/abas triviais | 2 tabelas novas; sessões livres sem template coexistindo |
| B — Templates como sessões `active` só | Zero tabelas | Confunde catálogo com execução; inativar template apagaria/confundiria sessão |
| C — Templates em `activity_records` | Zero schema | Perde estrutura de séries-alvo; histórico ambíguo |

### Decisão tomada
**Opção A**. `active` boolean no template (INV-19); `workout_sessions.template_id` FK SET NULL (INV-20).

### Consequências
- Positivas: abas Ativos/Inativos/Histórico triviais; fluxo guiado simples; edição não vaza.
- Negativas/dívida: novas tabelas; sessões órfãs de template (template deletado → `template_id=NULL`, sessão permanece).

---

## Decisão 6 — Chat de treino dedicado (espaço separado)

### Contexto
Cliente quer "o próprio chat de workouts", no mesmo padrão do chat de alimentação, com header de atividades do dia + kcal e botões próprios (RF-018/019).

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Página dedicada `/workouts/chat` espelhando `(app)/chat` + `messages.via='workout'`** (escolhida) | UX consistente com alimentação; header/botões específicos; reuso total de mídia/audit/polling; backward-compatible (default `via='food'`) | Coluna nova + filtro em todas as queries de chat; branch de prompt no `MessageProcessor` |
| B — Reusar `/chat` com toggle de modo | Sem rota nova | Estado global confuso; prompt diferente; header/botões condicionais |
| C — Dois pools/`workout_messages` separada | Isolamento absoluto | Duplica Message + ponte mídia + FK audit; poll duplicado; LLM não recebe histórico → isolamento de memória não se aplica (Art. II §2) |

### Decisão tomada
**Opção A** (confirmada em 2026-08-14). `messages` ganha coluna `via` (`'food'` default / `'workout'`); `GET /chat/messages` e `MessageProcessor` filtram por `via`. Prompt do treino selecionado pela `via` da mensagem de entrada.

### Consequências
- Positivas: cada chat tem prompt/contexto próprio (alimentação não polui treino); header e botões dedicados; mídia/audit/polling intactos; default `'food'` elimina backfill.
- Negativas/dívida: toda query de listagem de chat precisa do filtro `via` (regressão de polling mitigada por teste de integração); branch de prompt no processor; `proxy.ts` + acesso via CTA (tab bar mobile segue SP-NM sem tab nova).

---

## Decisão 7 — Fluxo guiado: botões como conveniência sobre mensagens estruturadas

### Contexto
Cliente quer seleção de template/exercício por botões e repetição de sequência (RF-020).

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Botões mapeiam para o mesmo protocolo de chat (intents/mensagens)** (escolhida) | Estado no DB; EVT; LLM não precisa lembrar; sequência é só re-listar | Precisar de intents de navegação (`workout_next_exercise`) |
| B — Botões chamam endpoints HTTP dedicados | Mais "nativo" | Duplica lógica de sessão; divergência entre caminhos |
| C — Botões só estilizam, LLM decide tudo | Zero backend novo | LLM requer memorizar estado → quebra EVT/INV-1 |

### Decisão tomada
**Opção A** — botões disparam mensagens/intents estruturados. `WorkoutService.next_exercise_prompt` re-lista exercícios do template de forma determinística.

---

## Decisão 8 — Cronômetro (RF-021): UI-only, tempo determinístico no backend

### Contexto
Cliente quer cronômetro ao iniciar treino, parado ao encerrar, com tempo registrado.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Cronômetro frontend; `duration=ended_at-started_at` como fonte** (escolhida) | Registro determinístico; idempotente; puff concorrente irrelevante | Cronômetro pode "pular" se sessão encerra por outro device (aceito — single-user) |
| B — Persistir ticks do cronômetro | "Tempo real" excluindo pausas | Complexo; inconsistente com SP-126 |

### Decisão tomada
**Opção A**. UI exibe tempo decorrido derivado; backend grava `ended_at - started_at`.

---

## Decisão 9 — Imagem de treino (RF-022) reutiliza pipeline de mídia

### Contexto
Cliente pediu enviar imagem com atividade. Como processar?

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Reusar `POST /media` + `media_ids` + LLM Sonnet** (escolhida) | Zero infra nova; mesmo fluxo do chat de alimentação; extrai título/atividade/intensidade/kcal | Imagem sem kcal → MET; LLM pode inventar título (mitigado por `confidence` + `is_estimate`) |
| B — OCR próprio | Determinístico | Não captura intensidade/kcal; over-engineering |
| C — Upload separado | Isolamento | Duplica pipeline de mídia |

### Decisão tomada
**Opção A** — `WorkoutImageIn` extraído pela LLM; apenas campos explicitados são persistidos (INV-1).

---

## Decisão 10 — Edição de peso/séries/kcal (RF-023) com reconsolidação (INV-20)

### Contexto
Cliente quer editar pelo chat e pelo `/day`. Como manter `/day` consistente depois da consolidação?

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Editar set/sessão e re-consolidar `activity_record` se sessão encerrada** (escolhida) | `/day` fiel ao que o usuário corrigiu; INV-20 | Edição re-dispara consolidação (custo baixo — 1 sessão) |
| B — Editar sem reconsolidar (INV-17 puro) | Simples | `/day` diverge do histórico de treino — cliente quis edição visível no dia → inconsistência |
| C — Bloquear edição de sessão encerrada | Consitência | Cliente pediu edição também no `/day` — bloquear seria UX ruim |

### Decisão tomada
**Opção A**. PATCH `/records/workout-sets/{id}` (peso/reps) e PATCH `/records/workout-sessions/{id}` (kcal reportada); dia fechado → 409.

### Consequências
- Positivas: edição visível e consistente; auditoria total.
- Negativas/dívida: reconsolidação precisa garantir que `activity_record` não duplica (upsert por `workout_session_id`).

---

## Decisão 11 — Sessões órfãs aceitas

### Contexto
Usuário pode iniciar sessão e nunca encerrar, nem fechar dia.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Aceitar; SP-125 cobre caso mais comum (close day)** (escolhida) | Sem cron/monitor; MVP simples | Sessões `active` antigas continuam |
| B — Cron fecha sessões >24h | Realística | Infra nova (cron); UX grátis se user volta e treino fechado |
| C — LLM avisa continuamente | UX | Ruído |

### Decisão tomada
**Opção A**. Documentado em ADR-011.

---

## Decisão 12 — Antecipar `CALC_METHOD_LABEL_PT['workout_session']` no frontend

### Contexto
Bloco 6 (`daily-detail-view`) já adicionou label `'sessão de treino'` (`types.ts:142`) mesmo sem implementação.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Antecipada em Bloco 6** (escolhida) | Sem regressão visual quando implementado | Código para feature não-existente |
| B — Adicionar só quando módulo implementado | Sem código morto | Risco de mostrar label cru |

### Decisão tomada
**Opção A** — `types.ts:142` já tem `'sessão de treino'`.

---

## Decisão 13 — Intents de treino fora de `_STRUCTURED_INTENTS`

### Contexto
Meal/water/beverage/activity compartilham pipeline genérico. Treino tem fluxos próprios.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Handlers dedicados** (escolhida) | Cada handler tem fluxo próprio (histórico, guiado, template, imagem); isolado | Boilerplate; dispatcher deve explicitar |
| B — Reuso de pipeline genérico | Menos boilerplate | Não comporta lookup histórico + template + N sets |
| C — Um handler só switch | Conciso | Switch case legibilidade |

### Decisão tomada
**Opção A**. Roteados fora de `_STRUCTURED_INTENTS`.

---

## Dívida técnica conhecida

| Item | Impacto | Prioridade |
|---|---|---|
| Bloco 3 + módulo inteiros não implementados | Feature não disponível | Alta — spec aceita; aguarda spec:/plan:/tasks:/feat: |
| Dupla origem de kcal (reportada vs MET) | Semântica `calc_method` precisa ser clara | Média |
| `messages.via` (pool único com filtro) | Toda query de listagem de chat precisa filtrar `via` | Média |
| Template deletado → `template_id=NULL` em sessões (dangling) | Histórico preserva sessão sem template (aceito) | Baixa |
| MET fixo sub-estimado p/ musculação intensa | `kcal_burned` baixista (quando não reportado) | Baixa |
| Sessões órfãs sem recharge | Acumulação de sessões `active` | Baixa |
| Semantic retry LLM pode repetir `clarify` sem guidance | Repetitivo | Baixa |
| `WorkoutHistoryCard`/destaque visual (T-B308) postergado | UX "ok" sem blink PR | Baixa |
| Reconsolidação pode duplicar `activity_record` se upsert mal feito | Snapshot incorreto | Alta (mitigar por `workout_session_id` único) |
| Sem cron de housekeeping sobre `workout_*` | Tabelas podem crescer | Baixa |
| `apps/api/tests/test_workout.py` inexistente — cobertura 0% | Módulo não implementado | Alta — criar com a implementação |

## Riscos identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| Módulo nunca implementado | Média | Médio | Spec aceita + proposta do cliente; planejar spec:/plan:/tasks: |
| Race 2 start simultâneos | Baixa | Médio | Index parcial + unique; service auto-encerra |
| LLM parser errado ("só a barra") | Média | Baixo | Backend `weight_kg>0`; `clarify` |
| Imagem sem kcal → MET ou NULL | Média | Baixo | Warning `weight_kg_required_for_kcal`; INV-21 |
| INV-20 reconsolidação duplica `activity_record` | Média | Médio | Upsert por `workout_session_id`; teste TC-I-012 |
| Histórico fuzzy retorna falso-positive ("supino reto" casa "supino reto máquina") | Média | Baixo | Review de `normalized_name`; refinamento incremental |
| Migration destrutiva em prod sem rollback | Baixa | Alto | Alembic downgrade testado em staging |
| `weight_kg` mudou no perfil entre sessões | Baixa | Baixo | Histórico usa peso de `workout_sets` (medido); perfil só pra MET consolidado |
| Mensagens de treino misturadas com alimentação | Média | Médio | `via`/scope separado + prompt dedicado |

> Nota: SP-170..179 são **propostas** — fora da spec canônica `001`. Antes de qualquer implementação, abrir PRs `spec:` (atualizar `specs/001-mvp-registro-diario/spec.md`), `plan:` e `tasks:` (T-B3xx novos) conforme fluxo SDD do AGENTS.md.