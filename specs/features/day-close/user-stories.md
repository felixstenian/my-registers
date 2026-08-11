# Histórias de Usuário — Encerramento de dia

## Personas

- **Felix (P1)** — encerra dias regularmente para consolidar histórico.
- **Sistema** — enforce imutabilidade pós-close.

---

### US-001 — Encerrar dia via botão

**Como** Felix,
**Quero** clicar em "Encerrar dia" no header do chat,
**Para que** o dia atual congele e eu veja uma narrativa curta.

**Critérios de aceitação resumidos:**
- [ ] Modal `CloseDayModal` mostra resumo + botão confirm.
- [ ] `POST /days/{today}/close` → 200 com narrative.
- [ ] `DayTotalsBar` mostra `status=closed` + disclaimer.

**Cobertura**: SP-100, T-704.

---

### US-002 — Encerrar dia via chat

**Como** Felix,
**Quero** digitar "encerrar dia" e receber a narrativa como assistant message,
**Para que** eu não precise sair do chat.

**Critérios de aceitação resumidos:**
- [ ] LLM classifica `intent=close_day`.
- [ ] `_handle_close_day` roda o service.
- [ ] Assistant message tem `content=<narrative com disclaimer>`, `llm_intent='close_day'`.

**Cobertura**: SP-100.

---

### US-003 — Idempotência silenciosa

**Como** Felix,
**Quero** clicar "Encerrar" 2× por engano e não ver erro,
**Para que** UX seja tolerante.

**Critérios de aceitação resumidos:**
- [ ] 2ª chamada em dia `closed` → 200 com snapshot atual.
- [ ] `closed_at` não muda.
- [ ] `snapshot.narrative` **não** é regenerada.
- [ ] `was_already_closed=true` na resposta.

**Cobertura**: SP-101, Const. §29.

---

### US-004 — Encerrar dia sem registros

**Como** Felix,
**Quero** fechar um dia mesmo sem ter registrado nada,
**Para que** o histórico registre "domingo — sem input".

**Critérios de aceitação resumidos:**
- [ ] `get_or_create` cria day_log vazio.
- [ ] Snapshot zerado.
- [ ] Narrativa fallback (LLM ainda gera texto curto sobre zeros).
- [ ] Disclaimer presente.

**Cobertura**: SP-100, RF-010.

---

### US-005 — Ver narrativa que respeita meus valores

**Como** Felix,
**Quero** que a narrativa cite os números exatos do meu snapshot,
**Para que** o texto seja confiável.

**Critérios de aceitação resumidos:**
- [ ] `call_narrative` recebe `totals_payload` com `kcal_in, water_ml, ...`.
- [ ] Prompt instrui "use exatos".
- [ ] LLM não recalcula (INV-1 estrutural).

**Cobertura**: SP-103.

---

### US-006 — Ter disclaimer sempre presente

**Como** Felix (implícito — auditoria),
**Quero** que toda narrativa termine com o disclaimer legal,
**Para que** compliance esteja assegurada.

**Critérios de aceitação resumidos:**
- [ ] `narrative` sempre termina com `"As estimativas nutricionais são aproximações..."`.
- [ ] Se LLM incluir espontaneamente, não duplica.
- [ ] Fallback textual (LLM off) também tem disclaimer.

**Cobertura**: SP-104, Const. §26.

---

### US-007 — Dia fechado imutável

**Como** Felix,
**Quero** que ao tentar corrigir "aumenta o arroz pra 300g" em dia fechado, receba 409,
**Para que** meu histórico seja confiável.

**Critérios de aceitação resumidos:**
- [ ] Após close, tentativa de PATCH `food_items` em dia fechado → 409 `conflict_closed_day`.
- [ ] DELETE idem.
- [ ] Snapshot lê congelado (via daily-snapshot INV-5).

**Cobertura**: INV-5, integração com [`record-correction`](../record-correction/) e [`record-deletion`](../record-deletion/).

---

### US-008 — Encerrar dia passado retrospectivamente

**Como** Felix,
**Quero** encerrar 27/jul (ontem) hoje (28/jul), porque esqueci ontem,
**Para que** meu histórico não fique com dia "aberto órfão".

**Critérios de aceitação resumidos:**
- [ ] `POST /days/2026-07-27/close` funciona mesmo hoje sendo 28/jul.
- [ ] `/day/[date]` mostra botão "Encerrar dia" se `status='open'` (SP-155 v1.11).
- [ ] Snapshot recomputa com registros vivos daquele dia.

**Cobertura**: SP-100, SP-155 v1.11.

---

### US-009 — Ter audit trail do fechamento

**Como** operador,
**Quero** poder consultar `audit_events` e ver quando cada dia foi fechado,
**Para que** eu tenha rastreabilidade.

**Critérios de aceitação resumidos:**
- [ ] Cada close cria 1 linha em `audit_events` com `action='close'`, `before={status:open}`, `after={status:closed, closed_at, snapshot_version}`.
- [ ] `message_id` presente se disparado por chat, `null` se por REST.

**Cobertura**: INV-10, RF-009.
