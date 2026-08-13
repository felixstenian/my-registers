/**
 * Setup project — roda antes dos specs autenticados.
 *
 * 1. Reset DB (drena queues LLM + recria admin).
 * 2. POST /auth/login → cookies HttpOnly.
 * 3. Salva storageState em `e2e/.auth/admin.json`.
 *
 * O project `chromium` (playwright.config.ts) tem `dependencies: ['setup']`
 * + `storageState: STORAGE_STATE_PATH`, entao todo spec autenticado ja
 * comeca logado. Specs de auth (T-E06) declaram `test.use({ storageState:
 * { cookies: [], origins: [] } })` para comecar sem cookies.
 */

import { test as setup } from '@playwright/test';
import {
  ADMIN_EMAIL,
  ADMIN_PASSWORD,
  API_BASE,
  STORAGE_STATE_PATH,
} from './support/constants';

setup('autentica admin e salva storageState', async ({ request }) => {
  const reset = await request.post(`${API_BASE}/test/reset`);
  if (!reset.ok()) {
    throw new Error(`reset falhou: ${reset.status()} ${await reset.text()}`);
  }

  const login = await request.post(`${API_BASE}/auth/login`, {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
  if (!login.ok()) {
    throw new Error(`login falhou: ${login.status()} ${await login.text()}`);
  }

  await request.storageState({ path: STORAGE_STATE_PATH });
});
