// Compartilhado entre setup, fixtures e specs.
// Valores sao pareados com docker-compose.e2e.yml + `python -m app.cli bootstrap`.

export const API_BASE = 'http://localhost:8001';
export const WEB_BASE = 'http://localhost:3001';
export const ADMIN_EMAIL = 'admin@example.com';
export const ADMIN_PASSWORD = 'adminadmin';
export const STORAGE_STATE_PATH = 'e2e/.auth/admin.json';
