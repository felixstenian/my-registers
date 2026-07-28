import { cookies } from 'next/headers';
import Link from 'next/link';
import type { Metadata } from 'next';
import { DayView } from '../DayView';
import type { DaySnapshot } from '../types';

export const metadata: Metadata = {
  title: 'Dia · my-registers',
};

export const dynamic = 'force-dynamic';

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

async function fetchDate(
  date: string,
): Promise<DaySnapshot | { error: string; status: number }> {
  const cookieStore = await cookies();
  const cookieHeader = cookieStore.toString();
  const backend = process.env.INTERNAL_API_URL ?? 'http://localhost:8000';
  const res = await fetch(`${backend}/days/${date}`, {
    headers: { cookie: cookieHeader },
    cache: 'no-store',
  });
  if (!res.ok) {
    return { error: `Erro ao carregar ${date}.`, status: res.status };
  }
  return (await res.json()) as DaySnapshot;
}

export default async function DayByDatePage({
  params,
}: {
  params: Promise<{ date: string }>;
}) {
  const { date } = await params;

  if (!DATE_PATTERN.test(date)) {
    return (
      <main className="mx-auto max-w-3xl p-4">
        <ErrorPanel>
          Data inválida: <code>{date}</code>. Formato esperado: <code>YYYY-MM-DD</code>.
        </ErrorPanel>
      </main>
    );
  }

  const result = await fetchDate(date);

  if ('error' in result) {
    return (
      <main className="mx-auto max-w-3xl p-4">
        <ErrorPanel>
          {result.status === 404
            ? 'Nenhum registro encontrado nesta data.'
            : result.error}
          <div className="mt-3">
            <Link
              href="/day"
              className="text-sm text-slate-600 underline dark:text-slate-300"
            >
              Voltar para hoje
            </Link>
          </div>
        </ErrorPanel>
      </main>
    );
  }

  // Dias passados são read-only nesta rota (edição via chat evita
  // confusão de "data efetiva" da mutação).
  return <DayView data={result} allowClose={false} />;
}

function ErrorPanel({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded border border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900/50 dark:text-slate-300">
      {children}
    </div>
  );
}
