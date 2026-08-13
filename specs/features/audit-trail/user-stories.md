# Histórias de Usuário — Trilha de auditoria

## Personas

- **Felix (operador)** — consulta `audit_events` via SQL para entender "o que aconteceu com o item X".
- **Sistema (não-persona)** — garante que toda mutação tem rastro para INV-10.

---

### US-001 — Rastrear por que um item tem kcal inesperada

**Como** Felix auditando,
**Quero** consultar `audit_events WHERE entity_id = 'item-uuid'` e ver o histórico de mudanças,
**Para que** eu entenda se foi criado com estimativa LLM ou corrigido manualmente.

**Critérios de aceitação:**
- [ ] Após criar item com LLM: 1 linha `action='create', actor='llm', after={kcal: 0}` (sem catálogo).
- [ ] Após corrigir via chat: 1 linha `action='correct', actor='llm', before={kcal:0}, after={kcal:286}`.
- [ ] Sequência de `created_at` permite reconstruir o estado em qualquer ponto.

**Cobertura**: INV-10, RF-001, RF-005.

---

### US-002 — Confirmar que fechamento de dia foi auditado

**Como** Felix,
**Quero** ver `audit_events WHERE entity_type='day_log' AND action='close'`,
**Para que** eu saiba exatamente quando cada dia foi fechado.

**Critérios de aceitação:**
- [ ] `before={status: "open"}`, `after={status: "closed", closed_at, snapshot_version}`.
- [ ] `actor='user'` (fechamento é sempre decisão do usuário).
- [ ] `message_id` presente se fechado pelo chat.

**Cobertura**: INV-10, RF-008.

---

### US-003 — Distinguir ação do usuário vs. da LLM

**Como** operador,
**Quero** filtrar `audit_events WHERE actor='user'` para ver apenas mudanças manuais,
**Para que** eu separe o que a LLM fez do que o usuário explicitamente editou.

**Critérios de aceitação:**
- [ ] REST PATCH food_item → `actor='user'`.
- [ ] Chat correct → `actor='llm'`.
- [ ] Chat delete → `actor='llm'`; REST delete → `actor='user'`.

**Cobertura**: RF-013, RF-014.

---

### US-004 — Ver que soft delete preservou o estado anterior

**Como** Felix,
**Quero** consultar `audit_events WHERE action='delete'` e ver o `before` do item,
**Para que** eu recupere os valores caso precise recriar o registro.

**Critérios de aceitação:**
- [ ] `before` tem snapshot completo do item (grams, kcal, macros, etc.).
- [ ] `after=NULL` (entidade não existe mais como dado vivo).

**Cobertura**: INV-10, RF-006, RF-012.

---

### US-005 — Audit atômico com a mutação

**Como** Felix,
**Quero** que se uma mutação falhar e der rollback, o audit também desfaça,
**Para que** nunca haja audit sem mutação correspondente ou vice-versa.

**Critérios de aceitação:**
- [ ] `AuditEventRepository.record` chama `session.flush()` dentro da mesma transação.
- [ ] Rollback da transação (ex.: erro em DailyRecomputeService) desfaz tanto o registro quanto o audit.

**Cobertura**: RNF-001.
