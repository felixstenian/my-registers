async function fetchApiHealth(): Promise<{ status: string; service: string } | { error: string }> {
  const url = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
  try {
    const res = await fetch(`${url}/health`, { cache: 'no-store' });
    if (!res.ok) return { error: `HTTP ${res.status}` };
    return await res.json();
  } catch (err) {
    return { error: err instanceof Error ? err.message : 'unknown' };
  }
}

export default async function HomePage() {
  const apiHealth = await fetchApiHealth();
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col items-start justify-center gap-6 p-8">
      <h1 className="text-3xl font-semibold">my-registers</h1>
      <p className="text-slate-600 dark:text-slate-300">
        Esqueleto Fase 0. Fluxo real de chat, upload e tabela nutricional entra nas fases
        seguintes (ver <code>app_plan.md</code>).
      </p>

      <section className="w-full rounded-lg border border-slate-200 p-4 dark:border-slate-800">
        <h2 className="mb-2 text-lg font-medium">Backend</h2>
        <pre className="overflow-auto rounded bg-slate-100 p-3 text-sm dark:bg-slate-900">
          {JSON.stringify(apiHealth, null, 2)}
        </pre>
      </section>

      <footer className="mt-8 text-xs text-slate-500">
        As estimativas nutricionais desta ferramenta são aproximações e não substituem
        acompanhamento médico ou nutricional.
      </footer>
    </main>
  );
}
