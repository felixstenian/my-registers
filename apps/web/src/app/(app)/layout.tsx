import { cookies } from 'next/headers';
import Link from 'next/link';
import { redirect } from 'next/navigation';
import { InstallButton } from './InstallButton';
import { LogoutButton } from './logout-button';

type Me = {
  id: string;
  email: string;
  display_name: string | null;
  timezone: string;
};

async function fetchMe(): Promise<Me | null> {
  const cookieStore = await cookies();
  const cookieHeader = cookieStore.toString();
  const backend = process.env.INTERNAL_API_URL ?? 'http://localhost:8000';
  const res = await fetch(`${backend}/auth/me`, {
    headers: { cookie: cookieHeader },
    cache: 'no-store',
  });
  if (!res.ok) return null;
  return (await res.json()) as Me;
}

export default async function ProtectedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const me = await fetchMe();
  if (!me) {
    redirect('/login');
  }
  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between border-b border-slate-200 px-6 py-3 text-sm dark:border-slate-800">
        <div className="flex items-center gap-4">
          <Link href="/chat" className="font-medium hover:opacity-80">
            my-registers
          </Link>
          <nav className="flex items-center gap-3 text-slate-500 dark:text-slate-400">
            <Link href="/chat" className="hover:text-slate-900 dark:hover:text-slate-100">
              Chat
            </Link>
            <Link
              href="/day"
              className="hover:text-slate-900 dark:hover:text-slate-100"
            >
              Hoje
            </Link>
            <Link
              href="/weekly"
              className="hover:text-slate-900 dark:hover:text-slate-100"
            >
              Semana
            </Link>
          </nav>
        </div>
        <div className="flex items-center gap-3 text-slate-500 dark:text-slate-400">
          <span>{me.email}</span>
          <InstallButton />
          <LogoutButton />
        </div>
      </header>
      <div className="flex-1">{children}</div>
    </div>
  );
}
