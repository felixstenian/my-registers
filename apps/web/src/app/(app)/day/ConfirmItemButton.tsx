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

  if (state === 'done') return null;

  const disabled = state === 'confirming';

  const onClick = async (e: React.MouseEvent) => {
    // Impede que o click abra/feche o <details> pai (o botão vive dentro
    // do <summary> — evento propaga por default).
    e.preventDefault();
    e.stopPropagation();

    setState('confirming');
    const result = await api(`/records/food-items/${itemId}/confirm`, {
      method: 'POST',
    });
    if (result.ok) {
      setState('done');
      router.refresh();
    } else {
      setState('idle');
    }
  };

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title="Confirmar item — remove o alerta"
      className="ml-1.5 rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800 transition hover:bg-amber-200 disabled:opacity-60 dark:bg-amber-900/40 dark:text-amber-300 dark:hover:bg-amber-900/60"
    >
      {disabled ? 'confirmando…' : 'confirmar'}
    </button>
  );
}
