// SP-151 — Refeições agrupadas por meal_slot.
// Server component. Ordena por occurred_at dentro do slot; renderiza uma
// tabela grid-based com FoodItemRow por item.

import { FoodItemRow } from './FoodItemRow';
import { fmtKcal, fmtTime } from './format';
import { MEAL_SLOT_LABEL_PT, type FoodRecord, type MealSlot } from './types';

export function MealSection({ slot, records }: { slot: MealSlot; records: FoodRecord[] }) {
  if (records.length === 0) return null;

  const kcalSum = records.reduce(
    (acc, rec) => acc + rec.items.reduce((s, i) => s + (i.kcal ?? 0), 0),
    0,
  );
  const label = MEAL_SLOT_LABEL_PT[slot];
  const firstTime = fmtTime(records[0].occurred_at);

  return (
    <section className="rounded border border-slate-200 dark:border-slate-800">
      <header className="flex items-baseline justify-between border-b border-slate-200 bg-slate-50 px-3 py-2 text-sm dark:border-slate-800 dark:bg-slate-900/50">
        <div>
          <span className="font-semibold">{label}</span>
          {firstTime && (
            <span className="ml-2 text-xs text-slate-500 dark:text-slate-400">
              {firstTime}
            </span>
          )}
        </div>
        <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
          {fmtKcal(kcalSum)}
        </span>
      </header>

      {/* Cabeçalho da tabela — mesmo grid do FoodItemRow.summary. */}
      <div className="grid grid-cols-12 gap-2 border-b border-slate-100 px-3 py-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-500 dark:border-slate-800 dark:text-slate-400">
        <span className="col-span-4">Item</span>
        <span className="col-span-2 text-right">Quantidade</span>
        <span className="col-span-2 text-right">Calorias</span>
        <span className="col-span-1 text-right" title="Proteína">
          P
        </span>
        <span className="col-span-1 text-right" title="Carboidratos">
          C
        </span>
        <span className="col-span-1 text-right" title="Gordura">
          G
        </span>
        <span className="col-span-1 text-right" title="Fibras">
          Fib
        </span>
      </div>

      {records.flatMap((rec) => rec.items.map((item) => <FoodItemRow key={item.id} item={item} />))}
    </section>
  );
}
