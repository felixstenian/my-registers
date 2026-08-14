/**
 * Helpers de chat via HTTP direto (`page.request`) — usados pelos specs
 * e pelo seed para registrar mensagens e aguardar a resposta do worker
 * sem depender da UI (mais rápido e menos flaky).
 *
 * Assumem que o beforeEach do spec já rodou resetDb + loginAdmin.
 */

import type { Page } from '@playwright/test';
import { API_BASE } from './constants';

/**
 * POSTa uma mensagem no /chat/messages e retorna o message_id.
 */
export async function postChat(page: Page, text: string): Promise<string> {
  const post = await page.request.post(`${API_BASE}/chat/messages`, {
    data: { text, media_ids: [] },
  });
  if (!post.ok()) {
    throw new Error(`POST /chat/messages failed: ${post.status()} ${await post.text()}`);
  }
  return (await post.json()).message_id;
}

/**
 * Busy-wait em /chat/messages?after=<message_id> até a assistant message
 * aparecer (garante que o worker já commitou food_items + snapshot).
 */
export async function waitForAssistant(
  page: Page,
  afterMessageId: string,
  label = 'assistant',
): Promise<void> {
  for (let i = 0; i < 40; i++) {
    const res = await page.request.get(
      `${API_BASE}/chat/messages?after=${afterMessageId}`,
    );
    if (res.ok()) {
      const body = (await res.json()) as { messages: { role: string }[] };
      if (body.messages.some((m) => m.role === 'assistant')) return;
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`waitForAssistant(${label}): assistant message não apareceu em 10s`);
}