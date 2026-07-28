'use client';

// SP-155 — navegação temporal no /day.
// Client component: precisa de `useRouter` + estado local do <input>.
// Cliente decide "hoje" via `todayLocalISO()` (respeita timezone do
// browser, que casa com timezone do user na maioria dos casos pessoais).

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { addDaysISO, compareISO, todayLocalISO } from './format';

export function DayNavigator({ date }: { date: string }) {
  const router = useRouter();
  const today = todayLocalISO();
  const isToday = compareISO(date, today) === 0;
  const isFuture = compareISO(date, today) > 0;

  const prevDate = addDaysISO(date, -1);
  const nextDate = addDaysISO(date, +1);
  const canGoNext = compareISO(nextDate, today) <= 0;

  const [picked, setPicked] = useState(date);

  const goToPicked = () => {
    if (!picked || picked === date) return;
    if (compareISO(picked, today) > 0) return; // sanity: futuro bloqueado
    if (compareISO(picked, today) === 0) {
      router.push('/day');
    } else {
      router.push(`/day/${picked}`);
    }
  };

  return (
    <nav
      aria-label="Navegar entre dias"
      className="flex flex-wrap items-center gap-2 text-xs"
    >
      <Link
        href={`/day/${prevDate}`}
        className="rounded border border-slate-300 px-2 py-1 text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
      >
        ← Dia anterior
      </Link>

      {!isToday && (
        <Link
          href="/day"
          className="rounded border border-slate-300 px-2 py-1 font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          Hoje
        </Link>
      )}

      {canGoNext && !isFuture && (
        <Link
          href={compareISO(nextDate, today) === 0 ? '/day' : `/day/${nextDate}`}
          className="rounded border border-slate-300 px-2 py-1 text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          Próximo dia →
        </Link>
      )}

      <span className="ml-auto flex items-center gap-1">
        <label htmlFor="day-picker" className="text-slate-500 dark:text-slate-400">
          Ir para:
        </label>
        <input
          id="day-picker"
          type="date"
          value={picked}
          max={today}
          onChange={(e) => setPicked(e.target.value)}
          className="rounded border border-slate-300 bg-white px-1.5 py-0.5 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
        />
        <button
          type="button"
          onClick={goToPicked}
          disabled={!picked || picked === date}
          className="rounded bg-slate-900 px-2 py-0.5 text-white transition disabled:opacity-40 dark:bg-slate-100 dark:text-slate-900"
        >
          Ir
        </button>
      </span>
    </nav>
  );
}
