import { defineConfig, devices } from '@playwright/test';

/**
 * Config Playwright — E2E golden path (T-E04..T-E11).
 *
 * Stack alvo: docker-compose.e2e.yml (api :8001, web :3001, APP_ENV=test).
 * Sobe via `./scripts/e2e-bootstrap.sh` antes de rodar.
 *
 * `workers: 1` intencional na v1: fixtures resetam DB via /test/reset,
 * então paralelismo cross-spec quebraria isolamento. Se virar gargalo,
 * migrar pra reset-por-transação no backend.
 */
export default defineConfig({
  testDir: './e2e',
  testIgnore: ['**/support/**'],
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI
    ? [['html', { open: 'never' }], ['github']]
    : [['html', { open: 'never' }], ['list']],
  use: {
    baseURL: 'http://localhost:3001',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    // Const. Art. VIII: PWA/service worker fica ativo em produção,
    // mas em E2E desativamos pra evitar cache do login stale.
    serviceWorkers: 'block',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
