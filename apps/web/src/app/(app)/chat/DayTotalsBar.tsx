'use client';

/**
 * SP-116 — barra fixa com os totais do dia.
 *
 * Fetches `GET /days/today` no primeiro render e revalida sempre que a
 * página do chat detecta uma nova assistant message (via `revalidateKey`).
 * Colapsa em uma linha rolável horizontalmente em telas pequenas.
 *
 * Warnings de `needs_confirmation` na lista de food_items geram um badge
 * clicável que abre o `PendingItemsModal`.
 */

import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api-client';

export type FoodItemRef = {
  id: string;
  detected_name: string;
  grams?: number | null;
  ml?: number | null;
  quantity?: number | null;
  unit?: string | null;
  kcal?: number | null;
  needs_confirmation?: boolean | null;
};

type DayResponse = {
  date: string;
  status: 'open' | 'closed';
  totals: {
    kcal_in: number;
    kcal_out: number;
    protein_g: number;
    carbs_g: number;
    fat_g: number;
    fiber_g: number;
    water_ml: number;
    other_liquids_ml: number;
  };
  records: {
    food: Array<{ id: string; items: FoodItemRef[] }>;
    water: unknown[];
    beverage: unknown[];
    activity: unknown[];
  };
};

const nfInt = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 });

function fmtInt(n: number): string {
  return nfInt.format(n);
}

function collectPendingItems(day: DayResponse | null): FoodItemRef[] {
  if (!day) return [];
  const items: FoodItemRef[] = [];
  for (const record of day.records.food) {
    for (const item of record.items) {
      if (item.needs_confirmation) items.push(item);
    }
  }
  return items;
}

export function DayTotalsBar({
  revalidateKey,
  onPendingClick,
}: {
  revalidateKey: number;
  onPendingClick: (items: FoodItemRef[]) => void;
}) {
  const [day, setDay] = useState<DayResponse | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const result = await api<DayResponse>('/days/today');
    if (result.ok) setDay(result.data);
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load, revalidateKey]);

  const pending = collectPendingItems(day);

  if (loading && day === null) {
    return (
      <div className="mb-2 rounded border border-slate-200 px-3 py-2 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
        Carregando totais do dia…
      </div>
    );
  }

  const totals = day?.totals;
  const empty =
    !totals ||
    (totals.kcal_in === 0 &&
      totals.kcal_out === 0 &&
      totals.water_ml === 0 &&
      totals.other_liquids_ml === 0);

  if (empty) {
    return (
      <div className="mb-2 rounded border border-dashed border-slate-300 px-3 py-2 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
        Nenhum registro hoje — mande sua primeira mensagem.
      </div>
    );
  }

  const kcalOut = totals!.kcal_out;
  const balance = totals!.kcal_in - kcalOut;
  const otherLiquids = totals!.other_liquids_ml;

  return (
    <div className="mb-2 flex items-center gap-4 overflow-x-auto rounded border border-slate-200 bg-slate-50 px-3 py-2 text-xs dark:border-slate-800 dark:bg-slate-900/50">
      <Stat label="Cal. in" value={`${fmtInt(totals!.kcal_in)} kcal`} accent />
      {kcalOut > 0 && (
        <>
          <Stat label="Cal. out" value={`${fmtInt(kcalOut)} kcal`} />
          <Stat
            label="Saldo"
            value={`${balance >= 0 ? '+' : ''}${fmtInt(balance)} kcal`}
          />
        </>
      )}
      <Stat label="P" value={`${fmtInt(totals!.protein_g)}g`} />
      <Stat label="C" value={`${fmtInt(totals!.carbs_g)}g`} />
      <Stat label="G" value={`${fmtInt(totals!.fat_g)}g`} />
      <Stat label="Fib" value={`${fmtInt(totals!.fiber_g)}g`} />
      <Stat label="Água" value={`${fmtInt(totals!.water_ml)} ml`} />
      {otherLiquids > 0 && (
        <Stat label="Outros líq." value={`${fmtInt(otherLiquids)} ml`} />
      )}
      {pending.length > 0 && (
        <button
          type="button"
          onClick={() => onPendingClick(pending)}
          className="ml-auto shrink-0 rounded-full bg-amber-100 px-2.5 py-1 font-medium text-amber-800 hover:bg-amber-200 dark:bg-amber-900/40 dark:text-amber-300 dark:hover:bg-amber-900/60"
        >
          {pending.length} {pending.length === 1 ? 'item precisa' : 'itens precisam'} de confirmação
        </button>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div className="flex shrink-0 items-baseline gap-1">
      <span className="text-slate-500 dark:text-slate-400">{label}:</span>
      <span className={accent ? 'text-sm font-semibold' : 'font-medium'}>{value}</span>
    </div>
  );
}
