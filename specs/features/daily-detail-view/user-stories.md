# Histórias de Usuário — Visão detalhada do dia (Bloco 6)

> **Rastreabilidade**: SP-150..SP-155 · Personas: Felix (leitor), Felix (esquecido), Felix (curioso).

## Personas

- **Felix (leitor rápido)**: quer ver o dia inteiro de uma olhada sem depender do chat scroll.
- **Felix (esquecido)**: esqueceu de encerrar ontem e quer fazer retroativo.
- **Felix (curioso)**: quer saber a origem de cada valor (LLM, rótulo, manual) e a confiança.
- **Felix migrando do chat**: confirmou item pelo chat e quer ver a página `/day` atualizada.

---

### US-001 — Ver o dia atual em uma página (SP-150)
**Como** Felix (leitor rápido),
**Quero** uma página `/day` mostrando totais + refeições + hidratação + atividade do dia,
**Para que** eu acompanhe meu dia sem precisar scrollar no chat.

**Critérios de Aceitação resumidos:**
- [ ] `/day` server-rendered com `GET /days/today`.
- [ ] Header: data pt-BR + badge status + "Encerrar dia" (se aberto).
- [ ] Link "Hoje" no layout protegido.

**Notas:**
- Fonte: SP-150.

---

### US-002 — Ver refeições agrupadas por slot (SP-151)
**Como** Felix (leitor rápido),
**Quero** refeições em seções (Café/Almoço/Lanche/Jantar/Outros) com kcal parcial,
**Para que** eu saiba quanto cada momento do dia contribuiu.

**Critérios de Aceitação resumidos:**
- [ ] Ordem fixa `breakfast → lunch → snack → dinner → unspecified`.
- [ ] Slots vazios não renderizam.
- [ ] Cabeçalho do slot tem nome + horário + kcal parcial.
- [ ] Colunas Item/Quantidade/Calorias/P/C/G/Fib.

**Notas:**
- Fonte: SP-151.

---

### US-003 — Confirmar item pendente sem sair do /day (SP-151)
**Como** Felix (curioso),
**Quero** um botão "confirmar" inline no item pendente,
**Para que** eu valide a estimativa sem abrir o chat.

**Critérios de Aceitação resumidos:**
- [ ] Badge amarelo "confirmar" aparece quando `needs_confirmation`.
- [ ] Click confirma via `POST /confirm` e some.
- [ ] Página re-renderiza com o badge removido.

**Notas:**
- Fonte: SP-151. `ConfirmItemButton` é client; página principal continua server.

---

### US-004 — Saber que item está sem catálogo (SP-151)
**Como** Felix (curioso),
**Quero** um badge "sem catálogo" em items com `catalog_ref_id=null`,
**Para que** eu saiba que macros podem estar zerados e posso recuperar via rótulo.

**Critérios de Aceitação resumidos:**
- [ ] Badge cinza "sem catálogo" com tooltip.

**Notas:**
- Fonte: SP-151. Recuperação via chat (Bloco 5) ou foto do rótulo (Fase 4.b).

---

### US-005 — Expandir item para ver micros e origem (SP-152)
**Como** Felix (curioso),
**Quero** clicar em um item e ver sódio/cálcio/ferro/potássio + a origem,
**Para que** eu entenda a qualidade do dado.

**Critérios de Aceitação resumidos:**
- [ ] `<details>` nativo expande micros sem JS extra.
- [ ] Valores zero/nulos viram `—`.
- [ ] `source` em pt-BR (LLM/corrigido/rótulo (foto)/manual).
- [ ] `confidence` LLM só aparece quando `source='llm'`.
- [ ] Sem micros → "Sem micronutrientes registrados neste item."

**Notas:**
- Fonte: SP-152.

---

### US-006 — Ver hidratação, bebidas e atividade (SP-153)
**Como** Felix (leitor rápido),
**Quero** seções separadas para água pura, bebidas calóricas e atividade,
**Para que** eu enxergue cada categoria sem misturar.

