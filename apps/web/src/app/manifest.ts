import type { MetadataRoute } from 'next';

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'my-registers',
    short_name: 'my-reg',
    description:
      'Diário nutricional pessoal via chat com estimativas conservadoras. Registros de alimentos, hidratação e atividade.',
    start_url: '/chat',
    scope: '/',
    display: 'standalone',
    orientation: 'portrait',
    background_color: '#0f172a',
    theme_color: '#0f172a',
    lang: 'pt-BR',
    dir: 'ltr',
    icons: [
      { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
      { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
      { src: '/icons/icon-512-maskable.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
    ],
  };
}
