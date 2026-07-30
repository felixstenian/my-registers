# Casos de Teste — Composer do chat — UX (Bloco 1)

> **Rastreabilidade**: SP-15..SP-19 · Implementação: `apps/web/src/app/(app)/chat/page.tsx`.
> **Status dos testes automatizados**: [Implementação não localizada] — não há suíte de testes E2E/unitários no `apps/web` (sem `__tests__/`, `tests/` nem config Playwright/Cypress no repo até v1.3.0). Os casos abaixo são a especificação de cobertura **alvo**. <!-- TODO: configurar Playwright + adicionar suited dedicada -->

## Cobertura alvo

- **Unitários**: `mergeFiles` (lógica de cap/MIME/size/overflow), `UPLOAD_REASONS` mapping, `onTextareaKeyDown` (Enter/Shift/IME/sending).
- **Integração (client-side)**: fluxo `uploadMedia` → `POST /chat/messages` → polling, com `fetch` mockado.
- **E2E**: jornada de envio de mensagem com texto + foto via drag-and-drop em viewport desktop e mobile.

---

## Testes Unitários

### TC-U-001 — `mergeFiles` rejeita MIME fora do allowlist
- **Módulo**: `apps/web/src/app/(app)/chat/page.tsx`
- **Função/Método**: `mergeFiles([<video.mp4>], 'replace')`
- **Entrada**: `[{ name: 'clip.mp4', type: 'video/mp4', size: 1000 }]`
- **Saída esperada**: `files=[]`, `fileErrors=["Formato de `clip.mp4` não suportado. Envie JPEG, PNG ou WEBP."]`
- **Tipo**: Edge case (SP-18)

### TC-U-002 — `mergeFiles` rejeita arquivo > 8 MB
- **Função/Método**: `mergeFiles([{ name: 'big.jpg', type: 'image/jpeg', size: 9*1024*1024 }], 'replace')`
- **Saída esperada**: `files=[]`, `fileErrors=[/^`big.jpg` é maior que 8 MB/]`
- **Tipo**: Edge case (SP-18)

### TC-U-003 — `mergeFiles` aplica cap de 4 em modo replace
- **Entrada**: 5 JPEGs válidos, `files` inicial vazio.
- **Saída esperada**: `files.length === 4`, `fileErrors` menciona nome do 5º.
- **Tipo**: Edge case (SP-17)

### TC-U-004 — `mergeFiles` em append acumula respeitando pré-anexados
- **Entrada**: `files=[a,b]`, append de 4 arquivos válidos.
- **Saída esperada**: `files.length === 4` (2 existentes + 2 novos), `fileErrors` lista 2 rejeitados por cap.
- **Tipo**: Edge case (SP-17)

### TC-U-005 — `UPLOAD_REASONS` mapeia códigos do backend
- **Função/Método**: `UPLOAD_REASONS['file_too_large']('x.jpg')`
- **Saída esperada**: contém "maior que 8 MB"; cada código produz string pt-BR com o `{name}` interpolado; código desconhecido → "Não foi possível enviar `{name}`. Tente novamente."
- **Tipo**: Happy path + Edge case (SP-18)

### TC-U-006 — `onTextareaKeyDown` Enter envia em condição válida
- **Entrada**: `{ key: 'Enter', shiftKey: false, nativeEvent: { isComposing: false } }`, `text='oi'`, `sending=false`.
- **Saída esperada**: `preventDefault()` chamado, `performSend` disparado.
- **Tipo**: Happy path (SP-15)

### TC-U-007 — `onTextareaKeyDown` Enter ignorado sob bloqueios
- **Entradas**: (a) `sending=true`; (b) `text=''` e `files=[]`; (c) `{ shiftKey: true }`; (d) `{ nativeEvent: { isComposing: true } }`.
- **Saída esperada**: `performSend` **não** é chamado em nenhuma condição.
- **Tipo**: Edge case (SP-15 + IME)

---

## Testes de Integração (client-side)

