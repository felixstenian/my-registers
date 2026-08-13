# Trade-offs — Composer do chat — UX (Bloco 1)

> **Rastreabilidade**: SP-15..SP-19 · [`architecture.md`](./architecture.md) · Bloco 1 (T-B101..T-B105) em [`specs/001-mvp-registro-diario/tasks.md`](../../001-mvp-registro-diario/tasks.md).
> Não há ADR específica para o Bloco 1 (decisões de UI registradas inline no `tasks.md` e neste arquivo).

## Decisão 1 — Componente único `ChatPage` (sem decomposição)

### Contexto
Bloco 1 introduziu SP-15..19 (envio, câmera, cap de anexos, erros, drag-and-drop) sobre o `ChatPage` já existente. Estado altamente acoplado: envio depende de `text`+`files`+`sending`; polling depende de `lastIdRef`; modais dependem de `totalsRevalidateKey`. Avaliava-se extrair hooks (`useComposer`, `useChatPolling`, `useFileAttachments`).

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Componente único** (escolhida) | Estado co-localizado sem lift; menos arquivos/alocação; refatoração barata depois | Arquivo de 568 linhas; teste unitário exige mock pesado do componente todo |
| B — Hooks customizados (`useFileAttachments`, `usePolling`) | Testável isoladamente; legibilidade | Lift de estado entre hooks; boilerplate; ganho pequeno no MVP |
| C — Decomposição em sub-componentes (`MessageList`, `Composer`, `DropZone`) | Separação visual | Props-drilling profundo; estado compartilhado impede corte limpo |

### Decisão tomada
**Opção A** — Manter `ChatPage` como componente único. Justificativa: o acoplamento entre os estados faz a decomposição custar mais em plumbing do que em clareza no escopo MVP; refatoração postergada sem custo técnico crescente (入口 único).

### Consequências
- Positivas: mudanças em fluxo de envio/anexar ficam em um arquivo; menos risco de desincronia entre hooks.
- Negativas / dívida técnica: arquivo grande; testes unitários dedicados a `mergeFiles` exigem extração futura. Registrado em `architecture.md` (Decisão 1).

---

## Decisão 2 — Replicar validações do backend client-side

### Contexto
Backend (`POST /media`, SP-11) já valida allowlist MIME, cap de 4 anexos e 8 MB por arquivo. A questão: confiar só no backend ou antecipar client-side?

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Validar client-side + backend** (escolhida) | Feedback imediato (sem round-trip); arquivos de 100 MB não derrubam o proxy Next | Duplicação de constantes (`ACCEPT_MIME`, `MAX_FILE_BYTES`) entre client e backend |
| B — Só backend | Sem duplicação; fonte única de verdade | UX lenta; arquivos gigantes podem falhar no proxy antes do JSON de erro |
| C — Só client-side | Sem duplicação de regras no servidor | Inseguro: DevTools bypassa (viola Art. III §10 implícito — backend é fonte) |

### Decisão tomada
**Opção A** — Replicar `MAX_FILE_BYTES=8MB`, `ACCEPT_MIME` e cap de 4 no client. A duplicação é deliberada e comentada no topo do `page.tsx` ("Deve refletir o allowlist do backend"). Backend continua a fonte de verdade da segurança.

### Consequências
- Positivas: UX; resiliência ao proxy Next derrubar requests grandes.
- Negativas / dívida técnica: se backend mudar allowlist (ex.: ACEPitar HEIC futuro), `ACCEPT_MIME` precisa atualização manual. Risco baixo (raramente muda).

---

## Decisão 3 — `mergeFiles` com modos `replace` vs `append`

### Contexto
Input file nativo substitui a seleção anterior; drag-and-drop intuitivamente acumula. Avaliava-se unificar num único modo.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — `replace` para input, `append` para drop** (escolhida) | Espelha intenção do gesto; consistente com apps de upload comuns | Lógica com branch (`base = mode === 'append' ? files : []`) |
| B — Sempre `replace` | Mais simples | Drop apaga pré-anexados — frustrante |
| C — Sempre `append` | Consistente | Input file não acumula por padrão (precisaria workaround) |

### Decisão tomada
**Opção A** — Modo explícito por origem. Implementação: `page.tsx:214-262`.

### Consequências
- Positivas: UX natural; sem workaround em nenhum modo.
- Negativas: branch de lógica no `mergeFiles` (mínimo).

---

## Decisão 4 — `dragCounterRef` para mitigar flicker de enter/leave

