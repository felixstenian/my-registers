# Trade-offs — Registro de alimentos

## Decisão 1 — LLM interpreta, backend calcula (Const. Art. II §5, INV-1)

### Contexto

A tentação óbvia com modelos multimodais é deixar a LLM devolver `kcal`, `protein_g` etc. já calculados. Rapidez de implementação seria enorme. Mas modelos são não-determinísticos, e cálculos nutricionais são a métrica que o usuário mais confia. Uma versão nova do modelo (Sonnet 4.7 amanhã) que muda 2% em kcal médio quebraria história de meses do usuário.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — LLM só extrai (grams, unit, is_estimate); backend calcula (escolhida) | Determinismo total; histórico estável a mudanças de modelo/prompt; testes mockam LLM trivialmente | Dependência do catálogo TBCA local (bootstrap obrigatório); sem catálogo → `no_catalog_hit` |
| B — LLM devolve kcal já calculado | Zero manutenção de catálogo | Não determinístico; histórico "flutua" a cada upgrade de modelo; teste tem que aceitar tolerância; viola Art. II |
| C — Híbrido: LLM propõe, backend confirma se coerente com catálogo | "Melhor dos dois mundos" | Complexo, ambíguo (o que é "coerente"?), difícil de auditar |

### Decisão tomada

**Opção A.** Codificada como INV-1 e assertada por `test_llm_kcal_lies_ignored_backend_calculates`. `FoodItemIn` usa `extra="ignore"` para tolerar campos calorimétricos que a LLM emitir espontaneamente, garantindo que sejam descartados sem quebrar validação.

### Consequências

- **Positivas**: histórico consistente; troca de modelo é indolor; testes rápidos com mock; UX previsível.
- **Negativas / dívida técnica**: qualquer alimento fora do TBCA cai em `no_catalog_hit` — motiva `manual-catalog-recovery` (Bloco 5, `feat/bloco-5-catalog-recovery`); catálogo hardcoded exige atualização periódica (v1.3.0 já pegou dessincronia entre seed enriquecido e testes hardcoded).

---

## Decisão 2 — Colunas nutricionais materializadas em `food_items`

### Contexto

Poderia armazenar apenas `catalog_ref_id` + `grams`/`ml` e calcular `kcal` sob demanda. Reduziria colunas de 9 para 2. Porém `DailyRecomputeService` faria N joins e recalcularia a cada leitura.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Materializar kcal + macros + micros no item (escolhida) | Recompute é `SUM` puro no Postgres; histórico estável a mudanças do catálogo; leitura O(1) | Escrita ~9 colunas por item; recompute completo custa mais que delta (aceito) |
| B — Calcular on-read | Schema mais enxuto | Todo recompute vira N+1 lookup; mudança no seed retro-modifica histórico (ruim) |
| C — Materializar só kcal, deixar macros derivados | Compromisso ruim | Perde consistência entre visões |

### Decisão tomada

**Opção A.** Como `DailyRecomputeService` roda em toda mutação (Const. §10, INV-4), custo de leitura é o dominante; escrita extra em item é aceitável e cabe no envelope de latência (P50 ≤ 6s texto puro).

### Consequências

- **Positivas**: snapshot é `SELECT SUM(kcal), SUM(protein_g), ... FROM food_items WHERE ... AND deleted_at IS NULL`; nenhuma dependência atual do catálogo em runtime.
- **Negativas**: mudança de valor em `nutrient_facts` **não** retrocede em items existentes (aceito — histórico congelado é feature, não bug).

---

## Decisão 3 — Recompute from-scratch, nunca delta (INV-4)

### Contexto

Registro do dia é composto de alimentos, água, bebidas e atividades; cada um pode ser criado, corrigido ou deletado. Tentar manter `daily_snapshots` incremental (`kcal_in += novo_item.kcal`, `kcal_in -= item_deletado.kcal`) parece óbvio.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Recomputar SUM completo a cada mutação (escolhida) | Impossível ter drift; código é uma linha de agregação SQL; deleção soft "é grátis" (`WHERE deleted_at IS NULL`) | Custo por mutação é O(N_registros_do_dia) |
| B — Delta incremental | Escrita muito rápida | Bugs sutis em race conditions, soft delete, undo de correção; nunca é auditável ("kcal_in tá errado, mas por quê?") |

### Decisão tomada

**Opção A.** N por dia é ordem de 10-30; agregação SQL é ~10ms.

### Consequências

- **Positivas**: bug de drift é impossível por construção; migrations que alteram schema de items podem re-rodar recompute sem preocupação; correção arbitrária no passado é trivial (só rodar recompute do dia).
- **Negativas**: em picos hipotéticos (100 items/dia), custo por mutação cresce linear — não é problema no MVP single-user.

---

## Decisão 4 — Reason strings em `ComputedNutrition.reasons`

### Contexto

