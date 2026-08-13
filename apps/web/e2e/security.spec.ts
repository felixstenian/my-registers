/**
 * Segurança — cookie tampering, refresh token reuso (INV-6), /auth/me leak.
 *
 * Restaurado de security.spec.ts + session.spec.ts (deletados em
 * fix/fe-01-fe-05). Cobertura:
 *
 *   AC-012 / TC-I-013 — cookie access adulterado → 401 sem eco do payload.
 *   TC-E-004 / AC-007 / INV-6 — refresh vazado após rotação invalida família.
 *   AC-011 / INV-7 — GET /auth/me não vaza password_hash.
 *   AC-008 / TC-E-001 — logout revoga refresh + rota protegida redireciona.
 */

import { expect, test } from './support/test';
import { request } from '@playwright/test';
import { API_BASE, ADMIN_EMAIL, ADMIN_PASSWORD } from './support/constants';

// ---------------------------------------------------------------------------
// Cookie tampering + refresh reuso (anônimos)
// ---------------------------------------------------------------------------

test.describe('Segurança — cookie e refresh token', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ resetDb }) => {
    await resetDb();
  });

  test('cookie access adulterado → 401 sem eco do payload (AC-012/TC-I-013)', async ({
    page,
  }) => {
    const tampered =
      'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhY2Nlc3MtdGFrZW4iLCJleHAiOjk5OTk5OTk5OTl9.invalid-signature-tampered';

    const res = await page.request.get(`${API_BASE}/auth/me`, {
      headers: { Cookie: `access_token=${tampered}` },
    });

    expect(res.status()).toBe(401);
    const body = await res.json();
    expect(body.code).toBe('unauthorized');

    const raw = JSON.stringify(body);
    expect(raw).not.toContain('access-taken');
    expect(raw).not.toContain('invalid-signature-tampered');
    expect(raw).not.toMatch(/traceback|stacktrace/i);
  });

  test('refresh vazado após rotação invalida a família inteira (TC-E-004/AC-007/INV-6)', async () => {
    const browserA = await request.newContext();
    const browserB = await request.newContext();

    try {
      const loginA = await browserA.post(`${API_BASE}/auth/login`, {
        data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
      });
      expect(loginA.status()).toBe(204);

      const stateA = await browserA.storageState();
      const t1 = stateA.cookies.find((c) => c.name === 'refresh_token')?.value;
      expect(t1).toBeTruthy();

      // 2. A rotaciona T1 -> T2 (jar do A agora guarda T2).
      const refreshA = await browserA.post(`${API_BASE}/auth/refresh`);
      expect(refreshA.status()).toBe(204);

      // 3. Atacante (B) reaproveita T1 roubado apos a rotação.
      //    Backend detecta reuso de token revogado -> 401 + revoke_family.
      const refreshB = await browserB.post(`${API_BASE}/auth/refresh`, {
        headers: { Cookie: `refresh_token=${t1}` },
      });
      expect(refreshB.status()).toBe(401);
      const bodyB = await refreshB.json();
      expect(bodyB.code).toBe('invalid_refresh');

      // 4. A tenta usar T2 (legítimo) — família foi toda invalidada.
      const refreshA2 = await browserA.post(`${API_BASE}/auth/refresh`);
      expect(refreshA2.status()).toBe(401);
      const bodyA2 = await refreshA2.json();
      expect(bodyA2.code).toBe('invalid_refresh');
    } finally {
      await browserA.dispose();
      await browserB.dispose();
    }
  });
});

// ---------------------------------------------------------------------------
// Sessão autenticada — logout, redirect, /auth/me leak
// ---------------------------------------------------------------------------

test.describe('Sessão — logout e proteção pós-logout', () => {
  test.beforeEach(async ({ resetDb, loginAdmin }) => {
    await resetDb();
    await loginAdmin();
  });

  async function apiLogout(page: import('@playwright/test').Page) {
    const res = await page.request.post(`${API_BASE}/auth/logout`);
    expect(res.status()).toBe(204);
    await page.context().clearCookies();
  }

  test('/login com cookie válido redireciona /chat (AC-013)', async ({ page }) => {
    await page.goto('/login');
    await expect(page).toHaveURL(/\/chat$/);
  });

  test('após logout, /chat redireciona /login?next=/chat (TC-E-001)', async ({ page }) => {
    await apiLogout(page);
    await page.goto('/chat');
    await expect(page).toHaveURL(/\/login\?next=(?:%2F|\/)chat$/);
  });

  test('após logout, refresh com token revogado retorna 401 (TC-E-001/AC-008)', async ({
    page,
  }) => {
    const cookiesBefore = await page.context().cookies();
    const oldRefresh = cookiesBefore.find((c) => c.name === 'refresh_token')?.value;
    expect(oldRefresh).toBeTruthy();

    await apiLogout(page);

    const res = await page.request.post(`${API_BASE}/auth/refresh`, {
      headers: { Cookie: `refresh_token=${oldRefresh}` },
    });

    expect(res.status()).toBe(401);
    const body = await res.json();
    expect(body.code).toBe('invalid_refresh');
  });

  test('GET /auth/me nunca expõe password_hash (AC-011/INV-7)', async ({ page }) => {
    const res = await page.request.get(`${API_BASE}/auth/me`);

    expect(res.status()).toBe(200);
    const body = await res.json();

    expect(body).not.toHaveProperty('password_hash');
    expect(JSON.stringify(body)).not.toMatch(/password_hash|argon2/i);
  });
});