### Contexto
`dragenter`/`dragleave` disparam ao transitar entre filhos do `<form>` (textarea, chips, botões), causando flicker na borda tracejada. Avaliava-se usar `relatedTarget` checks ou `pointer-events: none` nos filhos.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Contador via `useRef`** (escolhida) | Robusto; não depende de estrutura filha; 1 ref | Ligeiramente mais estado |
| B — `relatedTarget.contains(form)` | Sem estado extra | Frágil com SVG/elements dinâmicos; edge cases |
| C — `pointer-events: none` em filhos durante drag | Zero JS | Pode bloquear tooltips/ui; quebra acessibilidade |

### Decisão tomada
**Opção A** — `dragCounterRef` incrementa em `dragenter`, decrementa em `dragleave`, `isDragging=false` só quando 0. Implementação: `page.tsx:116,362-378`.

### Consequências
- Positivas: feedback estável; tolerante a estrutura filha mudar.
- Negativas: nenhum custo significativo.

---

## Decisão 5 — Poll imediato antes do `setInterval`

### Contexto
Resposta do assistente pode chegar em <1500ms (primeiro tick). Avaliava-se só usar `setInterval` ou começar com `setTimeout`:

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Poll imediato + setInterval 1500ms** (escolhida) | Captura resposta rápida; UX responsiva | 1 chamada extra no pior caso |
| B — Só setInterval | Mais simples | UX percebe latência de 1500ms mesmo já pronta |
| C — WebSocket/SSE | Push real-time | Infra mais complexa; backend usa poll (ADR-009 `BackgroundTasks`) |

### Decisão tomada
**Opção A** — `tick()` chamado imediatamente; se não resolve, agenda `setInterval(tick, POLL_INTERVAL_MS)`. `pollRef` guardado para cleanup. Implementação: `page.tsx:163-197`.

### Consequências
- Positivas: latência percebida mínima; continua respeitando `POLL_CAP_MS=60s`.
- Negativas: 1 fetch extra em path pessimista; desprezível vs UX.

---

## Decisão 6 — `capture="environment"` como dica (não garantia)

### Contexto
SP-16 pede "câmera traseira em mobile". O atributo HTML `capture` é uma dica (`hint`) ao SO; depende do browser/OS; em desktop é ignorado.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — `capture="environment"` como dica** (escolhida) | Zero custo; melhor UX mobile sem afetar desktop | Não garante câmera traseira em todos OS |
| B — Detecção mobile + UX condicional | Controle | Complexidade; user-agent sniffing frágil |
| C — Ignorar SP-16 no MVP | Sem pré-requisitos mobile | Perde appetizer mobile |

### Decisão tomada
**Opção A** — Atributo no `<input type="file">`; spec aceita comportamento "ignorado em desktop". Implementação: `page.tsx:523`.

### Consequências
- Positivas: mobile já oferece "Tirar foto" quando suportado.
- Negativas: dispositivos sem câmera traseira podem abrir front cam; aceito como fronteira.

---

## Dívida técnica conhecida

| Item | Impacto | Prioridade |
|---|---|---|
| Componente `ChatPage` de 568 linhas — sem extração de hooks | Legibilidade/testabilidade | Baixa (funciona; refatorar ao adicionar 4ª feature de chat) |
| Ausência de testes E2E de composer (`apps/web` sem Playwright/Cypress) | Regressão de UX só pega via smoke manual | Média (ver [`test-cases.md`](./test-cases.md)) |
| Constantes duplicadas client/backend (`ACCEPT_MIME`, `MAX_FILE_BYTES`) | Mudança no backend exige sync manual | Baixa (allowlist raramente muda) |
| Sem telemetria de erros client-side | Falhas de upload/upload só visíveis ao usuário | Média (Sentry/analytics não configurado) |

## Riscos identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| Browser mobile ignora `capture` | Alta (varia por SDK) | Baixo | Texto-placeholder explicita fluxo; backend aceita qualquer MIME do allowlist |
| Usuário anexa 4 fotos > 8 MB | Média | Baixo | Erro client-side imediato por arquivo; texto preservado |
| Polling atinge 60s em pico de Anthropic | Baixa | Médio | Timeout gracioso explica; resposta ainda pode chegar (msg exibe isso) |
| DevTools bypassa client-side | Alta | Baixo | Backend re-invalidates (SP-11); segurança não depende do client |
| Estado `files` e `sending` dessincronizam com foco fora do tab | Baixa | Médio | `startPolling` + `useEffect(() => stopPolling, ...)` para cleanup on unmount; `sending` em `try/finally` |