Quando `NutritionCalculator` devolve zeros, precisa comunicar por quê (falta hit? falta gramas? basis desconhecido?). Poderia usar exception, `Optional`, enum.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — `reasons: list[str]` (escolhida) | Múltiplas razões coexistem; fácil de virar warning no snapshot; grep-friendly | Sem tipagem forte no valor |
| B — `Enum(NoCatalogHit, MissingGrams, ...)` | Type-safe | Extensibilidade cara; nomes em código não casam com códigos no cliente (`no_catalog_hit`) |
| C — Levantar exception | Explícito | Force o caller a wrappar; N itens = N try/except |

### Decisão tomada

**Opção A.** Strings casam 1:1 com códigos de warning no snapshot; `MealService._create_item` faz o forwarding trivial (`for reason in computed.reasons: if reason.startswith("missing_"):`).

### Consequências

- **Positivas**: cliente do frontend recebe códigos estáveis; adicionar nova razão é adicionar string; testes assertam `reasons=["no_catalog_hit"]` diretamente.
- **Negativas**: falta lint que garanta que reason strings usadas casam com "códigos de erro estáveis" declarados em `spec.md §5.2` — potencial dívida (test unitário poderia fechar).

---

## Decisão 5 — Threshold de confiança fixo em `0.5`

### Contexto

`needs_confirmation` é acionado por `confidence < 0.5`. É arbitrário; poderia ser configurável ou por-tipo.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Constante `LOW_CONFIDENCE_THRESHOLD = 0.5` (escolhida) | Simples; documentado no service; ajuste é 1 linha | Fixo para todos os alimentos |
| B — Configurável por env | Ajuste no ar | Superficialmente flexível; ninguém tunou em MVP |
| C — Por alimento (via catálogo) | Modelo mais rico | Overkill para MVP; catálogo teria coluna extra |

### Decisão tomada

**Opção A.** Constant literal em `services/meal.py`; se precisar mudar, revisão de PR e teste ajustado juntos.

### Consequências

- **Positivas**: código legível; teste `test_sp24_low_confidence_flags_needs_confirmation` é preciso.
- **Negativas**: se o modelo mudar de escala de confidence (Sonnet 4.7 pode ser mais calibrado), threshold precisa ser revisitado.

---

## Dívida técnica conhecida

| Item | Impacto | Prioridade |
|---|---|---|
| Catálogo TBCA hardcoded no seed (`tbca_seed.py`); atualizar exige PR + revisar testes hardcoded (15 asserts em 8 files quebrados no PR #34) | Médio — sincronia manual | Alta (mitigar com teste de integridade seed × asserts) |
| `raw_llm_response` gravado em `messages`, mas sem rotação/purga; volumes crescem indefinidamente | Baixo (ainda) | Baixa |
| `MealService.create_from_llm` levanta `ValueError` puro em `food_items=[]` — bug de caller silenciado como erro genérico | Baixo (defensivo) | Baixa |
| Falta métrica de taxa de `no_catalog_hit` por semana — sinal para investir em seed | Médio (UX) | Média (motiva `manual-catalog-recovery` do Bloco 5) |
| Sem lint que garanta reason strings de `ComputedNutrition.reasons` estão declaradas em `spec.md §5.2` | Baixo | Baixa |

## Riscos identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| Nova versão do modelo Anthropic (Sonnet 4.7+) altera calibração de `confidence` e faz threshold 0.5 virar "quase tudo cai em `needs_confirmation`" | Média | Médio — usuário se cansa de confirmar | Monitorar taxa; recalibrar threshold; considerar per-intent |
| Prompt muda e a LLM começa a emitir `grams_estimate=None` mais frequentemente | Baixa | Alto — item cai em `missing_grams`, kcal=0 | Warning `missing_grams` é visível; ajustar prompt no `system_v2.md` + adicionar teste de regressão |
| Anthropic outage por > 60s (SP-14) | Baixa | Médio — mensagem "não consegui interpretar" | Fallback automático Sonnet → Haiku via `AnthropicClient`; usuário reformula |
| Seed TBCA dessincronizado com testes hardcoded | Média | Baixo — CI pega | Fase 10 (v1.3.0) já cobre; adicionar teste que valida seed contra `nutrient_facts` mínimo esperado |
| Concorrência: duas mensagens do mesmo user chegam simultaneamente e recompute vira race | Baixa (single-user MVP) | Baixo | Aceito por ora (MVP); em multi-user, adicionar advisory lock por `day_log_id` no `DailyRecomputeService` |
| Catálogo cresce demais (`LocalTBCACatalog` em memória) | Baixa (poucas centenas de items) | Baixo | Move-o para query direta em `nutrient_facts` quando passar de ~10k items |

## Alternativas para pós-MVP

- **Streaming da resposta do assistant** (SSE) — hoje é polling; latência percebida seria menor.
- **Cache de lookup do catálogo** por request — hoje `LocalTBCACatalog.lookup` já é O(1) em memória, mas em multi-user pode virar hot path.
- **Vetor embedding do `normalized_name`** para fuzzy match ("arroz branco" vs "arroz branco cozido") — hoje depende de `normalize_name` + exact match; funciona bem pt-BR mas quebra em pequenas variações.
- **`food_items.origin_photo_media_id`** — apontar cada item para a foto de origem quando SP-22 dispara. Facilitaria auditoria e re-processamento com modelo mais novo.
