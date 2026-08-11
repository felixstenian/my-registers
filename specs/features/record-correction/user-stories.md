# Histórias de Usuário — Correção de registros

## Personas

- **Felix (P1)** — corrige quantidades quando percebe erro (LLM leu concha errada, foto ambígua, esqueceu de mencionar).

---

### US-001 — Corrigir por chat quando único item

**Como** Felix,
**Quero** dizer "corrija o frango para 220g" quando só tenho um frango no dia,
**Para que** meus totais reflitam a verdade sem eu precisar clicar em nada.

**Critérios de aceitação:**
- [ ] LLM extrai `intent=correct_record, target_hint="frango", changes={grams:220}`.
- [ ] `TargetMatcher` acha único candidato.
- [ ] `food_items.grams=220`, `kcal` recomputado, `source='user_corrected'`.
- [ ] Assistant confirma "arroz do almoço corrigido pra 220g" + tabela SP-118.

**Cobertura**: SP-70.

---

### US-002 — Ser avisado quando ambíguo

**Como** Felix,
**Quero** ver "qual frango? do almoço ou do jantar?" quando 2 itens iguais existem,
**Para que** eu especifique sem alterar o dado errado.

**Critérios de aceitação:**
- [ ] 2 items "frango" (lunch + dinner); hint "corrija o frango".
- [ ] `AmbiguousTarget` levanta; **nenhuma** mutação.
- [ ] Assistant devolve clarify pedindo desambiguação.

**Cobertura**: SP-71.

---

### US-003 — Qualificar por refeição

**Como** Felix,
**Quero** dizer "o frango do almoço era 220g" e o backend saber qual é,
**Para que** eu resolva a ambiguidade na primeira tentativa.

**Critérios de aceitação:**
- [ ] `_detect_meal_slot(["almoco"])` → `lunch`.
- [ ] Item do lunch ganha +5 no score, isolando vencedor.
- [ ] Corrigido apenas o item do almoço.

**Cobertura**: SP-72.

---

### US-004 — Não corrigir dia fechado

**Como** Felix,
**Quero** ver mensagem clara ao tentar corrigir dia já encerrado,
**Para que** meu histórico não vire ilusão.

**Critérios de aceitação:**
- [ ] Via chat: `DayClosedError` → assistant devolve "Dia já fechado; crie novo registro hoje".
- [ ] Via REST: 409 `conflict_closed_day`.
- [ ] Nenhuma linha em `audit_events` gerada.

**Cobertura**: SP-73, INV-5.

---

### US-005 — Ver total do dia atualizar sozinho

**Como** Felix,
**Quero** que ao corrigir "arroz para 200g", o `DayTotalsBar` já reflita no próximo polling,
**Para que** eu não precise refrescar.

**Critérios de aceitação:**
- [ ] `DailyRecomputeService.recompute` roda ao fim.
- [ ] `snapshot.version` incrementa.
- [ ] Próximo `GET /days/today` retorna kcal novo.

**Cobertura**: INV-4.

---

### US-006 — Corrigir via modal (SP-117)

**Como** Felix,
**Quero** clicar em "Confirmar" no card de item com `needs_confirmation=true` e editar valores no modal,
**Para que** eu não precise digitar frase completa pra correção pequena.

**Critérios de aceitação:**
- [ ] `PATCH /records/food-items/{id}` aceita grams/ml/quantity/unit.
- [ ] Item ganha `source='user_corrected'`, `needs_confirmation=false`.
- [ ] `catalog_ref_id` retroativo se seed foi enriquecido no meio.
- [ ] Snapshot recomputa.

**Cobertura**: SP-117, RF-011.

---

### US-007 — Corrigir atividade sem peso corporal

**Como** Felix (sem `weight_kg` no perfil),
**Quero** corrigir duração de corrida sem receber erro fatal,
**Para que** eu possa registrar mesmo antes de setar meu peso.

**Critérios de aceitação:**
- [ ] Duration muda; warning `missing_weight_kg` emitido.
- [ ] `kcal_burned` fica como está (não recompute).
- [ ] Correção não falha; audit registrado.

**Cobertura**: SP-61 lateral, RF-008.

---

### US-008 — Sobrescrever kcal via valor reportado

**Como** Felix,
**Quero** dizer "corrija a corrida — o relógio marcou 380 kcal",
**Para que** o cálculo MET seja substituído pelo real.

**Critérios de aceitação:**
- [ ] `changes.kcal_burned_reported=380` OU `changes.kcal_burned=380`.
- [ ] `record.kcal_burned=380`, `calc_method='user_manual'`.
- [ ] Audit before/after registrado.

**Cobertura**: RF-008.

---

### US-009 — Rastrear correções via audit

**Como** operador auditando,
**Quero** poder consultar `audit_events` e ver o antes/depois de cada correção,
**Para que** eu recupere a história completa.

**Critérios de aceitação:**
- [ ] `audit_events` tem linha `action='correct'` por correção.
- [ ] `before/after` shape adequado ao kind (food inclui macros; water só volume_ml).
- [ ] `actor='llm'` via chat, `'user'` via REST.
- [ ] `message_id` presente se chat, `null` se REST.

**Cobertura**: SP-74, INV-10.
