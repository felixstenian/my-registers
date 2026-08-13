# Histórias de Usuário — Edição inline de registros na página `/day`

> **Rastreabilidade**: SP-160..SP-169, INV-14 · Personas: Felix (preciso), Felix (curioso), Felix (rótulo).

## Personas

- **Felix (preciso)**: notou que o rótulo foi lido incorreto e quer corrigir sem digitar no chat.
- **Felix (curioso)**: quer validar o número de kcal de um item que parece estranho.
- **Felix (rótulo)**: cadastrou produto via foto; agora quer revisar os valores per-100g lidos.

---

### US-001 — Corrigir quantidade do alimento sem sair do `/day` (SP-160)
**Como** Felix (preciso),
**Quero** expandir o item e editar `grams`/`ml` direto na tabela,
**Para que** eu não precise redigir no chat "corrija o frango para 150g" (caminho incerto).

**Critérios de Aceitação resumidos:**
- [ ] Expandir item mostra inputs `grams`/`ml` (ou `quantity`+`unit`) com valores atuais.
- [ ] "Salvar" desabilitado até algo mudar.
- [ ] Após salvar: totais do dia atualizam, snapshot version incrementa, audit gravado.

**Notas:**
- Fonte: SP-160. Backend já existe (`PATCH /records/food-items/{id}`).

---

### US-002 — Não editar item em dia encerrado (SP-161)
**Como** Felix,
**Quero** que o painel de edição não apareça em dia `closed`,
**Para que** eu não corrompa a imutabilidade (INV-5) por engano.

**Critérios de Aceitação resumidos:**
- [ ] Dia `closed`: inputs `disabled` + dica "Dia encerrado é imutável; corrija via novo registro no dia atual".
- [ ] Bypass via API → 409 `conflict_closed_day`.

**Notas:**
- Fonte: SP-161, INV-5.

---

### US-003 — Editar valores do rótulo do produto (SP-162)
**Como** Felix (rótulo),
**Quero** editar `kcal`/macros per-100g do rótulo direto no item que referencia o fact,
**Para que** eu corrija leitura errada da LLM sem precisar saber qual endpoint chamar.

**Critérios de Aceitação resumidos:**
- [ ] Inputs per-100g só aparecem se `has_catalog && source ∈ {label_ocr, manual}`.
- [ ] Fact TBCA/USDA mostra "Catálogo canônico — não editável" (sem inputs per-100g).
- [ ] Após salvar, fact fica `verified_by_user=true`.

**Notas:**
- Fonte: SP-162, estende SP-33. Backend já existe (`PATCH /nutrient-facts/{id}`).

---

### US-004 — Propagação automática ao editar rótulo (SP-163, INV-14)
**Como** Felix (rótulo),
**Quero** que ao corrigir `kcal` do rótulo, todos os itens já consumidos desse produto sejam recalculados,
**Para que** eu não precise editar um por um.

**Critérios de Aceitação resumidos:**
- [ ] Após PATCH fact: todos `food_items`/`beverage_records` vivos em dias abertos que referenciam o fact são recomputados.
- [ ] Itens em dia fechado pulam (`propagation_skipped` com `reason='day_closed'`).
- [ ] Snapshot de cada dia aberto afetado é recompute'd.
- [ ] Audit gravado por item propagado.

**Notas:**
- Fonte: SP-163, INV-14. Novo módulo `nutrient_fact_propagation.py`. ADR-013.

---

### US-005 — Editar volume de água (SP-164)
**Como** Felix (preciso),
**Quero** editar `volume_ml` da água direto na seção de hidratação,
**Para que** eu corrija "um copo" que veio como 500ml mas era 250ml.

**Critérios de Aceitação resumidos:**
- [ ] Expandir item em Hidratação mostra input `volume_ml`.
- [ ] Após salvar: Água total do dia atualiza; audit gravado; 404/409 respeitados.

**Notas:**
- Fonte: SP-164. Novo endpoint `PATCH /records/water/{id}`.

---

### US-006 — Editar volume de bebida calórica (SP-165)
**Como** Felix (preciso),
**Quero** editar `volume_ml` de uma bebida na seção de bebidas,
**Para que** eu ajuste o refrigerante que o copo era maior.

**Critérios de Aceitação resumidos:**
- [ ] Expandir item em Bebidas mostra input `volume_ml`.
- [ ] Se a bebida tem fact: macros recomputados proporcionalmente ao novo volume.

**Notas:**
- Fonte: SP-165. Novo endpoint `PATCH /records/beverage/{id}`.

---

### US-007 — Editar duração/intensidade/kcal de atividade (SP-166)
**Como** Felix (preciso),
**Quero** editar `duration_minutes`/`intensity`/`kcal_burned` de uma atividade,
**Para que** eu corrija "corri 40 min" que era 35 min sem refazer pelo chat.

**Critérios de Aceitação resumidos:**
- [ ] Seção Atividade expansível com inputs `duration_minutes`, `intensity` (select), `kcal_burned`.
- [ ] `kcal_burned` explícito → `calc_method='user_manual'`.
- [ ] Sem `kcal_burned` + sem peso corporal → warning + mantém kcal anterior.

**Notas:**
- Fonte: SP-166. Novo endpoint `PATCH /records/activity/{id}`.

---

### US-008 — Editar com bom feedback visual (SP-167)
**Como** Felix,
**Quero** feedback claro ao salvar (loading, erro, sucesso),
**Para que** eu saiba se a edição foi aplicada.

**Critérios de Aceitação resumidos:**
- [ ] Spinner durante o PATCH.
- [ ] Erro inline (`aria-live`) com código estável (`conflict_closed_day` etc.).
- [ ] Sucesso colapsa o painel e revalida a página.
- [ ] Foco no primeiro input ao expandir; "Cancelar" reverte.

**Notas:**
- Fonte: SP-167.

---

### US-009 — Painéis nas seções auxiliares (SP-168)
**Como** Felix (preciso),
**Quero** o mesmo padrão de edição nas seções de hidratação/bebida/atividade,
**Para que** a UX seja consistente em todo o `/day`.

**Critérios de Aceitação resumidos:**
- [ ] `AuxiliarySections.tsx` extende com expansão `<details>` + forms inline.
- [ ] Mesmas garantias de dia fechado, loading/erro/sucesso, a11y.

**Notas:**
- Fonte: SP-168 (`should`).

---

### US-010 — Página atualiza sozinha após editar (SP-169)
**Como** Felix,
**Quero** que a tabela e os totais atualizem sem precisar F5,
**Para que** eu veja imediatamente o efeito da correção.

**Critérios de Aceitação resumidos:**
- [ ] Server Action `revalidatePath('/day')` + `revalidatePath('/day/[date]')`.
- [ ] Se propagação afetou outros dias: toast + link ao dia afetado.

**Notas:**
- Fonte: SP-169 (`should`).

---

### US-011 — Ver aviso legal mantido após editar (Const. Art. VII §26)
**Como** Felix,
**Quero** que o disclaimer continue visível no rodapé do `/day` após edição,
**Para que** eu não esqueça que é estimativa.

**Critérios de Aceitação resumidos:**
- [ ] `<Disclaimer/>` permanece na re-renderização pós-edição.

**Notas:**
- Não-funcional RNF-005.