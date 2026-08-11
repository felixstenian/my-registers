# Trade-offs — PWA — instalabilidade + shell offline (Bloco 4)

> **Rastreabilidade**: SP-128..SP-135 + INV-11 · Bloco 4 (T-B401..T-B410) em [`tasks.md`](../../001-mvp-registro-diario/tasks.md). Não há ADR específica para PWA — decisões registradas inline no `tasks.md`/`docs/pwa.md` e neste arquivo.

## Decisão 1 — Serwist em vez de Workbox/`next-pwa`

### Contexto
Bloco 4 precisava de um service worker com runtime caching declarativo em Next 16. Opções: Workbox puro (manual), `next-pwa` (wrapper comum) ou Serwist.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — `@serwist/next`** (escolhida) | Suporte Next 16 first-class; manutenção ativa; API declarativa idêntica ao Workbox | Lib mais jovem que Workbox (~2024) |
| B — `next-pwa` | Wrapper muito usado | **Arquivado** (mantenedor declarou end-of-life); quebra em Next 15+ |
| C — Workbox puro | Muito estável (Google) | Setup manual pesado; sem convenção Next |

### Decisão tomada
**Opção A** — Serwist via `@serwist/next` ^9.5.12. Justificativa: `next-pwa` archived elimina a escolha óbvia; Serwist é a continuação comunitária e está mantida.

### Consequências
- Positivas: config declarativa em 1 arquivo (`next.config.mjs`); `runtimeCaching` com classes Workbox-familiar; `disable` em dev transparente.
- Negativas / dívida técnica: Serwist não suporta Turbopack (ver Decisão 2).

---

## Decisão 2 — Build `--webpack` em vez de Turbopack

