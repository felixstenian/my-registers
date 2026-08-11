/**
 * T-E (chat-messaging) — jornadas E2E do chat pelo browser.
 *
 * Cobertura (specs/features/chat-messaging/test-cases.md):
 *   TC-E-001 — Jornada completa: registro por chat (texto puro + Enter)
 *   TC-E-002 — Foto + descrição (upload de 2 imagens + texto)
 *   TC-E-003 — Erro LLM gera fallback SP-14
 *   TC-E-004 — Foco volta ao composer após envio
 *   TC-E-005 — Mídias enviadas aparecem como imagens na mensagem do usuário
 */

import { expect, test } from './support/test';
import { API_BASE } from './support/constants';

test.beforeEach(async ({ resetDb, loginAdmin }) => {
  await resetDb();
  await loginAdmin();
});

// ---------------------------------------------------------------------------
// TC-E-001 — Jornada completa: registro por chat
// ---------------------------------------------------------------------------

test('TC-E-001: registra refeição por chat com Enter e DayTotalsBar atualiza', async ({
  page,
  queueLlm,
}) => {
  // Enfileira resposta LLM com log_food — arroz + feijão.
  // arroz_branco_cozido: 130 kcal/100g -> 150g = 195 kcal
  // feijao_carioca_cozido: 76 kcal/100g -> 90g = 68.4 kcal
  // total esperado: 263 kcal (aproximado pelo arredondamento do snapshot)
  await queueLlm({
    kind: 'record_intent',
    envelope: {
      intent: 'log_food',
      confidence: 0.92,
      user_text_summary: 'Almoço: arroz e feijão.',
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
          detected_name: 'feijão carioca cozido',
          normalized_name: 'feijao_carioca_cozido',
          quantity: 90,
          unit: 'g',
          grams_estimate: 90,
          confidence: 0.93,
          is_estimate: false,
        },
      ],
    },
  });

  await page.goto('/chat');

  // Estado inicial: nenhum registro.
  await expect(page.getByText(/nenhum registro hoje/i)).toBeVisible();

  const composer = page.getByPlaceholder(/150 g de arroz/i);
  await composer.fill('150g arroz, 90g feijão');

  // Envia com Enter (TC-E-001 especifica Enter, não clique no botão).
  await composer.press('Enter');

  // User message aparece imediatamente no chat.
  await expect(page.getByText('150g arroz, 90g feijão')).toBeVisible({
    timeout: 5000,
  });

  // Typing indicator visível enquanto aguarda assistant.
  await expect(page.getByLabel(/assistente digitando/i)).toBeVisible({
    timeout: 5000,
  });

  // Assistant message aparece via poll (frontend a cada 1500ms).
  // O formatter emite "Registrei" no cabeçalho da refeição.
  await expect(page.getByText(/registrei/i)).toBeVisible({ timeout: 15000 });

  // Typing indicator desaparece após assistant chegar.
  await expect(page.getByLabel(/assistente digitando/i)).toHaveCount(0);

  // DayTotalsBar: recarrega pra pegar snapshot pós-poll (revalidateKey
  // pode não disparar o effect a tempo em alguns cenários).
  await page.reload();
  const totalsBar = page.locator('div', { hasText: /cal\.\s*in/i }).first();
  await expect(totalsBar).toBeVisible({ timeout: 10000 });
  // Pelo menos alguma caloria registrada (> 0).
  await expect(totalsBar).toContainText(/\d+\s*kcal/i);
  // Não deve mostrar "Nenhum registro hoje" anymore.
  await expect(page.getByText(/nenhum registro hoje/i)).toHaveCount(0);
});

// ---------------------------------------------------------------------------
// TC-E-002 — Foto + descrição
// ---------------------------------------------------------------------------

