---
name: frontend-improvements
description: Use when reviewing, auditing, or refactoring the Next.js 16 + React 19 front-end in apps/web (src/app, src/lib, proxy.ts). Covers React/Next patterns, web performance, maintainability/DRY, and error/loading state handling. Triggers on requests like "review the front-end", "find improvements in apps/web", "audit chat/day/weekly components", or when touching .tsx/.ts files under apps/web/src.
---

# Front-end improvements (apps/web)

Aplica-se apenas ao front-end em `apps/web` (Next.js 16 App Router + React 19 + Tailwind + Serwist). **Não use** para o backend `apps/api` nem para configuração do próprio opencode.

## Quando ativar

- O usuário pede revisão/auditoria/refatoração do front-end, ou cita `chat`, `day`, `weekly`, `apps/web`, componentes `.tsx`, ou "melhorias no front".
- O usuário está editando arquivos sob `apps/web/src` e pede sugestões de melhoria.
- **Não ativar** para: backend Python, migrations, infra Docker, docs SDD, ou config do opencode.

## Escopo de categorias (priorize nesta ordem)

1. **React/Next patterns** — modelagem de componentes e uso correto do App Router.
2. **Performance web** — bundle, imagens, SW, fetch.
3. **Manutenibilidade/DRY** — duplicação, extração, naming.
4. **Tratamento de erros/loading** — edge cases do `api-client`, estados de UI.

## Stack e regras fixas (não inventar)

Confirmar lendo o código antes de sugerir — não assumir bibliotecas não presentes em `apps/web/package.json`:

- **Next.js 16.2.10** App Router, **React 19.0.0**, **TypeScript 5.7 strict**, **Tailwind 3.4**, **Serwist 9.5** (PWA).
- Build **usa `--webpack`** (Serwist ainda não suporta Turbopack — issue serwist/serwist#54). Nunca sugerir trocar para Turbopack.
- Service worker em `src/app/sw.ts` aplica `NetworkOnly` em `/api/*` (INV-11). Não sugerir estratégias de cache para rotas de API.
- `src/lib/api-client.ts` é o único cliente HTTP: `api<T>()` retorna `ApiResult<T>` discriminated union (`{ ok: true; data } | { ok: false; error }`). Sempre tratar os dois ramos — nunca usar `as` para escapar do `ok`.
- Paths: `@/*` → `./src/*`. Server components que chamam a API usam `INTERNAL_API_URL`; browser usa relativo `/api` via proxy em `src/proxy.ts`.
- Código/comentários em **inglês**; docs SDD e commits em **pt-BR** (regra do repo). Não adicionar comentários ao código a menos que o usuário peça.
- Restrições da Constituição que afetam o front: aviso legal obrigatório (Art. VII §26) em toda view de dia/semana; dia `closed` é imutável (Art. VIII) — UI não deve oferecer edição nesses casos.

## Checklist de análise

Para cada arquivo sob revisão, percorra:

### React/Next patterns
- Componente deve ser `'use client'` só se usar hooks/eventos; caso contrário prefira Server Component.
- `useEffect` com dependências faltando/sobrando; `useCallback`/`useMemo` só quando mede re-render real (não micro-otimizar sem motivo).
- `key` em listas: estável e único (não usar índice se a lista reordena). Em `chat/page.tsx` as chaves de `files` usam `${file.name}-${idx}` — flag se virar padrão em outras listas.
- Props drilling vs composição; estado local onde deveria ser derivado.
- Fetch em Server Components com `cache: 'no-store'` (já padrão do `api-client`) — não sugerir `force-cache` para dados de chat/dia.
- PWA: `sw.ts` e `manifest.ts` só mexer se o pedido for explicitamente PWA.

### Performance web
- `next/image` para imagens estáticas em `public/`; `<img>` só para URLs dinâmicas de mídia do backend (já é o caso em `chat`).
- Imports pesados dinâmicos (`next/dynamic`) para modais usados raramente (ex.: `CloseDayModal`, `PendingItemsModal`).
- Evitar água em client components: mover lógica pura para fora de `'use client'`.
- Não sugerir lazy de componentes já no caminho crítico acima da dobra.
- Re-renders: estado que muda a cada tick de poll (`messages`, `awaitingAssistant`) — conferir se filhos pesados são memoizados.

### Manutenibilidade/DRY
- Componentes com >250 linhas misturando view + lógica: propor extração de hooks (`useChatPoll`, `useFileAttachments`).
- Strings de erro UI duplicadas — centralizar em `src/lib/error-messages.ts` se virar padrão.
- Formatação (`format.ts` em `day/`) é o único lugar para `Intl`/pipes — não re-implementar inline.
- Tipos duplicados entre `apps/web` e respostas da API: sugerir tipos em `src/lib/types.ts` espelhando o schema do backend, nunca `any`.
- Convenção de naming: arquivos de componente em PascalCase (`AssistantContent.tsx`); hooks/util em camelCase.

### Tratamento de erros/loading
- Toda chamada `api<T>()` deve tratar `!result.ok` com mensagem acionável ao usuário (não só `console.error`).
- Estados de loading explícitos (`sending`, `awaitingAssistant`) — conferir cobertura para toda ação async.
- Polling em `chat/page.tsx`: `POLL_CAP_MS` de 60s com `stopPolling('timeout')` — não remover; se sugerir mudança, manter o cap.
- Falha de rede (fetch throw): o `api-client` não captura exceção de rede — flag se um chamador não envolve em try/catch.
- 401/403: atualmente sem interceção global; se surgir, sugerir redirect para `/login` consistente (não inventar endpoint novo).

## Como reportar (sempre em pt-BR)

Para cada melhoria encontrada, liste:

```
[severidade] arquivo:linha — título
Problema: <o que está errado, em 1-2 frases>
Sugestão: <como corrigir, com snippet se útil>
Risco: <baixo/médio/alto + por que>
```

Severidades:
- **bloqueante** — bug funcional, quebra de INV, ou viola Constituição.
- **alta** — erro de runtime provável, estado inconsistente, UX quebrada.
- **média** — manutenibilidade, performance perceptível, DRY gritante.
- **baixa** — nitpick de estilo, micro-otimização sem medição.

## Aplicação de fixes (fluxo "Relatar + propor fix")

1. Rode `pnpm --filter web typecheck && pnpm --filter web lint` antes de sugerir qualquer fix para ter baseline.
2. Relate **todas** as melhorias (não apenas as que vai aplicar).
3. Proponha fixes apenas para melhorias **triviais e seguras** (ex.: `key` faltando, dependência de `useEffect`, erro não tratado óbvio, extração de hook sem mudar comportamento).
4. **Não aplique** automaticamente: refactors que tocam >1 arquivo, mudanças em `sw.ts`/`proxy.ts`, mudanças em lógica de poll, qualquer coisa que toque estado global ou invariantes (INV-11, Art. VII §26, Art. VIII).
5. Antes de aplicar, mostre o diff proposto e aguarde confirmação.
6. Após aplicar, rode novamente `pnpm --filter web typecheck` e, se o SW for tocado, `pnpm --filter web verify:sw` (garante INV-11).
7. Nunca commitar — o usuário decide.

## Armadilhas conhecidas deste repo

- `chat/page.tsx` é grande (~568 linhas) com poll + upload + drag-drop + modais —refatorar exige cuidado com closures do `useCallback` e com `lastIdRef`/`pollRef`.
- `DayView.tsx` e `WeeklyReportView.tsx` compartilham o Disclaimer (Art. VII §26) — não remover nem duplicar.
- `proxy.ts` valida só presença de cookie; validação real é no backend — não sugerir lógica de auth no proxy.
- `next.config.mjs` tem config específica para o Serwist; mexer sem ler o `verify-sw.mjs` pode quebrar INV-11.
