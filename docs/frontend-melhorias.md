# Levantamento de melhorias — front-end (`apps/web`)

Data: 2026-07-30 · Escopo: `apps/web` (Next.js 16 App Router + React 19 + Tailwind 3.4 + Serwist 9.5)

Levantamento estático do front-end em busca de melhorias de código e boas práticas, organizado em **tarefas FE-XX para implementação posterior**. Nenhuma alteração de código foi aplicada neste levantamento.

## Baseline executado

| Check | Resultado |
|---|---|
| `pnpm --filter web typecheck` | ✅ passa |
| `pnpm --filter web lint` | ❌ quebrado — `next lint` não existe mais no Next 16 e não há config de ESLint no repo (ver FE-05) |

## Convenções deste documento

- **Severidades**: `bloqueante` (bug funcional / quebra de INV / viola Constituição) · `alta` (erro de runtime provável, estado inconsistente, UX quebrada) · `média` (manutenibilidade, performance perceptível, DRY) · `baixa` (nitpick, micro-otimização).
- **Risco**: chance de a correção introduzir regressão.
- IDs `FE-XX` são locais deste documento, sem relação com os `T-XXX` do `tasks.md` SDD.

## Restrições que NENHUMA tarefa pode violar

- **INV-11**: `sw.ts` mantém `NetworkOnly` em `/api/*`. Não introduzir cache de API. Se `sw.ts` for tocado, rodar `pnpm --filter web verify:sw`.
- **Art. VII §26**: o aviso legal não pode ser removido de nenhuma view (FE-12 só centraliza, não remove).
- **Art. VIII**: dia `closed` é imutável — nenhuma tarefa pode introduzir UI de edição em dia fechado.
- **Polling do chat**: manter `POLL_CAP_MS` (60s) e `stopPolling('timeout')` em qualquer refactor (FE-06, FE-16).
- **Build**: manter `--webpack` (Serwist não suporta Turbopack).
- **proxy.ts**: validação real de auth é no backend; não adicionar lógica de auth no proxy.

---

## Prioridade 1 — severidade alta

### FE-01 — Hardening do `api-client` contra falha de rede + feedback em ações silenciosas ✅

**Severidade**: alta · **Risco**: baixo (mudança contida no `api-client` + ajustes pontuais nos chamadores)
**Status**: concluído (2026-07-30). `api()` envolve `fetch` em try/catch → `{ ok: false, error: { code: 'network_error' }, status: 0 }`. Chamadores trataram `!ok`: ConfirmItemButton (alert inline + idle), PendingItemsModal (alert + item permanece), WeeklyReportView (retry), DayTotalsBar (erro discreto + retry, mantém dados velhos em revalidação), `uploadMedia` (try/catch próprio). CloseDayModal já tinha fase `error`. Typecheck/lint verdes.

**Achados cobertos**:

