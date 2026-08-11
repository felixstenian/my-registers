# Trade-offs — Renderização de assistant messages (Bloco 2)

> **Rastreabilidade**: SP-115..SP-118 · Bloco 2 (T-B201..T-B205) em [`tasks.md`](../../001-mvp-registro-diario/tasks.md). Não há ADR específica para o Bloco 2 — decisões registradas inline no `tasks.md`/`message_formatter.py` e neste arquivo.

## Decisão 1 — Backend gera markdown; frontend só renderiza

### Contexto
SP-118 pede formato tabular padronizado das assistant messages. Avaliava-se onde a formatação acontece: backend monta markdown, ou backend envia JSON estruturado e frontend monta a tabela?

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Backend gera markdown, frontend só renderiza** (escolhida) | Valores numéricos sempre determinísticos (Art. II); dialeto fixo mantém parser client simples; persistência da message é legível em qualquer cliente | Acoplamento: mudar formato exige deploy backend |
| B — Backend envia JSON estruturado, frontend monta tabela | Frontend totalmente livre para formatar | Risco de cálculo/format no front (viola Art. II implícito); duplicação de regras pt-BR |
| C — Usar biblioteca markdown no front (`react-markdown`) | Robustez de parser | Bundle maior; suporta dialeto amplo desnecessário |

### Decisão tomada
**Opção A** — `message_formatter` produz markdown pt-BR; `AssistantContent` render só o subconjunto conhecido. Justificativa: o conteúdo é produzido pelo backend, então o dialeto é fechado; manter `Intl.NumberFormat` na barra é OK porque ali ela recebe JSON (totais), não markdown.

### Consequências
- Positivas: consistência numérica garantida; parser client minimalista (152 linhas sem deps).
- Negativas / dívida técnica: mudar layout da tabela exige edição backend + front (mínimo pois ambos são nossos).

---

## Decisão 2 — Parser markdown sem biblioteca externa

### Contexto
`AssistantContent` precisa renderizar bold + tabelas + parágrafos. Avaliava-se `react-markdown` + `remark-gfm` ou parser próprio.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Parser próprio** (`parseBlocks`, ~30 linhas) (escolhida) | Bundle enxuto; dialeto restrito ao que o backend emite; zero deps | Manutenção se o backend emitir feature markdown nova (ex.: links) |
| B — `react-markdown` + plugins | Robustez;eatures automáticas | ~80 KB bundle; abre parsing a HTML injection se futuro markdown tiver html |
| C — Markdown→JSX compile-time | Zero runtime cost | Não se aplica — conteúdo é runtime (vindo da API) |

### Decisão tomada
**Opção A** — Parser minimalista. O backend é a única fonte de markdown; dialeto controlado. Implementação: `parseBlocks`/`splitRow`/`renderInline`.

### Consequências
- Positivas: bundle ~sem overhead; manutenção barata (dialecto fixo).
- Negativas: se SP-115 evoluir para cards customizados (ex.: gráficos), parser atual não atende; refatoração prevista sem urgência.

---

## Decisão 3 — `revalidateKey` prop pattern (sem SWR/React Query)

### Contexto
A barra precisa re-fetch de `/days/today` quando o poll do `ChatPage` detecta nova assistant message. Avaliava-se SWR/React Query com focus revalidation ou pattern manual de prop.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — `revalidateKey: number` no useEffect** (escolhida) | Mínimo overhead; já existe padrão no `ChatPage`; zero deps | Re-fetch manual sempre quequé a barra revalide |
| B — SWR com `mutate('/days/today')` | Cache + dedupe; revalidação por foco | Dependency nova; state global; payoff baixo só pra 1 endpoint |
| C — React Query com invalidation | Idem B + devtools | Idem B |

### Decisão tomada
**Opção A** — `useEffect(() => load(), [..., revalidateKey])`. `ChatPage` incrementa a cada assistant message; `DayTotalsBar`, `PendingItemsModal` (via `onChanged`) propagam. Implementação: `DayTotalsBar.tsx:85-87`.

### Consequências
- Positivas: sem state library; fluxo explícito.
- Negativas / dívida técnica: se houver 3º+ consumidor de `/days/today`, coordenar `revalidateKey` entre componentes vira incômodo; considerar SWR nesse ponto.

---

## Decisão 4 — `POST /records/food-items/{id}/confirm` dedicado (não PATCH)

### Contexto
SP-117 original altava `PATCH /records/food-items/{id}` re-enviando grams/kcal atuais. Problema descoberto em produção: items só com `quantity` (sem grams/ml) viravam no-op — backend entendia "sem mudança" e não desmarcava `needs_confirmation`, modal fechava sem sair do estado pendente.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Endpoint POST dedicado só desmarca** (escolhida) | Idempotente; items só com `quantity` funcionam; sem recompute | Endpoint extra; sem flexibilidade de ajustar valores no confirm |
| B — Corrigir o bug no PATCH (re-render grams explicitly) | Sem endpoint novo | Front precisava mandar `quantity` mesmo quando igual; frágil |
| C — Confirm por chat ("confirmo") | Reusa fluxo chat existente (SP-24a) | Fora do escopo do modal inline; UX diferente |

### Decisão tomada
**Opção A** — `POST /records/food-items/{id}/confirm` sem body; backend só desmarca `needs_confirmation`; sem recompute de macros (item já tem valores computados quando criado); `already_confirmed` retornado na resposta. Implementação: `records.py:251+`, `PendingItemsModal.tsx:9-18` (comentário explicativo).

