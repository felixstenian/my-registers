# Histórias de Usuário — Renderização de assistant messages (Bloco 2)

> **Rastreabilidade**: SP-115..SP-118 · Persona principal: Felix.

## Personas

- **Felix (leitor rápido)**: quer entender o que registrou sem ler texto corrido; tabelas são mais rápidas.
- **Felix (acompanhamento)**: quer ver totais do dia sem sair do chat.
- **Felix (em dúvida)**: a LLM errou quantidade/alimento e quer corrigir ou descartar sem reescrever.

---

### US-001 — Ler resposta como card estruturado (SP-115/118)
**Como** Felix (leitor rápido),
**Quero** que o assistente responda com tabelas (refeição + total do dia) em vez de texto corrido,
**Para que** eu entenda macros e kcal em uma olhada.

**Critérios de Aceitação resumidos:**
- [ ] Cada intent de registro gera cabeçalho + 2 tabelas + disclaimer.
- [ ] Tabelas renderizadas como cards com borda e header.
- [ ] Sem biblioteca de markdown externa (dialeto controlado).

**Notas:**
- Fonte: SP-115 + SP-118. Backend produz markdown; UI só renderiza.

---

### US-002 — Distinguir estimativas de medidas exatas (SP-118)
**Como** Felix,
**Quero** ver `≈` antes de valores aproximados e itálico visual,
**Para que** eu saiba quais números confiar.

**Critérios de Aceitação resumidos:**
- [ ] `≈` aparece quando ≥1 item é estimado ou pendente.
- [ ] Água/volume nunca recebem `≈`.
- [ ] Células com `≈` renderizadas em itálico.

**Notas:**
- Fonte: SP-118. Decisão determinística no backend (`_has_approx_food_items`).

---

### US-003 — Ver totais do dia sem sair do chat (SP-116)
**Como** Felix (acompanhamento),
**Quero** uma barra fixa acima das mensagens com kcal_in, macros e água,
**Para que** eu acompanhe o dia em tempo real enquanto converso.

**Critérios de Aceitação resumidos:**
- [ ] Barra consulta `/days/today` ao montar.
- [ ] Revalida a cada nova assistant message.
- [ ] Estado vazio explicativo quando não há registros.
- [ ] Colapsa horizontalmente em telas pequenas mantendo kcal_in visível.

**Notas:**
- Fonte: SP-116.

---

### US-004 — Saber quantos itens precisam confirmação (SP-116/117)
**Como** Felix (em dúvida),
**Quero** um badge "N itens precisam de confirmação" na barra de totais,
**Para que** eu não perca itens que a LLM classificou com baixa confiança.

**Critérios de Aceitação resumidos:**
- [ ] Badge clicável abre modal com lista.
- [ ] Badge some quando não há pendentes.

**Notas:**
- Fonte: SP-116 (badge) + SP-117 (modal). Lista vem de `collectPendingItems`.

---

### US-005 — Confirmar item pendente inline (SP-117)
**Como** Felix (em dúvida),
**Quero** um botão "Confirmar" em cada item pendente,
**Para que** eu valide o registro sem redigitar tudo.

**Critérios de Aceitação resumidos:**
- [ ] `POST /records/food-items/{id}/confirm` desmarca `needs_confirmation`.
- [ ] Idempotente — confirmar item já confirmado não quebra.
- [ ] Barra revalida após ação.

**Notas:**
- Fonte: SP-117. Sem recompute de macros (item já tem valores). `already_confirmed` retornado.

---

### US-006 — Descartar item errado (SP-117)
**Como** Felix (em dúvida),
**Quero** um botão "Descartar" no modal,
**Para que** eu remova registros que a LLM criou errado.

**Critérios de Aceitação resumidos:**
- [ ] `DELETE /records/food-items/{id}` (soft delete + recompute, INV-4).
- [ ] Audit gravada (INV-10).
- [ ] Item some da lista; barra revalida.

**Notas:**
- Fonte: SP-117. Dia fechado bloqueia (INV-5).

---

### US-007 — Ver aviso legal no rodapé (Const. Art. VII §26)
**Como** Felix,
**Quero** ver "As estimativas nutricionais são aproximações..." em toda resposta,
**Para que** eu saiba que não substitui acompanhamento profissional.

**Critérios de Aceitação resumidos:**
- [ ] Disclaimer sempre presente após as tabelas.
- [ ] Fonte reduzida mas legível (não tooltip).

**Notas:**
- Fonte: Constituição Art. VII §26, reforçado por SP-118.