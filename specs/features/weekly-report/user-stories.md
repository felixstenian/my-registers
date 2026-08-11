# Histórias de Usuário — Relatório semanal

## Personas

- **Felix (P1)** — revisão semanal para entender tendências ao longo dos dias fechados.

---

### US-001 — Ver resumo da semana via página /weekly

**Como** Felix,
**Quero** abrir `/weekly` e ver tabela dos últimos 7 dias fechados com totais e médias,
**Para que** eu tenha visão de tendência sem precisar consultar cada dia separado.

**Critérios de aceitação:**
- [ ] `GET /weekly` com ≥ 7 dias fechados → `days_included=7`, `per_day` com 7 entradas ASC.
- [ ] `totals.kcal_in` = soma dos 7 snapshots.
- [ ] `averages.kcal_in` = totals / 7.
- [ ] Nenhum dia aberto incluído.

**Cobertura**: SP-110, SP-111, SP-113, INV-8.

---

### US-002 — Ver relatório parcial com aviso de histórico insuficiente

**Como** Felix (primeira semana usando o app),
**Quero** ver os dias que já fechei mesmo sendo menos de 7,
**Para que** eu não fique bloqueado esperando 7 dias.

**Critérios de aceitação:**
- [ ] 3 dias fechados → `days_included=3`, `warnings=[{code:"insufficient_history", days_available:3}]`.
- [ ] Narrativa menciona histórico limitado (ou fallback).

**Cobertura**: SP-110.

---

### US-003 — Não esperar nova LLM ao chamar /weekly repetidamente

**Como** Felix,
**Quero** que chamar `/weekly` duas vezes sem fechar dia novo retorne o mesmo relatório,
**Para que** a página carregue rápido sem custo extra de Anthropic.

**Critérios de aceitação:**
- [ ] 2ª chamada: `snapshot_versions` igual → mesmo `id`, sem chamar `call_weekly_narrative`.
- [ ] `version` não incrementa.
- [ ] `generated_at` não muda.

**Cobertura**: SP-112.

---

### US-004 — Ver relatório atualizado após fechar novo dia

**Como** Felix,
**Quero** que ao fechar o 8º dia, o semanal traga a janela nova (mais recente vs. mais antigo),
**Para que** a visão seja sempre dos últimos 7 fechados.

**Critérios de aceitação:**
- [ ] Novo `window_start`, `window_end` após novo dia fechado.
- [ ] `snapshot_versions` diferente → narrativa regenerada.
- [ ] `version` incrementa.

**Cobertura**: SP-112.

---

### US-005 — Pedir resumo semanal via chat

**Como** Felix,
**Quero** digitar "resumo semanal" no chat e receber a narrativa lá mesmo,
**Para que** eu não precise sair do chat para ver tendências.

**Critérios de aceitação:**
- [ ] `intent=weekly_summary` → `WeeklyReportService.generate(user)`.
- [ ] Assistant message com narrativa + disclaimer.
- [ ] Totais exibidos em formato SP-118.

**Cobertura**: SP-110, SP-111.

---

### US-006 — Confiar nos números (LLM não calcula)

**Como** Felix,
**Quero** garantia de que os totais do semanal são os mesmos que os snapshots somados,
**Para que** o relatório seja auditável.

**Critérios de aceitação:**
- [ ] Se LLM retornar lixo (mock), `totals.kcal_in` continua = soma real dos snapshots.
- [ ] `test_llm_lies_do_not_affect_stored_totals` cobre.

**Cobertura**: INV-1, SP-111.

---

### US-007 — Ver dias ordenados do mais antigo ao mais recente

**Como** Felix,
**Quero** que a tabela `per_day` mostre segunda → domingo (não domingo → segunda),
**Para que** eu leia a progressão natural da semana.

**Critérios de aceitação:**
- [ ] `_per_day` ordena `closed_days ASC` por `log_date`.
- [ ] `per_day[0].date` é o dia mais antigo da janela.

**Cobertura**: SP-113.

---

### US-008 — Narrativa com disclaimer sempre presente

**Como** Felix (compliance),
**Quero** que o relatório semanal sempre termine com o aviso legal,
**Para que** conformidade esteja garantida.

**Critérios de aceitação:**
- [ ] `narrative` sempre termina com `"As estimativas nutricionais são aproximações..."`.
- [ ] Mesmo em fallback (LLM off) ou quando LLM já incluiu o texto.

**Cobertura**: Const. §26, SP-111.

---

### US-009 — Não ver relatório de outro usuário

**Como** operador,
**Quero** que usuário A nunca veja dados de usuário B,
**Para que** privacidade seja garantida.

**Critérios de aceitação:**
- [ ] `_fetch_last_closed_days` filtra por `user_id`.
- [ ] `_find_existing` filtra por `user_id`.
- [ ] `test_reports_are_isolated_per_user` cobre.

**Cobertura**: Const. §21.