### TC-I-001 — Envio com texto + mídia → polling captura resposta
- **Fluxo**: `uploadMedia` (mock 201) → `POST /chat/messages` (mock 200 `{message_id}`) → `GET /chat/messages?after=...` (mock retorna assistant).
- **Pré-condições**: cookie `access_token` presente; `fetch` mockado.
- **Passos**: preencher texto, anexar JPEG válido, disparar `performSend`.
- **Resultado esperado**: `messages` recebe user + assistant; `text=''` e `files=[]`; `awaitingAssistant=false`; `totalsRevalidateKey` incrementa.
- **Tipo**: Happy path

### TC-I-002 — Upload parcialmente falho não aborta envio
- **Fluxo**: `uploadMedia` → 1º 201, 2º 400 `{code:'file_too_large'}` → `POST /chat/messages` só com `media_ids=[id1]`.
- **Resultado esperado**: `fileErrors` contém mensagem do 2º arquivo; mensagem enviada com texto + mídia válida; texto não é limpo se `POST` falha.
- **Tipo**: Error case (SP-18)

### TC-I-003 — Polling atinge `POLL_CAP_MS` (60s) sem resposta
- **Fluxo**: `GET /chat/messages?after=...` sempre vazio; avançar relógio 60s+.
- **Resultado esperado**: `awaitingAssistant=false`, `error` contém "A resposta demorou mais do que o esperado...".
- **Tipo**: Error case

### TC-I-004 — Poll imediato captura resposta já chegada
- **Fluxo**: primeira chamada `tick()` já encontra assistant message.
- **Resultado esperado**: `setInterval` não é agendado; polling encerra em 1 tick.
- **Tipo**: Edge case

---

## Testes E2E

### TC-E-001 — Jornada desktop: texto + drag-and-drop de foto
- **Persona**: Felix (desktop Chrome).
- **Jornada**: /chat → digita "150 g de arroz" → arrasta `prato.jpg` do Finder → solta no compositor → Enter.
- **Passos**:
  1. Verificar borda tracejada aparece durante drag.
  2. Verificar chip com `prato.jpg` no composer após drop.
  3. Verificar mensagem do usuário aparece no histórico com a imagem.
  4. Verificar resposta do assistant surge (mockada ou real).
- **Resultado esperado**: fluxo completo sem erros; feedback visual em cada etapa.

### TC-E-002 — Jornada mobile: captura de câmera
- **Persona**: Felix (mobile Safari/Chrome).
- **Passos**: abrir `input file` → verificar oferta de "Tirar foto" → capturar (mock de câmera) → verificar anexo.
- **Resultado esperado**: `capture="environment"` renderizado; fluxo de envio conclui.
- **Notas**: E2E real depende de device farm; emuladores podem não expor `capture`.

### TC-E-003 — Erro de limite de anexos visível
- **Passos**: anexar 5 JPEGs via input em desktop.
- **Resultado esperado**: 4 chips no composer; lista de erro com nome do 5º arquivo em `<ul role="alert">`.

### TC-E-004 — Erro de tamanho visível antes do upload
- **Passos**: arrastar JPEG de 9 MB.
- **Resultado esperado**: nenhum chip; mensagem de erro "maior que 8 MB" aparece imediatamente (sem round-trip).

---

## Testes de Regressão

Casos críticos a manter a cada release do compositor:

- **R-001** (SP-15): Enter envia; Shift+Enter quebra; Enter durante `sending` não dispara duplicado.
- **R-002** (SP-17): cap de 4 respeitado em ambos modos (`replace`/`append`) com nomes nos erros.
- **R-003** (SP-18): cap de 8 MB client-side bloqueia antes do upload; texto não perdido em falha.
- **R-004** (SP-19): `dragCounterRef` evita flicker ao transitar entre filhos; feedback removido ao drop/leave.
- **R-005**: poll imediato + `POLL_CAP_MS=60s` (timeout gracioso).
- **R-006**: `credentials: 'include'` + `cache: 'no-store'` em `POST /media` (cookie `access_token` enviado).