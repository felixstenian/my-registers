# Especificações Técnicas — Visão detalhada do dia (Bloco 6)

> **Rastreabilidade**: SP-150..SP-155 · Implementação: `apps/web/src/app/(app)/day/` (11 arquivos) + `apps/web/src/app/(app)/day/[date]/page.tsx` + `apps/api/app/services/day_query.py::_load_food` (micros).

## Escopo técnico

Página Next 16 App Router com dois entrypoints (`/day` para hoje e `/day/[date]` para passado) que delegam ao `DayView` compartilhado. Server components (zero JS no render de tabelas), com pontos client-only isolados:

- `DayNavigator` (navegação temporal via `useRouter`).
- `ConfirmItemButton` (POST inline + `router.refresh()`).
- `CloseDayButton` (abre `CloseDayModal` reusado do chat).
- `RefreshOnFocus` (refresh no mount + `visibilitychange` debounce).

Backend sem mudanças — consome `GET /days/today` e `GET /days/{date}` (feature `daily-snapshot`). `_load_food` (`day_query.py`) já retorna micros (`sodium_mg`/`calcium_mg`/`iron_mg`/`potassium_mg`) e metadata (`source`/`confidence`/`has_catalog`/`is_estimate`/`needs_confirmation`).

## Interface (arquivos)

### `/day/page.tsx` (SP-150) — server component
```tsx
export const dynamic = 'force-dynamic';
async function fetchToday(): Promise<DaySnapshot | { error: string }> {
  const cookieStore = await cookies();
  const cookieHeader = cookieStore.toString();
  const backend = process.env.INTERNAL_API_URL ?? 'http://localhost:8000';
  const res = await fetch(`${backend}/days/today`,
    { headers: { cookie: cookieHeader }, cache: 'no-store' });
  return res.ok ? res.json() : { error: `Erro ${res.status}...` };
}
export default async function DayPage() {
  const result = await fetchToday();
  return 'error' in result ? <ErrorPanel/> : <DayView data={result} allowClose />;
}
```

### `/day/[date]/page.tsx` (SP-154/155) — server component
- `params: Promise<{ date: string }>` (Next 16 async dynamic params).
- `DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/` rejeita path traversal antes do fetch.
- Data futura (`compareISO(date, todayLocalISO()) > 0`) → "Não é possível ver o futuro" + link "Voltar para hoje" (não chama backend).
- `GET /days/{date}` → 404 amigável ("Nenhum registro encontrado nesta data") + link "Voltar para hoje".
- `<DayView data={result} allowClose />` — `allowClose=true` permite encerrar dia passado aberto.

### `DayView.tsx` — compartilhado (SP-150..154)
Props: `data: DaySnapshot`, `allowClose: boolean`. Estrutura:
1. `<RefreshOnFocus />` (staleness guard).
2. Header: data pt-BR (`fmtDateFull`) + badge `closed`/`open` + `<CloseDayButton>` (só se `allowClose && status==='open' && !isEmpty`).
3. `<DayNavigator date={data.date} />` (SP-155).
4. `EmptyState` se `isEmpty`, senão:
   - `<TotalsCard>` — grid 12-col com køl-in/out/saldo/macros/água/outros.
   - `<MealSection slot records>` para cada slot em `MEAL_SLOT_ORDER`.
   - `<HydrationSection>` / `<BeverageSection>` / `<ActivitySection>`.
   - `<NarrativeCard>` se `data.narrative` (pós-fechamento).
5. `<Disclaimer />` (Art. VII §26).

`groupBySlot`: bucketiza `FoodRecord[]` por `meal_slot` (slots desconhecidos → `unspecified`); ordena por `occurred_at` dentro do slot.

### `MealSection.tsx` (SP-151) — server component
Retorna `null` se `records.length === 0`. Cabeçalho: nome pt-BR (`MEAL_SLOT_LABEL_PT`) + horário do primeiro registro + kcal parcial (soma de `rec.items[].kcal`). Grid 12-col header espelha o grid do `FoodItemRow.summary`. `records.flatMap(rec => rec.items.map(item => <FoodItemRow/>))`.

### `FoodItemRow.tsx` (SP-152) — server, `<details>` nativo
`<summary>` grid 12-col: detected_name + `<ConfirmItemButton>` (se `needs_confirmation`) + badge "sem catálogo" (se `!has_catalog`). Colunas: Quantidade/Calorias/P/C/G/Fib. Expansão revela micros (Sódio/Cálcio/Ferro/Potássio mg), Origem (`SOURCE_LABEL_PT`), Confiança LLM (só se `source==='llm'`). Sem micros → "Sem micronutrientes registrados neste item."

