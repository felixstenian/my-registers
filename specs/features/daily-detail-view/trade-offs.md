# Trade-offs — Visão detalhada do dia (Bloco 6)

> **Rastreabilidade**: SP-150..SP-155 · Bloco 6 (T-B601..T-B608) em [`tasks.md`](../../001-mvp-registro-diario/tasks.md); PRs #43/#44/#46. Não há ADR específica para o Bloco 6 — decisões registradas inline no `tasks.md` e neste arquivo.

## Decisão 1 — Server components por padrão + islands client

### Contexto
Tabela de refeições, seções auxiliares e `<details>` de item poderiam ser 100% client (estado) ou 100% server. Avaliava-se cual arquitetura.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Server por padrão + islands client** (escolhida) | FCP rápido; bundle leve; SEO-friendly; `<details>` nativo sem JS | Interatividade requer 4 ilhas client (navigator/confirm/close/refresh) |
| B — Tudo client (use client na página) | Estado central; fácil animação | Bundle grande; hidrata bloqueia |
| C — 100% server (sem islands)sem interatividade | Impossível — precisa `useRouter` para navigator/close/confirm/refresh | — |

### Decisão tomada
**Opção A** — Apenas 4 compos client (`DayNavigator`, `ConfirmItemButton`, `CloseDayButton`, `RefreshOnFocus`); restante é server.

### Consequências
- Positivas: performance; code split natural; build menor.
- Negativas / dívida técnica: prop `allowClose` passa por server; algumas mudanças exigem coordenação server/client.

---

## Decisão 2 — `<details>` nativo em vez de lib de accordion

### Contexto
SP-152 pede expansão de item revelando micros + origem. Opções: `<details>` HTML5 ou lib React (`radix-ui`/`headlessui`).

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — `<details>` nativo** (escolhida) | Zero JS/dep; acessível padrão; estilizável | Sem animação; estado continuo entre pages (recolhe ao re-render) |
| B — Lib React (`radix-ui`) | Animação fine-grained; persistência de estado | Bundle + dep; código extra |
| C — `useState` custom | Controle total | Código; server impossibilita sem hydration |

### Decisão tomada
**Opção A** — `<details>/<summary>` no `FoodItemRow`. Justificativa: esporádico; sem animação justa; acessibilidade grátis.

### Consequências
- Positivas: 0 deps; `<details>` reset por re-render não incomoda (usuário expande o que interessa).
- Negativas: sem animação; estado de abertura não persiste entre refreshs (aceito).

---

## Decisão 3 — `RefreshOnFocus` em vez de `revalidate`/ISR

### Contexto
`/day` precisa refletir confirmações/edições feitas pelo chat em outro dispositivo. `force-dynamic` cobre HTTP fetch mas não cobre Router Cache do Next (client-side).

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — `RefreshOnFocus` client (mount + visibilitychange debounce)** (escolhida) | Combate staleness client-side; barato; UX graciosa | 1 fetch extra por mount/focus |
| B — `revalidate={0}` no fetch server | Sem cache HTTP | Não resolve Router Cache client-side |
| C — SWR/React Query no client | Cache e revalidation | State library extra por 1 pagina |
| D — Refresh no `popstate`/`push` | Event-driven | Não cobre `visibilitychange` (cross-device) |

### Decisão tomada
**Opção A** — `RefreshOnFocus` vazio (render null) dispara `router.refresh()` no mount + `visibilitychange` debounce 2s. Justificativa: cobre os dois cenários (mesma app, cross-device); custo baixo em single-user.

### Consequências
- Positivas: dados fresh sem usuário pensar.
- Negativas / dívida técnica: 1 fetch extra por mount (acceptável single-user; rever multi-user); pode re-renderizar abaixo do usuário expandindo `<details>` (estado recolhe) — aceito.

---

## Decisão 4 — Backend sem mudanças

