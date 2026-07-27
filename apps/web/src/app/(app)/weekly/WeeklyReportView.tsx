'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api-client';

type Totals = {
  kcal_in: number;
  kcal_out: number;
  kcal_balance: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number;
  water_ml: number;
  other_liquids_ml: number;
};

type DayRow = Totals & {
  date: string;
  closed_at: string | null;
  version: number;
};

type WeeklyResponse = {
  id: string;
  window_start: string | null;
  window_end: string | null;
  days_included: number;
  totals: Totals;
  averages: Totals;
  per_day: DayRow[];
  warnings: Array<{ code?: string; days_available?: number; [key: string]: unknown }>;
  narrative: string | null;
  generated_at: string;
  version: number;
};

const nfInt = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 });
const nfDateShort = new Intl.DateTimeFormat('pt-BR', {
  day: '2-digit',
  month: '2-digit',
});
const nfWeekday = new Intl.DateTimeFormat('pt-BR', { weekday: 'short' });

function fmtInt(n: number): string {
  return nfInt.format(n);
}

function fmtDateShort(iso: string): string {
  const [y, m, d] = iso.split('-').map((s) => parseInt(s, 10));
  const dt = new Date(y, m - 1, d);
  return nfDateShort.format(dt);
}

function fmtWeekday(iso: string): string {
  const [y, m, d] = iso.split('-').map((s) => parseInt(s, 10));
  const dt = new Date(y, m - 1, d);
  return nfWeekday.format(dt).replace('.', '');
}

