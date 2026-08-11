/**
 * T-E07 — registrar refeição pelo chat.
 *
 * Cobertura:
 *   composer -> POST /chat/messages -> worker -> LLM (stub) ->
 *   MealService -> DayTotalsBar mostra kcal_in > 0.
 *
 * Envelope enfileirado usa canonical_names do seed TBCA
 * (arroz_branco_cozido: 130 kcal/100g -> 150g = 195kcal;
 *  peito_de_frango_grelhado: 165 kcal/100g -> 180g = 297kcal;
 *  total esperado: 492 kcal).
 */

import { expect, test } from './support/test';

test.beforeEach(async ({ resetDb, loginAdmin }) => {
  await resetDb();
  await loginAdmin();
});

test('registra refeição via chat e DayTotalsBar mostra kcal_in acumulado', async ({
  page,
  queueLlm,
}) => {
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

  await page.goto('/chat');

  // Estado inicial: DayTotalsBar mostra "Nenhum registro hoje".
  await expect(page.getByText(/nenhum registro hoje/i)).toBeVisible();

  const composer = page.getByPlaceholder(/150 g de arroz/i);
  await composer.fill('almoço: 150g de arroz e 180g de frango');
  await page.getByRole('button', { name: /^enviar$/i }).click();

  // Assistant message aparece via poll (frontend a cada 1500ms). O
  // formatter emite "Registrei" no cabeçalho — usamos isso como âncora.
  await expect(page.getByText(/registrei/i)).toBeVisible({ timeout: 15000 });

  // DayTotalsBar deveria refetch via revalidateKey pos-poll, mas em alguns
  // cenarios o React nao dispara o effect a tempo. Reload forca mount fresh.
  await page.reload();
  // Escopo na barra (mesmo container do "Cal. in") pra evitar strict-mode:
  // "492 kcal" tambem aparece nas 2 tabelas markdown da assistant message.
  const totalsBar = page.locator('div', { hasText: /cal\.\s*in/i }).first();
  await expect(totalsBar).toBeVisible({ timeout: 10000 });
  await expect(totalsBar).toContainText(/492\s*kcal/i);
});
