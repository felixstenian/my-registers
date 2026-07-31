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

import { useCallback, useEffect, useRef, useState } from 'react';
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
  onCloseDayClick,
}: {
  revalidateKey: number;
  onPendingClick: (items: FoodItemRef[]) => void;
  onCloseDayClick: (date: string) => void;
}) {
  const [day, setDay] = useState<DayResponse | null>(null);
  const dayRef = useRef<DayResponse | null>(null);
  const [loading, setLoading] = useState(true);
  // FE-01: antes, falha na 1ª carga (rede fora) deixava a barra em "Carregando
  // totais do dia…" para sempre (loading→false, day=null cairia no estado
  // "vazio" enganoso). Agora exibimos erro discreto com retry; revalidações
  // que falham mantêm os dados velhos (salvo quando ainda não há dados).
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const result = await api<DayResponse>('/days/today');
    if (result.ok) {
      dayRef.current = result.data;
      setDay(result.data);
      setErrorMsg(null);
    } else if (dayRef.current === null) {
      // Só exibe erro quando não há dados antigos a mostrar; com dados
      // velhos disponíveis, mantemos o último snapshot válido.
      setErrorMsg(result.error?.message ?? 'Falha ao carregar totais do dia.');
    }
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

  if (errorMsg && day === null) {
    return (
      <div className="mb-2 flex items-center justify-between gap-2 rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
        <span>{errorMsg}</span>
        <button
          type="button"
          onClick={() => void load()}
          className="shrink-0 rounded bg-red-800 px-2.5 py-1 font-medium text-white transition hover:bg-red-900 dark:bg-red-900 dark:hover:bg-red-800"
        >
          Tentar novamente
        </button>
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
  const isClosed = day!.status === 'closed';

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
          className="shrink-0 rounded-full bg-amber-100 px-2.5 py-1 font-medium text-amber-800 hover:bg-amber-200 dark:bg-amber-900/40 dark:text-amber-300 dark:hover:bg-amber-900/60"
        >
          {pending.length} {pending.length === 1 ? 'item precisa' : 'itens precisam'} de confirmação
        </button>
      )}
      {/* T-704: botão de encerramento. Só aparece quando ainda está aberto
          e existe pelo menos um registro (INV-5: nada útil em fechar um
          dia vazio). Empurrado pra direita com ml-auto. */}
      {!isClosed && (
        <button
          type="button"
          onClick={() => onCloseDayClick(day!.date)}
          className="ml-auto shrink-0 rounded-full border border-slate-300 px-2.5 py-1 font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          Encerrar dia
        </button>
      )}
      {isClosed && (
        <span className="ml-auto shrink-0 rounded-full bg-emerald-100 px-2.5 py-1 font-medium text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300">
          Dia encerrado
        </span>
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
