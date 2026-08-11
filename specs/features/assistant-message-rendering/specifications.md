# Especificações Técnicas — Renderização de assistant messages (Bloco 2)

> **Rastreabilidade**: SP-115..SP-118 · Backend: `apps/api/app/services/message_formatter.py` · Frontend: `apps/web/src/app/(app)/chat/{AssistantContent,DayTotalsBar,PendingItemsModal}.tsx`.

## Escopo técnico

Dois lados conectados por um contrato markdown:

- **Backend** (`message_formatter.py`): produz o `content` markdown da assistant message a partir do resultado determinístico de cada intent. Funções `compose_meal`, `compose_water`, `compose_beverage`, `compose_activity`. Chamadas por `MessageProcessor._handle_registration` passando `local_today(user.timezone)`.
- **Frontend** (três componentes client): `AssistantContent` faz parse/render do markdown; `DayTotalsBar` exibe/revalida totais via `GET /days/today`; `PendingItemsModal` torna inline a confirmação/descarte de itens pendentes.

Sem endpoints novos — usa `GET /days/today` (SP-90), `POST /records/food-items/{id}/confirm`, `DELETE /records/food-items/{id}` (features existentes).

## Interface

### `AssistantContent({ content }: { content: string })`

Parser markdown mínimo → lista de `Block`:

```ts
type Block =
  | { type: 'table'; rows: string[][] }
  | { type: 'paragraph'; text: string };
```

Regras de parsing (`parseBlocks`):
- Linha em branco → separador.
- `|` inicial + próxima linha começando em `| ---` → tabela; coleta linhas `|...|` consecutivas; `splitRow` corta em `|` e trim.
- Caso contrário → parágrafo (junta linhas não vazias e não-`|`).

Render:
- `paragraph` → `<p className="whitespace-pre-wrap leading-relaxed">`.
- `table` → `<div>` com borda + `<table>`; `<thead>` fundo slate; `<td>` label (col 0) text-slate-600, demais font-medium.
- `**bold**` → `<strong>` (regex `/\*\*(.+?)\*\*/g`).
- Detecção: célula contém `≈` → classe `italic`; label (col 0) termina em `*` → classe `text-amber-700`.

### `DayTotalsBar({ revalidateKey, onPendingClick, onCloseDayClick })`

```ts
type FoodItemRef = {
  id: string; detected_name: string;
  grams?: number | null; ml?: number | null; quantity?: number | null; unit?: string | null;
  kcal?: number | null; needs_confirmation?: boolean | null;
};
```

- `useEffect` re-fetch de `/days/today` quando `revalidateKey` muda (e no mount).
- `collectPendingItems(day)` percorre `records.food[*].items` filtrando `needs_confirmation`.
- Estados: `loading` (skeleton), `empty` (kcal_in=0 && outros=0 → dashed box), `closed` (badge "Dia encerrado").
- Colapsa horizontal: container `overflow-x-auto`; cada `<Stat>` é `shrink-0`.
- `Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 })`.

### `PendingItemsModal({ items, onClose, onChanged })`

- Overlay fixo `role="dialog" aria-modal`; fecha ao clicar background.
- `confirm(item)`: `POST /records/food-items/${id}/confirm` (sem body) → `onChanged()`.
- `discard(item)`: `DELETE /records/food-items/${id}` → `onChanged()`.
- `busyId` bloqueia botões durante request em curso.

## Modelo de dados (contratos usados)

### `DayResponse` (consumido pela barra)

```ts
type DayResponse = {
  date: string; status: 'open' | 'closed';
  totals: { kcal_in: number; kcal_out: number; protein_g: number; carbs_g: number;
            fat_g: number; fiber_g: number; water_ml: number; other_liquids_ml: number; };
  records: { food: Array<{ id: string; items: FoodItemRef[] }>; water: unknown[];
             beverage: unknown[]; activity: unknown[]; };
};
```

### Markdown emitido pelo `message_formatter`

Estrutura de `content` (SP-118):

```
Registrei o almoço.

**Total da refeição — Almoço**

| Indicador | Total |
| --- | --- |
| Calorias | ≈ 186 kcal |
| Proteínas | ≈ 4,6 g |
...

**Total acumulado — 30/07/2026**

| Indicador | Total |
| --- | --- |
| Calorias Consumidas | 1.200 kcal |
...

As estimativas nutricionais são aproximações...
**Confirma estes itens?** — feijão, sushi ninja
```

## Fluxo de dados

### Render de assistant message (SP-115/118)

