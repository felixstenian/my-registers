import { cookies } from 'next/headers';
import type { Metadata } from 'next';
import { DayView } from './DayView';
import type { DaySnapshot } from './types';

export const metadata: Metadata = {
  title: 'Dia · my-registers',
};

// Sempre renderizado no servidor — os records mudam a cada mensagem
// no chat, então cache HTTP não faz sentido aqui.
export const dynamic = 'force-dynamic';

async function fetchToday(): Promise<DaySnapshot | { error: string }> {
  const cookieStore = await cookies();
  const cookieHeader = cookieStore.toString();
  // Server components chamam via DNS interno do compose (INTERNAL_API_URL);
  // aprendizado do hotfix #25.
  const backend = process.env.INTERNAL_API_URL ?? 'http://localhost:8000';
  const res = await fetch(`${backend}/days/today`, {
    headers: { cookie: cookieHeader },
    cache: 'no-store',
  });
  if (!res.ok) {
    return { error: `Erro ${res.status} ao carregar o dia.` };
  }
  return (await res.json()) as DaySnapshot;
}

export default async function DayPage() {
  const result = await fetchToday();

  if ('error' in result) {
    return (
      <main className="mx-auto max-w-3xl p-4">
        <div className="rounded border border-red-200 bg-red-50 px-4 py-6 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          {result.error}
        </div>
      </main>
    );
  }

  return <DayView data={result} allowClose />;
}