```
[alta] src/lib/api-client.ts:23 — fetch sem try/catch propaga exceção de rede
Problema: `api()` não captura exceção de rede (offline, backend fora, CORS).
Todo chamador sem try/catch próprio vira unhandled rejection — e todos,
exceto LoginForm, estão nesse caso.
Sugestão: envolver o fetch em try/catch e retornar
`{ ok: false, error: { code: 'network_error', message: 'Falha de rede. Verifique sua conexão.' }, status: 0 }`.
Assim todos os chamadores caem no ramo `!result.ok` que já deveriam tratar.

[alta] src/app/(app)/day/ConfirmItemButton.tsx:26 — botão trava em "confirmando…" se a rede falhar
Problema: exceção de rede deixa `state='confirming'` para sempre; e quando a
API responde erro, o botão volta a `idle` sem avisar nada ao usuário.
Sugestão: com FE-01, tratar `!result.ok` exibindo mensagem inline e voltando a `idle`.

[alta] src/app/(app)/chat/PendingItemsModal.tsx:44-61 — confirm/discard sem feedback de erro
Problema: se a API falha, `busyId` reseta e nada acontece na tela — usuário
clica e não tem resposta nenhuma.
Sugestão: estado de erro inline no modal (`role="alert"`), mantendo o item na lista.

[alta] src/app/(app)/chat/CloseDayModal.tsx:78 — trava em "Encerrando o dia…" se a rede falhar
Problema: exceção de rede deixa o modal na fase `submitting` indefinidamente.
Sugestão: coberto pelo try/catch do api-client + transição para fase `error`.

[alta] src/app/(app)/weekly/WeeklyReportView.tsx:70 — trava em "Carregando…" se a rede falhar
Problema: exceção de rede no efeito inicial deixa a tela em loading eterno.
Sugestão: coberto pelo try/catch do api-client → fase `error` com botão "tentar novamente".

[média] src/app/(app)/chat/page.tsx:289 — performSend sem catch
Problema: falha de rede no loop de upload ou no POST final não mostra erro
algum (só o `finally` reseta `sending`).
Sugestão: com api-client capturando, `uploadMedia` precisa do mesmo tratamento
(fetch próprio em chat/page.tsx:63) e `performSend` deve exibir mensagem acionável.

[média] src/app/(app)/chat/DayTotalsBar.tsx:78 — load sem tratamento de erro
Problema: falha silenciosa mantém dados velhos; falha de rede na 1ª carga
deixa "Carregando totais do dia…" para sempre.
Sugestão: estado de erro discreto na barra com retry.
```

**Critério de aceite**: com o backend derrubado, nenhuma ação do front fica em estado de loading eterno e todas exibem mensagem acionável em pt-BR. `pnpm --filter web typecheck` verde.

---

### FE-02 — Corrigir estado stale do `DayNavigator` entre navegações ✅

**Severidade**: alta · **Risco**: baixo
**Status**: concluído (2026-07-30). `useState(date)` → `useState<string | null>(null)` + `picked = edit ?? date` (padrão React 19 "state derived from prop"); input mostra a data da rota atual após soft nav. Sem `useEffect`, sem remount via `key`. Typecheck/lint verdes.

```
[alta] src/app/(app)/day/DayNavigator.tsx:23 — `picked` não acompanha a prop `date`
Problema: em soft navigation `/day/X` → `/day/Y` (links "Dia anterior"/"Próximo
dia"), o Next preserva o estado de client components na mesma posição da árvore.
O input de data continua mostrando X e o botão "Ir" navega de volta para X.
Sugestão: guardar apenas a edição do usuário — `useState<string | null>(null)`
e valor efetivo `picked ?? date` — ou renderizar com `<DayNavigator key={date} />`
no DayView para forçar remount por data.
```

**Critério de aceite**: navegar por "Dia anterior"/"Próximo dia" atualiza o input para a data da página atual.

---

### FE-03 — Validar parâmetro `next` no LoginForm (open redirect) ✅

**Severidade**: alta (segurança) · **Risco**: baixo
**Status**: concluído (2026-07-30). `nextParam` → `safeNext` via IIFE que aceita apenas paths começando com `/` e não `//`; fallback `/chat`. `?next=https://evil.com` cai em `/chat`; `?next=/day` segue funcionando. Typecheck/lint verdes.

```
[alta] src/app/(auth)/login/LoginForm.tsx:16 — redirect para URL arbitrária após login
Problema: `searchParams.get('next')` vai direto para `router.replace()`. Uma URL
`/login?next=https://evil.com` redireciona o usuário autenticado para fora do app.
Sugestão: aceitar apenas paths internos:
  const raw = searchParams.get('next');
  const nextParam = raw && raw.startsWith('/') && !raw.startsWith('//') ? raw : '/chat';
```

**Critério de aceite**: `?next=https://evil.com` cai em `/chat`; `?next=/day` continua funcionando.

---

### FE-04 — Tratamento consistente de 401/403 no client ✅

