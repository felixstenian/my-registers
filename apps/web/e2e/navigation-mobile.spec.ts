/**
 * T-NM-05 — E2E da navegação mobile (SP-NM-01..07).
 *
 * Cobertura:
 *   SP-NM-01 — /chat não rola a página (header não sai de vista)
 *   SP-NM-02 — header sticky
 *   SP-NM-03 — bottom tab bar visível no mobile com aba ativa (aria-current)
 *   SP-NM-04 — barra não cobre compositor/disclaimer do /chat
 *   SP-NM-05 — desktop inalterado (sem barra, nav inline no header)
 *
 * Viewports: mobile (Pixel-like 390×844) e desktop (1280×800) no mesmo
 * arquivo via `test.use`.
 *
 * `beforeEach` com resetDb+loginAdmin é OBRIGATÓRIO: specs anteriores da
 * suíte truncam o banco e recriam o admin com um novo id — o token do
 * storageState passa a apontar pra um usuário inexistente e o `/chat`
 * entra em redirect loop com `/login` (ver support/test.ts).
 */

import { expect, test } from './support/test';

test.beforeEach(async ({ resetDb, loginAdmin }) => {
  await resetDb();
  await loginAdmin();
});

test.describe('navegação mobile', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('SP-NM-03/04: barra visível com aba Chat ativa e não cobre composer/disclaimer', async ({
    page,
  }) => {
    await page.goto('/chat');

    const nav = page.getByRole('navigation', { name: 'Navegação principal' });
    await expect(nav).toBeVisible();
    await expect(nav.getByRole('link', { name: 'Chat' })).toHaveAttribute(
      'aria-current',
      'page',
    );

    // SP-NM-04: o botão de envio fica acima da barra fixa.
    const submit = page.getByRole('button', { name: 'Enviar' });
    await submit.scrollIntoViewIfNeeded();
    const submitBox = await submit.boundingBox();
    const navBox = await nav.boundingBox();
    expect(submitBox).not.toBeNull();
    expect(navBox).not.toBeNull();
    expect(submitBox!.y + submitBox!.height).toBeLessThanOrEqual(navBox!.y + 1);

    // Art. VII §26: disclaimer continua visível com a barra presente.
    await expect(page.getByText(/As estimativas nutricionais/)).toBeVisible();
  });

  test('SP-NM-03: aba ativa segue Chat → Hoje → Semana', async ({ page }) => {
    await page.goto('/chat');
    const nav = page.getByRole('navigation', { name: 'Navegação principal' });

    await nav.getByRole('link', { name: 'Hoje' }).click();
    await expect(page).toHaveURL(/\/day$/);
    await expect(nav.getByRole('link', { name: 'Hoje' })).toHaveAttribute(
      'aria-current',
      'page',
    );

    await nav.getByRole('link', { name: 'Semana' }).click();
    await expect(page).toHaveURL(/\/weekly$/);
    await expect(nav.getByRole('link', { name: 'Semana' })).toHaveAttribute(
      'aria-current',
      'page',
    );
  });

  test('SP-NM-01/02: header sticky e /chat rola só internamente', async ({ page }) => {
    await page.goto('/chat');

    const header = page.getByRole('banner');
    expect(await header.evaluate((el) => getComputedStyle(el).position)).toBe('sticky');

    // O importante (SP-NM-01/02) é que o header NÃO saia de vista ao
    // tentar rolar — a conversa rola dentro do container, a página mal
    // move (rounding de dvh pode dar 1-2px). Assere pelo bounding box.
    await page.evaluate(() => window.scrollTo(0, 500));
    await expect(header).toBeVisible();
    const headerBox = await header.boundingBox();
    expect(headerBox).not.toBeNull();
    expect(headerBox!.y).toBeGreaterThanOrEqual(-1);
    expect(headerBox!.y).toBeLessThanOrEqual(1);
  });
});

test.describe('desktop inalterado', () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test('SP-NM-05: sem bottom bar e com nav inline no header', async ({ page }) => {
    await page.goto('/chat');

    await expect(
      page.getByRole('navigation', { name: 'Navegação principal' }),
    ).toBeHidden();
    await expect(page.getByRole('link', { name: 'Semana' })).toBeVisible();
  });
});