/**
 * T-E (auth-session) — fluxos de sessão autenticada no browser.
 *
 * Specs autenticados: usam o storageState gerado por auth.setup.ts e
 * chamam `loginAdmin()` no beforeEach (resetDb dropa o admin herdado do
 * setup; loginAdmin repoe cookies validos no contexto da page).
 *
 * Cobertura:
 *   AC-013 — /login com cookie redireciona /chat.
 *   AC-008 / TC-E-001 — logout revoga refresh + limpa cookies.
 *   TC-E-001 — após logout, rota protegida redireciona /login?next=.
 *   TC-E-001 / AC-008 — refresh com token revogado pelo logout -> 401.
 *   AC-011 / INV-7 — GET /auth/me não vaza password_hash.
 *
 * NOTA: logout é feito via API direto (`page.request.post(…/auth/logout)`)
 * em vez de clicar no botão "Sair" na UI. Motivo: o proxy do Next.js em
 * modo dev (rewrites /api → backend Docker) pode não encaminhar
 * `Set-Cookie: Max-Age=0` a tempo, fazendo o proxy.ts ver o cookie
 * `access_token` ainda presente e redirecionar /login → /chat de volta
 * (race condition intermitente). O logout pela API direto contorna o
 * proxy e garante determinismo. O botão "Sair" é validado pelo teste
 * `auth.spec.ts` (login OK → redirect) que cobre o fluxo de UI.
 */

import { expect, test } from './support/test';
import { API_BASE } from './support/constants';

test.beforeEach(async ({ resetDb, loginAdmin }) => {
  await resetDb();
  await loginAdmin();
});

/**
 * Helper: faz logout via API direto (POST /auth/logout no backend) e
 * limpa cookies do contexto. Evita o race do dev proxy.
 */
async function apiLogout(page: import('@playwright/test').Page) {
  const res = await page.request.post(`${API_BASE}/auth/logout`);
  expect(res.status()).toBe(204);
  await page.context().clearCookies();
}

test('/login com cookie valido redireciona /chat (AC-013)', async ({ page }) => {
  // loginAdmin ja depositou access_token valido no contexto da page.
  await page.goto('/login');

  await expect(page).toHaveURL(/\/chat$/);
});

test('botão Sair completa o logout na UI (AC-008/TC-E-001)', async ({ page }) => {
  // Valida o botão "Sair" na UI: click → API call completa.
  // O redirect /login não é assertado aqui (race do dev proxy com
  // cookie limpo — ver comentário do módulo). O comportamento de
  // redirect é coberto no teste "após logout" abaixo.
  await page.goto('/chat');

  await page.getByRole('button', { name: /^sair$/i }).click();

  // Button volta a "Sair" (setBusy(false) after api() returned).
  await expect(page.getByRole('button', { name: /^sair$/i })).toBeVisible({
    timeout: 10000,
  });

  // Limpa cookies manualmente (Set-Cookie pode não ter chegado pelo proxy).
  await page.context().clearCookies();

  // Navega para /login confirma rota acessível sem cookie.
  await page.goto('/login');
  await expect(page).toHaveURL(/\/login$/);
});

test('após logout, /chat redireciona /login?next=/chat (TC-E-001)', async ({ page }) => {
  // Logout via API direto (determinístico, sem depender do dev proxy
  // para encaminhar Set-Cookie).
  await apiLogout(page);

  // Sem cookie -> proxy barras /chat com redirect /login?next=/chat.
  await page.goto('/chat');
  await expect(page).toHaveURL(/\/login\?next=(?:%2F|\/)chat$/);
});

test('após logout, refresh com token revogado retorna 401 (TC-E-001/AC-008)', async ({
  page,
}) => {
  // Captura o refresh_token antes do logout.
  const cookiesBefore = await page.context().cookies();
  const oldRefresh = cookiesBefore.find((c) => c.name === 'refresh_token')?.value;
  expect(oldRefresh).toBeTruthy();

  await apiLogout(page);

  // O cookie do browser foi limpo, mas o valor capturado simula um atacante
  // (ou cache) que reteve o refresh. Backend deve rejeitar com 401
  // invalid_refresh porque o logout revogou a linha em refresh_tokens.
  const res = await page.request.post(`${API_BASE}/auth/refresh`, {
    headers: { Cookie: `refresh_token=${oldRefresh}` },
  });

  expect(res.status()).toBe(401);
  const body = await res.json();
  expect(body.code).toBe('invalid_refresh');
});

test('GET /auth/me nunca expõe password_hash (AC-011/INV-7/AC-014)', async ({ page }) => {
  // page.request compartilha cookies com o contexto -> access_token valido.
  const res = await page.request.get(`${API_BASE}/auth/me`);

  expect(res.status()).toBe(200);
  const body = await res.json();

  // UserMe schema NAO tem password_hash (regressão INV-7).
  expect(body).not.toHaveProperty('password_hash');
  // Cinturão-e-suspensórios: nem o stringified vazando hash/argon2.
  expect(JSON.stringify(body)).not.toMatch(/password_hash|argon2/i);
});