'use client';

/**
 * SP-173 — header do chat de treino dedicado.
 *
 * Variante do `DayTotalsBar` com foco em **atividades realizadas no dia +
 * calorias gastas** (não macros de alimentação). Feed: `GET /days/today`
 * (snapshot) no primeiro render e em cada `revalidateKey`. Quando não há
 * dados do dia, não aparecem atividades nem kcal — só o item de "sem
 * registros" e o optional `onCloseDayClick`-like disabled state.
 */

import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api-client';

type ActiveRecord = {
  id: string;
  detected_name: string | null;
  activity_type: string | null;
  duration_minutes: number | null;
  intensity: string | null;
  kcal_burned: number | null;
  calc_method: string | null;
};

type DayResponse = {
  date: string;
  status: 'open' | 'closed';
  totals: {
    kcal_out: number;
  };
  records: {
    activity: ActiveRecord[];
  };
};

const nfInt = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 });

function fmtInt(n: number): string {
  return nfInt.format(n);
}

export function WorkoutTotalsHeader({ revalidateKey }: { revalidateKey: number }) {
  const [day, setDay] = useState<DayResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const result = await api<DayResponse>('/days/today');
    if (result.ok) {
      setDay(result.data);
      setErrorMsg(null);
    } else if (day === null) {
      setErrorMsg(result.error?.message ?? 'Falha ao carregar atividades do dia.');
    }
    setLoading(false);
  }, [day]);

  useEffect(() => {
    void load();
  }, [load, revalidateKey]);

  if (loading && day === null) {
    return (
      <div className="mb-2 rounded border border-slate-200 px-3 py-2 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
        Carregando atividades do dia…
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

  const activities = day?.records.activity ?? [];
  const kcalOut = day?.totals.kcal_out ?? 0;

  if (activities.length === 0 && kcalOut === 0) {
    return (
      <div className="mb-2 rounded border border-dashed border-slate-300 px-3 py-2 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
        Nenhuma atividade registrada hoje.
      </div>
    );
  }

  return (
    <div className="mb-2 flex items-center gap-4 overflow-x-auto rounded border border-slate-200 bg-slate-50 px-3 py-2 text-xs dark:border-slate-800 dark:bg-slate-900/50">
      <div className="flex shrink-0 flex-col gap-1">
        <span className="text-slate-500 dark:text-slate-400">Atividades hoje</span>
        {activities.length === 0 ? (
          <span className="font-medium">—</span>
        ) : (
          <ul className="space-y-0.5">
            {activities.map((a) => (
              <li key={a.id} className="flex items-baseline gap-1.5">
                <span className="font-medium">{a.detected_name ?? a.activity_type ?? 'Atividade'}</span>
                {a.duration_minutes !== null && (
                  <span className="text-slate-500 dark:text-slate-400">
                    {fmtInt(a.duration_minutes)} min
                  </span>
                )}
                {a.kcal_burned !== null && (
                  <span className="text-slate-600 dark:text-slate-300">
                    {fmtInt(a.kcal_burned)} kcal
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
      {kcalOut > 0 && (
        <div className="flex shrink-0 items-baseline gap-1">
          <span className="text-slate-500 dark:text-slate-400">Cal. gastas:</span>
          <span className="font-semibold">{fmtInt(kcalOut)} kcal</span>
        </div>
      )}
    </div>
  );
}