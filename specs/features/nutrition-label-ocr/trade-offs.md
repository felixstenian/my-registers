# Trade-offs — Leitura de rótulo nutricional (Fase 4.b)

## Decisão 1 — Catálogo compartilhado (`nutrient_facts` sem `user_id`)

### Contexto
Produtos cadastrados por rótulo precisam ficar no catálogo para lookup futuro. Em MVP single-user, não há motivo para isolar por usuário.

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A. `nutrient_facts` sem `user_id`** (escolhida) | Simples. `LocalTBCACatalog.lookup` não filtra por dono. | Em multi-tenant, produtos de um usuário vazam para outro. `PATCH` sem dono — qualquer auth edita. |
| B. `owner_user_id` nullable | Isolamento em multi-tenant. | Complexidade: lookup precisa decidir entre catálogo global (TBCA) e por usuário. |
| C. Catálogo por usuário totalmente separado | Isolamento total. | TBCA seria duplicado por usuário; desperdício. |

### Decisão Tomada
**Opção A** — sem `user_id`. MVP é single-user; `TBCA_2023` é global por natureza.

### Consequências
- **Positivas**: `LocalTBCACatalog` simples; `PATCH` só checa auth.
- **Negativas / dívida técnica**: multi-tenant precisaria `owner_user_id` + revisão de lookup e PATCH. Marcado como risco.

---

## Decisão 2 — Normalizar `per_serving` para `per_100g|per_100ml` no upsert

### Contexto
Rótulos brasileiros usam `per_serving` com `serving_size_g|ml`. `NutritionCalculator` só sabe escalar por grams/ml a partir de `per_100g|per_100ml`.

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A. Normalizar no upsert** (`_resolve_basis_and_scale`) (escolhida) | Catálogo só armazena basis canônico. `NutritionCalculator` não muda. | Informação original do rótulo (per_serving) é perdida — só fica o normalizado. |
| B. Persistir `per_serving` + escalar no lookup | Preserva original. | `NutritionCalculator` precisa de branch para `per_serving`. `CheckConstraint` em `basis` teria que permitir `per_serving`. |
| C. Persistir ambos (`basis` + `serving_size`) e escalar sob demanda | Flexível. | Redundância; duas fontes de verdade. |

### Decisão Tomada
**Opção A** — normalizar no upsert. `serving_grams` é preservado (para `also_consumed.servings`), mas `basis` vira `per_100g|per_100ml`.

### Consequências
- **Positivas**: `NutritionCalculator` permanece simples. `CheckConstraint` em `basis` só permite 2 valores.
- **Negativas**: se alguém quiser mostrar "valor por porção" na UI, precisa reescalar a partir de `per_100g` + `serving_grams`.

---

## Decisão 3 — Idempotência por `barcode` com fallback `(canonical_name, brand)`

### Contexto
Felix pode refotografar o mesmo produto. Não queremos duplicar `nutrient_facts`.

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A. `barcode` (chave forte) + fallback `(canonical, brand)`** (escolhida) | Barcode é único por produto. Sem barcode, par canônico+marca é proxy. | Sem barcode e com marca ambígua, pode atualizar errado. |
| B. Só `(canonical_name, brand)` | Sem depender de barcode. | Dois produtos diferentes com mesmo nome canônico e marca (ex.: sabores) conflitam. |
| C. Sempre criar novo + merge no lookup | Sem perda de informação. | Catálogo incha; lookup fica complexo. |

### Decisão Tomada
**Opção A** — barcode优先; fallback por par canônico+marca.

### Consequências
- **Positivas**: `test_upsert_updates_existing_on_repeat_barcode` valida; catálogo não incha.
- **Negativas**: produtos sem barcode e com mesmo nome+marca se sobrescrevem. Risco baixo em MVP.

---

## Decisão 4 — `NutritionLabelIn(_StrictBase)` com `extra="forbid"`

