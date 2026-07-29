/**
 * T-E06 — golden path de autenticação.
 *
 * Ambos os casos rodam sem o storageState do setup: sobrescrevem para
 * `{ cookies: [], origins: [] }` para começar de forma anônima.
 */

import { ADMIN_EMAIL, ADMIN_PASSWORD } from './support/constants';
import { expect, test } from './support/test';

test.use({ storageState: { cookies: [], origins: [] } });

test.beforeEach(async ({ resetDb }) => {
  // Reset garante admin recém-criado (o setup roda uma vez, mas outros
  // specs podem ter alterado o DB).
  await resetDb();
});

test('login OK redireciona para /chat', async ({ page }) => {
  await page.goto('/login');

  await page.getByLabel('E-mail').fill(ADMIN_EMAIL);
  await page.getByLabel('Senha').fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: /entrar/i }).click();

  await expect(page).toHaveURL(/\/chat$/);
});

test('senha errada mostra mensagem inline', async ({ page }) => {
  await page.goto('/login');

  await page.getByLabel('E-mail').fill(ADMIN_EMAIL);
  await page.getByLabel('Senha').fill('senha-errada-123');
  await page.getByRole('button', { name: /entrar/i }).click();

  // Next injeta um role="alert" vazio pro announcer de rota; casamos por
  // texto pra pegar so o `<p role="alert">` do LoginForm.
  const alert = page.getByText(/e-mail ou senha inv[áa]lidos/i);
  await expect(alert).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
});
