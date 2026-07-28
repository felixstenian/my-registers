'use client';

// T-B601 — botão isolado que abre o CloseDayModal do chat.
// Extrai a mecânica de acionamento (state + click handler) do
// DayTotalsBar pra ser reusada aqui na /day sem depender do chat page.

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { CloseDayModal } from '../chat/CloseDayModal';

export function CloseDayButton({ date }: { date: string }) {
  const [open, setOpen] = useState(false);
  const router = useRouter();

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
      >
        Encerrar dia
      </button>
      {open && (
        <CloseDayModal
          date={date}
          onClose={() => setOpen(false)}
          // Após encerrar, refresh do server component pra re-renderizar
          // status='closed' + narrativa (que só aparece pós-fechamento).
          onClosed={() => router.refresh()}
        />
      )}
    </>
  );
}