### Contexto
Rótulo tem campos bem definidos (kcal, macros, micros, serving). Diferente de `FoodItemIn`/`BeverageIn` que são livres.

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A. `extra="forbid"`** (escolhida) | Estrito; LLM inventando campo é sinal de erro. | Pode invocar `validation_exhausted` se LLM adicionar campo legítimo não mapeado. |
| B. `extra="ignore"` | Tolerante. | Mascara erros; campos úteis futuros podem ser silenciosamente descartados. |

### Decisão Tomada
**Opção A** — `forbid`. Rótulo é estruturado; se a LLM devolver lixo, melhor pedir retry do que persistir errado.

### Consequências
- **Positivas**: contrato claro; `test_per_serving_without_size_rejected` valida o validator.
- **Negativas**: se Anthropic adicionar campo novo no schema do tool_use, precisa atualizar `NutritionLabelIn`.

---

## Decisão 5 — `PATCH` só edita `label_ocr` e `manual`

### Contexto
SP-33 permite confirmar/ajustar valores. Mas facts `TBCA_2023`/`USDA_FDC` são canônicos — editar quebraria SP-35.

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A. Só `label_ocr` e `manual`** (escolhida) | Catálogo canônico permanece confiável. | Usuário não pode corrigir erro do TBCA (raro, mas possível). |
| B. Permitir editar tudo | Flexível. | Corrói a noção de fonte canônica; precedência SP-35 perde sentido. |
| C. Permitir editar mas marcar `overridden=true` | Flexível + rastreável. | Complexo; sem demanda no MVP. |

### Decisão Tomada
**Opção A** — só `label_ocr` e `manual`. `test_patch_nutrient_fact_refuses_tbca_source` valida.

### Consequências
- **Positivas**: `TBCA_2023` permanece fonte de verdade canônica.
- **Negativas**: se TBCA tiver erro, único caminho é cadastrar `label_ocr` alternativo e marcar `verified_by_user=true` (vence na precedência).

---

## Decisão 6 — `also_consumed` no mesmo envelope vs. mensagem separada

### Contexto
"Foto do rótulo + comi 170g" é uma interação natural. Separar em duas mensagens seria fricção.

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A. `also_consumed` no mesmo `NutritionLabelIn`** (escolhida) | Uma mensagem, uma transação. UX natural. | Envelope mais complexo; LLM precisa extrair dois blocos. |
| B. Mensagem separada para consumo | Simples; reutiliza `log_food`. | Fricção: Felix precisa enviar duas mensagens. |
| C. Intent composto `log_label_and_food` | Explícito. | Mais um intent; dispatch mais complexo. |

### Decisão Tomada
**Opção A** — `also_consumed` no mesmo envelope. `test_also_consumed_creates_food_record` valida.

### Consequências
- **Positivas**: UX fluida; transação atômica (fato + consumo).
- **Negativas**: LLM precisa extrair ambos; se errar o consumo, só o fato é cadastrado.

---

## Dívida Técnica Conhecida

| Item | Impacto | Prioridade |
|---|---|---|
| `nutrient_facts` sem `user_id` (catálogo compartilhado) | Vazamento em multi-tenant | Média (só relevante se sair de single-user) |
| `PATCH` sem filtro de dono | Qualquer auth edita facts `label_ocr` | Média (mesma condição) |
| `per_serving` original não preservado (só normalizado) | UI não pode mostrar "por porção" sem reescalar | Baixa |
| `aliases` só tem 2 entradas (`canonical` + `normalize_name(product_name)`) | Lookup por sinônimos limitado | Baixa |

## Riscos Identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| LLM lê rótulo errado (OCR impreciso) | Média | Médio (macros errados no catálogo) | `PATCH` permite corrigir; `verified_by_user` sinaliza confiança |
| Produto sem barcode colide com outro de mesmo nome+marca | Baixa | Baixo (sobrescreve) | Raro em MVP; `_find_existing_label_fact` é determinístico |
| Multi-tenant sem isolamento de catálogo | Baixa (MVP) | Alto (vazamento) | Só relevante se sair de single-user; ver Decisão 1 |
| `per_serving` com `serving_size=0` → divisão por zero | Baixa | Médio (ValueError) | `_resolve_basis_and_scale` defende; Pydantic `gt=0` poderia ser adicionado |
