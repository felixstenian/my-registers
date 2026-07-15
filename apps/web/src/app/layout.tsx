import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'my-registers',
  description: 'Registro diário de alimentação, hidratação e atividade por chat',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body className="min-h-screen bg-white text-slate-900 antialiased dark:bg-slate-950 dark:text-slate-100">
        {children}
      </body>
    </html>
  );
}
