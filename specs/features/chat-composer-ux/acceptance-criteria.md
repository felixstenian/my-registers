# Critérios de Aceitação — Composer do chat — UX (Bloco 1)

> **Rastreabilidade**: SP-15..SP-19 · Contratos: [`requirements.md`](./requirements.md), [`specifications.md`](./specifications.md).

## AC-001 — Envio por Enter (SP-15)

**Dado que** o compositor tem texto não-vazio (ou mídia anexada) e não há envio em curso,
**Quando** o usuário pressiona Enter (sem Shift, fora de composição IME),
**Então** a mensagem é enviada e o polling da resposta do assistente inicia.

**Dado que** o usuário está compondo texto multilinha,
**Quando** pressiona Shift+Enter,
**Então** uma quebra de linha é inserida (comportamento nativo) sem enviar.

**Dado que** o compositor está vazio (sem texto e sem mídia) OU há envio em curso,
**Quando** o usuário pressiona Enter,
**Então** a tecla é ignorada (anti-duplo-envio / anti-envio vazio).

**Notas de validação:**
- Considera `event.nativeEvent.isComposing` (IME chinês/japonês/coreano).
- `event.preventDefault()` só é chamado quando o envio vai ocorrer; caso contrário o Enter nativo fluiria.
- Implementação: `onTextareaKeyDown` em `apps/web/src/app/(app)/chat/page.tsx:349`.

---

## AC-002 — Captura de câmera em mobile (SP-16)

**Dado que** o usuário está em um dispositivo mobile com câmera,
**Quando** abre o seletor de anexo,
**Então** o SO oferece "Tirar foto" além de "Escolher da galeria", preferindo a câmera traseira.

**Dado que** o usuário está em desktop,
**Quando** abre o seletor de anexo,
**Então** `capture="environment"` é ignorado e o seletor de arquivo normal aparece.

**Notas de validação:**
- `capture` é dica para o SO; não garante câmera traseira em todos os dispositivos.
- Implementação: `<input type="file" capture="environment">` em `page.tsx:517-532`.

---

## AC-003 — Limite de 4 anexos com feedback por nome (SP-17)

**Dado que** o usuário seleciona N arquivos válidos (após filtro de MIME/tamanho) e a soma com pré-anexados excede 4,
**Quando** `mergeFiles` processa a seleção,
**Então** os 4 primeiros são aceitos e cada excedente é listado por nome com motivo "Limite de 4 anexos por mensagem".

**Dado que** o usuário arrasta 6 arquivos (drag-and-drop) já tendo 2 anexados,
**Quando** solta os arquivos,
**Então** apenas 2 dos 6 arrastados são aceitos (total=4) e os outros 4 constam na lista de erro por nome.

**Notas de validação:**
- Contagem inclui arquivos pré-anexados (`base` em modo append).
- Modo `replace` (input file) substitui `base=[]`; modo `append` (drop) acumula.
- Implementação: `mergeFiles` em `page.tsx:214-262`.

---

## AC-004 — Mensagens de erro amigáveis por arquivo (SP-18)

**Dado que** o backend rejeita upload com `code='file_too_large'`,
**Quando** `uploadMedia` retorna `{ ok: false, file, reason }`,
**Então** a UI exibe "`` `foto.jpg` `` é maior que 8 MB e não pode ser enviada. Reduza a qualidade ou tire outra."

| `code` do backend | Mensagem pt-BR (com `{name}` substituído) |
|---|---|
| `file_too_large` | `` `{name}` é maior que 8 MB e não pode ser enviada. Reduza a qualidade ou tire outra. `` |
| `invalid_image` | `` `{name}` não parece ser uma imagem válida. `` |
| `unsupported_media_type` | `` Formato de `{name}` não suportado. Envie JPEG, PNG ou WEBP. `` |
| `empty_upload` | `` `{name}` está vazia. `` |
| desconhecido | `` Não foi possível enviar `{name}`. Tente novamente. `` |

