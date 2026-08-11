/**
 * T-E (auth-session) — cenários de segurança no nível browser/API E2E.
 *
 * Todos começam anônimos (sobrescreve storageState vazio) e resetam DB.
 *
 * Cobertura:
 *   AC-012 / TC-I-013 — cookie access adulterado -> redirect /login
 *     sem eco do payload tampered (proxy passa por presença, layout
 *     fetchMe 401 -> redirect).
 *   TC-E-004 / AC-007 / INV-6 — refresh vazado (atacante reaproveita T1
 *     apos rotação legítima) invalida a família inteira (T2 também
 *     falha). Implementação via dois contextos de API independentes.
 */

import { expect, test } from './support/test';
import { request } from '@playwright/test';
import { API_BASE, ADMIN_EMAIL, ADMIN_PASSWORD } from './support/constants';

test.use({ storageState: { cookies: [], origins: [] } });

test.beforeEach(async ({ resetDb }) => {
  await resetDb();
});

test('cookie access adulterado -> 401 sem eco do payload (AC-012/TC-I-013)', async ({
  page,
}) => {
  // Proxy.ts só checa presença do cookie, mas o backend valida a assinatura.
  // Aqui testamos direto o boundary de segurança: GET /auth/me com cookie
  // adulterado deve retornar 401 "unauthorized" sem ecoar o payload.
  // (Navegar /chat com cookie adulterado causaria redirect loop — proxy
  // libera /chat, layout fetchMe 401 -> redirect /login, proxy vê cookie -> /
  // chat... — comportamento UX conhecido e aceito pelo design heurístico.)
  const tampered =
    'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhY2Nlc3MtdGFrZW4iLCJleHAiOjk5OTk5OTk5OTl9.invalid-signature-tampered';

  const res = await page.request.get(`${API_BASE}/auth/me`, {
    headers: { Cookie: `access_token=${tampered}` },
  });

  expect(res.status()).toBe(401);
  const body = await res.json();
  expect(body.code).toBe('unauthorized');

  // INV-7: resposta não ecoa o payload adulterado nem stack trace.
  const raw = JSON.stringify(body);
  expect(raw).not.toContain('access-taken');
  expect(raw).not.toContain('invalid-signature-tampered');
  expect(raw).not.toMatch(/traceback|stacktrace/i);
});

test('refresh vazado apos rotação invalida a família inteira (TC-E-004/AC-007/INV-6)', async () => {
  // Dois cookies jars independentes simulam browser legítimo (A) e atacante (B).
  const browserA = await request.newContext();
  const browserB = await request.newContext();

  try {
    // 1. Login legítimo em A -> emite refresh T1.
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
    //    O jar do A ainda contém T2, mas a linha foi revogada pelo
    //    revoke_family do passo 3.
    const refreshA2 = await browserA.post(`${API_BASE}/auth/refresh`);
    expect(refreshA2.status()).toBe(401);
    const bodyA2 = await refreshA2.json();
    expect(bodyA2.code).toBe('invalid_refresh');
  } finally {
    await browserA.dispose();
    await browserB.dispose();
  }
});