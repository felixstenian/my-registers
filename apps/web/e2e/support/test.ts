/**
 * Test fixture estendido com helpers pra E2E controlar backend em
 * APP_ENV=test:
 *
 *   test('...', async ({ page, queueLlm, resetDb }) => { ... })
 *
 * - `queueLlm(kind, payload)` — enfileira envelope canned pro
 *   TestAnthropicClient. Chamar antes de interacoes que disparam LLM
 *   (envio de mensagem, encerramento de dia, etc.).
 * - `resetDb()` — TRUNCATE + recria admin. Usar em beforeEach quando
 *   o teste precisa de estado zerado.
 *
 * Ambos usam `page.request` — compartilha cookies com o browser mas
 * podem ser chamados em qualquer momento (endpoints sao unauth).
 */

import { test as base, expect } from '@playwright/test';
import { ADMIN_EMAIL, ADMIN_PASSWORD, API_BASE } from './constants';
import type { LLMKind, QueuePayload } from './types';

type Fixtures = {
  queueLlm: (payload: QueuePayload) => Promise<void>;
  resetDb: () => Promise<void>;
  loginAdmin: () => Promise<void>;
};

export const test = base.extend<Fixtures>({
  queueLlm: async ({ page }, use) => {
    await use(async (payload) => {
      const body: Record<string, unknown> = { kind: payload.kind };
      if (payload.kind === 'record_intent') {
        body.envelope = payload.envelope;
      } else if (payload.kind === 'record_intent_error') {
        body.error = payload.error;
      } else {
        body.text = payload.text;
      }
      const res = await page.request.post(`${API_BASE}/test/queue-llm-response`, {
        data: body,
      });
      if (!res.ok()) {
        throw new Error(
          `queueLlm(${payload.kind}) falhou: ${res.status()} ${await res.text()}`,
        );
      }
    });
  },
  resetDb: async ({ page }, use) => {
    await use(async () => {
      const res = await page.request.post(`${API_BASE}/test/reset`);
      if (!res.ok()) {
        throw new Error(`resetDb falhou: ${res.status()} ${await res.text()}`);
      }
    });
  },
  loginAdmin: async ({ page }, use) => {
    // Necessario apos resetDb() em specs autenticados: o TRUNCATE dropou o
    // admin, deixando o storageState apontando pra um user inexistente
    // (redirect loop no /chat). Usar page.request substitui o cookie no
    // context da page, e o proximo page.goto ja usa o cookie novo.
    await use(async () => {
      const login = await page.request.post(`${API_BASE}/auth/login`, {
        data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
      });
      if (!login.ok()) {
        throw new Error(`loginAdmin falhou: ${login.status()}`);
      }
    });
  },
});

export { expect };
export type { LLMKind };