### `ConfirmItemButton.tsx` — client
`POST /records/food-items/${id}/confirm` → `router.refresh()`. State `idle|confirming|done`. `e.preventDefault()` + `e.stopPropagation()` para não toggle do `<details>` pai. Some em `done`.

### `CloseDayButton.tsx` (T-701/T-704 reuse) — client
Abre `CloseDayModal` (do chat); `onClosed` → `router.refresh()`.

### `DayNavigator.tsx` (SP-155) — client
`useRouter` + `useState(picked)`. Calcula `prevDate`/`nextDate` via `addDaysISO`. Condições de visibilidade: "Hoje" escondido no dia atual; "Próximo dia" só se `nextDate <= today`. `<input type="date" max={today}>` + botão "Ir" → `router.push('/day' | '/day/[date]')`. Futuro bloqueado client-side (sanity).

### `RefreshOnFocus.tsx` — client
`useEffect(() => router.refresh(), [])` no mount; `visibilitychange` listener com debounce `FOCUS_MIN_INTERVAL_MS = 2000`. Combate staleness do Router Cache do Next após mutações externas (ex.: confirmação no chat em outro dispositivo).

### `format.ts` — formatters + aritmética de datas
`fmtInt`/`fmtGrams`/`fmtKcal`/`fmtMg`/`fmtMl`/`fmtDateFull`/`fmtTime`/`fmtAmount`/`fmtConfidence` (todos pt-BR; `null|undefined|0` → `—`). Aritmética: `isoToParts`/`partsToIso`/`addDaysISO`/`todayLocalISO`/`compareISO` (UTC interno p/ evitar DST drift).

### `types.ts` — contratos + dicionários pt-BR
`DaySnapshot`/`DayTotals`/`FoodRecord`/`FoodItem`/`WaterRecord`/`BeverageRecord`/`ActivityRecord`. Maps: `MEAL_SLOT_ORDER`, `MEAL_SLOT_LABEL_PT`, `ACTIVITY_TYPE_LABEL_PT`, `CALC_METHOD_LABEL_PT`, `SOURCE_LABEL_PT`.

## Modelo de dados

Consumo do `DaySnapshot` (`GET /days/today`/`GET /days/{date}`):

```ts
interface DaySnapshot {
  date: string; status: 'open'|'closed'; closed_at: string|null;
  totals: { kcal_in; kcal_out; kcal_balance; protein_g; carbs_g; fat_g;
            fiber_g; sodium_mg; calcium_mg; iron_mg; potassium_mg;
            water_ml; other_liquids_ml; };
  records: { food: FoodRecord[]; water: WaterRecord[];
             beverage: BeverageRecord[]; activity: ActivityRecord[]; };
  warnings: Array<Record<string, unknown>>;
  narrative: string|null; snapshot_version: number;
}
interface FoodItem {
  id; detected_name;
  grams; ml; quantity; unit;                                  // quantidade
  kcal; protein_g; carbs_g; fat_g; fiber_g;                  // macros
  sodium_mg; calcium_mg; iron_mg; potassium_mg;               // micros (SP-152)
  confidence; has_catalog; is_estimate; needs_confirmation;   // metadata
  source: 'llm'|'user_corrected'|'label_ocr'|'user_manual';
}
```
Backend `_load_food` (`day_query.py:136`) produz o dict com micros e metadata; `DaySnapshotOut` é o schema Pydantic canônico.

## Fluxo de dados

### Render `/day` hoje (SP-150)
1. Server component `fetchToday()` — `GET /days/today` com `cookie: cookieHeader` (server pass-through).
2. 200 → `DayView`; erro → ErrorPanel.
3. `DayView` agrupa `food` por `meal_slot`, determina `isEmpty`.
4. Renderiza `RefreshOnFocus` → `router.refresh()` no mount.
5. `MealSection` por slot em ordem canônica; `FoodItemRow` por item.
6. `AuxiliarySections` cada uma com `if (records.length === 0) return null`.

### Confirmar item inline (SP-151)
1. User clica `<ConfirmItemButton>` dentro do `<summary>`.
2. `e.preventDefault/stopPropagation` impede toggle do `<details>`.
3. `POST /records/food-items/{id}/confirm` via `api-client`.
4. Success → `state='done'` (component retorna `null`) + `router.refresh()` → server component re-renderiza sem o badge.

