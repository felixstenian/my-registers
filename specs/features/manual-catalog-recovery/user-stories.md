# Histórias de Usuário — Recuperação manual de itens sem catálogo

## Personas

- **Felix (P1)** — dono; frustra-se quando "sushi ninja rolls" cai como 0 kcal e não sabe o que fazer.

---

### US-001 — Ver claramente que houve um item sem catálogo

**Como** Felix,
**Quero** que a assistant message me diga "sem catálogo para: pão de queijo" com 3 opções claras,
**Para que** eu não precise adivinhar como resolver.

**Critérios de aceitação resumidos:**
- [ ] `compose_meal` detecta warnings `no_catalog_hit` e anexa bloco distinto.
- [ ] 3 CTAs: 📸 rótulo, ✏️ manual, ❌ descartar.
- [ ] Aviso legal continua no final.
- [ ] Item continua persistido com kcal=0 (nada muda estruturalmente).

**Cobertura**: SP-140, T-B501, T-B507.

---

### US-002 — Cadastrar manualmente sem foto

**Como** Felix,
**Quero** clicar em "Cadastrar manualmente" e preencher um form curto com nome + kcal + P/C/G,
**Para que** eu não precise sair do chat para atualizar o catálogo.

**Critérios de aceitação resumidos:**
- [ ] Botão abre modal `ManualCatalogForm.tsx` com campos mínimos.
- [ ] Campos opcionais (micros, aliases) em accordion.
- [ ] Submit chama `POST /nutrient-facts/manual`.
- [ ] Após 201, `DayTotalsBar` revalida e form fecha.

**Cobertura**: SP-141, T-B506.

---

### US-003 — Ver kcal do item legado atualizar sozinho

**Como** Felix,
**Quero** que ao cadastrar "pão de queijo congelado" (que ainda está no diário zerado), o item automaticamente recalcule com os novos valores,
**Para que** o total do dia fique correto sem eu precisar corrigir manualmente.

**Critérios de aceitação resumidos:**
- [ ] Form envia `promote_food_item_id` do item legado (persistido no state).
- [ ] Backend em transação única: cria fact + promove item + recompute snapshot + audit.
- [ ] `needs_confirmation` do item vai pra `false`.
- [ ] Snapshot reflete kcal novo.

**Cobertura**: SP-142, T-B504.

---

### US-004 — Cadastrar sem promoção quando item já foi deletado

**Como** Felix,
**Quero** poder cadastrar "pão de queijo" mesmo depois de já ter deletado o item original,
**Para que** o próximo registro do mesmo alimento resolva macros pelo catálogo do meu user.

**Critérios de aceitação resumidos:**
- [ ] Body inclui `promote_food_item_id` de item já com `deleted_at != NULL`.
- [ ] Response 201 com `promotion.warning = 'promotion_failed'`.
- [ ] Fact continua criado; nada de rollback.
- [ ] Próximo registro de "pão de queijo" acerta o novo fact.

**Cobertura**: SP-142.

---

### US-005 — Não vazar cadastro de outro user

**Como** operador auditando o app,
**Quero** garantir que user A não consegue promover um `food_item` de user B por engano,
**Para que** o isolamento por user seja mantido (Const. §21).

**Critérios de aceitação resumidos:**
- [ ] Se `promote_food_item_id` pertence a `food_records.user_id != current_user.id`, response é 201 com `promotion.warning='promotion_failed'`.
- [ ] Fact criado pertence a `current_user` (via `created_by`).
- [ ] User B **não** vê nem usa o fact de A.
- [ ] Teste T-B505 cobre isolamento cross-user.

**Cobertura**: SP-142, RNF-004.

---

### US-006 — Dia fechado protegido

**Como** Felix,
**Quero** que promoção em item de dia fechado seja bloqueada,
**Para que** dias fechados permaneçam imutáveis (INV-5).

**Critérios de aceitação resumidos:**
- [ ] Se `item.food_record.day_log.status == 'closed'` → promoção pula.
- [ ] Fact continua sendo criado (spec §142).
- [ ] Warning no body (exato código a confirmar em T-B505).

**Cobertura**: SP-142, INV-5.

---

### US-007 — Descartar item sem preencher form

**Como** Felix,
**Quero** clicar em "Descartar" e o composer pré-preencher `apaga pão de queijo`,
**Para que** eu só precise apertar Enter.

**Critérios de aceitação resumidos:**
- [ ] Botão do CTA "Descartar" injeta texto no composer.
- [ ] Envio dispara intent `delete_record` (feature [`record-deletion`](../record-deletion/)).
- [ ] Item some do snapshot no próximo recompute.

**Cobertura**: SP-140, T-B507, integração com [`record-deletion`](../record-deletion/).
