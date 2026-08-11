# Trade-offs — Correção de registros

## Decisão 1 — Ambiguidade nunca muta (SP-71)

### Contexto

LLM extrai `target_hint` grosseiro. Backend precisa decidir: adivinhar o melhor candidato ou abortar e pedir esclarecimento?

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Ambíguo → `AmbiguousTarget` → clarify (escolhida) | Correção 100% verificável; sem corrupção silenciosa | User reformula |
| B — Pegar o mais recente | UX rápida | Mutação silenciosa; user pode nem notar erro |
| C — LLM re-perguntar (interactive) | Fluido | Precisaria estado conversacional; MVP não tem |

### Decisão tomada

**Opção A.** Const. §5: LLM não pode desambiguar por conta. Backend força desambiguação humana.

### Consequências

- **Positivas**: histórico correto por design; audit sempre justifica.
- **Negativas**: user pode ficar frustrado em edge cases ambíguos. Aceito.

---

## Decisão 2 — Score por token overlap + bônus meal_slot

### Contexto

Como decidir qual candidato bate mais com `target_hint`? Opções: exact match, embedding, fuzzy, token overlap.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Token overlap simples + +5 meal_slot (escolhida) | Barato; testável; pt-BR-friendly | Falha em variações profundas |
| B — Embedding + cosine | Robusto | Precisa modelo; latência |
| C — Fuzzy match Levenshtein | Tolera typos | Ainda ambíguo em pt-BR sinônimos |

### Decisão tomada

**Opção A.** `_score = |tokens ∩ candidate_tokens|; +5 if meal_slot matches`.

### Consequências

- **Positivas**: código legível; 5 linhas.
- **Negativas**: "arroz integral" vs "arroz branco" ambos casam com "arroz" → ambíguo → user reformula (aceito).

---

## Decisão 3 — Recompute inline (síncrono) após correção

### Contexto

Após mudar `grams`, recomputar macros. Fazer inline no service ou disparar background?

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Inline (escolhida) | Consistência imediata; response reflete estado final | Latência maior |
| B — Fire-and-forget worker | Latência mínima do PATCH | Snapshot stale entre PATCH e recompute |
| C — Background com espera | Compromisso | Complexidade |

### Decisão tomada

**Opção A.** Recompute é ~10ms; user espera resposta final.

### Consequências

- **Positivas**: `RecordSummary` retornado já reflete valores novos.
- **Negativas**: PATCH latency inclui recompute — <200ms mesmo assim.

---

## Decisão 4 — `source='user_corrected'` só em FOOD/BEVERAGE

### Contexto

Water e activity não tem coluna `source` no mesmo sentido.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Só onde faz sentido (escolhida) | Schema consistente | Assimetria por kind |
| B — Adicionar `source` em water/activity | Uniforme | Coluna sempre 'user' ou 'llm'; sem valor |

### Decisão tomada

**Opção A.** Activity já tem `calc_method` que serve propósito similar.

### Consequências

- **Positivas**: schema enxuto.
- **Negativas**: `_apply_water_changes` e `_apply_activity_changes` não seguem padrão de source. Documentação cobre.

---

## Decisão 5 — PATCH retroativo resolve `catalog_ref_id` faltante

### Contexto

Bug histórico: items criados antes do seed TBCA rodar tinham `catalog_ref_id=NULL`. Precisamos de fix para itens legados.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — PATCH tenta lookup sempre; promove se achar (escolhida) | Self-heal | Custo extra por PATCH |
| B — Script CLI de "reconciliação" | Explícito | Runbook manual |
| C — Ignorar (items ficam órfãos) | Simples | UX ruim; histórico com kcal=0 |

### Decisão tomada

**Opção A.** Custo é 1 query a mais no PATCH (leve).

### Consequências

- **Positivas**: bug resolvido on-demand; sem intervenção operacional.
- **Negativas**: PATCH duplica lookup mesmo se `catalog_ref_id` já existe. Aceito.

---

## Decisão 6 — Chat: sem mudança → erro; REST: sem mudança → 200

### Contexto

