# Histórias de Usuário — Chat e mensagens

## Personas

- **Felix (P1)** — usuário final, conversa em pt-BR.
- **Sistema (não-persona)** — governança de histórico (auditoria + Const. §21).

---

### US-001 — Enviar mensagem simples de texto

**Como** Felix,
**Quero** digitar "150g arroz, 90g feijão" e apertar Enviar,
**Para que** o backend registre e me devolva a tabela em segundos.

**Critérios de aceitação resumidos:**
- [ ] `POST /chat/messages { text }` → 202 imediato.
- [ ] Assistant message chega via polling em até ~6s (P50).
- [ ] Sem mídia = OK.

**Cobertura**: SP-10, RF-001.

---

### US-002 — Enviar foto do prato

**Como** Felix,
**Quero** anexar 1-4 fotos e mandar sem texto,
**Para que** o assistente identifique os alimentos.

**Critérios de aceitação resumidos:**
- [ ] Upload prévio via `POST /media` devolve `media_id`.
- [ ] `POST /chat/messages { media_ids: [...] }` linka.
- [ ] Sem texto + sem mídia → 422.
- [ ] > 4 mídias → 422.

**Cobertura**: SP-11, RF-002, RF-004.

---

### US-003 — Não perder histórico ao corrigir

**Como** Felix,
**Quero** corrigir "o arroz era 200g" e ver que a mensagem original **fica** no chat,
**Para que** eu tenha rastro do que aconteceu.

**Critérios de aceitação resumidos:**
- [ ] Correção não deleta mensagens antigas.
- [ ] `GET /chat/messages?before=<id>` navega histórico.
- [ ] `audit_events` grava mudança no record; message continua.

**Cobertura**: SP-12, RF-014.

---

### US-004 — Receber esclarecimento quando mensagem é ambígua

**Como** Felix,
**Quero** ver "Pode detalhar?" quando mando "hoje foi puxado",
**Para que** eu saiba reformular.

**Critérios de aceitação resumidos:**
- [ ] `intent=clarify` → assistant devolve pergunta.
- [ ] **Nenhum** food_record, water_record, activity_record criado.
- [ ] Mensagem original persiste (não vira erro).

**Cobertura**: SP-13, RF-012.

---

### US-005 — Fallback quando LLM falha

**Como** Felix,
**Quero** ver "Não consegui interpretar; pode reformular?" em vez de silêncio quando a LLM tem timeout,
**Para que** eu saiba que a próxima ação é reenviar.

**Critérios de aceitação resumidos:**
- [ ] Timeout ou erro após retries → assistant SP-14 texto.
- [ ] `raw_llm_response.error` guarda motivo pra debug.
- [ ] Zero records criados.

**Cobertura**: SP-14, RF-013.

---

### US-006 — Ver mensagens em ordem cronológica

**Como** Felix,
**Quero** que o chat renderize as mensagens na ordem que aconteceram,
**Para que** eu leia como conversa.

**Critérios de aceitação resumidos:**
- [ ] `GET /chat/messages` sem cursor → **as mais recentes** (não as antigas).
- [ ] `after=<last>` → mensagens novas (polling).
- [ ] `before=<oldest>` → scroll pra cima (histórico).
- [ ] Ordem ASC dentro da página.

**Cobertura**: SP-12, RF-008, RF-009.

---

### US-007 — Nunca ver mídia de outro user

**Como** operador de segurança,
**Quero** que se user A tentar linkar media_id do user B, a request seja rejeitada,
**Para que** o isolamento seja mantido.

**Critérios de aceitação resumidos:**
- [ ] `MediaRepository.list_by_ids` filtra por `user_id`.
- [ ] Response 422 `unknown_media` (não "existe mas não é seu").

**Cobertura**: SP-11, Const. §21, RF-005.

---

### US-008 — Registrar respeitando meu fuso

**Como** Felix,
**Quero** que "café" enviado às 23:50 BRT em 12/jul vá pro dia 12,
**Para que** meu dia local seja consistente.

**Critérios de aceitação resumidos:**
- [ ] `local_today('America/Sao_Paulo')` decide `log_date` do `day_log`.
- [ ] `DayLogRepository.get_or_create` idempotente.
- [ ] Snapshot subsequente reflete no dia 12, não 13.

**Cobertura**: SP-92, RF-007.

---

### US-009 — Ver foto que enviei

**Como** Felix,
**Quero** que a mensagem do meu chat mostre a foto que anexei (thumbnail),
**Para que** eu confirme visualmente o que foi enviado.

**Critérios de aceitação resumidos:**
- [ ] `MessageOut.media[]` inclui URL pré-assinada MinIO.
- [ ] URL expira em ~1h; cliente renderiza `<img src>`.
- [ ] `content_type` orientar cliente sobre extensão.

**Cobertura**: SP-11, RF-010, integração com [`media-storage`](../media-storage/).
