/**
 * T-E08 — /day mostra a refeicao seedada com detalhamento por item.
 *
 * Continua o flow do T-E07 (mas via seed direto na API, sem UI):
 * cadastra almoco arroz + frango, abre /day e valida que a secao
 * "Almoço" tem os 2 items. Expande o `<details>` do arroz pra verificar
 * que a lista de micros esta la (Sodio, Calcio, Ferro, Potassio).
 */

import { expect, test } from './support/test';
import { seedLunchMeal } from './support/seed';

test.beforeEach(async ({ resetDb, loginAdmin, page, queueLlm }) => {
  await resetDb();
  await loginAdmin();
  await seedLunchMeal({ page, queueLlm });
});

test('/day mostra secao Almoço com 2 items e permite expandir micros', async ({
  page,
}) => {
  await page.goto('/day');

  // Header "Almoço" e' um <span className="font-semibold"> dentro do
  // <header> da secao. Não usar getByText({ exact: true }): o <select> de
  // meal_slot do DailyAddForm tambem tem um <option>Almoço</option> no DOM,
  // o que estoura strict mode (locator ambiguo). Escopamos ao header.
  await expect(
    page.locator('header span.font-semibold', { hasText: 'Almoço' }),
  ).toBeVisible();

  // Ambos os items renderizam o detected_name no summary (col-span-4).
  await expect(page.getByText('arroz branco cozido')).toBeVisible();
  await expect(page.getByText('peito de frango grelhado')).toBeVisible();

  // <details> HTML nativo — o click no summary do arroz toggla open.
  const arrozSummary = page.locator('summary').filter({ hasText: 'arroz branco cozido' });
  await arrozSummary.click();

  // Apos expandir, os labels de micronutrientes aparecem dentro do details.
  const arrozDetails = page.locator('details').filter({ hasText: 'arroz branco cozido' });
  await expect(arrozDetails.getByText('Sódio')).toBeVisible();
  await expect(arrozDetails.getByText('Cálcio')).toBeVisible();
  await expect(arrozDetails.getByText('Ferro')).toBeVisible();
  await expect(arrozDetails.getByText('Potássio')).toBeVisible();
});
