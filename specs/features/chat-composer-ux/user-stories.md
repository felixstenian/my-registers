# Histórias de Usuário — Composer do chat — UX (Bloco 1)

> **Rastreabilidade**: SP-15..SP-19 · Persona principal: Felix.

## Personas

- **Felix (desktop)**: usa teclado; quer enviar rápido com Enter.
- **Felix (mobile)**: usa celular; quer tirar foto direto da câmera.
- **Felix com vários arquivos**: quer anexar múltiplas fotos e arrastar do Finder.

---

### US-001 — Enviar com Enter
**Como** Felix (desktop),
**Quero** apertar Enter para enviar e Shift+Enter para quebrar linha,
**Para que** eu digite rápido sem usar o mouse.

**Critérios de Aceitação resumidos:**
- [ ] Enter sem Shift envia a mensagem.
- [ ] Shift+Enter insere quebra de linha.
- [ ] Textarea vazia + sem mídia → Enter ignorado.
- [ ] Envio em curso → Enter ignorado (anti-duplo).

**Notas:**
- Fonte: SP-15. IME (`isComposing`) respeitado.

---

### US-002 — Tirar foto direto no mobile
**Como** Felix (mobile),
**Quero** que o seletor de arquivo ofereça "Tirar foto",
**Para que** eu fotografe o prato/rótulo sem sair do app.

**Critérios de Aceitação resumidos:**
- [ ] `<input type="file" capture="environment">` em mobile.
- [ ] Câmera traseira preferida por padrão.
- [ ] Em desktop, `capture` é ignorado (seletor normal).

**Notas:**
- Fonte: SP-16.

---

### US-003 — Saber quando excedi o limite de anexos
**Como** Felix com vários arquivos,
**Quero** ver o nome de cada foto rejeitada quando passo de 4,
**Para que** eu saiba quais não foram anexadas.

**Critérios de Aceitação resumidos:**
- [ ] N>4 → aceita os 4 primeiros.
- [ ] Lista nome de cada rejeitado com motivo.
- [ ] Contagem inclui pré-anexados.

**Notas:**
- Fonte: SP-17.

---

### US-004 — Mensagens de erro amigáveis no upload
**Como** Felix,
**Quero** ver "`foto.jpg` é maior que 8 MB" em vez de erro genérico,
**Para que** eu saiba o que fazer.

**Critérios de Aceitação resumidos:**
- [ ] `file_too_large` → cita nome + "maior que 8 MB".
- [ ] `invalid_image` → cita nome + "não parece ser uma imagem válida".
- [ ] `unsupported_media_type` → cita nome + "Envie JPEG, PNG ou WEBP".
- [ ] Batch não aborta por 1 falha.
- [ ] Compositor não fecha nem perde texto.

**Notas:**
- Fonte: SP-18.

---

### US-005 — Arrastar arquivos para o compositor
**Como** Felix com vários arquivos,
**Quero** arrastar fotos do Finder para o compositor,
**Para que** eu não precise abrir o seletor de arquivo.

**Critérios de Aceitação resumidos:**
- [ ] Drop adiciona arquivos (modo append).
- [ ] Aplica mesmas regras (MIME, cap de 4, erros SP-18).
- [ ] Feedback visual enquanto arrasta (borda tracejada).
- [ ] Feedback removido ao sair ou soltar.

**Notas:**
- Fonte: SP-19.

---

### US-006 — Não perder texto ao ver erro de upload
**Como** Felix,
**Quero** que o texto que digitei permaneça se um anexo falhar,
**Para que** eu não precise redigitar.

**Critérios de Aceitação resumidos:**
- [ ] `setText('')` só roda após `POST /chat/messages` sucesso.
- [ ] Erros de upload não limpam o texto.

**Notas:**
- [Inferido do código] linha 329-333.
