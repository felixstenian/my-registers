'use client';

// Botão inline que confirma um food_item sem sair do /day.
// Substitui o badge estático "confirmar" — depois de OK, some (state
// local) e dispara router.refresh() pra re-renderizar o server component.

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { api } from '@/lib/api-client';

export function ConfirmItemButton({ itemId }: { itemId: string }) {
  const router = useRouter();
  const [state, setState] = useState<'idle' | 'confirming' | 'done'>('idle');
  // FE-01: antes, falha de rede/HTTP deixava o botão em "confirmando…"
  // indefinidamente ou voltava a `idle` sem avisar nada. Agora exibimos
  // o erro inline (role="alert") e limpamos ao tentar de novo.
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  if (state === 'done') return null;

  const disabled = state === 'confirming';

  const onClick = async (e: React.MouseEvent) => {
    // Impede que o click abra/feche o <details> pai (o botão vive dentro
    // do <summary> — evento propaga por default).
    e.preventDefault();
    e.stopPropagation();

    setErrorMsg(null);
    setState('confirming');
    const result = await api(`/records/food-items/${itemId}/confirm`, {
      method: 'POST',
    });
    if (result.ok) {
      setState('done');
      router.refresh();
    } else {
      setState('idle');
      setErrorMsg(result.error?.message ?? 'Não foi possível confirmar o item.');
    }
  };

  return (
    <span className="ml-1.5 inline-flex items-center gap-1.5">
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        title="Confirmar item — remove o alerta"
        className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800 transition hover:bg-amber-200 disabled:opacity-60 dark:bg-amber-900/40 dark:text-amber-300 dark:hover:bg-amber-900/60"
      >
        {disabled ? 'confirmando…' : 'confirmar'}
      </button>
      {errorMsg && (
        <span role="alert" className="text-[10px] text-red-600 dark:text-red-400">
          {errorMsg}
        </span>
      )}
    </span>
  );
}
