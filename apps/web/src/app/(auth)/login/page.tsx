import { Suspense } from 'react';
import { LoginForm } from './LoginForm';

export default function LoginPage() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-sm flex-col justify-center gap-6 p-8">
      <div>
        <h1 className="text-2xl font-semibold">my-registers</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Acesso restrito. Entre com sua conta.
        </p>
      </div>

      <Suspense fallback={<div className="h-64" aria-hidden />}>
        <LoginForm />
      </Suspense>

      <footer className="text-xs text-slate-500 dark:text-slate-400">
        As estimativas nutricionais desta ferramenta são aproximações e não substituem
        acompanhamento médico ou nutricional.
      </footer>
    </main>
  );
}
