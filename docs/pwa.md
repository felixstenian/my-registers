# PWA — como instalar e o que esperar

Referência: spec §3.13 (SP-128..SP-135). Bloco 4 no `tasks.md`.

O app é instalável como PWA em iOS Safari, Android Chrome/Edge e desktop Chrome/Edge. **Requer HTTPS** — em `localhost` funciona sem TLS, mas em outros hosts é obrigatório.

## Instalar

### iOS Safari (iPhone/iPad)

1. Abra `https://myregister.felix.dev.br` no Safari (não funciona em outros browsers do iOS).
2. Botão "Compartilhar" (quadrado com seta) na barra inferior.
3. Rola até "Adicionar à Tela de Início".
4. Confirma o nome e toque em "Adicionar".

Depois disso o app abre em standalone (sem barra do Safari). O ícone tem cor `#0f172a` e as letras `mr`.

### Android Chrome / Edge

Um de dois caminhos:

- Se o browser mostrou um banner "Instalar app" na parte inferior — toca nele.
- Ou: menu (3 pontos) → "Instalar app" (às vezes aparece como "Adicionar à Tela de Início").

O app também vai exibir um botão **"Instalar"** no header quando o Chrome dispara o evento `beforeinstallprompt` — é a alternativa dentro da própria app.

### Desktop Chrome / Edge

- Ícone de instalação (monitor com seta pra baixo) aparece na barra de endereço quando o app é elegível.
- Ou: menu (3 pontos) → "Instalar my-registers".

## Como saber se está instalado

Aberto em standalone (sem barra de endereço do browser) = instalado. Em iOS a app aparece na tela de início com o ícone customizado; em Android idem; em Desktop vira uma janela independente com sua própria entrada no Dock/Taskbar.

## Atualizações

Toda vez que um deploy novo sobe, o service worker detecta a nova versão em background. Quando você abre a app:

1. SW novo instala silenciosamente (fica em `waiting`).
2. Um toast persistente "Nova versão disponível" aparece no rodapé.
3. Clique em "Recarregar" — o SW novo assume e a página recarrega com o código atualizado.

Se você fechar a app sem atualizar, o SW novo continua em `waiting` na próxima abertura até você recarregar — não perde a atualização.

## Offline

O que funciona sem conexão:

- **Shell da app** (HTML, CSS, JS estáticos) é servido do cache do SW.
- Navegações pra rotas já visitadas retornam o HTML cacheado.
- Ícones e manifest carregam do cache.

O que **não** funciona:

- Toda chamada `/api/*` (dados de negócio) é bloqueada por design (**INV-11**). Nunca cacheamos totais, mensagens ou registros — snapshots vêm sempre do banco (Const. Art. III §10).
- Rotas nunca visitadas caem na página `/offline`.

Se você tentar ações que dependem da API (enviar mensagem, encerrar dia), a request vai falhar. Uma futura versão pode implementar fila offline (feature `B-08` no backlog).

## Como desinstalar

- **iOS:** long-press no ícone → "Remover App".
- **Android:** long-press → arrastar pra lixeira, ou Settings → Apps → my-registers → Desinstalar.
- **Desktop Chrome/Edge:** dentro da app, menu (3 pontos) → "Desinstalar my-registers".

Desinstalar apaga o cache do SW e cookies isolados da app; login é perdido.

> Também é o único jeito, no iOS, de puxar ícone/manifest novos após
> um deploy que trocou esses assets. Ver seção
> [Ícones ou manifest não atualizam após deploy](#ícones-ou-manifest-não-atualizam-após-deploy).

## Diagnóstico (dev/ops)

### O botão "Instalar" não aparece

- Browser não suporta `beforeinstallprompt` (Safari, Firefox mobile).
- App já está instalada (o botão some após `appinstalled`).
- Manifest tem erro — abre DevTools → Application → Manifest e confirma que carregou sem warnings.

### O toast "Nova versão" não aparece após deploy

- SW ainda não detectou. Force via DevTools → Application → Service Workers → "Update on reload" + reload.
- Deploy pode ter mantido o mesmo `sw.js` — Serwist regenera o bundle a cada build.

### Ícones ou manifest não atualizam após deploy

O service worker cacheia `manifest.webmanifest`, `sw.js` e os PNGs de
ícone com estratégia cache-first (via `defaultCache` do Serwist). Depois
que o usuário instalou a app, esses assets podem ficar no cache do SW
por até 24-48h — mesmo com deploy novo — se o update flow for ignorado.

Sintomas típicos:

- Ícone antigo continua no home screen do iOS/Android
- "Nome" da app na tela de instalação ainda é o velho
- `manifest.webmanifest` que o DevTools mostra é a versão anterior

Ordem de resolução:

1. **Aceite o toast "Nova versão disponível"** quando aparecer — dispara
   `SKIP_WAITING` e recarrega com o SW novo. É o caminho normal.
2. **Force update manual** se o toast não aparecer:
   - DevTools → Application → Service Workers → clique em "skipWaiting"
     no worker em `waiting`, seguido de reload.
   - Ou clique em "Unregister" e recarrega — o SW novo instala do zero.
3. **Ícone do home screen (iOS)** só atualiza quando o usuário
   desinstala e reinstala a app. iOS não re-lê o manifest depois que a
   app foi adicionada. Aviso: reinstalar apaga cookies isolados do
   PWA — usuário precisa fazer login de novo.
4. **Android/Chrome desktop** relêem o manifest a cada abertura
   standalone; um "Fechar tudo" + reabrir normalmente pega a versão
   nova em ≤ 1 dia.

**Regra pro operador:** ao trocar ícone/manifest, deploy + esperar
propagação do SW **não é suficiente** pra que o home screen atualize em
usuários já instalados. Comunicar reinstalação é o único caminho
determinístico. Isso vale mesmo mudando `theme_color`, `short_name`,
etc. Uma mudança silenciosa em `.png` só aparece pra novos usuários.

### `/offline` aparece mesmo online

- SW está servindo cache stale porque a rede falhou dentro dos 5s do `networkTimeoutSeconds`.
- Verifica se a API responde: `curl -I https://myregister.felix.dev.br/api/health`.

### Lighthouse PWA score

Rodar local:

```bash
pnpm --filter web build
pnpm --filter web start &
sleep 3
npx lighthouse http://localhost:3000/chat --only-categories=pwa --view
```

Meta: score ≥ 90 (T-B409 gate).

## Arquivos-chave

| Arquivo | Papel |
|--|--|
| `apps/web/src/app/manifest.ts` | Manifest webapp (SP-128) |
| `apps/web/src/app/layout.tsx` | Meta tags iOS + link do manifest (SP-129) |
| `apps/web/src/app/sw.ts` | Service Worker (SP-130 + INV-11) |
| `apps/web/src/app/sw-update-prompt.tsx` | Toast de update (SP-132) |
| `apps/web/src/app/(app)/InstallButton.tsx` | Botão instalar (SP-133) |
| `apps/web/src/app/offline/page.tsx` | Fallback offline (SP-135) |
| `apps/web/public/icons/` | Ícones 192/512/180/maskable (SP-131) |
| `apps/web/scripts/verify-sw.mjs` | Sanity check estático (T-B409) |
