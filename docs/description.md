# Como funciona o registro de alimentos — visão simplificada

Explicação do fluxo end-to-end quando o usuário manda uma mensagem tipo "100g de arroz" no chat. Cobre os **dois cenários** possíveis (catálogo tem o alimento vs catálogo não tem) e explica **por que o Bloco 5 existe** e como ele entra.

## Peças em jogo

Antes de descrever o fluxo, três conceitos-chave:

| Peça | O que é | Onde vive |
|--|--|--|
| **`nutrient_facts`** | Catálogo nutricional. Cada linha = "1 alimento" com kcal/proteína/carbo/gordura/etc. por 100 g (ou por 100 ml). Ex.: `arroz_branco_cozido` → `130 kcal/100g`. | Tabela Postgres, populada pelo seed TBCA + labels de fotos + cadastros manuais. |
| **`food_items`** | Registro do consumo do usuário. Ex.: "às 12:30 comi 150 g de arroz". Aponta pra `nutrient_facts.id` via `catalog_ref_id` **quando existe match**. | Tabela Postgres, gravada a cada mensagem `log_food`. |
| **`catalog_ref_id`** | Ligação. Se preenchido, sabemos exatamente qual entrada do catálogo foi usada e a macro é confiável. Se `NULL`, o item foi registrado mas ficou "solto". | Coluna FK em `food_items`. |

## Cenário 1 — Alimento **já cadastrado** (caminho feliz)

```
Usuário no chat: "150g de arroz"
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. LLM (Anthropic Claude) interpreta a mensagem            │
│    - Extrai: detected_name="arroz", grams=150,             │
│              normalized_name="arroz_branco_cozido"          │
│    - Devolve JSON estruturado via `tool_use`                │
│    - LLM NÃO calcula macros — só nomeia o item              │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. MealService.create_from_llm                             │
│    - Chama `catalog.lookup("arroz_branco_cozido")`          │
│    - Achou! → devolve hit com per_100g nutricional          │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. NutritionCalculator.compute(hit, grams=150)             │
│    - Determinístico no backend (INV-1)                      │
│    - kcal = 150 × 130 / 100 = 195                           │
│    - proteina = 150 × 2.7 / 100 = 4.05                      │
│    - ... (todos os macros escalados)                        │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. Persiste food_item                                       │
│    - kcal=195, protein_g=4.05, ..., is_estimate=False       │
│    - catalog_ref_id = <id do arroz no nutrient_facts>       │
│    - needs_confirmation = False   ← ✓ tudo certo            │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. DailyRecomputeService.recompute                          │
│    - Soma todos os food_items vivos do dia                  │
│    - Atualiza daily_snapshots (kcal_in, protein_g, etc.)    │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. message_formatter.compose_meal                           │
│    - Monta assistant message em pt-BR:                      │
│      "Registrei almoço.                                     │
│       | Calorias | 195 kcal |                               │
│       | Proteína | 4,1 g    |  ..."                         │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
Usuário vê a resposta no chat. `/day` mostra o item. Fim.
```

**Sinais visuais no chat/day:** valores normais, sem badge amarelo, sem `≈` antes dos números.

## Cenário 2 — Alimento **NÃO cadastrado** (é onde o Bloco 5 entra)