### Consequências
- Positivas: UX estável; fluxo inline funcional mesmo para items só com unidade doméstica; idempotente.
- Negativas: o confirm não permite ajustar valores — caso futuro precise, criar novo endpoint PATCH de correção (feature `record-correction`).

---

## Decisão 5 — Tabela "Total da refeição" agrega só items da mensagem (não do dia)

### Contexto
SP-118 explicita que a 1ª tabela mostra só o registro atual; a 2ª mostra o dia. Avaliava-se mostrar só o dia ou ambos.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Duas tabelas (msg + dia)** (escolhida) | Usuário vê "quanto esta refeição contribuiu" vs "como está o dia total" | Soma extra no backend (mínimo) |
| B — Só tabela do dia | Menos código | Usuário não sabe se esta refeição foi 600 kcal ou 600 do total |
| C — Uma tabela só com diff do dia | Compacto | Confuso; perde contexto do total |

### Decisão tomada
**Opção A** — `compose_*` monta 1ª tabela somando apenas `meal.items`/`r` (o registro atual); 2ª tabela vem de `_daily_totals_table(snapshot, ...)`. Implementação: `message_formatter.py:184-316`.

### Consequências
- Positivas: clareza; alinhado à spec SP-118.
- Negativas: nenhuma — soma no backend barata.

---

## Decisão 6 — `≈` determinístico centralizado em `_has_approx_food_items`

### Contexto
SP-118 obriga `≈` em linhas nutricionais quando ≥1 item envolvido é estimado. Regra espalhada entre `compose_*` poderia desyncronizar.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Função única `_has_approx_food_items`** (escolhida) | Regra centralizada; testável isoladamente | 1 indirection |
| B — Cada `compose_*` checa inline | Sem helper | Duplicação; risco de divergência |
| C — Flag no snapshot | Backend computa antes | Acoplamento snapshot↔formato; novo contrato |

### Decisão tomada
**Opção A** — helper que checa `is_estimate`/`needs_confirmation` em items + set de warnings codes; retorna `bool` alimentando `_fmt_kcal(approx)`/`_fmt_g(approx)` e `_daily_totals_table(approx)`. Implementação: `message_formatter.py:170-176`.

### Consequências
- Positivas: testável (TC-U-007/008); mudar regra muda em 1 lugar.
- Negativas: nenhuma significativa.

---

## Decisão 7 — Co-localização dos modais em `ChatPage` (host pattern)

### Contexto
`PendingItemsModal` (Bloco 2) e `CloseDayModal` (T-704) são abertos a partir de `DayTotalsBar` e hospedados por `ChatPage`. Avaliava-se cada componente abrir seu próprio modal.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Host (`ChatPage`) hospeda modais** (escolhida) | Estado compartilhado (`revalidateKey`); reutilização em `/day` (Bloco 6) | Props callbacks arrow entre componentes |
| B — Cada trigger renderiza seu modal | Encapsulamento | Múltiplas instâncias; difícil coordenar revalidação |
| C — ModalProvider context | API limpa | Over-engineering para MVP |

### Decisão tomada
**Opção A** — `ChatPage` mantém `pendingItems`, `closingDate`; renderiza condicionalmente os 2 modais; callbacks (`onPendingClick`, `onCloseDayClick`) vêm do `DayTotalsBar`. Implementação: `page.tsx:396-412`.

### Consequências
- Positivas: `/day` (Bloco 6) reusa `CloseDayButton`/`CloseDayModal` com mesma arquitetura; estado central.
- Negativas / dívida técnica: `ChatPage` cresce; reutilizar o pattern em mais features de chat torna-o "god component" (ver dívida em [`chat-composer-ux/trade-offs.md`](../chat-composer-ux/trade-offs.md) A1).

---

## Dívida técnica conhecida

| Item | Impacto | Prioridade |
|---|---|---|
| `apps/web` sem suíte de testes JS (parser, `collectPendingItems`) — alvo em [`test-cases.md`](./test-cases.md) só especificado | Regressões UI só pegas por smoke manual | Média |
| Parser markdown client não suporta links/listas (se futuro markdown evoluir) | Limita futuras edições do `message_formatter` | Baixa |
| `revalidateKey` prop pattern não escala para 3º+ consumidor de `/days/today` | Coordenar revalidação manual entre componentes | Baixa (atualmente 1 consumidor) |
| Confirm não permite ajustar valores (só desmarca) — ajuste via feature `record-correction` | UX extra passo para usuários que querem confirmar + editar | Baixa |
| Sem telemetria front (render latency, open-rate de modal) | Difícil medir UX | Média |
| `ChatPage` hospedando 2+ modais tende a "god component" | Legibilidade/testabilidade | Média |

## Riscos identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| Backend muda dialecto markdown e parser client não cobre | Baixa (mesmo time) | Médio | Testes de regressão (R-005); teste de contrato markdown↔render |
| `≈` aparece onde não deve (decoração UI confunde com dado) | Média | Médio | `≈` só vem do backend; client não injeta — decisão A1 |
| Polling revalida barra fora de ordem (assistant antes do snapshot recompute) | Baixa | Baixo | Backend recompute happens antes do `compose_*`; snapshot consistente quando lido |
| Usuário confirma item em dia recém-fechado (race) | Baixa | Médio | INV-5 bloqueia backend; UI esconde botão quando `status='closed'` |
| Modal abre em mobile pequeno cobrindo todo o overlay | Alta (esperado) | Baixo | `max-h-[80vh] overflow-y-auto`; fecha por overlay/× |
| Disclaimer some em UI customizada futura | Média | Alto (viola §26) | R-008 testa presença sempre; revisão de PR checa |