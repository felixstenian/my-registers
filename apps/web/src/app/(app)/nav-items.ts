/**
 * Destinos primários da navegação — single source of truth.
 *
 * Módulo compartilhado (SEM `'use client'`) para que tanto o layout
 * server quanto o `BottomNav` client importem a mesma lista (Next.js
 * não propaga named exports de constantes de módulos client para
 * server components).
 */

export type NavItem = {
  href: '/chat' | '/day' | '/weekly';
  label: string;
  icon: 'chat' | 'day' | 'week';
};

export const NAV_ITEMS: NavItem[] = [
  { href: '/chat', label: 'Chat', icon: 'chat' },
  { href: '/day', label: 'Hoje', icon: 'day' },
  { href: '/weekly', label: 'Semana', icon: 'week' },
];
