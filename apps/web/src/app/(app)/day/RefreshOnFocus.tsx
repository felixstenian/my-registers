'use client';

// Salvaguarda pra staleness do server component:
//
//   1. **Mount** — toda navegação pra /day dispara router.refresh().
//      Cobre "usuário confirmou item pelo chat + navegou pro /day":
//      sem esse refresh o Router Cache do Next serviria a versão
//      renderizada antes da confirmação (visibilitychange NÃO dispara
//      em navegação client-side dentro do mesmo app).
//
//   2. **visibilitychange → visible** — pega o cenário do usuário
//      deixando a aba aberta, indo pro Slack/browser em outra janela,
//      confirmando algo em outro dispositivo, e voltando. Debounce de
//      2s evita spam quando o usuário alterna abas rapidinho.
//
// Trade-off: uma request extra ao server por navegação. Aceitável pra
// app single-user; se um dia virar multi-user + tráfego, revisitar.

import { useRouter } from 'next/navigation';
import { useEffect, useRef } from 'react';

const FOCUS_MIN_INTERVAL_MS = 2000;

export function RefreshOnFocus() {
  const router = useRouter();
  const lastRefreshRef = useRef(0);

  useEffect(() => {
    // Refresh no mount — a razão principal desse componente existir.
    router.refresh();
    lastRefreshRef.current = Date.now();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState !== 'visible') return;
      const now = Date.now();
      if (now - lastRefreshRef.current < FOCUS_MIN_INTERVAL_MS) return;
      lastRefreshRef.current = now;
      router.refresh();
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, [router]);

  return null;
}
