'use client';

import { useEffect, useState } from 'react';

/**
 * SP-132 — Detecta service worker novo instalado e oferece reload.
 *
 * Fluxo:
 * 1. Registra o SW ao montar (se browser suporta e prod).
 * 2. Quando um SW novo entra em `installed` E já existe um controller
 *    ativo, sabemos que é update (não primeira instalação).
 * 3. Exibe toast persistente; clique manda SKIP_WAITING pro SW novo
 *    e recarrega quando o novo assume o controle.
 */
export function SwUpdatePrompt() {
  const [waitingWorker, setWaitingWorker] = useState<ServiceWorker | null>(null);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (!('serviceWorker' in navigator)) return;
    if (process.env.NODE_ENV !== 'production') return;

    let cancelled = false;

    navigator.serviceWorker
      .register('/sw.js', { scope: '/' })
      .then((registration) => {
        if (cancelled) return;

        if (registration.waiting && navigator.serviceWorker.controller) {
          setWaitingWorker(registration.waiting);
        }

        registration.addEventListener('updatefound', () => {
          const newWorker = registration.installing;
          if (!newWorker) return;
          newWorker.addEventListener('statechange', () => {
            if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
              setWaitingWorker(newWorker);
            }
          });
        });
      })
      .catch(() => {
        // Silencioso: falha de SW não deve quebrar a app.
      });

    const onControllerChange = () => {
      window.location.reload();
    };
    navigator.serviceWorker.addEventListener('controllerchange', onControllerChange);

    return () => {
      cancelled = true;
      navigator.serviceWorker.removeEventListener('controllerchange', onControllerChange);
    };
  }, []);

  if (!waitingWorker) return null;

  const onReload = () => {
    waitingWorker.postMessage({ type: 'SKIP_WAITING' });
  };

  return (
    <div
      role="alert"
      className="fixed bottom-4 left-1/2 z-50 flex -translate-x-1/2 items-center gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm shadow-lg dark:border-slate-700 dark:bg-slate-900"
    >
      <span>Nova versão disponível.</span>
      <button
        type="button"
        onClick={onReload}
        className="rounded bg-slate-900 px-3 py-1 text-xs font-medium text-white dark:bg-slate-100 dark:text-slate-900"
      >
        Recarregar
      </button>
    </div>
  );
}