```
Usuário no chat: "100g de pão de queijo congelado"
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. LLM interpreta                                          │
│    - Extrai: normalized_name="pao_de_queijo_congelado"      │
│    - Mesma coisa do cenário 1                               │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. MealService.create_from_llm                             │
│    - Chama `catalog.lookup("pao_de_queijo_congelado")`      │
│    - ❌ Não achou → hit = None                              │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. NutritionCalculator.compute(hit=None, grams=100)        │
│    - Sem hit = retorna TUDO zerado (Const. §5-6 / INV-1)    │
│    - LLM NÃO chuta macros (viola INV-1)                     │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. Persiste food_item                                       │
│    - kcal=0, proteina=0, ...   ← ⚠ tudo zerado              │
│    - catalog_ref_id = NULL                                  │
│    - needs_confirmation = True                              │
│    - warning gerado: {                                      │
│        code: "no_catalog_hit",                              │
│        item_id: "<uuid>",                                   │
│        detected_name: "pão de queijo congelado"             │
│      }                                                       │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. DailyRecomputeService.recompute                          │
│    - Soma normal, mas esse item entra como 0 kcal           │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. compose_meal detecta warning `no_catalog_hit` (Bloco 5!) │
│    - Anexa MARCADOR na assistant message:                   │
│      <!-- catalog-recovery: <uuid> -->                      │
│      **Sem catálogo para:** **pão de queijo congelado**     │
│      Como você quer resolver?                               │
│      - 📸 Enviar foto do rótulo                              │
│      - ✏️ Cadastrar manualmente                              │
│      - ❌ Descartar item                                     │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 7. AssistantContent (frontend) parseia o marcador          │
│    - Reconhece <!-- catalog-recovery: id -->                │
│    - Extrai nomes em **bold** da label "Sem catálogo para:" │
│    - Renderiza CARD AMARELO com:                            │
│      • Nome do item                                         │
│      • Botão [✏️ Cadastrar] por item                         │
│      • Instrução textual pras opções foto/descartar         │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
Usuário vê o card + tem 3 caminhos pra resolver ↓
```

## O que o usuário pode fazer com o item zerado

Aqui é onde o **Bloco 5 (SP-140..SP-142)** entrega valor real. Antes do Bloco 5 existir, o usuário via os macros zerados e não sabia como corrigir sem descobrir os caminhos escondidos.

### Opção A — Cadastrar manualmente (Bloco 5, SP-141+142)

```
Clica [✏️ Cadastrar] no card
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ ManualCatalogForm abre (modal)                              │
│  - Nome pré-preenchido ("Pão de queijo congelado")          │
│  - canonical_name gerado auto (pao_de_queijo_congelado)     │
│  - Usuário preenche: basis, kcal, P/C/G                     │
│  - promote_food_item_id = <uuid do item zerado>             │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ POST /nutrient-facts/manual                                 │
│                                                             │
│  Passo 1: cria fact novo                                    │
│    source='manual', verified_by_user=True,                  │
│    created_by=<user.id>                                     │
│                                                             │
│  Passo 2: _try_promote_item (SP-142)                        │
│    - Acha item pelo uuid                                    │
│    - Atualiza catalog_ref_id = <novo fact.id>               │
│    - Recomputa macros via NutritionCalculator               │
│    - needs_confirmation = False                             │
│    - source = 'user_corrected'                              │
│    - Grava audit_event action='correct'                     │
│    - Chama DailyRecomputeService.recompute                  │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
Item volta pra vida com macros corretos.
Próximas mensagens com "pão de queijo congelado" acham o fact.
```

**Vantagem long-term:** o fact fica salvo no catálogo (`created_by` do usuário). Toda vez que ele registrar esse alimento de novo, cai no Cenário 1 sem pop-up.

### Opção B — Enviar foto do rótulo (Fase 4.b, SP-30..35)

Fluxo antigo, não é do Bloco 5:

1. Usuário anexa foto da tabela nutricional do produto na próxima mensagem
2. LLM lê o rótulo (OCR + estrutura)
3. Backend cria fact com `source='label_ocr'`, `verified_by_user=False`
4. Usuário PATCH `/nutrient-facts/{id}` pra confirmar valores

Diferença vs Opção A: precisa da embalagem física; útil pra itens comprados. Cadastro manual funciona pra qualquer coisa (comida caseira, restaurante, produto sem rótulo legível).

### Opção C — Descartar

Se o item foi um engano, ou o usuário não quer se preocupar:

```
No chat: "apaga o pão de queijo"
        │
        ▼
LLM interpreta como intent `delete_record`
        │
        ▼
DeletionService faz soft-delete (deleted_at=now)
        │
        ▼
Snapshot recomputado (item some da lista)
```

