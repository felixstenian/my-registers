# Histórias de Usuário — PWA — instalabilidade + shell offline (Bloco 4)

> **Rastreabilidade**: SP-128..SP-135 + INV-11 · Personas: Felix (mobile), Felix (desktop), Felix (iOS).

## Personas

- **Felix (Android)**: quer instalar na home screen e abrir como app.
- **Felix (iOS)**: quer adicionar à tela de início e ver standalone sem barra do Safari.
- **Felix (desktop)**: quer ícone na barra de tarefas/dock abrindo como janela standalone.
- **Felix offline**: perdeu sinal no metrô e quer ao menos ver a app sem tela branca.
- **Felix pós-deploy**: quer ver o que mudou sem fechar todas as abas.

---

### US-001 — Instalar como app no Android (SP-128/131/133)
**Como** Felix (Android),
**Quero** ver um banner/botão "Instalar" e ter o app instalável com ícone na home screen,
**Para que** eu abra como app em vez de navegar pelo navegador.

**Critérios de Aceitação resumidos:**
- [ ] `beforeinstallprompt` disparado; botão "Instalar" aparece no header.
- [ ] Clique abre prompt nativo; install cria ícone.
- [ ] App abre em `display: standalone` (sem UI do browser).
- [ ] Ícone 192/512/maskable corretos no manifest.

**Notas:**
- Fonte: SP-128/131/133. Botão some em `display-mode: standalone`.

---

### US-002 — Adicionar à tela de início no iOS (SP-129)
**Como** Felix (iOS),
**Quero** usar "Adicionar à Tela de Início" no Safari e abrir standalone,
**Para que** eu não veja a barra do Safari.

**Critérios de Aceitação resumidos:**
- [ ] `apple-mobile-web-app-capable=yes` no root layout.
- [ ] `apple-touch-icon` 180×180.
- [ ] `status-bar-style=default`.
- [ ] App abre em modo standalone.

**Notas:**
- Fonte: SP-129. iOS não tem `beforeinstallprompt`; install via menu Share.

---

### US-003 — Abrir rápido com shell offline (SP-130)
**Como** Felix offline,
**Quero** que a app carregue (pelo menos o shell) mesmo offline,
**Para que** eu não veja tela branca do browser.

**Critérios de Aceitação resumidos:**
- [ ] `/_next/static/*` cacheado (SWR).
- [ ] Navegações HTML: `NetworkFirst` com fallback pro shell.
- [ ] `/api/*` nunca cacheado (INV-11).
- [ ] `navigationPreload` paralleliza network com SW boot.

**Notas:**
- Fonte: SP-130 + INV-11.

---

### US-004 — Ver página amigável offline (SP-135)
**Como** Felix offline,
**Quero** ver uma página "Sem conexão" com botão "Tentar novamente",
**Para que** eu saiba que falta internet e tente quando voltar.

**Critérios de Aceitação resumidos:**
- [ ] Rota carregada offline (sem cache HTML) cai em `/offline`.
- [ ] Página exibe mensagem + aviso legal (Art. VII §26) + botão.
- [ ] Click no botão faz `window.location.reload()`.

**Notas:**
- Fonte: SP-135. Fallback só para `destination === 'document'`.

---

### US-005 — Saber quando há versão nova (SP-132)
**Como** Felix pós-deploy,
**Quero** ver um toast "Nova versão disponível" com botão "Recarregar",
**Para que** eu atualize sem precisar fechar todas as abas.

**Critérios de Aceitação resumidos:**
- [ ] SW novo em `installed` + já existe `controller` → toast aparece.
- [ ] Clique em "Recarregar" → `SKIP_WAITING` + reload em `controllerchange`.
- [ ] Toast some após reload (waitingWorker = null no novo carregamento).
- [ ] Erros de registro do SW são silenciosos (não quebram app).

**Notas:**
- Fonte: SP-132. `skipWaiting` é opt-in.

---

### US-006 — Não ver o botão "Instalar" depois de instalado (SP-133)
**Como** Felix já instalado,
**Quero** que o botão "Instalar" some,
**Para que** a UI não tenha ruído desnecessário.

**Critérios de Aceitação resumidos:**
- [ ] `display-mode: standalone` → botão oculto no mount.
- [ ] `appinstalled` event → estado `installed=true`.
- [ ] Navegadores sem `beforeinstallprompt` (Safari/Firefox) nunca mostram o botão.

**Notas:**
- Fonte: SP-133.

---

### US-007 — Ver aviso legal sempre, mesmo offline (Const. Art. VII §26)
**Como** Felix,
**Quero** ver o disclaimer "As estimativas nutricionais são aproximações..." na `/offline`,
**Para que** eu saiba que não substitui acompanhamento profissional mesmo sem fluxo ativo.

**Critérios de Aceitação resumidos:**
- [ ] `/offline` tem o aviso em footer (fonte reduzida mas legível).

**Notas:**
- Fonte: Constituição Art. VII §26 reforçado por SP-135.

---

### US-008 — (opcional) Splash iOS não branco (SP-134)
**Como** Felix (iOS) abrindo standalone,
**Quero** ver uma splash com branding em vez de tela branca,
**Para que** a abertura pareça app nativo.

**Critérios de Aceitação resumidos:**
- [ ] `apple-touch-startup-image` para iPhone SE/8 + iPhone 15/16 Pro (3 sizes).
- [ ] iPad opcional.

**Notas:**
- Fonte: SP-134. **Status: adiado (T-B408)**, depende de asset de design real. Currently tela branca ~500ms.