### Encerrar dia (T-704 reflui em Bloco 6)
1. User clica `<CloseDayButton>` (visível se `allowClose && status==='open' && !isEmpty`).
2. Abre `CloseDayModal` (do chat) com a data.
3. Confirm fecha → `router.refresh()` re-renderiza com `status='closed'` + narrativa.

### Navegação temporal (SP-155)
1. User clica "← Dia anterior" → `Link href="/day/${prevDate}"` (sempre presente).
2. "Próximo dia →" — `Link` só renderizado se `compareISO(nextDate, today) <= 0`.
3. "Hoje" — `Link href="/day"` — escondido no dia atual.
4. Date picker → `setPicked` → botão "Ir" → `router.push('/day' | '/day/${picked}')`.
5. Data futura em `/day/[date]`: `compareISO` server-side bloqueia antes do backend → "Não é possível ver o futuro".

## Regras de negócio

1. **`/day` é dia atual**; `/day/[date]` é dia passado (PR #46 permite encerrar retroativo em dia aberto).
2. **Read-only por design**: sem botões de editar/excluir item na página; exceção: `ConfirmItemButton` (não-mutação do valor, só desmarca flag) e `CloseDayButton` (fecha dia).
3. **`EmptyState`** distingue `closed` ("Este dia foi encerrado sem registros.") de `open` ("Ainda não há nada registrado hoje. Comece pelo chat.").
4. **Order dentro do slot**: ordena `occurred_at` ASC — mesma refeição pode ter vários registros.
5. **`TotalsCard`** mostra `Cal. out`/`Saldo` só se `kcal_out>0`; `Outros líq.` só se `other_liquids_ml>0`.
6. **Micros só quando algnhum >0**: `showMicros` flag; caso contrário exibe "Sem micronutrientes registrados."
7. **Confiança LLM só** quando `source==='llm'`.
8. **Futuro bloqueado client/server** sem chamar backend (UX + economia de request).
9. **Path traversal rejeitado**: `^\d{4}-\d{2}-\d{2}$` antes do fetch em `/day/[date]`.
10. **Aviso legal obrigatório** (`Disclaimer`) em todas as renderizações (Art. VII §26).

## Configurações e variáveis de ambiente

| Variável | Descrição | Padrão | Obrigatória |
|---|---|---|---|
| `INTERNAL_API_URL` | URL interna para server components chamar o backend (DNS interno do compose) | — | Sim (server) |
| `TZ` | Timezone do container (docker-compose) — usado por `todayLocalISO()` server-side como fallback | — | Sim (infra) |

Sem variáveis específicas da feature.

## Referências de implementação

- **Entrypoints**: `apps/web/src/app/(app)/day/page.tsx` (44 linhas), `apps/web/src/app/(app)/day/[date]/page.tsx`.
- **Render compartilhado**: `apps/web/src/app/(app)/day/DayView.tsx` (175 linhas) — `groupBySlot`, `TotalsCard`, `NarrativeCard`, `EmptyState`, `Disclaimer`.
- **Refeições**: `MealSection.tsx` (57), `FoodItemRow.tsx` (71) — `<details>` expansível; `ConfirmItemButton.tsx` (48).
- **Seções auxiliares**: `AuxiliarySections.tsx` (142) — `HydrationSection`/`BeverageSection`/`ActivitySection`.
- **Navegação temporal**: `DayNavigator.tsx` (88) — SP-155.
- **Refresh staleness**: `RefreshOnFocus.tsx` (48).
- **Close refletido**: `CloseDayButton.tsx` (35) — reusa `CloseDayModal` do chat.
- **Formatadores**: `format.ts` (133) — pt-BR + aritmética de datas.
- **Contratos/state**: `types.ts` (145) — `DaySnapshot` + dicionários pt-BR.
- **Backend shape**: `apps/api/app/services/day_query.py::_load_food` (micros + metadata).
- **Layout/proxy**: `apps/web/src/app/(app)/layout.tsx:47` (link "Hoje"), `apps/web/src/proxy.ts:8` (`/day` em `PROTECTED_PREFIXES`).
- **Weekly link**: `apps/web/src/app/(app)/weekly/WeeklyReportView.tsx:226` — coluna "Dia" vira `<Link href={`/day/${row.date}`}>`.
- **Tests**: [Implementação não localizada] — `apps/web` sem Vitest/Playwright; `apps/api/tests/test_day_close_report.py` cobre backend parcialmente.