1. `MessageProcessor._handle_registration` recebe o resultado do intent (meal/water/beverage/activity) + `recompute.snapshot`.
2. Chama a função `compose_*` correspondente passando `local_today(user.timezone)`.
3. `compose_*` produz markdown e o salva como `assistant_message.content` (persistido + retornado).
4. Cliente polla `GET /chat/messages?after=`, recebe a mensagem, renderiza `<AssistantContent content={m.content} />` apenas para `role='assistant'`.
5. `parseBlocks` → `Block[]` → renderiza cards/parágrafos.

### Revalidação da barra (SP-116)

1. Poll do `ChatPage` detecta nova `role='assistant'` → `setTotalsRevalidateKey(k => k+1)`.
2. `DayTotalsBar` reage ao `revalidateKey` no `useEffect` → re-fetch `/days/today`.
3. `collectPendingItems` recalcula pendentes; badge aparece/desaparece.

### Confirmação inline (SP-117)

1. Badge clicado no `DayTotalsBar` → `onPendingClick(items)`.
2. `ChatPage` seta `pendingItems` → renderiza `PendingItemsModal`.
3. **Confirmar** → `POST /records/food-items/{id}/confirm`; backend desmarca `needs_confirmation` (sem recompute de macros — item já tem valores), grava `audit_events`.
4. **Descartar** → `DELETE`; soft delete + recompute (INV-4) + audit.
5. `onChanged()` → `ChatPage` incrementa `totalsRevalidateKey` e fecha modal. Barra re-busca `/days/today`.

## Regras de negócio

1. **Formatação pt-BR determinística**: `_fmt_int` (1200→1.200), `_fmt_dec` (46.7→46,7), `_fmt_kcal`/`_fmt_g` (com prefixo `≈ ` opcional), `_fmt_ml`/`_fmt_min` (sem `≈`).
2. **`≈` só em estimativa**: `_has_approx_food_items` verifica `is_estimate`/`needs_confirmation` em items OU warnings `low_confidence_item`/`no_catalog_hit`. Água e volume nunca.
3. **Tabela de refeição agrega só	os items da mensagem**: somas (`kcal_sum`, `p_sum`, ...) iteram `meal.items` — não o snapshot diário.
4. **`Calorias Gastas`/`Saldo` só quando `kcal_out > 0`**: evita ruído em dias sem atividade.
5. **`Líquidos Totais*`**: `*` no rótulo e nota em rodapé quando `other_liquids_ml > 0`.
6. **Warnings deduplicados**: `_warnings_block` preserva ordem, remove duplicados por nome.
7. **Disclaimer sempre presente** (Const. Art. VII §26) — fonte reduzida mas legível.
8. **Endpoint `/confirm` idempotente e sem recompute**: `already_confirmed` retornado; backend só desmarca `needs_confirmation`.
9. **Modal fecha por overlay/×/ação**: `onChanged` sinaliza pai.

## Configurações e variáveis de ambiente

| Variável | Descrição | Padrão | Obrigatória |
|---|---|---|---|
| `INTERNAL_API_URL` | URL interna para server components (`/day` reusa `CloseDayModal`) | — | Sim (server) |
| `NEXT_PUBLIC_API_URL` | URL base relativa `/api` para client (`DayTotalsBar`/`PendingItemsModal`) | `/api` | Sim (client) |

Sem variáveis específicas do bloco — formatters são hardcoded no backend.

## Referências de implementação

- **Backend formato**: `apps/api/app/services/message_formatter.py` (324 linhas) — `_fmt_*`, `_table`, `_daily_totals_table`, `_warnings_block`, `compose_*`.
- **Orquestração**: `apps/api/app/services/message_processor.py::_handle_registration` (delega para `compose_*`).
- **Frontend render**: `apps/web/src/app/(app)/chat/AssistantContent.tsx` (152 linhas) — `parseBlocks`, `renderInline`, `splitRow`.
- **Barra de totais**: `apps/web/src/app/(app)/chat/DayTotalsBar.tsx` (185 linhas) — `DayResponse`, `collectPendingItems`, `Stat`.
- **Modal**: `apps/web/src/app/(app)/chat/PendingItemsModal.tsx` (130 linhas) — `confirm`, `discard`.
- **Host**: `apps/web/src/app/(app)/chat/page.tsx` — integra os três; `totalsRevalidateKey`, `pendingItems`.
- **Endpoint confirm**: `apps/api/app/api/routes/records.py` — `POST /records/food-items/{id}/confirm` (linha ~251).
- **Testes**: `apps/api/tests/test_message_formatter.py` (18 casos, parte dos 226 tests do backend).