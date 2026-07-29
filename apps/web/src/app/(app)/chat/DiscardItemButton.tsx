'use client';

// Stub. Impl real vem em T-B542: chama DELETE /records/food-items/{id}
// (ou intent equivalente) e dispara onDiscarded pra hide da UI.

export function DiscardItemButton({
  itemName,
  onDiscarded,
}: {
  itemId: string;
  itemName: string;
  onDiscarded: () => void;
}) {
  return (
    <button
      type="button"
      onClick={() => {
        if (window.confirm(`Descartar "${itemName || 'este item'}"? (stub — T-B542)`)) {
          onDiscarded();
        }
      }}
      className="rounded border border-slate-400 bg-white px-2 py-1 text-xs font-medium text-slate-600 transition hover:bg-slate-100 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
    >
      🗑 Descartar
    </button>
  );
}