**Dado que** há 3 arquivos e 1 falha no upload,
**Quando** o batch termina,
**Então** os 2 válidos são anexados/enviados e apenas o rejeitado aparece em `fileErrors` (batch não aborta).

**Dado que** o upload falha mas o texto está preenchido,
**Quando** `performSend` finaliza,
**Então** o texto permanece (limpeza só ocorre após `POST /chat/messages` sucesso).

**Notas de validação:**
- Cap de 8 MB também validado client-side (`MAX_FILE_BYTES`) para feedback antes do round-trip.
- Implementação: `UPLOAD_REASONS` em `page.tsx:55-61`, `uploadMedia` em `63-87`, `performSend` em `289-340`.

---

## AC-005 — Drag-and-drop de arquivos (SP-19)

**Dado que** o usuário arrasta arquivos do Finder sobre o compositor,
**Quando** `dragenter` dispara (`dataTransfer.types` inclui `Files`),
**Então** o compositor exibe borda tracejada + fundo diferenciado (`isDragging=true`).

**Dado que** o usuário arrasta sobre filhos do formulário e depois sai,
**Quando** `dragleave` equilibra os contadores (`dragCounterRef` atinge 0),
**Então** o feedback visual é removido sem flicker.

**Dado que** o usuário solta os arquivos,
**Quando** `onDrop` dispara,
**Então** os arquivos são processados por `mergeFiles(dropped, 'append')` aplicando MIME/cap/erros (SP-17/18).

**Notas de validação:**
- `dragCounterRef` evita flicker ao transitar entre elementos filhos.
- Em mobile, comportamento touch do SO prevalece; drop é opcional (spec aceita).
- Implementação: `onDragEnter`/`onDragOver`/`onDragLeave`/`onDrop` em `page.tsx:362-387`.

---

## AC-006 — Polling de resposta do assistente

**Dado que** a mensagem do usuário foi enviada com sucesso,
**Quando** `startPolling` inicia,
**Então** poll imediato + `setInterval(1500ms)` buscam `GET /chat/messages?after={lastId}` até surgir `role='assistant'` ou atingir 60s.

**Dado que** 60s se passam sem resposta,
**Quando** `POLL_CAP_MS` é atingido,
**Então** polling para e erro gracioso é exibido ("A resposta demorou mais do que o esperado...").

**Notas de validação:**
- Poll imediato previta resposta já chegada dentro do primeiro intervalo.
- Ao receber assistant message, `totalsRevalidateKey++` dispara revalidação da `DayTotalsBar` (SP-116).
- [Inferido do código] — relacionado à feature `assistant-message-rendering`.

---

## Cenários de Borda

| Cenário | Comportamento Esperado |
|---|---|
| Mesmo arquivo selecionado 2x seguidas via input | `e.target.value=''` após change permite re-selecionar após remover. |
| Arquivo com MIME vazio (`file.type=''`) | Rejeitado por `ACCEPT_MIME` → erro `unsupported_media_type`. |
| Drop de itens não-File (texto, URL arrastada) | `dataTransfer.types` sem `Files` → handlers retornam cedo, nada muda. |
| Drop durante envio em curso (`sending=true`) | Arquivos são anexados ao estado (não há bloqueio explícito); envio atual não é afetado. |
| Upload retorna JSON sem `code` | `code='upload_failed'` → mensagem genérica "Não foi possível enviar...". |
| Resposta do assistente chega antes do primeiro tick | Poll imediato captura; `setInterval` não chega a ser agendado. |

## Critérios de Não-Funcionalidade

| Critério | Threshold |
|---|---|
| Feedback de erro client-side (8 MB, MIME) | Imediato, sem round-trip |
| Intervalo de polling | 1500ms |
| Cap de polling (timeout gracioso) | 60000ms |
| Limite de anexos | 4 por mensagem |
| Tamanho máx. por arquivo (client-side) | 8 MB (`MAX_FILE_BYTES`) |
| Cookies em upload | `credentials: 'include'` |
| Cache de upload | `cache: 'no-store'` |