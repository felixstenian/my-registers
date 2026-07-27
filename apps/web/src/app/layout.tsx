import type { Metadata, Viewport } from 'next';
import './globals.css';
import { SwUpdatePrompt } from './sw-update-prompt';

export const metadata: Metadata = {
  title: 'my-registers',
  description: 'Registro diário de alimentação, hidratação e atividade por chat',
  applicationName: 'my-registers',
  appleWebApp: {
    capable: true,
    title: 'my-registers',
    statusBarStyle: 'default',
  },
  formatDetection: { telephone: false },
  icons: {
    icon: [
      { url: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
      { url: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
    ],
    apple: [{ url: '/icons/apple-touch-icon.png', sizes: '180x180', type: 'image/png' }],
  },
};

export const viewport: Viewport = {
  themeColor: '#0f172a',
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body className="min-h-screen bg-white text-slate-900 antialiased dark:bg-slate-950 dark:text-slate-100">
        {children}
        <SwUpdatePrompt />
      </body>
    </html>
  );
}
