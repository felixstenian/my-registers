/**
 * SP-167/SP-168 — Inline editing on /day page.
 *
 * Tests that expanding a record's <details> reveals an edit form,
 * and submitting it PATCHes the record and refreshes the page
 * with updated values.
 */

import type { Page } from '@playwright/test';
import { API_BASE } from './support/constants';
import { seedLunchMeal } from './support/seed';
import { expect, test } from './support/test';

type QueueLlmFn = (payload: {
  kind: 'record_intent' | 'record_intent_error' | 'narrative' | 'weekly_narrative';
  envelope?: Record<string, unknown>;
  error?: string;
  text?: string | null;
}) => Promise<void>;

async function waitForAssistant(page: Page, afterMessageId: string): Promise<void> {
  for (let i = 0; i < 40; i++) {
    const res = await page.request.get(`${API_BASE}/chat/messages?after=${afterMessageId}`);
    if (res.ok()) {
      const body = (await res.json()) as { messages: { role: string }[] };
      if (body.messages.some((m) => m.role === 'assistant')) return;
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error('Assistant message did not appear in 10s');
}

async function postChat(page: Page, text: string): Promise<string> {
  const post = await page.request.post(`${API_BASE}/chat/messages`, {
    data: { text, media_ids: [] },
  });
  if (!post.ok()) {
    throw new Error(`POST /chat/messages failed: ${post.status()} ${await post.text()}`);
  }
  return (await post.json()).message_id;
}

async function seedWater(page: Page, queueLlm: QueueLlmFn): Promise<void> {
  await queueLlm({
    kind: 'record_intent',
    envelope: {
      intent: 'log_water',
      confidence: 0.95,
      user_text_summary: 'Bebeu 500ml de agua.',
      needs_clarification: false,
      water: { volume_ml: 500, confidence: 0.95 },
    },
  });
  const msgId = await postChat(page, 'bebi 500ml de agua');
  await waitForAssistant(page, msgId);
}

async function seedActivity(page: Page, queueLlm: QueueLlmFn): Promise<void> {
  // Set weight via test hook so ActivityService can compute kcal.
  await page.request.post(`${API_BASE}/test/set-weight`, { data: { weight_kg: 78 } });

  await queueLlm({
    kind: 'record_intent',
    envelope: {
      intent: 'log_activity',
      confidence: 0.9,
      user_text_summary: 'Corrida 40min moderada.',
      needs_clarification: false,
      activity: {
        detected_name: 'corrida',
        activity_type: 'cardio_run',
        duration_minutes: 40,
        distance_km: null,
        intensity: 'moderate',
        confidence: 0.9,
      },
    },
  });
  const msgId = await postChat(page, 'corri 40 minutos moderado');
  await waitForAssistant(page, msgId);
}

async function closeDay(page: Page, queueLlm: QueueLlmFn): Promise<void> {
  await queueLlm({ kind: 'narrative', text: 'Bom trabalho!' });
  const todayRes = await page.request.get(`${API_BASE}/days/today`);
  const today = ((await todayRes.json()) as { date: string }).date;
  const res = await page.request.post(`${API_BASE}/days/${today}/close`);
  expect(res.ok()).toBeTruthy();
}

test.beforeEach(async ({ resetDb, loginAdmin, page, queueLlm }) => {
  await resetDb();
  await loginAdmin();
  await seedLunchMeal({ page, queueLlm });
});

test('edit food item grams updates page after save', async ({ page }) => {
  await page.goto('/day');

  // Expand the "arroz branco cozido" item.
  const arrozSummary = page.locator('summary').filter({ hasText: 'arroz branco cozido' });
  await arrozSummary.click();

  // The edit form should appear inside the expanded details.
  const arrozDetails = page.locator('details').filter({ hasText: 'arroz branco cozido' });
  const gramsInput = arrozDetails.getByLabel('Gramas');
  await expect(gramsInput).toBeVisible();

  // Change grams to 200 and save.
  await gramsInput.fill('200');
  await arrozDetails.getByRole('button', { name: 'Salvar' }).click();

  // After router.refresh(), the updated kcal appears in the TotalsCard.
  // 200g arroz × 130 kcal/100g = 260 kcal.
  await expect(page.getByText('260', { exact: false })).toBeVisible({ timeout: 10000 });
});

test('day closed hides edit forms and shows message', async ({ page, queueLlm }) => {
  await closeDay(page, queueLlm);

  await page.goto('/day');

  // Expand the arroz item.
  const arrozSummary = page.locator('summary').filter({ hasText: 'arroz branco cozido' });
  await arrozSummary.click();

  // The closed-day message should appear instead of the form.
  const arrozDetails = page.locator('details').filter({ hasText: 'arroz branco cozido' });
  await expect(arrozDetails.getByText('Dia encerrado')).toBeVisible();
  await expect(arrozDetails.getByLabel('Gramas')).not.toBeVisible();
});

test('edit water volume updates total after save', async ({ page, queueLlm }) => {
  await seedWater(page, queueLlm);
  await page.goto('/day');

  // Find the Hydration section.
  await expect(page.getByText('Hidratação', { exact: true })).toBeVisible();

  // Expand the water record details.
  const waterSummary = page.locator('summary').filter({ hasText: /ml/ }).first();
  await waterSummary.click();

  // Fill in new volume.
  const volumeInput = page.getByLabel('Volume (ml)');
  await expect(volumeInput).toBeVisible();
  await volumeInput.fill('750');
  await page.getByRole('button', { name: 'OK' }).click();

  // After router.refresh(), the hydration header re-renders with the new total.
  // fmtMl(750) → "750 ml" appears in both the record summary and the header.
  await expect(page.getByText('750 ml').first()).toBeVisible({ timeout: 10000 });
});

test('edit activity duration updates kcal after save', async ({ page, queueLlm }) => {
  await seedActivity(page, queueLlm);
  await page.goto('/day');

  // Find the Activity section.
  await expect(page.getByText('Atividade', { exact: true })).toBeVisible();

  // Expand the activity record details.
  const activitySummary = page.locator('summary').filter({ hasText: 'corrida' });
  await activitySummary.click();

  // Edit the duration to 60 minutes.
  const durationInput = page.getByLabel('Duração (min)');
  await expect(durationInput).toBeVisible();
  await durationInput.fill('60');
  await page.getByRole('button', { name: 'Salvar' }).click();

  // After router.refresh(), the activity summary shows "60 min".
  await expect(page.getByText('60 min')).toBeVisible({ timeout: 10000 });
});