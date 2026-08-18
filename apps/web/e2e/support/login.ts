/**
 * Login via UI (form /login) com proteção contra o flake de hidratação.
 *
 * Em `next dev` (webpack), o form chega SSR PEM o onSubmit: a hidratação
 * do React ainda não anexou os handlers. Um click nesse gap dispara o
 * submit GET nativo do HTML (`/login?email=…&password=…`) em vez do POST
 * via JS — quebra os testes de login de forma intermitente (flake visto em
 * auth.spec.ts:49 e FE-03).
 *
 * `waitForHydrated` espera o React assumir o DOM (chaves internas
 * `__reactProps`/`__reactFiber` anexadas ao input controlado) antes de
 * preencher/sumir — aí o onSubmit já está ativo e o click é determinístico.
 * Bônus: também evita que `fill` aconteça antes da hidratação e seja
 * sobrescrito pelo estado controlado (`value` volta a `''`).
 */

import type { Page } from '@playwright/test';
import { ADMIN_EMAIL, ADMIN_PASSWORD } from './constants';

export async function waitForHydrated(page: Page): Promise<void> {
  await page.waitForFunction(() => {
    const node =
      document.querySelector<HTMLElement>('input[name="email"]') ??
      document.querySelector<HTMLElement>('button[type="submit"]');
    if (!node) return false;
    return Object.keys(node).some(
      (key) => key.startsWith('__reactProps') || key.startsWith('__reactFiber'),
    );
  });
}

export async function loginViaForm(
  page: Page,
  email: string = ADMIN_EMAIL,
  password: string = ADMIN_PASSWORD,
): Promise<void> {
  await waitForHydrated(page);
  await page.getByLabel('E-mail').fill(email);
  await page.getByLabel('Senha').fill(password);
  await page.getByRole('button', { name: /^entrar$/i }).click();
}