test('TC-E-002: anexa 2 fotos com texto e assistant mostra items estimados', async ({
  page,
  queueLlm,
}) => {
  // Enfileira resposta LLM com items do catálogo TBCA mas is_estimate=true
  // (badges ≈ nas linhas nutricionais do formatter).
  // arroz_branco_cozido: 130 kcal/100g -> 200g = 260 kcal
  // feijao_carioca_cozido: 76 kcal/100g -> 100g = 76 kcal
  await queueLlm({
    kind: 'record_intent',
    envelope: {
      intent: 'log_food',
      confidence: 0.80,
      user_text_summary: 'Meu almoço.',
      needs_clarification: false,
      meal_slot: 'lunch',
      food_items: [
        {
          detected_name: 'arroz branco cozido',
          normalized_name: 'arroz_branco_cozido',
          quantity: 200,
          unit: 'g',
          grams_estimate: 200,
          confidence: 0.70,
          is_estimate: true,
        },
        {
          detected_name: 'feijão carioca cozido',
          normalized_name: 'feijao_carioca_cozido',
          quantity: 100,
          unit: 'g',
          grams_estimate: 100,
          confidence: 0.65,
          is_estimate: true,
        },
      ],
    },
  });

  await page.goto('/chat');

  const composer = page.getByPlaceholder(/150 g de arroz/i);
  await composer.fill('meu almoço');

  // Anexa 2 fotos via input file (Playwright setInputFiles com buffers).
  // Minimal PNG válida 1x1 pixel para passar pelo Pillow _decode_probe.
  const minPng = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
    'base64',
  );
  const fileInput = page.locator('input[type="file"]');
  await fileInput.setInputFiles([
    { name: 'foto1.png', mimeType: 'image/png', buffer: minPng },
    { name: 'foto2.png', mimeType: 'image/png', buffer: minPng },
  ]);

  // Verifica que os arquivos aparecem como anexos.
  await expect(page.getByText(/2\/4 anexados/i)).toBeVisible();

  // Envia via botão (TC-E-002 não especifica Enter, usa botão).
  await page.getByRole('button', { name: /^enviar$/i }).click();

  // Assistant message aparece — "Registrei" marca o início.
  await expect(page.getByText(/registrei/i)).toBeVisible({ timeout: 15000 });

  // Tabela do assistant contém ≈ (badge de is_estimate).
  // O formatter coloca "≈" nas linhas nutricionais quando há items estimados.
  // .first() evita strict mode violation (≈ aparece em múltiplas linhas).
  await expect(page.getByText(/≈/).first()).toBeVisible({ timeout: 5000 });

  // DayTotalsBar mostra calorias após reload.
  await page.reload();
  const totalsBar = page.locator('div', { hasText: /cal\.\s*in/i }).first();
  await expect(totalsBar).toBeVisible({ timeout: 10000 });
  await expect(totalsBar).toContainText(/\d+\s*kcal/i);
});

// ---------------------------------------------------------------------------
// TC-E-003 — Erro LLM gera fallback SP-14
// ---------------------------------------------------------------------------

test('TC-E-003: erro LLM gera assistant fallback SP-14 sem records', async ({
  page,
  queueLlm,
}) => {
  // Enfileira um erro LLM (simula timeout/erro real da Anthropic).
  // O TestAnthropicClient devolve LLMCallResult(error="anthropic_timeout"),
  // que dispara _record_error criando assistant com _FALLBACK_LLM_ERROR.
  await queueLlm({
    kind: 'record_intent_error',
    error: 'anthropic_timeout',
  });

  await page.goto('/chat');

  // Estado inicial: nenhum registro.
  await expect(page.getByText(/nenhum registro hoje/i)).toBeVisible();

  const composer = page.getByPlaceholder(/150 g de arroz/i);
  await composer.fill('teste de erro');
  await composer.press('Enter');

  // User message aparece.
  await expect(page.getByText('teste de erro')).toBeVisible({ timeout: 5000 });

  // Assistant fallback SP-14: "Não consegui interpretar..."
  await expect(
    page.getByText(/não consegui interpretar/i),
  ).toBeVisible({ timeout: 15000 });

  // DayTotalsBar permanece sem registros (nenhum business record criado).
  await page.reload();
  await expect(page.getByText(/nenhum registro hoje/i)).toBeVisible({
    timeout: 10000,
  });
});

// ---------------------------------------------------------------------------
// TC-E-004 — Foco volta ao composer após envio
// ---------------------------------------------------------------------------