**Critérios de Aceitação resumidos:**
- [ ] Hidratação: lista horário+volume + total `Água: N ml`.
- [ ] Bebidas: tabela item/volume/kcal/P/C/G; badge "confirmar" se pendente.
- [ ] Atividade: nome+tipo pt-BR+duração+intensidade+kcal+method pt-BR.
- [ ] Cada seção some se sua lista é vazia.

**Notas:**
- Fonte: SP-153.

---

### US-007 — Ver dia passado (SP-154)
**Como** Felix (curioso),
**Quero** acessar `/day/[date]` para revisar um dia anterior,
**Para que** euCallBack recupere história sem precisar do `/weekly`.

**Critérios de Aceitação resumidos:**
- [ ] Rota server-rendered valida `YYYY-MM-DD`.
- [ ] 404 amigável quando `day_log` não existe.
- [ ] Link "Voltar para hoje".
- [ ] Edição de records exclusiva do chat (não há botões na página).

**Notas:**
- Fonte: SP-154.

---

### US-008 — Encerrar dia passado que fiquei aberto (SP-154 revisitado)
**Como** Felix (esquecido),
**Quero** ver o botão "Encerrar dia" em um dia passado ainda `status='open'`,
**Para que** eu encerre retroativamente sem precisar digitar data.

**Critérios de Aceitação resumidos:**
- [ ] `allowClose=true` em `/day/[date]`.
- [ ] Botão "Encerrar dia" aparece quando `status='open'` (mesmo para dia passado).
- [ ] Backend `POST /days/{date}/close` funciona em qualquer data aberta.
- [ ] Pós-fechamento: refresh mostra `status='closed'` + narrativa.

**Notas:**
- Fonte: SP-154 (v1.11 spec), PR #46.

---

### US-009 — Não ver o futuro (SP-155)
**Como** Felix,
**Quero** ver mensagem amigável ao tentar acessar uma data futura,
**Para que** eu não fique confuso com tela de erro confuso.

**Critérios de Aceitação resumidos:**
- [ ] Data maior que hoje (fuso local) → "Não é possível ver o futuro" + link "Voltar para hoje".
- [ ] Não chama backend.

**Notas:**
- Fonte: SP-155.

---

### US-010 — Navegar entre dias (SP-155)
**Como** Felix (curioso),
**Quero** botões prev/next/Hoje + date picker no header do `/day`,
**Para que** eu passe pelos dias sem digitar URL.

**Critérios de Aceitação resumidos:**
- [ ] "← Dia anterior" sempre presente.
- [ ] "Próximo dia →" escondido no dia atual (e se `nextDate > today`).
- [ ] "Hoje" escondido no dia atual.
- [ ] `<input type="date" max={today}>` + botão "Ir".

**Notas:**
- Fonte: SP-155.

---

### US-011 — Saltar do /weekly para um dia específico (SP-155)
**Como** Felix (curioso),
**Quero** clicar no "Dia" da tabela do `/weekly` e ir para `/day/[date]`,
**Para que** eu aprofunde em um dia que me chamou atenção.

**Critérios de Aceitação resumidos:**
- [ ] Coluna "Dia" do `/weekly` vira `<Link href={`/day/${row.date}`}>`.

**Notas:**
- Fonte: SP-155.

---

### US-012 — Ver página atualizada após conversar no chat (SP-150 não-funcional)
**Como** Felix migrando do chat,
**Quero** que o `/day` reflita minha confirmação no chat quando eu navegar,
**Para que** eu não veja dados velhos do Router Cache.

**Critérios de Aceitação resumidos:**
- [ ] `RefreshOnFocus` dispara `router.refresh()` no mount.
- [ ] `visibilitychange` com debounce 2s ao voltar pra aba.

**Notas:**
- [Inferido do código] — combate staleness do Router Cache do Next.