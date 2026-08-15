// Compartilhado entre setup, fixtures, specs e playwright.config.ts.
// Valores default pareados com docker-compose.e2e.yml +
// `python -m app.cli bootstrap`. Sobrescrevíveis via E2E_API_BASE /
// E2E_WEB_BASE caso a stack suba em portas diferentes.

export const API_BASE = process.env.E2E_API_BASE ?? 'http://localhost:8001';
export const WEB_BASE = process.env.E2E_WEB_BASE ?? 'http://localhost:3001';
export const ADMIN_EMAIL = 'admin@example.com';
export const ADMIN_PASSWORD = 'adminadmin';
export const STORAGE_STATE_PATH = 'e2e/.auth/admin.json';