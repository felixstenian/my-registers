'use client';

// Salvaguarda: quando o usuário volta pra aba do /day depois de
// ter mutado algo em outro lugar (ex.: confirmou item pelo chat,
// mandou novo registro pelo chat, etc.), o Next.js Router Cache
// pode servir a versão anterior do server component. Este componente
// dispara router.refresh() no `visibilitychange` → 'visible'.
//
// Debounce simples via ref: só refaz refresh se o último foi >2s
// atrás. Evita spam se o usuário fica alternando abas rapidinho.

import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

const MIN_INTERVAL_MS = 2000;

export function RefreshOnFocus() {
  const router = useRouter();

  useEffect(() => {
    let last = Date.now();
    const onVisibility = () => {
      if (document.visibilityState !== 'visible') return;
      const now = Date.now();
      if (now - last < MIN_INTERVAL_MS) return;
      last = now;
      router.refresh();
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, [router]);

  return null;
}
