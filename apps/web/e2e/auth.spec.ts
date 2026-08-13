/**
 * T-E06 — golden path de autenticação (browser anônimo).
 *
 * Todos os specs rodam sem o storageState do setup: sobrescrevem para
 * `{ cookies: [], origins: [] }` para começar de forma anônima.
 *
 * Cobertura (mapeada em specs/features/authentication-session):
 *   AC-001/TC-I-001 — login OK seta cookies HttpOnly.
 *   AC-002/TC-I-002 — email case-insensitive.
 *   AC-003/TC-I-003/TC-I-004 — credencial inválida genérica.
 *   AC-013/US-006 — redirect /login?next= e preservação do next.
 */

import { ADMIN_EMAIL, ADMIN_PASSWORD, API_BASE } from './support/constants';
import { expect, test } from './support/test';

test.use({ storageState: { cookies: [], origins: [] } });

test.beforeEach(async ({ resetDb }) => {
  // Reset garante admin recém-criado (o setup roda uma vez, mas outros
  // specs podem ter alterado o DB).
  await resetDb();
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

test('login OK redireciona para /chat', async ({ page }) => {
  await page.goto('/login');

  await page.getByLabel('E-mail').fill(ADMIN_EMAIL);
  await page.getByLabel('Senha').fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: /entrar/i }).click();

  await expect(page).toHaveURL(/\/chat$/);
});

test('login OK seta cookies HttpOnly access_token + refresh_token (AC-001/TC-I-001)', async ({
  page,
}) => {
  await page.goto('/login');

  await page.getByLabel('E-mail').fill(ADMIN_EMAIL);
  await page.getByLabel('Senha').fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: /entrar/i }).click();

  await expect(page).toHaveURL(/\/chat$/);

  const cookies = await page.context().cookies();
  const access = cookies.find((c) => c.name === 'access_token');
  const refresh = cookies.find((c) => c.name === 'refresh_token');

  expect(access).toBeTruthy();
  expect(refresh).toBeTruthy();
  expect(access?.httpOnly).toBe(true);
  expect(refresh?.httpOnly).toBe(true);
  // path="/" e SameSite=Lax (definidos em _set_session_cookies).
  expect(access?.path).toBe('/');
  expect(refresh?.path).toBe('/');
  expect(access?.sameSite).toBe('Lax');
  expect(refresh?.sameSite).toBe('Lax');
});

test('email case-insensitive loga com sucesso (AC-002/TC-I-002)', async ({ page }) => {
  // AC-002: login com email uppercase → backend faz .lower() antes do lookup.
  // Usa API direto em vez de UI porque o dev proxy do Next.js em Docker
  // pode retornar timeout/HTML intermitente (alert fallback "Não foi
  // possível autenticar."). O fluxo de login via UI já é coberto pelos
  // testes "login OK" acima; aqui o alvo é validar case-insensitivity.
  const res = await page.request.post(`${API_BASE}/auth/login`, {
    data: { email: 'ADMIN@Example.COM', password: ADMIN_PASSWORD },
  });
  expect(res.status()).toBe(204);

  // Cookies HttpOnly depositados no contexto da page (page.request
  // compartilha o cookie jar). Navegar pra /chat confirma E2E.
  await page.goto('/chat');
  await expect(page).toHaveURL(/\/chat$/);
});

test('email inexistente mostra erro inline genérico (AC-003/TC-I-004)', async ({ page }) => {
  await page.goto('/login');

  await page.getByLabel('E-mail').fill('naoexiste@example.com');
  await page.getByLabel('Senha').fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: /entrar/i }).click();

  // Mesma mensagem do "senha errada" — indistinguível (SP-02).
  const alert = page.getByText(/e-mail ou senha inv[áa]lidos/i);
  await expect(alert).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
});

test('rota protegida /chat sem cookie redireciona /login?next=/chat (AC-013/US-006)', async ({
  page,
}) => {
  await page.goto('/chat');

  await expect(page).toHaveURL(/\/login\?next=(?:%2F|\/)chat$/);
});

test('rota protegida /weekly sem cookie redireciona /login?next=/weekly (AC-013)', async ({
  page,
}) => {
  await page.goto('/weekly');

  await expect(page).toHaveURL(/\/login\?next=(?:%2F|\/)weekly$/);
});

test('login OK com ?next=/weekly preserva destino após autenticar (AC-013/US-006)', async ({
  page,
}) => {
  // /weekly sem cookie -> redirect /login?next=/weekly.
  await page.goto('/weekly');
  await expect(page).toHaveURL(/\/login\?next=(?:%2F|\/)weekly$/);

  await page.getByLabel('E-mail').fill(ADMIN_EMAIL);
  await page.getByLabel('Senha').fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: /entrar/i }).click();

  // LoginForm respeita searchParams.next -> router.replace('/weekly').
  // Next.js client-side navigation can race with RSC — use longer timeout.
  await expect(page).toHaveURL(/\/weekly$/, { timeout: 15000 });
});