kcal_in do dia continua o mesmo (item era zero mesmo), mas some do `/day` e do modal de pendentes.

### Opção D — Confirmar zero (sem corrigir)

Clica em "confirmar" no botão do `FoodItemRow` do `/day`. Backend chama `POST /records/food-items/{id}/confirm` que **só** desmarca a flag `needs_confirmation`. Kcal continua 0. Útil quando o item realmente não tem valor nutricional relevante (ex.: chá sem açúcar) e você não quer receber lembretes.

## Onde entra cada peça do Bloco 5

Recapitulando as 3 SPs da §3.14 da spec:

| SP | O que faz | Camada |
|--|--|--|
| **SP-140** | Anexa o card "Sem catálogo" na assistant message quando aparece warning `no_catalog_hit`. Marcador HTML-comment + texto pt-BR + CTAs. | Backend (`message_formatter`) + Frontend (`AssistantContent`) |
| **SP-141** | Endpoint `POST /nutrient-facts/manual` — cadastra fact novo sem precisar de foto de rótulo. Fica ligado ao user (`created_by`). | Backend (`routes/nutrient_facts.py`) |
| **SP-142** | Junto com SP-141, aceita `promote_food_item_id` que promove o item legado (zerado) usando o fact recém-criado. Recomputa macros + audit + snapshot na mesma transação. | Backend (`_try_promote_item` helper) + Frontend (`ManualCatalogForm`) |

Sem o Bloco 5:
- Usuário via macros zerados e não sabia o que fazer
- Precisava lembrar dos caminhos escondidos (foto de rótulo, correção via chat, etc.)
- Itens legados ficavam zerados no histórico pra sempre

Com o Bloco 5:
- Card claro no chat ("Sem catálogo: [item] · [✏️ Cadastrar]")
- Um clique + form curto resolve
- Snapshot corrigido em segundos
- Fact fica salvo pra próximas ocorrências

## Sinais visuais que você deve reconhecer

| Sinal | Significado |
|--|--|
| Card amarelo no chat: "Sem catálogo:" | Bloco 5 ativado — 1+ item da mensagem não achou o catálogo |
| Badge amarelo "confirmar" no `/day` | `needs_confirmation=True` — pode ser porque veio sem catálogo, ou porque a confiança da LLM foi baixa (< 0.5) |
| Badge cinza "sem catálogo" no `/day` | `catalog_ref_id=NULL` — item ficou zerado. Vá pro chat ou corrija via "corrija X 100g" |
| `≈` antes de kcal/g na tabela | Aproximação — algum item da linha é estimativa ou pending |
| kcal_in do dia menor que esperado | Provavelmente 1+ item ficou zerado — cheque `/day` e o badge "sem catálogo" |

## Referências no código

Se quiser cavar mais fundo:

- Modelo do item: `apps/api/app/models/food_item.py`
- Modelo do catálogo: `apps/api/app/models/nutrient_fact.py`
- Lookup: `apps/api/app/integrations/nutrition/local_tbca.py`
- Cálculo determinístico: `apps/api/app/services/nutrition_calculator.py`
- Criação a partir da LLM: `apps/api/app/services/meal.py` → `MealService.create_from_llm`
- Recompute: `apps/api/app/services/daily_recompute.py`
- Composer da assistant message: `apps/api/app/services/message_formatter.py` → `compose_meal` + `_no_catalog_recovery_block`
- Endpoint manual: `apps/api/app/api/routes/nutrient_facts.py` → `create_manual_nutrient_fact`
- UI do card: `apps/web/src/app/(app)/chat/AssistantContent.tsx` (parser + render do bloco `recovery`)
- Form: `apps/web/src/app/(app)/chat/ManualCatalogForm.tsx`
- Constituição relevante: Artigo II §5-7 (LLM não calcula), Artigo III §10 (recompute from-scratch)