User envia correction que não muda nada. Semanticamente diferente entre chat (intent explícito) e REST (form submit).

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Chat erro / REST 200 (escolhida) | Chat expõe misinterpretation LLM; REST tolera user clicando save vazio | Assimetria |
| B — Ambos erro | Consistente | REST ruim UX (user clica save sem mudar) |
| C — Ambos 200 | UX consistente | Chat perderia oportunidade de detectar erro LLM |

### Decisão tomada

**Opção A.**

### Consequências

- **Positivas**: cada camada com semântica adequada.
- **Negativas**: dev novo precisa saber a distinção. Documentado em ACs.

---

## Decisão 7 — Activity: `kcal_burned_reported` sobrescreve

### Contexto

User confia mais no smartwatch dele que no cálculo MET.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Reported wins, marca `calc_method='user_manual'` (escolhida) | Respeita autoridade do user; auditável | Perde info de estimativa MET original |
| B — Manter cálculo MET, ignorar reported | Consistência algorítmica | User frustrado |

### Decisão tomada

**Opção A.**

### Consequências

- **Positivas**: user tem controle.
- **Negativas**: relatórios futuros precisam segmentar por `calc_method` para comparar. Aceito.

---

## Decisão 8 — Weight missing → warning, sem falha

### Contexto

Activity requer `weight_kg` para recompute MET. Se ausente, o que fazer?

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Warning + `kcal_burned` como estava (escolhida) | Correção parcial funciona | kcal desatualizada |
| B — Erro fatal | Consistente | UX ruim (user não pode corrigir duration só porque não setou peso) |
| C — Pedir weight pelo chat | Fluido | Estado conversacional; MVP não tem |

### Decisão tomada

**Opção A.**

### Consequências

- **Positivas**: correção parcial ok.
- **Negativas**: `warnings` inclui `missing_weight_kg`; frontend precisa mostrar.

---

## Dívida técnica conhecida

| Item | Impacto | Prioridade |
|---|---|---|
| Score do matcher é primitivo — casos como "arroz branco cozido" vs "arroz branco" empatam facilmente | Médio (UX) | Média; fuzzy match ou embedding v2 |
| PATCH duplica lookup mesmo se `catalog_ref_id` já existe | Baixo | Baixa; otimização se hot path |
| `_KIND_HINTS` hardcoded — novo vocabulário exige PR | Baixo | Baixa; DB-driven se surgir demanda |
| `_MEAL_SLOT_HINTS` idem | Baixo | Baixa |
| Sem endpoint REST para corrigir water/beverage/activity — só via chat | Médio | Média; adicionar PATCH análogos |
| Sem "undo" de correção | Baixo | Baixa; audit permite; sem UI para reverter |
| Semânticas diferentes entre chat error e REST 200 sem mudança | Baixo | Baixa; documentado |

## Riscos identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| LLM extrai `target_hint` sem contexto → sempre ambíguo | Média | Médio | Prompt reforça extração de qualificador; teste E2E |
| `_KIND_HINTS` desatualizado (novo vocabulário) | Média (linguístico) | Baixo | Fallback: busca em todos os kinds |
| Correção após close (race entre close e correction concurrent) | Baixa | Alto | `_ensure_day_open` re-check dentro da transação |
| PATCH promoção retroativa falha para item com brand ≠ seed | Média | Baixo | Warning `no_catalog_hit`; user reforça |
| Regressão no `NutritionCalculator` (kcal diverge) | Baixa (testes cobrem) | Alto | Cobertura ≥90% |
| Ambiguidade percebida como bug pelo user novato | Média | Baixo | Assistant clarify explica |

## Alternativas para pós-MVP

- **PATCH `/records/water/{id}`, `/beverage/{id}`, `/activity/{id}`** análogos — UX de modal para todos os kinds.
- **Embedding-based matching** para `target_hint` — melhora ambiguidade natural.
- **Estado conversacional leve** — se `AmbiguousTarget` acontece, salvar candidatos e aceitar resposta simples ("o do almoço").
- **Batch correction**: "corrija arroz e feijão para 200g cada" — hoje precisa 2 mensagens.
- **Undo audit** — reverter correção via `PATCH /records/food-items/{id}/undo?event=<audit_id>`.
- **Métricas de qualidade**: rate de `AmbiguousTarget` semanal.
- **Suggestion mode**: assistant sugere correção antes de aplicar ("achei que era esse item — confirma?").
