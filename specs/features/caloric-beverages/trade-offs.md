# Trade-offs — Registro de bebidas calóricas

## Decisão 1 — Tabela dedicada `beverage_records` vs. unificada com água

### Contexto
SP-50..52 exigem registrar bebidas calóricas; SP-40..42 água pura. A Constituição Art. IV §13-14 fixa que bebida nunca conta em `water_ml` (INV-3) e água nunca em `other_liquids_ml` (INV-2). Mesma decisão de `water-tracking/trade-offs.md` decisão 1 — documentada lá em detalhe; aqui o foco é o lado beverage.

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A. Tabelas separadas** `beverage_records` + `water_records` (escolhida) | INV-3 enforced por separação física. `SUM(other_liquids_ml)` não precisa filtrar `kind`. Macros materializados só em beverage. | Dois schemas para manter. Switches `TargetKind.BEVERAGE` vs `.WATER` em correção/deleção. |
| B. `liquid_records` com `kind` | Um schema. | Risco de vazamento: `kind=beverage` poderia ir para `SUM(water_ml)` se filtro esquecido. INV-3 viraria validação runtime. |

### Decisão Tomada
**Opção A** — tabelas separadas. INV-3 é inegociável; a separação física é o enforcement mais forte.

### Consequências
- **Positivas**: `test_beverage_never_lands_in_water_table` fecha a questão. `DailyRecomputeService._aggregate_beverage` é direto.
- **Negativas / dívida técnica**: `correction.py` e `deletion.py` precisam de `TargetKind.BEVERAGE` vs `.WATER` (switches extras).

---

## Decisão 2 — Reutilizar `NutritionCatalog` + `NutritionCalculator` de alimentos

### Contexto
Bebidas calóricas precisam de lookup nutricional e cálculo de macros. Alimentos já têm `NutritionCatalog.lookup` + `NutritionCalculator.compute` testados (90% cobertura, plan.md §5.3).

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A. Reutilizar** `NutritionCatalog` + `NutritionCalculator` (escolhida) | Uma fonte de cálculo. Testes já existem. Catálogo TBCA cobre bebidas (leite, suco). | `compute(hit, grams=None, ml=...)` precisa de branch para basis `per_100ml` — já existe. |
| B. `BeverageCalculator` separado | Isolamento total. | Duplicação de lógica. Mais um ponto de manutenção. |

### Decisão Tomada
**Opção A** — reutilizar. `NutritionCalculator.compute(hit, grams=None, ml=volume_ml)` já suporta basis `per_100ml`; beverage só passa `ml` em vez de `grams`.

### Consequências
- **Positivas**: uma fonte de verdade para cálculo nutricional. Mudança em `NutritionCalculator` beneficia food + beverage.
- **Negativas**: se `compute` tiver bug em basis `per_100ml`, afeta ambos — mas testes cobrem.

---

## Decisão 3 — `BeverageIn(_LenientBase)` com `extra="ignore"` vs. `forbid`

### Contexto
A LLM frequentemente inventa campos em bebidas (`kcal`, `sugars_g`, `caffeine_mg`) que não consumimos. `WaterIn` é `_StrictBase` (`forbid`) porque água é simples; beverage é mais complexa.

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A. `extra="ignore"`** (escolhida) | Tolerância a lixo da LLM. Não quebra UX com `validation_exhausted`. | Pode mascarar campos úteis futuros se alguém adicionar e a LLM não emitir. |
| B. `extra="forbid"` | Estrito; rejeita payload inesperado. | Invocaria `validation_exhausted` com frequência — "Não consegui interpretar" em mensagens válidas. |

### Decisão Tomada
**Opção A** — `ignore`. Mesma estratégia de `FoodItemIn` e `ActivityIn` (documentada em `food-logging/architecture.md` decisão 3).

### Consequências
- **Positivas**: menos retrys semânticos. UX estável.
- **Negativas**: se a LLM emitir um campo que **deveríamos** consumir (ex.: `caffeine_mg` no futuro), não vamos notar até adicionar ao schema.

---

## Decisão 4 — `beverage_kind='other'` fixo no MVP

### Contexto
SP-50 menciona "café, leite, suco, refrigerante, chá adoçado, álcool" — sugere subtipos. Mas o MVP não usa essa discriminação em nenhuma regra.

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A. `Literal["other"]` fixo** (escolhida) | Simples. Sem regras por subtipo. | Sem diferenciação alcoólico/lácteo — não há warning de álcool, por exemplo. |
| B. Enum completo `('coffee','milk','juice','soda','tea','alcohol','other')` | Permite regras específicas (ex.: warning de álcool). | LLM precisa classificar; mais um ponto de falha. Sem demanda no MVP. |

### Decisão Tomada
**Opção A** — `Literal["other"]`. Sem uso do campo além do default hoje.

### Consequências
- **Positivas**: zero acoplamento com subtipos.
- **Negativas / dívida técnica**: se surgir requisito de warning de álcool ou relatório por tipo de bebida, será necessário evoluir o enum. Campo `beverage_kind` já existe no schema — migração só adicionaria valores.

---

## Decisão 5 — Sem gate defensivo para "água classificada como beverage"

### Contexto
`HydrationService` tem `_NON_WATER_HINTS` para rejeitar café/leite como `log_water`. Mas o inverso — água classificada como `log_beverage` — não tem gate. Se a LLM mandar "água" como `log_beverage`, persiste com `kcal=0` e soma em `other_liquids_ml` (incorreto).

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A. Sem gate** (escolhida hoje) | Simples. O prompt orienta a LLM. | Água pode inflar `other_liquids_ml` se LLM errar. |
| B. Hints reversos (`_WATER_IN_BEVERAGE_HINTS`) | Defensivo. | Mais uma lista manual. Risco de falso positivo ("água tônica" é bebida calórica). |

### Decisão Tomada
**Opção A** — sem gate. Risco baixo (LLM geralmente acerta água → `log_water`).

### Consequências
- **Positivas**: menos código, menos falsos positivos.
- **Negativas**: inconsistência técnica possível. Ver `<!-- TODO -->` em `specifications.md` regra 8.

---

## Dívida Técnica Conhecida

| Item | Impacto | Prioridade |
|---|---|---|
| `beverage_kind='other'` sem discriminação | Sem warning de álcool; relatório sem quebra por tipo | Baixa |
| Sem gate para "água como beverage" | `other_liquids_ml` pode inflar | Baixa |
| `is_estimate` hardcoded `False` (igual water) | SP-42 parcial | Média |
| Sem métricas de `no_catalog_hit` em beverage | Difícil saber se seed TBCA cobre bebidas comuns | Baixa |

## Riscos Identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| LLM classifica água como `log_beverage` | Baixa | Médio (`other_liquids_ml` inflado) | Prompt `system_v2.md` orienta; monitorar via audit |
| Catálogo TBCA sem bebida comum (ex.: energético) | Média | Baixo (fica zerado + pendente) | Seed enriquecido (#11); usuário pode cadastrar via `manual-catalog-recovery` |
| Bug em `NutritionCalculator` basis `per_100ml` | Baixa | Alto (afeta food + beverage) | Testes de `compute` com ml; cobertura 90% |