export function WeeklyReportView() {
  const [state, setState] = useState<
    | { phase: 'loading' }
    | { phase: 'ready'; data: WeeklyResponse }
    | { phase: 'error'; message: string }
  >({ phase: 'loading' });

  useEffect(() => {
    (async () => {
      const result = await api<WeeklyResponse>('/weekly');
      if (result.ok) {
        setState({ phase: 'ready', data: result.data });
      } else {
        setState({
          phase: 'error',
          message: result.error?.message ?? 'Não foi possível carregar o relatório.',
        });
      }
    })();
  }, []);

  if (state.phase === 'loading') {
    return (
      <div className="rounded border border-slate-200 px-4 py-6 text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">
        Carregando relatório semanal…
      </div>
    );
  }

  if (state.phase === 'error') {
    return (
      <div className="rounded border border-red-200 bg-red-50 px-4 py-6 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
        {state.message}
      </div>
    );
  }

  const data = state.data;
  const insufficient = data.warnings.some((w) => w.code === 'insufficient_history');

  if (data.days_included === 0) {
    return (
      <div className="rounded border border-dashed border-slate-300 px-4 py-6 text-sm text-slate-600 dark:border-slate-700 dark:text-slate-400">
        <p>
          Ainda não há dias encerrados. Encerre pelo menos um dia no chat para
          o relatório semanal começar a valer.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <WindowSummary data={data} />
      {insufficient && (
        <InsufficientHistoryBanner
          daysAvailable={
            data.warnings.find((w) => w.code === 'insufficient_history')?.days_available ??
            data.days_included
          }
        />
      )}
      <TotalsGrid label="Totais da semana" totals={data.totals} />
      <TotalsGrid label="Médias diárias" totals={data.averages} />
      <PerDayTable rows={data.per_day} />
      {data.narrative && <Narrative text={data.narrative} />}
      <Disclaimer />
    </div>
  );
}

function WindowSummary({ data }: { data: WeeklyResponse }) {
  const start = data.window_start;
  const end = data.window_end;
  if (!start || !end) {
    return (
      <p className="text-xs text-slate-500 dark:text-slate-400">
        {data.days_included} dia(s) encerrado(s) considerados.
      </p>
    );
  }
  return (
    <p className="text-xs text-slate-500 dark:text-slate-400">
      Janela: <strong>{fmtDateShort(start)}</strong> a <strong>{fmtDateShort(end)}</strong>{' '}
      · {data.days_included} dia(s) encerrado(s)
    </p>
  );
}

function InsufficientHistoryBanner({ daysAvailable }: { daysAvailable: number }) {
  return (
    <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
      Ainda não há 7 dias fechados. Mostrando os {daysAvailable} disponíveis. O
      relatório fica mais confiável quando a semana inteira estiver preenchida.
    </div>
  );
}

function TotalsGrid({ label, totals }: { label: string; totals: Totals }) {
  return (
    <section>
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {label}
      </h2>
      <div className="grid grid-cols-2 gap-2 rounded border border-slate-200 bg-slate-50 p-3 text-sm dark:border-slate-800 dark:bg-slate-900/50 sm:grid-cols-3">
        <Stat label="Cal. in" value={`${fmtInt(totals.kcal_in)} kcal`} />
        {totals.kcal_out > 0 && (
          <Stat label="Cal. out" value={`${fmtInt(totals.kcal_out)} kcal`} />
        )}
        {totals.kcal_out > 0 && (
          <Stat
            label="Saldo"
            value={`${totals.kcal_balance >= 0 ? '+' : ''}${fmtInt(totals.kcal_balance)} kcal`}
          />
        )}
        <Stat label="Proteína" value={`${fmtInt(totals.protein_g)} g`} />
        <Stat label="Carbo." value={`${fmtInt(totals.carbs_g)} g`} />
        <Stat label="Gordura" value={`${fmtInt(totals.fat_g)} g`} />
        <Stat label="Fibra" value={`${fmtInt(totals.fiber_g)} g`} />
        <Stat label="Água" value={`${fmtInt(totals.water_ml)} ml`} />
        {totals.other_liquids_ml > 0 && (
          <Stat label="Outros líq." value={`${fmtInt(totals.other_liquids_ml)} ml`} />
        )}
      </div>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between">
      <span className="text-slate-500 dark:text-slate-400">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

function PerDayTable({ rows }: { rows: DayRow[] }) {
  // SP-113: rows já vêm do backend em ordem cronológica ascendente.
  return (
    <section>
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        Detalhe por dia
      </h2>
      <div className="overflow-x-auto rounded border border-slate-200 dark:border-slate-800">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-900/50 dark:text-slate-400">
            <tr>
              <th className="px-3 py-2 text-left">Dia</th>
              <th className="px-3 py-2 text-right">Cal. in</th>
              <th className="px-3 py-2 text-right">Cal. out</th>
              <th className="px-3 py-2 text-right">Saldo</th>
              <th className="px-3 py-2 text-right">P</th>
              <th className="px-3 py-2 text-right">C</th>
              <th className="px-3 py-2 text-right">G</th>
              <th className="px-3 py-2 text-right">Água</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.date} className="border-t border-slate-100 dark:border-slate-800">
                <td className="px-3 py-2">
                  <div className="text-slate-500 dark:text-slate-400">
                    {fmtWeekday(row.date)}
                  </div>
                  <div className="font-medium">{fmtDateShort(row.date)}</div>
                </td>
                <td className="px-3 py-2 text-right">{fmtInt(row.kcal_in)}</td>
                <td className="px-3 py-2 text-right">
                  {row.kcal_out > 0 ? fmtInt(row.kcal_out) : '—'}
                </td>
                <td className="px-3 py-2 text-right">
                  {row.kcal_out > 0
                    ? `${row.kcal_balance >= 0 ? '+' : ''}${fmtInt(row.kcal_balance)}`
                    : '—'}
                </td>
                <td className="px-3 py-2 text-right">{fmtInt(row.protein_g)}g</td>
                <td className="px-3 py-2 text-right">{fmtInt(row.carbs_g)}g</td>
                <td className="px-3 py-2 text-right">{fmtInt(row.fat_g)}g</td>
                <td className="px-3 py-2 text-right">{fmtInt(row.water_ml)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Narrative({ text }: { text: string }) {
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

function Disclaimer() {
  // Const. Art. VII §26: aviso legal obrigatório em qualquer visualização
  // pública de dados agregados de alimentação/nutrição.
  return (
    <p className="border-t border-slate-100 pt-4 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
      As estimativas nutricionais desta ferramenta são aproximações e não substituem
      acompanhamento médico ou nutricional.
    </p>
  );
}