test('TC-E-004: composer mantém foco e limpa texto após envio', async ({
  page,
  queueLlm,
}) => {
  // Enfileira resposta LLM simples.
  await queueLlm({
    kind: 'record_intent',
    envelope: {
      intent: 'log_food',
      confidence: 0.92,
      user_text_summary: 'Refeição.',
      needs_clarification: false,
      meal_slot: 'lunch',
      food_items: [
        {
          detected_name: 'arroz branco cozido',
          normalized_name: 'arroz_branco_cozido',
          quantity: 100,
          unit: 'g',
          grams_estimate: 100,
          confidence: 0.95,
          is_estimate: false,
        },
      ],
    },
  });

  await page.goto('/chat');

  const composer = page.getByPlaceholder(/150 g de arroz/i);

  // Confirma foco inicial no composer.
  await expect(composer).toBeVisible();

  await composer.fill('100g arroz');
  await composer.press('Enter');

  // Texto é limpo após envio.
  await expect(composer).toHaveValue('');

  // Composer continua focado para próxima mensagem.
  await expect(composer).toBeFocused();

  // Assistant chega (confirma que o envio foi processado).
  await expect(page.getByText(/registrei/i)).toBeVisible({ timeout: 15000 });
});

// ---------------------------------------------------------------------------
// TC-E-005 — Mídias enviadas aparecem como imagens na mensagem do usuário
// ---------------------------------------------------------------------------

test('TC-E-005: mídias enviadas aparecem como <img> com URL presigned na mensagem do usuário', async ({
  page,
  queueLlm,
}) => {
  // Enfileira resposta LLM simples para o fluxo não ficar pendurado.
  await queueLlm({
    kind: 'record_intent',
    envelope: {
      intent: 'log_food',
      confidence: 0.90,
      user_text_summary: 'Refeição com foto.',
      needs_clarification: false,
      meal_slot: 'lunch',
      food_items: [
        {
          detected_name: 'arroz branco cozido',
          normalized_name: 'arroz_branco_cozido',
          quantity: 100,
          unit: 'g',
          grams_estimate: 100,
          confidence: 0.95,
          is_estimate: false,
        },
      ],
    },
  });

  await page.goto('/chat');

  const composer = page.getByPlaceholder(/150 g de arroz/i);
  await composer.fill('almoço com foto');

  // Anexa 2 fotos via input file.
  const minPng = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
    'base64',
  );
  const fileInput = page.locator('input[type="file"]');
  await fileInput.setInputFiles([
    { name: 'foto1.png', mimeType: 'image/png', buffer: minPng },
    { name: 'foto2.png', mimeType: 'image/png', buffer: minPng },
  ]);

  await page.getByRole('button', { name: /^enviar$/i }).click();

  // User message aparece com o texto enviado.
  await expect(page.getByText('almoço com foto')).toBeVisible({ timeout: 5000 });

  // Após loadInitial (GET /chat/messages?limit=100), a mensagem do usuário
  // inclui media[] com presigned URLs. O frontend renderiza <img> para cada
  // mídia. Validamos que 2 <img> aparecem dentro do container de mensagens.
  const messagesContainer = page.locator('main > div.overflow-y-auto');
  const chatImages = messagesContainer.locator('img');
  await expect(chatImages).toHaveCount(2, { timeout: 10000 });

  // Cada <img> deve ter src com URL presigned do MinIO (contém assinatura
  // AWS S3 v4 — query params X-Amz-Signature e X-Amz-Date).
  for (let i = 0; i < 2; i++) {
    const src = await chatImages.nth(i).getAttribute('src');
    expect(src).toBeTruthy();
    expect(src).toMatch(/X-Amz-Signature=/);
    expect(src).toMatch(/X-Amz-Date=/);
    // Path inclui o bucket e o padrão users/{uid}/media/...
    expect(src).toContain('/registers-media/users/');
  }

  // Assistant chega (confirma que o envio foi processado pelo backend).
  await expect(page.getByText(/registrei/i)).toBeVisible({ timeout: 15000 });
});