'use client';

export function OfflineRetryButton() {
  return (
    <button
      type="button"
      onClick={() => window.location.reload()}
      className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white transition dark:bg-slate-100 dark:text-slate-900"
    >
      Tentar novamente
    </button>
  );
}
