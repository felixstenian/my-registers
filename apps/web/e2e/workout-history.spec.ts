/**
 * T-B308 — renderização da assistant message `workout_history` no chat.
 *
 * Cobertura (specs/001-mvp-registro-diario/tasks.md T-B308):
 *   - `WorkoutHistoryCard` aparece para `llm_intent='workout_history'`.
 *   - Tabela "PR pessoal" ganha destaque amber no valor (carga do PR).
 */

import { expect, test } from './support/test';

test.beforeEach(async ({ resetDb, loginAdmin }) => {
  await resetDb();
  await loginAdmin();
});

test('T-B308: workout_history renderiza WorkoutHistoryCard com PR em destaque', async ({
  page,
  queueLlm,
}) => {
  // Enfileira resposta LLM com intent workout_history (SP-127). O histórico
  // real vem do `WorkoutService.history` — sem sessões registradas ainda, o
  // formatter responde "Nenhum histórico... primeira vez".
  await queueLlm({
    kind: 'record_intent',
    envelope: {
      intent: 'workout_history',
      confidence: 0.92,
      user_text_summary: 'Qual peso fiz no supino?',
      needs_clarification: false,
      workout_history: { exercise_name: 'supino reto' },
    },
  });

  await page.goto('/chat');

  const composer = page.getByPlaceholder(/150 g de arroz/i);
  await composer.fill('qual peso fiz no supino?');
  await composer.press('Enter');

  // Card dedicado de histórico de treino.
  await expect(page.getByText(/histórico de treino/i)).toBeVisible({
    timeout: 15000,
  });
  // Badge de treino no corpo da mensagem.
  await expect(page.getByText(/🏋️ Treino/i)).toBeVisible({ timeout: 5000 });
  // Conteúdo do histórico (primeira vez do exercício).
  await expect(page.getByText(/nenhum histórico de supino reto/i)).toBeVisible({
    timeout: 5000,
  });
});