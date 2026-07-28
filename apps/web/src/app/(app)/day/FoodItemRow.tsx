// SP-152 — Detalhamento por item via expansão <details>.
// Server component intencionalmente (sem estado no client): usa o
// elemento <details> HTML nativo pra colapso/expansão. Zero JS extra.

import { ConfirmItemButton } from './ConfirmItemButton';
import { fmtAmount, fmtConfidence, fmtGrams, fmtKcal, fmtMg } from './format';
import { SOURCE_LABEL_PT, type FoodItem } from './types';

export function FoodItemRow({ item }: { item: FoodItem }) {
  const amount = fmtAmount(item.grams, item.ml, item.quantity, item.unit);
  const showMicros =
    (item.sodium_mg ?? 0) > 0 ||
    (item.calcium_mg ?? 0) > 0 ||
    (item.iron_mg ?? 0) > 0 ||
    (item.potassium_mg ?? 0) > 0;

  return (
    <details className="border-t border-slate-100 dark:border-slate-800">
      <summary className="grid cursor-pointer grid-cols-12 items-center gap-2 px-3 py-2 text-sm hover:bg-slate-50 dark:hover:bg-slate-900/50">
        <span className="col-span-4 truncate font-medium">
          {item.detected_name}
          {item.needs_confirmation && <ConfirmItemButton itemId={item.id} />}
          {!item.has_catalog && (
            <span
              className="ml-1.5 rounded-full bg-slate-200 px-1.5 py-0.5 text-[10px] font-medium text-slate-700 dark:bg-slate-700 dark:text-slate-200"
              title="Sem catálogo — macros podem estar zerados"
            >
              sem catálogo
            </span>
          )}
        </span>
        <span className="col-span-2 text-right text-slate-600 dark:text-slate-400">
          {amount}
        </span>
        <span className="col-span-2 text-right font-medium">{fmtKcal(item.kcal)}</span>
        <span className="col-span-1 text-right">{fmtGrams(item.protein_g)}</span>
        <span className="col-span-1 text-right">{fmtGrams(item.carbs_g)}</span>
        <span className="col-span-1 text-right">{fmtGrams(item.fat_g)}</span>
        <span className="col-span-1 text-right">{fmtGrams(item.fiber_g)}</span>
      </summary>

      <div className="grid grid-cols-2 gap-x-6 gap-y-1 border-t border-slate-100 bg-slate-50 px-3 py-3 text-xs dark:border-slate-800 dark:bg-slate-900/40 sm:grid-cols-3">
        {showMicros ? (
          <>
            <MicroRow label="Sódio" value={fmtMg(item.sodium_mg)} />
            <MicroRow label="Cálcio" value={fmtMg(item.calcium_mg)} />
            <MicroRow label="Ferro" value={fmtMg(item.iron_mg)} />
            <MicroRow label="Potássio" value={fmtMg(item.potassium_mg)} />
          </>
        ) : (
          <div className="col-span-full italic text-slate-500 dark:text-slate-400">
            Sem micronutrientes registrados neste item.
          </div>
        )}
        <MicroRow label="Origem" value={SOURCE_LABEL_PT[item.source] ?? item.source} />
        {item.source === 'llm' && (
          <MicroRow label="Confiança da LLM" value={fmtConfidence(item.confidence)} />
        )}
      </div>
    </details>
  );
}

function MicroRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-slate-500 dark:text-slate-400">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}
