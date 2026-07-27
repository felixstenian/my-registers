import type { Metadata } from 'next';
import { OfflineRetryButton } from './OfflineRetryButton';

export const metadata: Metadata = {
  title: 'Sem conexão · my-registers',
};

export default function OfflinePage() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center gap-6 p-8 text-center">
      <div>
        <h1 className="text-2xl font-semibold">Sem conexão</h1>
        <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
          Algumas ações do my-registers ficam indisponíveis até você reconectar.
        </p>
      </div>

      <OfflineRetryButton />

      <footer className="mt-6 text-xs text-slate-500 dark:text-slate-400">
        As estimativas nutricionais desta ferramenta são aproximações e não substituem
        acompanhamento médico ou nutricional.
      </footer>
    </main>
  );
}
