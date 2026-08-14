'use client';

/**
 * SP-NM-03 — Bottom tab bar mobile (`< md`).
 *
 * Único client component novo desta feature: precisa de `usePathname()`
 * para o estado ativo. O layout server apenas o renderiza. Os ícones são
 * SVG inline (um único consumidor — sem abstrair `nav-icons`).
 */

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { NAV_ITEMS, type NavItem } from './nav-items';

function TabIcon({ name }: { name: NavItem['icon'] }) {
  const common = {
    width: 24,
    height: 24,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 2,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    'aria-hidden': true,
  } as const;

  // Lucide icons (paths públicos, sem dependência).
  if (name === 'chat') {
    return (
      <svg {...common}>
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      </svg>
    );
  }
  if (name === 'day') {
    return (
      <svg {...common}>
        <rect width="18" height="18" x="3" y="4" rx="2" />
        <path d="M8 2v4" />
        <path d="M16 2v4" />
        <path d="M3 10h18" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <rect width="18" height="18" x="3" y="4" rx="2" />
      <path d="M8 2v4" />
      <path d="M16 2v4" />
      <path d="M3 10h18" />
      <path d="m9 16 2 2 4-4" />
    </svg>
  );
}

function isActive(pathname: string, href: NavItem['href']): boolean {
  // `/day/[date]` (SP-154/155) mantém a aba "Hoje" ativa.
  return pathname === href || pathname.startsWith(`${href}/`);
}

export default function BottomNav() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Navegação principal"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-slate-200 bg-white/95 pb-[env(safe-area-inset-bottom)] backdrop-blur dark:border-slate-800 dark:bg-slate-950/95 md:hidden"
    >
      <ul className="flex">
        {NAV_ITEMS.map((item) => {
          const active = isActive(pathname, item.href);
          return (
            <li key={item.href} className="flex-1">
              <Link
                href={item.href}
                aria-current={active ? 'page' : undefined}
                className={`flex min-h-12 flex-col items-center justify-center gap-0.5 text-[11px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-500 dark:focus-visible:outline-slate-300 ${
                  active
                    ? 'text-slate-900 dark:text-slate-50'
                    : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200'
                }`}
              >
                <TabIcon name={item.icon} />
                <span>{item.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}