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
import { API_BASE } from './constants';

type LLMKind = 'record_intent' | 'narrative' | 'weekly_narrative';
type QueuePayload =
  | { kind: 'record_intent'; envelope: Record<string, unknown> }
  | { kind: 'narrative' | 'weekly_narrative'; text: string | null };

type Fixtures = {
  queueLlm: (payload: QueuePayload) => Promise<void>;
  resetDb: () => Promise<void>;
};

export const test = base.extend<Fixtures>({
  queueLlm: async ({ request }, use) => {
    await use(async (payload) => {
      const body: Record<string, unknown> = { kind: payload.kind };
      if (payload.kind === 'record_intent') {
        body.envelope = payload.envelope;
      } else {
        body.text = payload.text;
      }
      const res = await request.post(`${API_BASE}/test/queue-llm-response`, {
        data: body,
      });
      if (!res.ok()) {
        throw new Error(
          `queueLlm(${payload.kind}) falhou: ${res.status()} ${await res.text()}`,
        );
      }
    });
  },
  resetDb: async ({ request }, use) => {
    await use(async () => {
      const res = await request.post(`${API_BASE}/test/reset`);
      if (!res.ok()) {
        throw new Error(`resetDb falhou: ${res.status()} ${await res.text()}`);
      }
    });
  },
});

export { expect };
export type { LLMKind };