### Contexto
Next 16 suporta Turbopack por padrão em `next dev`/`next build`, mas Serwist ainda não é compatível ([serwist/serwist#54](https://github.com/serwist/serwist/issues/54)).

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — `--webpack` em dev e build** (escolhida) | Serwist funciona; Sem mudanças de comportamento | Perde ganhos de velocidade do Turbopack |
| B — Turbopack sem Serwist | Build orbit | Perde PWA |
| C — Turbopack + SW manual (sem Serwist) | Velocidade + PWA | Reimplementa runtimeCaching à mão — custo alto |

### Decisão tomada
**Opção A** — `dev` e `build`scripts usam `--webpack` explicitamente (ver `apps/web/package.json`).

### Consequências
- Positivas: PWA funciona; sem trabalho manual.
- Negativas / dívida técnica: lentidão relativa em builds grandes; tracking do issue serwist#54 para migrar quando suportado.

---

## Decisão 3 — `skipWaiting: false` (update opt-in via toast)

### Contexto
Quando um novo SW é baixado, ele entra em `waiting` até o anterior ser desativado. Workbox/Serwist permite `skipWaiting: true` (automático) ou herdar manualmente.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Opt-in via toast "Recarregar"** (escolhida) | Usuário decide quando; não quebra fluxos a meio (ex.: modal aberto) | Latência de update; usuário pode demorar a recarregar |
| B — `skipWaiting: true` automático | Novidades chegam rápido | Quebra fluxos in-flight; reload fora de controle |
| C — Sem prompt (só `clientsClaim` no novo) | Sem UI | Update pode nunca chegar (abas abertas mantêm velho SW) |

### Decisão tomada
**Opção A** — `skipWaiting: false` + `clientsClaim: true` + toast `SwUpdatePrompt` que manda `SKIP_WAITING`. Justificativa: próximo do O que aplicativos web maduros fazem (GitHub/GitLab). Implementação: `sw.ts:16`, `sw-update-prompt.tsx:62`.

### Consequências
- Positivas: UX previsível; usuário pode ignorar toast se ocupado.
- Negativas: alguns usuários em versão antiga; próximo deploy não força sync.

---

## Decisão 4 — `NetworkOnly` para `/api/*` (INV-11)

### Contexto
PWA permite `NetworkFirst`/`StaleWhileRevalidate` para servir dados offline. INV-11 proíbe cache de `/api/*` (negócio sempre do DB — Art. III §10). Já estava como restrição; restava confirmar a estratégia.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — `NetworkOnly` matcher `/api/`** (escolhida) | Garante INV-11; alcance auditável | Online required p/ dados |
| B — `NetworkFirst` com timeout 5s | Degrada gracefully offline | Servi totais obsoletos se cache hit |
| C — Sem matcher `/api/` (default cache) | Fácil | Violação direta INV-11 |

### Decisão tomada
**Opção A** — `new NetworkOnly()` no matcher `/^https?:\/\/[^/]+\/api\//`. `verify-sw.mjs` (T-B409) checa no CI.

### Consequências
- Positivas: integridade garantida; gate de regressão no CI.
- Negativas: sem dados offline — trade-off aceito (sem cache de totais do dia no MVP).

---

## Decisão 5 — `/offline` fora de `PROTECTED_PREFIXES`

### Contexto
`proxy.ts` protege `/chat`/`/weekly`/`/day` por cookie. `/offline` precisa ser acessível mesmo offline sem cookie.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — `/offline` público** (escolhida) | Acessível offline sem cookie; UX previsível | Sem auth check na página |
| B — `/offline` protegido | Consistente com outras rotas | Erro 401 offline → tela branca |

### Decisão tomada
**Opção A** — `/offline` **não** está em `PROTECTED_PREFIXES`. Justificativa: feedback mínino ao usuário numa situação de erro.

### Consequências
- Positivas: UX graciosa offline.
- Negativas: руки/a vulnerabilidade nula — `/offline` é estática, sem dados de usuário.

---

## Decisão 6 — `verify-sw.mjs` estático em vez de Vitest

### Contexto
T-B409 queria garantir INV-11 com cada PR. Avaliava-se adicionar Vitest + jsdom para teste unit do SW, ou check estático no bundle/Código.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Sanity estático via regex em `sw.ts`/bundle** (escolhida) | Zero nova dependency; roda em CI em ~50ms | Não testa comportamento runtime |
| B — Vitest + jsdom + sw testing | Testa realmente | Adicionar framework só por 1 assertion (T-B409 explicitou) |
| C — Puppeteer/Playwright testando SW | E2E real | Muito pesado para-config; CI lento |

### Decisão tomada
**Opção A** — `scripts/verify-sw.mjs` faz 5 asserts estáticos (matcher `/api/`, `NetworkOnly`, fallback `/offline`, `SKIP_WAITING`, bundle content). Justificativa: custo baixoão, pega regressões óbvias; Lighthouse PWA no prod completa o quadro.

### Consequências
- Positivas: CI enxuto; gate pré-merge effettivo.
- Negativas / dívida técnica: se alguém usar `StaleWhileRevalidate` ao invés de `NetworkOnly` no matcher `/api/`, verify pega; mas se naming de class mudar, regex pode quebrar — manutenção mínima.

---

## Decisão 7 — Ícones placeholder via `sharp` a partir de SVG

### Contexto
SP-131 requer 4 ícones PNG. Sem asset de design pronto, o time decidiu gerar placeholders deterministicamente.

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Placeholders via `sharp`** ('mr' em fundo `#0f172a`) (escolhida) | PWA funciona imediatamente; DPI/dim corretos | UI ainda não tem branding final |
| B — Aguardar asset de design | Branding | Bloqueia release |
| C — Stainless stock icon | Sem dependência | Sem branding; ruído |

### Decisão tomada
**Opção A** — script inline `sharp` gera 4 PNGs a partir de `icon.svg`. `docs/pwa.md` documenta pendência de substituir.

### Consequências
- Positivas: instalação funciona (Android/iOS/desktop); bloqueio não-infringido.
- Negativas / dívida técnica: ícone 'mr' provisório; T-B408 (SP-134 splash iOS) adiado justamente por depender do asset final.

---

## Decisão 8 — Toast de update em vez de banner permanente

### Contexto
SP-132 pede "toast persistente com botão Recarregar". Conceito: persistente quanto tempo? Discreto ou em face?

### Opções consideradas
| Opção | Prós | Contras |
|---|---|---|
| **A — Toast fixo bottom-center, removível só via reload** (escolhida) | Visto sem roubar foco; some após reload | Persiste entre rotas (poder food) — UX aceita |
| B — Banner no topo | Mais vísivel | Roubar espaço vertical |
| C — Modal blockante | Update crítico | Quebra UX |

### Decisão tomada
**Opção A** — `fixed bottom-4 left-1/2 z-50`; `role="alert"`; botão "Recarregar". Justificativa: SP-132 diz persistente — fica até reload (ação esperada).

### Consequências
- Positivas: discreto; acessível (`role="alert"`); um botão.
- Negativas: persistente pode incomodar — aceito pois só acontece após deploy.

---

## Dívida técnica conhecida

| Item | Impacto | Prioridade |
|---|---|---|
| Ícones placeholder (sem branding real) | UX de instalação ilustra 'mr' | Média — substituir quando asset chegar |
| T-B408 (SP-134 splash iOS) adiado | iOS mostra tela branca ~500ms abertura standalone | Baixa (SP é `may`) |
| Sem Vitest no `apps/web` — cobertura unitária é alvo apenas | Regressão só pega pelo Sanit + Lighthouse manual | Média — ver [`test-cases.md`](./test-cases.md) |
| `controllerchange` reload cada aba — versões divergentes entre abas até reload | Inconsistência temporal | Baixa (raro) |
| Sem telemetria SW (install/update/err) | Difícil medir adoption PWA | Média |
| `next-pwa`/Workbox archive — Sem migração alternativa documentada | Risk de Serwist future archive | Baixa |

## Riscos identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| Serwist quebra em Next major upgrade | Média | Alto | Tracking issue serwist#54; pin ^9.5.12 no lockfile |
| `verify-sw.mjs` regex falha ao renomear classes Serwist | Baixa | Médio | Manter regex wide (`SkipWaiting`, `NetworkOnly`); check de bundle cobre nomes loaded |
| Ícone padrão rejeitado por Lighthouse | Baixa | Médio | 192/512/maskable todos PNG com dimension válidos; Lighthouse score já verificado parcial |
| Usuário nunca vê update toast (subir scroll esconde) | Baixa | Baixo | `fixed bottom-4` sempre visível |
| Cache Storage acumula stale HTML | Média | Baixo | `StaleWhileRevalidate` revalida; `precache` Serwist limpa versões antigas |
| `/api/*` cacheado por erro futuro | Baixa | Alto (viola INV-11) | `verify-sw.mjs` bloqueia merge; code review|
| iOS WebKit não respeita `appleWebApp` | Média (var пор iOS) | Médio | Testar em Safari real; metatags são spec Apple |
| Splash iOS branco por T-B408 adiado | Alta (esperado) | Baixo | Documentado em `docs/pwa.md`; some quando asset chegar |