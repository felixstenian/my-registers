// SP-153 — Seções auxiliares: hidratação, bebidas, atividade.
// Todos server components. Cada seção some do render se não houver
// registros correspondentes.

import { fmtGrams, fmtInt, fmtKcal, fmtMl, fmtTime } from './format';
import { EditActivityForm, EditBeverageForm, EditWaterForm } from './edit-forms';
import {
  ACTIVITY_TYPE_LABEL_PT,
  CALC_METHOD_LABEL_PT,
  type ActivityRecord,
  type BeverageRecord,
  type WaterRecord,
} from './types';

export function HydrationSection({
  records,
  dayClosed = false,
}: {
  records: WaterRecord[];
  dayClosed?: boolean;
}) {
  if (records.length === 0) return null;
  const total = records.reduce((acc, r) => acc + r.volume_ml, 0);

  return (
    <section className="rounded border border-slate-200 dark:border-slate-800">
      <header className="flex items-baseline justify-between border-b border-slate-200 bg-slate-50 px-3 py-2 text-sm dark:border-slate-800 dark:bg-slate-900/50">
        <span className="font-semibold">Hidratação</span>
        <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
          Água: {fmtInt(total)} ml
        </span>
      </header>
      <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
        {records.map((r) => (
          <li key={r.id}>
            <details className="group">
              <summary className="flex cursor-pointer items-baseline justify-between px-3 py-2 text-slate-700 hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-900/50">
                <span className="text-xs text-slate-500 dark:text-slate-400">
                  {fmtTime(r.occurred_at)}
                </span>
                <span>{fmtMl(r.volume_ml)}</span>
              </summary>
              <div className="bg-slate-50 px-3 py-2 dark:bg-slate-900/40">
                <EditWaterForm record={r} dayClosed={dayClosed} />
              </div>
            </details>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function BeverageSection({
  records,
  dayClosed = false,
}: {
  records: BeverageRecord[];
  dayClosed?: boolean;
}) {
  if (records.length === 0) return null;
  const kcalSum = records.reduce((acc, r) => acc + (r.kcal ?? 0), 0);
  const mlSum = records.reduce((acc, r) => acc + r.volume_ml, 0);

  return (
    <section className="rounded border border-slate-200 dark:border-slate-800">
      <header className="flex items-baseline justify-between border-b border-slate-200 bg-slate-50 px-3 py-2 text-sm dark:border-slate-800 dark:bg-slate-900/50">
        <span className="font-semibold">Bebidas</span>
        <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
          {fmtInt(mlSum)} ml · {fmtKcal(kcalSum)}
        </span>
      </header>

      <div className="grid grid-cols-12 gap-2 border-b border-slate-100 px-3 py-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-500 dark:border-slate-800 dark:text-slate-400">
        <span className="col-span-5">Item</span>
        <span className="col-span-2 text-right">Volume</span>
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
      </div>

      <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
        {records.map((r) => (
          <li key={r.id}>
            <details className="group">
              <summary className="grid cursor-pointer grid-cols-12 gap-2 px-3 py-2 hover:bg-slate-50 dark:hover:bg-slate-900/50">
                <span className="col-span-5 truncate">
                  {r.detected_name || 'bebida'}
                </span>
                <span className="col-span-2 text-right text-slate-600 dark:text-slate-400">
                  {fmtMl(r.volume_ml)}
                </span>
                <span className="col-span-2 text-right font-medium">{fmtKcal(r.kcal)}</span>
                <span className="col-span-1 text-right">{fmtGrams(r.protein_g)}</span>
                <span className="col-span-1 text-right">{fmtGrams(r.carbs_g)}</span>
                <span className="col-span-1 text-right">{fmtGrams(r.fat_g)}</span>
              </summary>
              <div className="bg-slate-50 px-3 py-2 dark:bg-slate-900/40">
                <EditBeverageForm record={r} dayClosed={dayClosed} />
              </div>
            </details>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function ActivitySection({
  records,
  dayClosed = false,
}: {
  records: ActivityRecord[];
  dayClosed?: boolean;
}) {
  if (records.length === 0) return null;
  const kcalSum = records.reduce((acc, r) => acc + (r.kcal_burned ?? 0), 0);

  return (
    <section className="rounded border border-slate-200 dark:border-slate-800">
      <header className="flex items-baseline justify-between border-b border-slate-200 bg-slate-50 px-3 py-2 text-sm dark:border-slate-800 dark:bg-slate-900/50">
        <span className="font-semibold">Atividade</span>
        <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
          Calorias gastas: {fmtKcal(kcalSum)}
        </span>
      </header>

      <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
        {records.map((r) => {
          const kind = ACTIVITY_TYPE_LABEL_PT[r.activity_type] ?? r.activity_type;
          const method = CALC_METHOD_LABEL_PT[r.calc_method] ?? r.calc_method;
          return (
            <li key={r.id}>
              <details className="group">
                <summary className="grid cursor-pointer grid-cols-12 gap-2 px-3 py-2 hover:bg-slate-50 dark:hover:bg-slate-900/50">
                  <span className="col-span-4 truncate">
                    <span className="font-medium">{r.detected_name || kind}</span>
                    {r.detected_name && r.detected_name !== kind && (
                      <span className="ml-1 text-xs text-slate-500 dark:text-slate-400">
                        ({kind})
                      </span>
                    )}
                  </span>
                  <span className="col-span-2 text-right text-slate-600 dark:text-slate-400">
                    {r.duration_minutes ? `${fmtInt(r.duration_minutes)} min` : '—'}
                  </span>
                  <span className="col-span-2 text-right text-slate-600 dark:text-slate-400">
                    {r.intensity ?? '—'}
                  </span>
                  <span className="col-span-2 text-right font-medium">
                    {fmtKcal(r.kcal_burned)}
                  </span>
                  <span className="col-span-2 text-right text-[11px] italic text-slate-500 dark:text-slate-400">
                    {method}
                  </span>
                </summary>
                <EditActivityForm record={r} dayClosed={dayClosed} />
              </details>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
