'use client';

/**
 * T-B542 — botão de descarte do card recovery.
 *
 * Chama `DELETE /records/food-items/{id}` (SP-81, idempotente, faz o
 * recompute do dia por trás). Pede confirmação nativa antes; on OK,
 * dispara `onDiscarded()` — o pai (`AssistantContent`) adiciona o id
 * ao Set `discardedIds` e some com o item da UI.
 *
 * Não damos reload: o item legado tinha kcal=0, então os totais do
 * DayTotalsBar já refletem a realidade — a divergência é só o item
 * ainda aparecer no /day até a próxima navegação.
 */

import { api } from '@/lib/api-client';
import { useState } from 'react';

type Props = {
  itemId: string;
  itemName: string;
  onDiscarded: () => void;
};

export function DiscardItemButton({ itemId, itemName, onDiscarded }: Props) {
  const [state, setState] = useState<'idle' | 'deleting'>('idle');
  const [error, setError] = useState<string | null>(null);

  async function onClick() {
    if (state === 'deleting') return;
    // TODO: Adicionar modal de confirmação customizado, com explicação do que acontece ao descartar.
    const label = itemName || 'este item';
    if (!window.confirm(`Descartar "${label}" do registro?`)) return;
    setState('deleting');
    setError(null);
    const result = await api(`/records/food-items/${itemId}`, { method: 'DELETE' });
    if (!result.ok) {
      setState('idle');
      setError(result.error?.message ?? 'Falha ao descartar.');
      return;
    }
    onDiscarded();
  }

  return (
    <div className="inline-flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={onClick}
        disabled={state === 'deleting'}
        className="rounded border border-slate-400 bg-white px-2 py-1 text-xs font-medium text-slate-600 transition hover:bg-slate-100 disabled:opacity-60 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
      >
        {state === 'deleting' ? 'Descartando…' : '🗑 Descartar'}
      </button>
      {error && (
        <span role="alert" className="text-[11px] text-red-600 dark:text-red-400">
          {error}
        </span>
      )}
    </div>
  );
}
