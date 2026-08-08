# Histórias de Usuário — Remoção de registros

## Personas

- **Felix (P1)** — remove itens errados ou redundantes para manter o diário limpo.

---

### US-001 — Remover via chat

**Como** Felix,
**Quero** dizer "remova o refrigerante do almoço",
**Para que** ele saia dos meus totais sem precisar abrir um menu.

**Critérios de aceitação:**
- [ ] `intent=delete_record`, `target_hint="refrigerante almoço"`.
- [ ] `TargetMatcher` resolve único candidato.
- [ ] `deleted_at` setado; snapshot recomputa; `kcal_in` cai.
- [ ] Assistant confirma remoção com totais atualizados.

**Cobertura**: SP-80.

---

### US-002 — Remover via botão no modal (SP-117)

**Como** Felix,
**Quero** clicar "Descartar" no modal de item `needs_confirmation=true`,
**Para que** eu livre o diário de item sem catálogo que não vale a pena manter.

**Critérios de aceitação:**
- [ ] `DELETE /records/food-items/{id}` dispara.
- [ ] 200 `{already_deleted: false}`.
- [ ] Badge "sem catálogo" some; `DayTotalsBar` atualiza.

**Cobertura**: SP-81, integração com SP-117.

---

### US-003 — 2ª remoção do mesmo item é silenciosa

**Como** Felix,
**Quero** que clicar "remover" duas vezes (ou mandar mensagem duplicada) não gere erro,
**Para que** UX seja tolerante.

**Critérios de aceitação:**
- [ ] 2ª chamada REST → 200 `{already_deleted: true}`.
- [ ] `deleted_at` não muda.
- [ ] Sem novo `audit_events`.
- [ ] Sem recompute (redundante).

**Cobertura**: SP-81.

---

### US-004 — Não remover em dia fechado

**Como** Felix,
**Quero** ver 409 ao tentar `DELETE` em dia já encerrado,
**Para que** meu histórico seja imutável.

**Critérios de aceitação:**
- [ ] REST → 409 `conflict_closed_day`.
- [ ] Chat → `DayClosedError` → assistant informa.
- [ ] `deleted_at` inalterado.
- [ ] Sem audit.

**Cobertura**: SP-82, INV-5.

---

### US-005 — Não ver mensagem de chat apagada

**Como** Felix,
**Quero** que a mensagem "150g arroz" continue no chat mesmo depois de remover o item,
**Para que** eu entenda a história do dia.

**Critérios de aceitação:**
- [ ] `messages` inalteradas após delete.
- [ ] `food_items.deleted_at` setado, `food_records` mantido.
- [ ] `GET /chat/messages` ainda retorna a mensagem original.

**Cobertura**: SP-12, SP-80.

---

### US-006 — Ver audit trail da remoção

**Como** operador,
**Quero** consultar `audit_events` e ver o que foi removido e quando,
**Para que** eu reconstrua o estado anterior se necessário.

**Critérios de aceitação:**
- [ ] `audit_events` tem `action='delete'`, `before=<snapshot>`, `after=NULL`.
- [ ] `actor='llm'` se chat, `'user'` se REST.
- [ ] `message_id` presente se disparado por chat.

**Cobertura**: INV-10.

---

### US-007 — Remoção de tipos diferentes

**Como** Felix,
**Quero** remover água, bebida, atividade da mesma forma,
**Para que** não precise lembrar endpoints diferentes.

**Critérios de aceitação:**
- [ ] `/records/water/{id}`, `/records/beverage/{id}`, `/records/activity/{id}` — todos retornam `DeletionOut`.
- [ ] Via chat: `TargetMatcher` detecta kind por keywords (agua/cafe/treino/etc).
- [ ] Snapshot do kind removido some do recompute.

**Cobertura**: SP-80, SP-81.
