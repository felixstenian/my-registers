'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { FormEvent, useState } from 'react';
import { api } from '@/lib/api-client';

const ERROR_MESSAGES: Record<string, string> = {
  invalid_credentials: 'E-mail ou senha inválidos.',
  rate_limited: 'Muitas tentativas. Aguarde alguns minutos e tente de novo.',
  validation_error: 'Preencha e-mail e senha corretamente.',
};

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextParam = searchParams.get('next') ?? '/chat';
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = await api('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      });
      if (result.ok) {
        router.replace(nextParam);
        router.refresh();
        return;
      }
      setError(ERROR_MESSAGES[result.error.code] ?? 'Não foi possível autenticar.');
    } catch {
      setError('Falha de rede. Tente novamente.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-sm flex-col justify-center gap-6 p-8">
      <div>
        <h1 className="text-2xl font-semibold">my-registers</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Acesso restrito. Entre com sua conta.
        </p>
      </div>

      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">E-mail</span>
          <input
            type="email"
            name="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="rounded border border-slate-300 bg-white px-3 py-2 text-slate-900 outline-none focus:border-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Senha</span>
          <input
            type="password"
            name="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="rounded border border-slate-300 bg-white px-3 py-2 text-slate-900 outline-none focus:border-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
          />
        </label>

        {error && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white transition disabled:opacity-60 dark:bg-slate-100 dark:text-slate-900"
        >
          {submitting ? 'Entrando…' : 'Entrar'}
        </button>
      </form>

      <footer className="text-xs text-slate-500 dark:text-slate-400">
        As estimativas nutricionais desta ferramenta são aproximações e não substituem
        acompanhamento médico ou nutricional.
      </footer>
    </main>
  );
}