### Contexto
SP-152 requer micros + origem + confiança. Verificou-se se `_load_food` já retornava tudo.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Consumir `_load_food` existente** (escolhida) | Zero mudança backend; zero migração | — |
| B — Novo endpoint `/days/today/details` | Schema dedicado | Endpoint extra; duplicação |
| C — Estender `DaySnapshotOut` | Mais campo | Já tinha tudo |

### Decisão tomada
**Opção A** — Usar `GET /days/today`/`GET /days/{date}` existente; `_load_food` já retornava micros/metadata desde Fase 4.b. `types.ts` no front espelha o shape.

### Consequências
- Positivas: zero regressão de backend; build front único impacto.
- Negativas: especs backend e front devono ficar alinhados; refletir snapshot_version em types.

---

## Decisão 5 — `DayView` compartilhado entre `/day` e `/day/[date]`

### Contexto
SP-150 e SP-154 pedem páginas quase idênticas; diferenças são o endpoint e se é encerramento retroativo.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — `DayView` compartilhado + `allowClose`** (escolhida) | Zero duplicação; layout consistente | 2 entrypoints com fetch similar |
| B — Dois `DayView` separados | Isolamento | Duplicação de render |
| C — 1 page com param opcional | Único | Rota dinâmica static-params wrangling |

