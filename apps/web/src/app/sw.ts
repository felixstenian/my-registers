/// <reference lib="webworker" />
import { defaultCache } from '@serwist/next/worker';
import type { PrecacheEntry, SerwistGlobalConfig } from 'serwist';
import { Serwist, NetworkOnly, NetworkFirst, StaleWhileRevalidate } from 'serwist';

declare global {
  interface WorkerGlobalScope extends SerwistGlobalConfig {
    __SW_MANIFEST: (PrecacheEntry | string)[] | undefined;
  }
}

declare const self: ServiceWorkerGlobalScope;

const serwist = new Serwist({
  precacheEntries: self.__SW_MANIFEST,
  skipWaiting: false,
  clientsClaim: true,
  navigationPreload: true,
  runtimeCaching: [
    // SP-130 + INV-11: NUNCA cachear /api/*. Dados de negocio precisam
    // vir sempre do backend (Art. III §10 — snapshots vêm do DB).
    {
      matcher: /^https?:\/\/[^/]+\/api\//,
      handler: new NetworkOnly(),
    },
    // Navegações HTML: network-first com fallback pro shell offline.
    {
      matcher: ({ request }) => request.mode === 'navigate',
      handler: new NetworkFirst({
        cacheName: 'html-cache',
        networkTimeoutSeconds: 5,
      }),
    },
    // Assets estáticos do Next: stale-while-revalidate.
    {
      matcher: /\/_next\/static\/.*/,
      handler: new StaleWhileRevalidate({ cacheName: 'next-static-cache' }),
    },
    // Ícones e manifest: cache-first via defaults do Serwist.
    ...defaultCache,
  ],
  fallbacks: {
    entries: [
      {
        url: '/offline',
        matcher: ({ request }) => request.destination === 'document',
      },
    ],
  },
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    void self.skipWaiting();
  }
});

serwist.addEventListeners();
