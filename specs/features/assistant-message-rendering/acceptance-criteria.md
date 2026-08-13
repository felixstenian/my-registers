# Critérios de Aceitação — Renderização de assistant messages (Bloco 2)

> **Rastreabilidade**: SP-115..SP-118 · Contratos: [`requirements.md`](./requirements.md), [`specifications.md`](./specifications.md).

## AC-001 — Estrutura das assistant messages (SP-118)

**Dado que** um intent de registro (`log_food`/`log_water`/`log_beverage`/`log_activity`) foi processado com sucesso,
**Quando** a assistant message é persistida/retornada,
**Então** seu `content` contém, nesta ordem: (1) cabeçalho curto pt-BR ("Registrei o almoço.");
  (2) tabela "Total da refeição/registro/exercício"; (3) tabela "Total acumulado — DD/MM/YYYY"; (4) disclaimer; (5) bloco de warnings (opcional).

**Notas de validação:**
- Cabeçalho contextual: almoço→"Registrei o almoço."; água→"Registrei 500 ml de água."; bebida→"Registrei 300 ml de café."; atividade→"Registrei 40 min de corrida (moderada).".
- Duas tabelas separadas por linha em branco.

---

## AC-002 — Tabela "Total da refeição" agrega só items da mensagem (SP-118)

**Dado que** a mensagem criou 3 `food_items` para `lunch` (arroz/feijão/frango),
**Quando** `compose_meal` monta a tabela,
**Então** as linhas Calorias/Proteínas/Carboidratos/Gorduras/Fibras são **somatórios destes 3 items** (não do dia).

**Dado que** o intent é `log_water` com 500 ml,
**Quando** `compose_water` monta a tabela,
**Então** há uma única linha `Água | 500 ml` e nenhuma linha de macros (INV-2).

**Dado que** o intent é `log_activity` de 40 min,
**Quando** `compose_activity` monta a tabela,
**Então** há linhas `Duração | 40 min` e `Calorias gastas | ≈ 320 kcal`.

**Notas de validação:**
- `_dec(value)` normaliza `None` para `Decimal(0)`.

---

## AC-003 — Tabela diária contextual (SP-118)

**Dado que** `kcal_out = 0` (sem atividade no dia),
**Quando** `_daily_totals_table` é gerada,
**Então** só aparecem `Calorias Consumidas` (sem `Calorias Gastas` e sem `Saldo`).

**Dado que** `other_liquids_ml > 0` (café, leite...),
**Quando** a tabela diária é gerada,
**Então** o rótulo aparece `Líquidos Totais*` e abaixo da tabela há a nota "\* inclui café, leite, sucos e outras bebidas calóricas."

**Notas de validação:**
- `Saldo Calórico` mostra `+` quando `balance >= 0`.

---

## AC-004 — Prefixo `≈` determinístico (SP-118)

**Dado que** ≥1 `food_item` na mensagem tem `is_estimate=true` ou `needs_confirmation=true` (ou warning `low_confidence_item`/`no_catalog_hit`),
**Quando** a tabela é gerada,
**Então** todas as linhas nutricionais (Calorias/Proteínas/Carbs/Gorduras/Fibras) começam com `≈ `.

**Dado que** todos os items têm quantidade exata e catálogo confirmado,
**Quando** a tabela é gerada,
**Então** nenhuma linha tem `≈`.

**Dado que** o registro é água pura,
**Quando** a tabela é gerada,
**Então** a linha `Água` nunca tem `≈`.

**Notas de validação:**
- Volume de bebida também nunca recebe `≈` (`_fmt_ml`).
- Implementação: `_has_approx_food_items`; `_daily_totals_table(..., approx=...)`.

---

## AC-005 — Blocos de warnings (SP-118)

**Dado que** há items `needs_confirmation`/`no_catalog_hit`/`low_confidence_item` com nomes `["feijão", "sushi ninja", "feijão"]`,
**Quando** `_warnings_block` é gerado,
**Então** aparece "**Confirma estes itens?** — feijão, sushi ninja" (deduplicado, ordem preservada) após o disclaimer.

**Dado que** não há warnings relevantes,
**Quando** a mensagem é compostada,
**Então** o bloco de warnings é omitido.

---

## AC-006 — Renderização UI como cards (SP-115)

