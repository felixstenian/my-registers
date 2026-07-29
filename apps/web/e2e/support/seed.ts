/**
 * Helpers de seed para specs que precisam de estado pre-condicionado
 * (day com refeicao ja registrada, dia encerrado, etc). Cada helper
 * ataca via HTTP direto (`page.request`), evitando depender da UI —
 * mais rapido e menos flaky que reencenar a interacao no chat.
 *
 * Todos assumem que o beforeEach do spec ja rodou resetDb + loginAdmin.
 */

import type { Page } from '@playwright/test';
import { API_BASE } from './constants';

type QueueLlmFn = (payload: {
  kind: 'record_intent' | 'narrative' | 'weekly_narrative';
  envelope?: Record<string, unknown>;
  text?: string | null;
}) => Promise<void>;

/**
 * Registra almoco arroz + frango (492 kcal esperados). Enfileira o envelope
 * `log_food`, POSTa em /chat/messages (worker background processa via
 * TestAnthropicClient) e faz busy-wait em /days/today ate kcal_in > 0.
 */
export async function seedLunchMeal({
  page,
  queueLlm,
}: {
  page: Page;
  queueLlm: QueueLlmFn;
}): Promise<void> {
  await queueLlm({
    kind: 'record_intent',
    envelope: {
      intent: 'log_food',
      confidence: 0.92,
      user_text_summary: 'Almoço: arroz e frango.',
      needs_clarification: false,
      meal_slot: 'lunch',
      food_items: [
        {
          detected_name: 'arroz branco cozido',
          normalized_name: 'arroz_branco_cozido',
          quantity: 150,
          unit: 'g',
          grams_estimate: 150,
          confidence: 0.95,
          is_estimate: false,
        },
        {
          detected_name: 'peito de frango grelhado',
          normalized_name: 'peito_de_frango_grelhado',
          quantity: 180,
          unit: 'g',
          grams_estimate: 180,
          confidence: 0.94,
          is_estimate: false,
        },
      ],
    },
  });

  const post = await page.request.post(`${API_BASE}/chat/messages`, {
    data: { text: 'almoço: 150g de arroz e 180g de frango', media_ids: [] },
  });
  if (!post.ok()) {
    throw new Error(`seedLunchMeal POST /chat/messages: ${post.status()} ${await post.text()}`);
  }

  // Worker background processa em ms; damos ate 10s pra o commit aparecer.
  for (let i = 0; i < 40; i++) {
    const daysRes = await page.request.get(`${API_BASE}/days/today`);
    if (daysRes.ok()) {
      const day = (await daysRes.json()) as { totals: { kcal_in: number } };
      if (day.totals.kcal_in > 0) return;
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error('seedLunchMeal: /days/today permaneceu com kcal_in=0 apos 10s');
}