### Decisão tomada
**Opção A** — `day/page.tsx` e `day/[date]/page.tsx` chamam `<DayView data={result} allowClose />`. `allowClose=true` em `/day/[date]` para permitir encerramento retroativo (PR #46).

### Consequências
- Positivas: 1 arquivo mantém layout; mudanças em 1 lugar.
- Negativas: `allowClose` flag propaga especialidade; documentado em comments.

---

## Decisão 6 — `CloseDayButton` reusado do chat

### Contexto
T-704 já tinha `CloseDayModal` no chat; Bloco 6 precisa de encerrar do `/day` também.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Reusar `CloseDayModal`** (escolhida) | Consistência UX; zero duplicação | `CloseDayButton` é client (precisa de `useState`) |
| B — Novo modal próprio | Isolamento | Duplica overlay/aria/call |
| C — Redirect pra `/chat` + clicar | Sem código UI | UX péssima |

### Decisão tomada
**Opção A** — `CloseDayButton.tsx` é client, abre `CloseDayModal` importado de `../chat/`; `onClosed` faz `router.refresh()`.

### Consequências
- Positivas: 1 modal mantém 2 entrypoints; mudanças em 1 lugar.
- Negativas: acoplamento front entre Bloco 2 e Bloco 6 — aceitável.

---

## Decisão 7 — Aritmética de datas UTC interna

### Contexto
SP-155 pede `addDaysISO`, `todayLocalISO` para navigator. Avaliava-se usar `Date-fns`/`dayjs` ou matemática manual.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Manual com `Date.UTC`** (escolhida) | Zero dep; controle DST; bundle leve | Código manual (10 linhas) |
| B — `date-fns` | API robusta | ~20 KB dep pra 5 funções |
| C — `dayjs` | Leve | Plugin para UTC/pt-BR |

### Decisão tomada
**Opção A** — `format.ts` tem `isoToParts`/`partsToISO`/`addDaysISO`/`todayLocalISO`/`compareISO` usando `Date.UTC`. Justificativa: 5 funções, zero dep, defensivo contra DST.

### Consequências
- Positivas: zero NPM runtime; SPL Priorização por minimalismo.
- Negativas: manutenção se requisitos crescer (ex.: semanas/meses) — adicionar lib nesse ponto.

---

## Decisão 8 — Futuro bloqueado sem backend hit

### Contexto
SP-155: data futura não deve chamar backend.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — `compareISO` server before fetch** (escolhida) | Economia; UX graciosa; sem 500 | `todayLocalISO` server-side depende do TZ container |
| B — Fetch mesmo; backend 404 | Simples | Request waste; UX fica genérico 404 |
| C — Validate input only | Sem backend | Não cobre hoje vs futuro |

### Decisão tomada
**Opção A** — `day/[date]/page.tsx` checa `compareISO(date, todayLocalISO()) > 0` antes do fetch; renderiza "Não é possível ver o futuro". Justificativa: SP-155 explicita.

### Consequências
- Positivas: 0 round-trip backend; UX clara.
- Negativas: container TZ precisa bater com user; se divergir na borda, backend 404 cobre (`todayLocalISO` server vs browser).

---

## Decisão 9 — Read-only v1 (exceção: confirm/close)

### Contexto
A página `/day` poderia permitir editar/excluir items. Spec SP-154 (v1.8?) dita que mutações continuam via chat na v1.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Read-only + exceções (confirm/close)** (escolhida) | Simples; UI foca em leitura; paridade com spec | Usuário salta pro chat para editar |
| B — Edição inline completa | UX completa | Muta em dia passado complica "data efetiva"; maior escopo |
| C — Edição só em `/day` hoje | Permite mudar dia atual | Inconsistência com `/day/[date]` |

### Decisão tomada
**Opção A** — SEM botões de editar/excluir item na página; `ConfirmItemButton` (não-mutação de valor, só flag) e `CloseDayButton` (encerra, INV-5 respeitado) são exceções. Justificativa: SP-154 explicita; mutação via chat mantém interface única.

### Consequências
- Positivas: escopo controlado; muda pouco em dia fechado (INV-5).
- Negativas / dívida técnica: UX próxima melhoria — edição inline (v2), já mapeada em `app_plan.md`.

---

## Decisão 10 — Path traversal rejeitado por regex antes do fetch

### Contexto
`/day/[date]` recebe param arbitrário; avaliava-se deixar backend rejeitar ou validar client-side.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — `DATE_PATTERN` regex server-side antes do fetch** (escolhida) | Seguro; UX clara; não chega no backend | — |
| B — Passa direto pro backend | Sem código | Backend 422 genérico; risco path matching |
| C — Whitelist de chars | Semântica | Regex é equivalente e più conciso |

### Decisão tomada
**Opção A** — `DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/`; rejeita cedo com ErrorPanel "Data inválida".

### Consequências
- Positivas: segurança defesa em profundidade.
- Negativas: nenhum custo.

---

## Dívida técnica conhecida

| Item | Impacto | Prioridade |
|---|---|---|
| `apps/web` sem Vitest/Playwright — casos alvo só especificados | Regressão visual pega por smoke manual | Média |
| Sem Sentry/analytics front (page views, expand rate) | Difícil medir UX | Média |
| Container TZ pode divergir de user TZ; borda cai em 404 | UX inconsistente em fusos extremos | Baixa (raro em single-user BR) |
| `<details>` estado não persiste entre refreshs | UX recolher ao refresh pós-mutation | Baixa (aceito) |
| `RefreshOnFocus` 1 fetch extra por mount | Custo pífio em single-user; rever em multi | Baixa |
| Edição inline (v2) não mapeada ainda | UX salto pro chat | Média (já em backlog) |
| No toast on `ConfirmItemButton` failure | Usuário não sabe que falhou | Baixa |

## Riscos identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| Container TZ vs browser TZ divergem no limite do dia | Baixa | Médio | `TZ` env var no compose; backend 404 cai em ErrorPanel |
| Router Cache serve snapshot pré-mutação | Alta (sem mitigação) | Médio | `RefreshOnFocus` mount + visibilitychange |
| `<details>` quebra layout em mobile pequeno | Baixa | Baixo | Grid 12-col flex; testar 375px |
| Confirm inline em dia recém-fechado (race) | Baixa | Médio | INV-5 bloqueia backend; `CloseDayButton` some em `closed` |
| Futuro bypass via URL manual | Baixa | Baixo | Sanity client também bloqueia (defense in depth) |
| Narrativa longa quebra layout | Baixa | Baixo | `whitespace-pre-wrap`; aceito sem truncation |
| Link `/weekly` → `/day/[date]` em data fora do histórico | Baixa | Baixo | 404 amigável de SP-154 já cobre |
| `RefreshOnFocus` spama em troca rápida de abas | Média | Baixo | Debounce 2s |