**Dado que** a `AssistantContent` recebe um `content` markdown gerado pelo backend,
**Quando** faz o parse,
**Então** tabelas tornam-se `<div>` com borda + `<table>` (header slate destacado); bold inline vira `<strong>`; demais viram `<p>`.

**Dado que** uma célula de valor contém `≈`,
**Quando** é renderizada,
**Então** recebe `className="italic"`.

**Dado que** um label (coluna 0) termina em `*` (ex.: `Líquidos Totais*`),
**Quando** é renderizado,
**Então** recebe `className="text-amber-700"`.

**Notas de validação:**
- Parser não usa biblioteca externa; só bold + tabelas + parágrafos.

---

## AC-007 — Barra de totais (SP-116)

**Dado que** o usuário está autenticado em `/chat` com registros no dia,
**Quando** o `DayTotalsBar` monta,
**Então** exibe `Cal. in` (destaque), P/C/G/Fib, Água; `Outros líq.` só aparece se `other_liquids_ml > 0`; `Cal. out`/`Saldo` só se `kcal_out > 0`.

**Dado que** uma nova assistant message é detectada pelo polling,
**Quando** `totalsRevalidateKey` é incrementado,
**Então** a barra refaz `GET /days/today` e atualiza os valores.

**Dado que** o dia está vazio (`kcal_in=0` e líquidos=0),
**Quando** a barra monta,
**Então** exibe "Nenhum registro hoje — mande sua primeira mensagem".

**Dado que** a tela é pequena,
**Quando** a barra renderiza,
**Então** fica rolável horizontalmente (`overflow-x-auto`) com `kcal_in` sempre visível.

**Notas de validação:**
- `Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 })`.

---

## AC-008 — Badge e modal de pendentes (SP-116/117)

**Dado que** existem `food_items` com `needs_confirmation=true`,
**Quando** a barra monta,
**Então** exibe badge "N itens precisam de confirmação" (ou "1 item precisa...") com `bg-amber-100`.

**Dado que** o usuário clica no badge,
**Quando** `onPendingClick(items)` é chamado,
**Então** o `PendingItemsModal` abre listando cada item com nome, quantidade e kcal.

**Dado que** o usuário clica "Confirmar" em um item,
**Quando** `POST /records/food-items/{id}/confirm` retorna 200,
**Então** `onChanged()` é chamado; a barra revalida; o item some da lista; o modal fecha se não há mais pendentes.

**Dado que** o usuário clica "Descartar",
**Quando** `DELETE /records/food-items/{id}` retorna 200,
**Então** soft delete acontece, recompute do snapshot (INV-4), audit gravado (INV-10), barra revalida.

**Dado que** o item está em dia `status='closed'`,
**Quando** confirm/discard é chamado,
**Então** backend rejeita (INV-5).

---

## Cenários de Borda

| Cenário | Comportamento Esperado |
|---|---|
| Markdown com parágrafo entre tabelas | `parseBlocks` separa em 3 blocks (table/paragraph/table); cada um renderiza independente. |
| Tabela com 1 linha de header e divisor mas 0 linhas de body | `<tbody>` vazio; `<table>` ainda renderiza com header. |
| `≈` em célula de label | Não recebe itálico (só valores, col != 0). |
| `*` no meio de label | Não dispara amber accent — só termina em `*`. |
| Barra monta antes do `/days/today` chegar | Estado `loading` exibe "Carregando totais do dia…". |
| Poll detecta 2 assistant messages em sequência | `revalidateKey` incrementa uma vez por poll com assistant; barra refetch só ao final. |
| Modal aberto e overlay clicado | Fecha (`onClick={onClose}`) sem	action. |
| Confirmar item já confirmado | `POST /confirm` idempotente; backend retorna `already_confirmed=true`; UI não duplica ação. |
| `_fmt_dec(None)` | Retorna `"0"` (defensivo). |

## Critérios de Não-Funcionalidade

| Critério | Threshold |
|---|---|
| Parser markdown sem dependência externa | 0 libs adicionais no bundle |
| Disclaimer sempre visível | Não vira tooltip/não some |
| Modal acessível | `role="dialog"` + `aria-modal` + `aria-label` |
| Barra revalida ao receber assistant message | < 1 round-trip após incrementar `revalidateKey` |
| `≈` determinístico |_BACKEND decide, UI estiliza_|