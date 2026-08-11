# Requisitos — Renderização de assistant messages (Bloco 2)

> **Rastreabilidade**: SP-115..SP-118 em [`specs/001-mvp-registro-diario/spec.md`](../../001-mvp-registro-diario/spec.md#32-chat--mensagens) · Implementação: `apps/api/app/services/message_formatter.py` (backend, SP-118) + `apps/web/src/app/(app)/chat/{AssistantContent,DayTotalsBar,PendingItemsModal}.tsx` (frontend, SP-115/116/117). Bloco 2 (T-B201..T-B205) concluído em v1.0.0/v1.3.0.

## Visão geral

Transforma as respostas do assistente em conteúdo estruturado legível: (1) assistant messages viram tabelas markdown em pt-BR renderizadas como cards (SP-115/118); (2) uma barra fixa no `/chat` mostra os totais do dia e revalida a cada nova resposta (SP-116); (3) itens `needs_confirmation` ficam destacados e podem ser confirmados/descartados inline por modal (SP-117). Toda a formatação é determinística no backend — a UI só renderiza markdown conhecido.

## Requisitos funcionais

| ID | Requisito | SP | Prioridade |
|---|---|---|---|
| RF-001 | Após qualquer intent de registro (`log_food`/`log_water`/`log_beverage`/`log_activity`), a assistant message contém cabeçalho curto + tabela "Total da refeição/registro" + tabela "Total acumulado — DD/MM/YYYY" + aviso legal, nesta ordem. | SP-118 | May Have |
| RF-002 | Tabela "Total da refeição" agrega apenas `food_items` recém-criados nesta mensagem (não o dia todo); `log_water` → única linha `Água`; `log_activity` → linhas `Duração`+`Calorias gastas`. | SP-118 | May Have |
| RF-003 | Tabela diária contém `Calorias Consumidas`, `Calorias Gastas` (só se `kcal_out>0`), `Saldo Calórico` (só se `kcal_out>0`), `Proteínas`/`Carboidratos`/`Gorduras`/`Fibras`, `Água Pura`, `Líquidos Totais` (com `*` se `other_liquids_ml>0` + nota). | SP-118 | May Have |
| RF-004 | Números em pt-BR (vírgula decimal, ponto milhar). Prefixo `≈` em linha nutricional apenas quando ≥1 item envolvido tem `is_estimate=true` ou `needs_confirmation=true`. Água/volume nunca recebem `≈`. | SP-118 | May Have |
| RF-005 | Warnings (`needs_confirmation`/`no_catalog_hit`/`low_confidence_item`) viram bloco "Confirma estes itens? — <nomes>" abaixo do disclaimer, deduplicado preservando ordem. | SP-118 | May Have |
| RF-006 | UI do chat renderiza tabelas markdown como cards com header destacado; bold inline; parágrafos. Sem biblioteca de markdown externa (dialeto controlado pelo backend). | SP-115 | May Have |
| RF-007 | Células com `≈` (italic) e labels com `*` (amber accent) recebem destaque visual torado no parsing client-side. | SP-115 | May Have |
| RF-008 | Barra fixa acima da lista de mensagens mostra `kcal_in` (destaque), `kcal_out`/`Saldo` (se `>0`), P/C/G/Fib, Água, Outros líq. (se `>0`); colapsa horizontalmente em telas pequenas mantendo `kcal_in` visível. | SP-116 | May Have |
| RF-009 | Barra consulta `GET /days/today` no primeiro render e revalida via `revalidateKey` incrementado a cada nova assistant message detectada pelo polling. | SP-116 | May Have |
| RF-010 | Barra mostra estado vazio explicativo ("Nenhum registro hoje — mande sua primeira mensagem") quando `kcal_in=0` && sem líquidos. | SP-116 | May Have |
| RF-011 | Barra mostra badge clicável "N itens precisam de confirmação" quando `food_items` com `needs_confirmation=true` existem; abre modal. | SP-116/117 | May Have |
| RF-012 | Modal lista itens pendentes com nome + quantidade + kcal; botão **Confirmar** → `POST /records/food-items/{id}/confirm` (desmarca `needs_confirmation`, idempotente); botão **Descartar** → `DELETE /records/food-items/{id}` (soft delete + recompute). | SP-117 | May Have |
| RF-013 | Após ação no modal, sinaliza `onChanged()` para o pai revalidar a barra e fechar o modal. | SP-117 | May Have |

## Requisitos não funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | Backend é fonte de verdade da formatação; UI não reinterpreta valores numéricos (Const. Art. II — LLM não calcula, backend sim). | Integridade |
| RNF-002 | `Intl.NumberFormat('pt-BR')` na UI para formatar totais da barra (consistência com backend). | UX |
| RNF-003 | `≈` determinístico: backend decide; UI só estiliza (`isApproxCell`). | Confiabilidade |
| RNF-004 | Parser markdown client-side sem dependência externa — bundle enxuto. | Performance |
| RNF-005 | Aviso legal (Const. Art. VII §26) sempre presente no final da assistant message, fonte reduzida mas legível (não tooltip). | Conformidade |
| RNF-006 | Modal é acessível: `role="dialog"`, `aria-modal`, `aria-label`, fecha ao clicar overlay. | Acessibilidade |

## Restrições e premissas

- **SP-115..118 são `may`**: não bloqueiam MVP; já implementados e em produção desde v1.0.0/v1.3.0.
- **INV-4 (recompute from scratch)**: confirm/descartar dispara recompute do snapshot no backend; a UI apenas revalida via `GET /days/today`.
- **INV-2 (água ≠ macros)**: tabela de `log_water` nunca tem macros; só linha `Água`.
- **Dia fechado é imutável** (INV-5): `POST /records/food-items/{id}/confirm` e `DELETE` são bloqueados em dia `status='closed'`.
- **Dialeto markdown controlado**: conteúdo sempre gerado pelo backend; o parser suporta só o subconjunto que o `message_formatter` emite (bold, tabelas 2-cols, parágrafos).

## Dependências

**Depende de:**
- [`chat-messaging`](../chat-messaging/requirements.md) — `POST /chat/messages` (respostas que disparam renderização) + polling que incrementa `revalidateKey`.
- [`daily-snapshot`](../daily-snapshot/requirements.md) — `GET /days/today` fornece totais à barra.
- [`record-correction`](../record-correction/requirements.md) — `POST /records/food-items/{id}/confirm`.
- [`record-deletion`](../record-deletion/requirements.md) — `DELETE /records/food-items/{id}` (soft delete).
- [`food-logging`](../food-logging/requirements.md) — `food_items` com `needs_confirmation`/`is_estimate` são a origem dos warnings.
- [`anthropic-integration`](../anthropic-integration/requirements.md) — confirma SP-22/SP-24 produtozem `needs_confirmation`; este bloco só renderiza.

**Requerido por:**
- [`chat-composer-ux`](../chat-composer-ux/requirements.md) — `ChatPage` hospeda os componentes deste bloco; poll incrementa `totalsRevalidateKey`.
- [`day-close`](../day-close/requirements.md) — `CloseDayButton` na barra (T-704) reusa `CloseDayModal`.
- [`daily-detail-view`](../daily-detail-view/requirements.md) — `/day` reutiliza `CloseDayModal`/`CloseDayButton`.