**Severidade**: média-alta · **Risco**: médio (toca comportamento global de todas as chamadas)
**Status**: concluído (2026-07-30). `api()` no `api-client.ts`: 401 em path não-`/auth/*` → `window.location.assign('/login?next=<pathname+search>')`. Guard anti-loop (`isRedirectingToLogin`) evita N redirects concorrentes (poll + revalidação). `typeof window` check para SSR-safe. LoginForm (`/auth/login`) e logout (`/auth/logout`) excluídos. Typecheck/lint verdes.

```
[média] src/lib/api-client.ts — sessão expirada não redireciona
Problema: com o cookie expirado, o chat para de carregar mensagens, a
DayTotalsBar fica vazia e nada leva o usuário de volta ao login (o proxy só
checa presença do cookie, não validade).
Sugestão: no api-client, ao receber 401 em path que não seja `/auth/*`,
redirecionar para `/login?next=<pathname atual>` (window.location.assign).
Não inventar endpoint novo; reaproveitar o fluxo já existente do proxy.
```

**Critério de aceite**: cookie inválido + qualquer ação no chat → redirect para `/login` com `next` correto; falha de login em `/auth/login` NÃO redireciona.

---

## Prioridade 2 — severidade média

### FE-05 — Restaurar lint do front-end ✅

**Severidade**: média (tooling — impede baseline de qualidade) · **Risco**: baixo
**Status**: concluído (anteriormente ao levantamento). `package.json` já usa `lint: eslint .`, ESLint 9 + `eslint-config-next@16` em devDeps, `eslint.config.mjs` flat config presente, CI roda `pnpm --filter web lint` (`.github/workflows/ci.yml:104`). `RefreshOnFocus.tsx` já tem deps `[router]` corretas (sem `eslint-disable` residual). Lint passa com 0 erros (2 warnings pré-existentes: `postcss.config.mjs` default-export e `<img>` no chat — cobertos por FE-15).

```
[média] apps/web/package.json:9 — script `lint` quebrado
Problema: Next 16 removeu `next lint`; o script falha com "Invalid project
directory provided". Não existe eslint.config nem dependência de ESLint no
workspace, e o CI (job web) não roda lint.
Sugestão: adicionar `eslint` + `eslint-config-next` como devDeps, criar
`eslint.config.mjs` (flat config), trocar o script para `eslint .`, e incluir
no job web do `.github/workflows/ci.yml`.

[baixa] src/app/(app)/day/RefreshOnFocus.tsx:32 — eslint-disable de linter inexistente
Problema: comentário `eslint-disable-next-line react-hooks/exhaustive-deps`
referencia um setup que não existe. Ao ativar o lint, reescrever o efeito com
deps corretas em vez de manter o disable.
```

**Critério de aceite**: `pnpm --filter web lint` roda e passa (ou lista dívidas explícitas aprovadas); CI executa o lint.

---

### FE-06 — Memoização da lista de mensagens do chat

**Severidade**: média (performance perceptível) · **Risco**: médio (cuidado com props instáveis)

```
[média] src/app/(app)/chat/page.tsx:419-468 — a cada tecla digitada, todas as
mensagens re-renderizam e todo o markdown é re-parseado
Problema: `text` (composer) e `messages` vivem no mesmo componente; cada
keystroke re-executa `parseBlocks` de todas as assistant messages.
Sugestão: extrair `MessageBubble` com `React.memo` recebendo a message e um
boolean `confirmed` derivado de `confirmedFacts` (não passar o Set — identidade
muda a cada confirmação). Opcionalmente memoizar `parseBlocks` por content.
```

**Critério de aceite**: digitar no composer não re-renderiza balões de mensagens já existentes (verificável via React DevTools Profiler). Poll e `POLL_CAP_MS` intactos.

---

### FE-07 — Scroll automático inteligente no chat

**Severidade**: média (UX) · **Risco**: médio (comportamento sutil de scroll)

```
[média] src/app/(app)/chat/page.tsx:145-147 — scroll forçado ao fundo em toda
mudança de `messages`
Problema: usuário lendo o histórico é jogado para o fundo quando chega
mensagem nova pelo poll.
Sugestão: só auto-scrollar se o usuário já estiver perto do fundo (ex.:
`scrollHeight - scrollTop - clientHeight < 120` medido antes de aplicar a
nova mensagem) ou sempre que a última mensagem for do próprio usuário.
```

**Critério de aceite**: mensagem nova não arranca o usuário do meio do histórico; envio próprio continua scrollando para o fundo.

---

### FE-08 — `PendingItemsModal` não deve fechar a cada ação

**Severidade**: média (UX) · **Risco**: médio (muda contrato pai↔filho)

```
[média] src/app/(app)/chat/page.tsx:400-404 — onChanged fecha o modal após
cada confirmação/descarte
Problema: com 3 itens pendentes, o usuário precisa reabrir o modal 3 vezes
(badge → modal → ação → fecha → repete). O estado vazio do modal ("Nenhum item
pendente. Você pode fechar.") indica que o design original era permanecer aberto.
Sugestão: onChanged apenas revalida `/days/today`; o pai repassa `items`
atualizados ao modal aberto; modal sugere fechamento quando a lista esvaziar.
```

**Critério de aceite**: confirmar um item mantém o modal aberto com os demais; lista vazia mostra o estado vazio existente.

---

### FE-09 — `error.tsx` no grupo `(app)`

**Severidade**: média (UX/robustez) · **Risco**: baixo

```
[média] src/app/(app)/day/page.tsx:20 e (app)/layout.tsx:18 — fetch server-side
sem boundary de erro amigável
Problema: backend fora do ar faz `fetch` lançar exceção → tela de erro genérica
do Next (e em produção, ainda pior). `fetchToday`/`fetchMe` só tratam `!res.ok`.
Sugestão: `error.tsx` client no grupo `(app)` com mensagem pt-BR e botão
`tentar novamente` (reset). Opcionalmente `loading.tsx` para /day.
```

**Critério de aceite**: backend derrubado → página /day mostra erro amigável com retry, não a tela padrão do Next.

---

### FE-10 — Centralizar tipos da API em `src/lib/types.ts`

**Severidade**: média (DRY) · **Risco**: baixo

```
[média] Tipos duplicados entre componentes
Problema: `Totals` é definido em CloseDayModal.tsx:21 e WeeklyReportView.tsx:7;
`DayResponse` (DayTotalsBar.tsx:28) duplica `DaySnapshot` (day/types.ts);
`FoodItemRef` é exportado por um componente de UI; `Message`/`MediaRef` vivem
na page do chat.
Sugestão: `src/lib/types.ts` espelhando os schemas do backend (DaySnapshot,
DayTotals, WeeklyResponse, Message, MediaRef, FoodItemRef), consumido por chat,
day e weekly. day/types.ts passa a re-exportar os shapes compartilhados e manter
só labels/constantes locais (MEAL_SLOT_*, *_LABEL_PT).
```

**Critério de aceite**: cada shape de resposta da API definido em um único lugar; typecheck verde.

---

### FE-11 — Centralizar formatters em `src/lib/format.ts`

**Severidade**: média (DRY) · **Risco**: baixo

```
[média] Intl.NumberFormat/DateTimeFormat re-implementados em 4 arquivos
Problema: `nfInt`/`fmtInt` duplicados em CloseDayModal.tsx:43, DayTotalsBar.tsx:49,
PendingItemsModal.tsx:24 e WeeklyReportView.tsx:39 vs. day/format.ts. `fmtDatePt`
(CloseDayModal.tsx:56) é cópia quase idêntica de `fmtDateFull`; `fmtDateShort`/
`fmtWeekday` (WeeklyReportView.tsx:50-60) repetem o parse `split('-')`.
Sugestão: promover day/format.ts a src/lib/format.ts (format.ts é o único lugar
para Intl/pipes) e importar de lá em todos os componentes.
```

**Critério de aceite**: nenhum `new Intl.*` fora de `src/lib/format.ts`; saída visual idêntica.

---

### FE-12 — Componente `LegalDisclaimer` compartilhado

**Severidade**: média (risco de divergência em texto obrigatório — Art. VII §26) · **Risco**: baixo

```
[média] Texto legal duplicado em 5 lugares
Problema: DayView.tsx:167, WeeklyReportView.tsx:273, chat/page.tsx:562,
login/page.tsx:18 e offline/page.tsx:20 repetem o aviso obrigatório. Qualquer
mudança futura no texto precisa acertar 5 arquivos.
Sugestão: `<LegalDisclaimer />` em src/components (server component puro) com
o texto canônico, usado nos 5 pontos. NÃO remover de nenhuma view — apenas
centralizar a fonte.
```

**Critério de aceite**: texto existe em um único arquivo; as 5 views continuam exibindo o aviso.

---

### FE-13 — Lazy-load dos modais do chat

**Severidade**: média-baixa (bundle) · **Risco**: baixo

```
[média] src/app/(app)/chat/page.tsx:14-16 — modais raramente abertos no bundle inicial
Problema: CloseDayModal + PendingItemsModal (~370 linhas) entram no bundle do
chat mesmo sem nunca serem abertos.
Sugestão: `next/dynamic` para ambos (também no import de CloseDayModal em
day/CloseDayButton.tsx:9).
```

**Critério de aceite**: modais abrem normalmente; chunk separado visível no build.

---

### FE-14 — Acessibilidade e consistência dos modais

**Severidade**: média (a11y) · **Risco**: médio

```
[média] CloseDayModal.tsx e PendingItemsModal.tsx — sem Escape, sem focus
management, backdrop inconsistente
Problema: nenhum modal fecha com Escape nem move foco para dentro/retorna foco
ao fechar; `role="dialog"` sem `aria-labelledby`; PendingItemsModal fecha ao
clicar no backdrop, CloseDayModal não.
Sugestão: hook `useModalA11y(onClose)` (Escape + foco inicial + retorno de
foco), `aria-labelledby` apontando para o título, e decidir um comportamento de
backdrop único (recomendado: não fechar no backdrop em fluxo destrutivo —
CloseDayModal — e fechar nos demais).
```

**Critério de aceite**: Escape fecha ambos; foco entra no modal ao abrir e volta ao gatilho ao fechar; leitor de tela anuncia o título.

---

## Prioridade 3 — severidade baixa

### FE-15 — Limpezas pontuais

**Severidade**: baixa · **Risco**: baixo

```
[baixa] src/app/(app)/chat/AssistantContent.tsx:1 — `'use client'` redundante
Problema: não usa hooks/eventos; só é importado por client component, então a
diretiva não muda nada além de ruído.
Sugestão: remover a diretiva.

[baixa] src/app/(app)/chat/page.tsx:458 — non-null assertion `m.nutrient_fact_id!`
Problema: o guard no JSX já garante o valor; o `!` é ruído.
Sugestão: extrair `const factId = m.nutrient_fact_id` antes do bloco condicional.

[baixa] src/proxy.ts:8,32 — prefixo `/days` morto
Problema: não existe rota `/days` no app; matcher e PROTECTED_PREFIXES carregam
resíduo.
Sugestão: remover `/days` de ambos.

[baixa] src/app/(app)/chat/page.tsx:440 — imagens sem lazy loading e alt vazio
Problema: histórico longo com fotos carrega tudo de uma vez; `alt=""` trata
conteúdo enviado pelo usuário como decorativo.
Sugestão: `loading="lazy"` + `alt="Imagem anexada"` (URLs são dinâmicas do
backend — manter `<img>`, não trocar por next/image).

[baixa] src/app/(app)/chat/page.tsx:302 — uploads sequenciais
Problema: até 4 arquivos sobem um após o outro.
Sugestão: `Promise.all` sobre `uploadMedia` (ordem do array é preservada,
então ids e erros continuam alinhados aos arquivos).

[baixa] src/app/(app)/chat/page.tsx:63 — uploadMedia duplica lógica de fetch
Problema: fetch próprio com parse de erro paralelo ao api-client (justificado
por FormData/multipart).
Sugestão: ensinar o api-client a não setar content-type quando
`body instanceof FormData` e consumir `api()` também no upload.

[baixa] Classes Tailwind repetidas (~10 botões/badges idênticos)
Problema: strings de classe copiadas em vários componentes.
Sugestão (opcional): pequenos componentes Button/Badge ou constantes de classe.
```

**Critério de aceite**: typecheck verde; comportamento idêntico.

---

### FE-16 — Extrair hooks da `chat/page.tsx`

**Severidade**: média (manutenibilidade) · **Risco**: médio-alto — **fazer por último, isoladamente**

```
[média] src/app/(app)/chat/page.tsx — 568 linhas misturando view + poll +
upload + drag-drop + modais
Problema: página concentra 6 responsabilidades; qualquer mudança exige entender
o arquivo inteiro.
Sugestão: extrair `useChatPoll` (pollRef/pollStartRef/lastIdRef + start/stop,
mantendo POLL_CAP_MS e o tick imediato) e `useFileAttachments` (mergeFiles,
removeFileAt, drag handlers + contador). Envio (performSend) pode virar
`useSendMessage`. Fazer uma extração por PR, sem mudar comportamento.
Armadilha conhecida: closures do `useCallback` sobre `lastIdRef`/`pollRef` —
refs devem continuar refs (não virar state) para o interval não capturar valor
stale.
```

**Critério de aceite**: page abaixo de ~250 linhas; fluxo de envio/poll/upload byte-a-byte idêntico; typecheck verde + smoke manual do chat.

---

## Resumo executivo

| # | Tarefa | Severidade | Risco | Arquivos principais |
|---|---|---|---|---|
| FE-01 | api-client: captura de erro de rede + feedback em ações | alta | baixo | `lib/api-client.ts`, 6 chamadores |
| FE-02 | DayNavigator: estado stale entre dias | alta | baixo | `day/DayNavigator.tsx` |
| FE-03 | LoginForm: validar `?next=` | alta | baixo | `login/LoginForm.tsx` |
| FE-04 | 401 client-side → redirect login | média-alta | médio | `lib/api-client.ts` |
| FE-05 | Restaurar ESLint + CI | média | baixo | `package.json`, `eslint.config.mjs`, `ci.yml` |
| FE-06 | Memoizar lista de mensagens | média | médio | `chat/page.tsx` |
| FE-07 | Scroll automático inteligente | média | médio | `chat/page.tsx` |
| FE-08 | PendingItemsModal persistente | média | médio | `chat/page.tsx`, `chat/PendingItemsModal.tsx` |
| FE-09 | error.tsx no (app) | média | baixo | `(app)/error.tsx` (novo) |
| FE-10 | Tipos centralizados | média | baixo | `src/lib/types.ts` (novo) |
| FE-11 | Formatters centralizados | média | baixo | `src/lib/format.ts` (novo) |
| FE-12 | LegalDisclaimer compartilhado | média | baixo | `src/components/` (novo) |
| FE-13 | Lazy-load de modais | média-baixa | baixo | `chat/page.tsx`, `day/CloseDayButton.tsx` |
| FE-14 | A11y dos modais | média | médio | `chat/CloseDayModal.tsx`, `chat/PendingItemsModal.tsx` |
| FE-15 | Limpezas pontuais | baixa | baixo | vários |
| FE-16 | Extrair hooks do chat/page | média | médio-alto | `chat/page.tsx` |

**Ordem sugerida de execução**: FE-05 (restaura o baseline de lint) → FE-01, FE-02, FE-03, FE-04 (altas, independentes entre si) → FE-10, FE-11, FE-12 (DRY, preparam o terreno) → FE-06..FE-09, FE-13, FE-14 → FE-15 → FE-16 (por último e isolado, por risco).
