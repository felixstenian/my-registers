import type { Metadata } from 'next';
import { WeeklyReportView } from './WeeklyReportView';

export const metadata: Metadata = {
  title: 'Semana · my-registers',
};

/**
 * T-804 / SP-110..SP-113 — Relatório semanal.
 *
 * Página fina: só monta o server layout. O fetch e o rendering acontecem
 * no client component `WeeklyReportView` — evita SSR do relatório porque
 * a resposta pode variar por sessão (dias fechados podem ter mudado
 * entre uma navegação e outra) e queremos sempre a versão fresca.
 */
export default function WeeklyPage() {
  return (
    <main className="mx-auto max-w-3xl p-4 pb-[calc(env(safe-area-inset-bottom)+3.5rem)] md:pb-4">
      <h1 className="mb-2 text-lg font-semibold">Relatório semanal</h1>
      <p className="mb-4 text-xs text-slate-500 dark:text-slate-400">
        Últimos 7 dias com encerramento (SP-110). Dias abertos ficam de fora.
      </p>
      <WeeklyReportView />
    </main>
  );
}
