// Renderização compartilhada entre /day (dia atual) e /day/[date]
// (dia passado). Recebe o DaySnapshot já buscado; o page decide se
// mostra o botão Encerrar dia (só quando é dia atual + status=open).

import { ActivitySection, BeverageSection, HydrationSection } from './AuxiliarySections';
import { CloseDayButton } from './CloseDayButton';
import { DailyAddForm } from './DailyAddForm';
import { DayNavigator } from './DayNavigator';
import { fmtDateFull, fmtInt, fmtKcal } from './format';
import { MealSection } from './MealSection';
import { RefreshOnFocus } from './RefreshOnFocus';
import {
  MEAL_SLOT_LABEL_PT,
  MEAL_SLOT_ORDER,
  type DaySnapshot,
  type FoodRecord,
  type MealSlot,
} from './types';

export function DayView({
  data,
  allowClose,
}: {
  data: DaySnapshot;
  allowClose: boolean;
}) {
  const foodBySlot = groupBySlot(data.records.food);
  const isEmpty =
    data.records.food.length === 0 &&
    data.records.water.length === 0 &&
    data.records.beverage.length === 0 &&
    data.records.activity.length === 0;

  const dayClosed = data.status === 'closed';

  return (
    <main className="mx-auto max-w-4xl space-y-4 p-4 pb-[calc(env(safe-area-inset-bottom)+3.5rem)] md:pb-4">
      <RefreshOnFocus />
      <header className="space-y-3 border-b border-slate-200 pb-3 dark:border-slate-800">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold capitalize">{fmtDateFull(data.date)}</h1>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              {data.status === 'closed' ? (
                <span className="rounded-full bg-emerald-100 px-2 py-0.5 font-medium text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300">
                  Dia encerrado
                </span>
              ) : (
                <span className="rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                  Em aberto
                </span>
              )}
            </p>
          </div>
          {allowClose && data.status === 'open' && !isEmpty && (
            <CloseDayButton date={data.date} />
          )}
        </div>
        <DayNavigator date={data.date} />
      </header>

      {!dayClosed && <DailyAddForm date={data.date} />}

      {isEmpty ? (
        <EmptyState status={data.status} />
      ) : (
        <>
          <TotalsCard data={data} />

          {MEAL_SLOT_ORDER.map((slot) => (
            <MealSection
              key={slot}
              slot={slot}
              records={foodBySlot[slot] ?? []}
              dayClosed={dayClosed}
            />
          ))}

          <HydrationSection records={data.records.water} dayClosed={dayClosed} />
          <BeverageSection records={data.records.beverage} dayClosed={dayClosed} />
          <ActivitySection records={data.records.activity} dayClosed={dayClosed} />

          {data.narrative && <NarrativeCard text={data.narrative} />}
        </>
      )}

      <Disclaimer />
    </main>
  );
}

function groupBySlot(records: FoodRecord[]): Record<MealSlot, FoodRecord[]> {
  const out: Record<MealSlot, FoodRecord[]> = {
    breakfast: [],
    lunch: [],
    snack: [],
    dinner: [],
    unspecified: [],
  };
  for (const r of records) {
    const key: MealSlot = MEAL_SLOT_LABEL_PT[r.meal_slot] ? r.meal_slot : 'unspecified';
    out[key].push(r);
  }
  // Ordena por occurred_at dentro do slot (mesma refeição pode ter
  // vários registros — ex.: usuário adicionou item depois).
  for (const key of Object.keys(out) as MealSlot[]) {
    out[key].sort((a, b) => a.occurred_at.localeCompare(b.occurred_at));
  }
  return out;
}

function TotalsCard({ data }: { data: DaySnapshot }) {
  const t = data.totals;
  return (
    <section className="rounded border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-900/50">
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        Total do dia
      </h2>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
        <Stat label="Cal. in" value={fmtKcal(t.kcal_in)} accent />
        {t.kcal_out > 0 && <Stat label="Cal. out" value={fmtKcal(t.kcal_out)} />}
        {t.kcal_out > 0 && (
          <Stat
            label="Saldo"
            value={`${t.kcal_balance >= 0 ? '+' : ''}${fmtInt(t.kcal_balance)} kcal`}
          />
        )}
        <Stat label="Proteína" value={`${fmtInt(t.protein_g)} g`} />
        <Stat label="Carbo." value={`${fmtInt(t.carbs_g)} g`} />
        <Stat label="Gordura" value={`${fmtInt(t.fat_g)} g`} />
        <Stat label="Fibras" value={`${fmtInt(t.fiber_g)} g`} />
        <Stat label="Água" value={`${fmtInt(t.water_ml)} ml`} />
        {t.other_liquids_ml > 0 && (
          <Stat label="Outros líq." value={`${fmtInt(t.other_liquids_ml)} ml`} />
        )}
      </div>
    </section>
  );
}

function Stat({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="flex items-baseline justify-between">
      <span className="text-slate-500 dark:text-slate-400">{label}</span>
      <span className={accent ? 'font-semibold' : 'font-medium'}>{value}</span>
    </div>
  );
}

function NarrativeCard({ text }: { text: string }) {
  return (
    <section>
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        Resumo
      </h2>
      <div className="rounded border border-slate-200 bg-slate-50 p-3 text-sm dark:border-slate-800 dark:bg-slate-900/50">
        <p className="whitespace-pre-wrap text-slate-700 dark:text-slate-200">{text}</p>
      </div>
    </section>
  );
}

function EmptyState({ status }: { status: 'open' | 'closed' }) {
  return (
    <div className="rounded border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-600 dark:border-slate-700 dark:text-slate-400">
      {status === 'closed'
        ? 'Este dia foi encerrado sem registros.'
        : 'Ainda não há nada registrado hoje. Comece pelo chat.'}
    </div>
  );
}

function Disclaimer() {
  // Const. Art. VII §26 — obrigatório em visualização agregada.
  return (
    <p className="border-t border-slate-100 pt-4 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
      As estimativas nutricionais desta ferramenta são aproximações e não substituem
      acompanhamento médico ou nutricional.
    </p>
  );
}
