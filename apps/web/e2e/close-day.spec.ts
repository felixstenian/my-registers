/**
 * T-E09 — encerrar dia pelo chat + navegar /weekly -> /day/[date] read-only.
 *
 * Sequencia:
 *   seedLunchMeal -> /chat mostra "Encerrar dia" -> click abre modal ->
 *   enfileira narrative -> click "Encerrar" -> badge "Dia encerrado" ->
 *   /weekly renderiza linha do dia -> clique navega pra /day/[date] ->
 *   /day/[date] read-only (sem botao "Encerrar dia").
 */

import { expect, test } from './support/test';
import { seedLunchMeal } from './support/seed';

test.beforeEach(async ({ resetDb, loginAdmin, page, queueLlm }) => {
  await resetDb();
  await loginAdmin();
  await seedLunchMeal({ page, queueLlm });
});

test('encerra dia via modal e navega weekly -> day read-only', async ({
  page,
  queueLlm,
}) => {
  // DayCloseService gera narrativa via call_narrative — precisa da fila
  // do TestAnthropicClient com texto pronto.
  await queueLlm({ kind: 'narrative', text: 'Bom trabalho! Você registrou o almoço.' });

  await page.goto('/chat');

  // Recarrega DayTotalsBar pra pegar o snapshot pos-seed (revalidateKey
  // do poll nao dispara sem uma nova mensagem chegando).
  await page.reload();

  const totalsBar = page.locator('div', { hasText: /cal\.\s*in/i }).first();
  await expect(totalsBar).toBeVisible({ timeout: 10000 });

  await page.getByRole('button', { name: /^encerrar dia$/i }).click();

  // Modal de confirmacao.
  await expect(page.getByRole('heading', { name: /encerrar o dia\?/i })).toBeVisible();

  // Botao "Encerrar" dentro do modal (distinto do "Encerrar dia" do DayTotalsBar).
  await page.getByRole('button', { name: /^encerrar$/i }).click();

  // Apos POST /days/{date}/close, phase='done' mostra "Dia encerrado" no h2.
  await expect(
    page.getByRole('heading', { name: /^dia encerrado$/i }),
  ).toBeVisible({ timeout: 10000 });

  // O ClosedSummary tem um link "Ver semana" que leva direto pro /weekly
  // — usar isso confirma tambem o CTA. Alternativa seria clicar "Voltar"
  // e depois navegar, mas isso testa menos.
  await page.getByRole('link', { name: /ver semana/i }).click();
  const today = new Date().toISOString().slice(0, 10);
  const dayLink = page.locator(`a[href="/day/${today}"]`);
  await expect(dayLink).toBeVisible();
  await dayLink.click();

  await expect(page).toHaveURL(new RegExp(`/day/${today}$`));

  // Dia fechado: sem botao "Encerrar dia" no /day/[date].
  await expect(page.getByRole('button', { name: /^encerrar dia$/i })).toHaveCount(0);
  // Badge "Dia encerrado" no header do DayView confirma read-only.
  await expect(page.getByText(/^dia encerrado$/i).first()).toBeVisible();
});
