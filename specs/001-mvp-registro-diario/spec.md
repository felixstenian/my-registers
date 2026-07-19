# Feature Specification — MVP: Registro Diário por Chat com IA

**Feature ID:** 001-mvp-registro-diario
**Status:** In development (Fase 0 concluída, Fase 1 pendente)
**Owner:** Felix
**Constituição aplicável:** [`../../.specify/memory/constitution.md`](../../.specify/memory/constitution.md) v1.0.0
**Plano técnico:** [`plan.md`](plan.md) → [`../../app_plan.md`](../../app_plan.md)
**Tarefas:** [`tasks.md`](tasks.md)
**Decisões:** [`research.md`](research.md)

---

## Regras deste documento (spec-kit)

- Este arquivo descreve **o quê** e **por quê**, nunca **como** (implementação vive em `plan.md`).
- Cada requisito tem ID estável `SP-XX` — nunca renumerar; para deprecar, marcar `~~SP-XX~~ DEPRECATED (motivo)`.
- Cada `SP-XX` deve ter pelo menos um teste (unit, integration ou manual) rastreado em `tasks.md`.
- Palavras-chave (RFC 2119): **MUST**, **MUST NOT**, **SHOULD**, **MAY**.
- Critérios no formato Given / When / Then (Dado / Quando / Então).

Nesta spec, para o vocabulário do produto:
- `must` = bloqueia o MVP.
- `should` = importante mas negociável.
- `may` = fica para o pós-MVP.

---

## 1. Contexto e objetivo

**Problema.** Felix quer registrar sua alimentação, hidratação e atividade física por conversa natural (texto e foto), sem preencher formulário, e ver uma tabela consolidada de calorias, macros, micros básicos, água e outros líquidos atualizada a cada interação. Ao fim do dia e da semana, quer um resumo textual.

**Por que agora.** Ferramentas atuais (MyFitnessPal, FatSecret) exigem entrada manual estruturada. Modelos multimodais da Anthropic tornam viável interpretar prato + descrição + rótulo de embalagem em linguagem natural — mas confiar totalmente na LLM para cálculos e memória é frágil (Constituição, Artigos I e II).

**Resultado observável do MVP.** Uma web app privada em `https://<domínio>` onde Felix loga, conversa com o assistente, encerra dias e recebe relatórios diários e semanais. Nenhum outro usuário. Rodando em VPS única.

---

## 2. Personas e escopo

### 2.1 Persona P1 — Felix (usuário único)
Uso pessoal diário. Fluente em pt-BR, familiar com macros e treino. Acessa em desktop e mobile.

### 2.2 Cenário-âncora
1. Manhã: loga, registra o café-da-manhã por texto e foto de iogurte com rótulo. Sistema cadastra o produto (`nutrient_facts` com `source='label_ocr'`) e registra o consumo.
2. Ao longo do dia: 3-6 mensagens sobre refeições, água, café.
3. Pós-treino: "Corri 40 min moderado".
4. Fim do dia: "Encerrar dia" → recebe tabela + narrativa.
5. Domingo à noite: "Resumo semanal" → visão dos 7 dias fechados.

---

## 3. Requisitos funcionais

### 3.1 Autenticação e sessão

**SP-01** (`must`) — Login com email e senha.
- **Given** o admin foi criado via bootstrap (Constituição §24)
- **When** `POST /auth/login` com credenciais corretas
- **Then** resposta 204 + cookies `access_token` (JWT 15min) e `refresh_token` (opaco 14d), ambos `HttpOnly; SameSite=Lax`.
- UI redireciona para `/chat`.

**SP-02** (`must`) — Falha de login e brute force.
- Credenciais inválidas → 401 `{code: "invalid_credentials"}`, indistinguível entre "email inexistente" e "senha errada".
- 10 falhas no mesmo email em 15 min → 429 por até 15 min, mesmo com senha correta.
- 5 tentativas/min por IP → 429 independente do email.

**SP-03** (`must`) — Rotação de refresh (Constituição §17).
- Cada `POST /auth/refresh` revoga o anterior e emite novo par.
- Reuso de refresh revogado → invalida família inteira → força novo login.

**SP-04** (`must`) — Logout.
- `POST /auth/logout` → revoga refresh, limpa cookies (Max-Age=0), 204.

**SP-05** (`must`) — Ausência de cadastro e reset (Constituição §18).
- `POST /auth/register`, `POST /auth/forgot-password`, `POST /auth/reset-password` **MUST NOT** existir. Retornam 404 sem hint.

**SP-06** (`must`) — Proteção de rotas.
- Qualquer request sem `access_token` válido (exceto `/auth/login`, `/health`) → 401 JSON. UI redireciona para `/login`.

### 3.2 Chat

**SP-10** (`must`) — Envio de mensagem só com texto.
- `POST /chat/messages` com `{text}` → 202 `{message_id, status: "processing"}`.
- Em até 30s, mensagem `role="assistant"` disponível via `GET /chat/messages?after=<id>`.

**SP-11** (`must`) — Mensagem com fotos.
- 1 a 4 fotos por mensagem via `POST /media` (multipart, ≤ 8MB cada) → `media_id`.
- `POST /chat/messages` com `{text?, media_ids: [...]}` associa mídia à mensagem.

**SP-12** (`must`) — Histórico persistente.
- Todas as mensagens ficam em `messages` para sempre. Correção/exclusão de registros **não** apaga mensagens.
- `GET /chat/messages?limit=50&before=<id>` pagina cronologicamente.

**SP-13** (`must`) — Mensagem ambígua.
- Given "hoje foi puxado" (sem info registrável)
- Then assistente pede esclarecimento; **nenhum** registro é criado.

**SP-14** (`must`) — Timeout ou erro da LLM.
- >60s ou erro após 2 retries → assistente responde "Não consegui interpretar; pode reformular?" e grava `messages.raw_llm_response.error`. **Nada** persistido.

### 3.3 Registro de alimentos

**SP-20** (`must`) — Texto com quantidades explícitas.
- "150 g de arroz, 90 g de feijão, 180 g de frango" → 1 `food_records` + 3 `food_items`, macros resolvidos via catálogo, snapshot recalculado.

**SP-21** (`must`) — Unidade doméstica.
- "Uma concha de feijão" → `unit='concha'`, `grams` estimado, `is_estimate=true`, `confidence ≤ 0.7`. UI destaca visualmente.

**SP-22** (`must`) — Foto de prato sem texto ou com texto genérico.
- Foto + "meu almoço" → cada alimento visível vira `food_items` com `is_estimate=true`, `confidence ≤ 0.7`. Assistente lista + pede confirmação.

**SP-23** (`must`) — Alimento não encontrado no catálogo.
- `catalog_ref_id=null`, macros zerados, `warnings: {code: "no_catalog_hit"}`. Assistente pergunta valores por 100g **ou** marca.

**SP-24** (`must`) — Confiança baixa.
- `confidence < 0.5` → `needs_confirmation=true`, destaque na tabela, aguarda confirmação por chat ou `PATCH /records/food-items/{id}`.
- **Chat-side (SP-24a):** "confirmo", "sim", "está certo" → `intent=confirm_items` com `confirmation.scope='all'`. "Confirma o pão", "o queijo prato tá certo" → `scope='specific'` com `target_hints=[...]` casados via `TargetMatcher`. Sem itens pendentes → clarify ("não achei item pendente"). Confirmação NÃO recomputa snapshot (macros não mudam); apenas remove `needs_confirmation` e registra `audit_events(action='confirm')`. Dia fechado bloqueia (INV-5).

**SP-25** (`should`) — Múltiplas fotos.
- Até 4 fotos em uma mensagem, agrupadas em 1 `food_records` (não separa refeições distintas no MVP).

**SP-26** (`should`) — Refeição não classificada.
- `meal_slot` indefinido → `unspecified`. Não bloqueia.

### 3.4 Leitura de tabela nutricional (rótulo)

**SP-30** (`must`) — Cadastro de produto por foto do rótulo.
- Foto do rótulo sem menção a consumo → nova linha em `nutrient_facts` com `source='label_ocr'`, `label_media_id`, `verified_by_user=false`. **Nenhum** `food_records`.
- Assistente exibe cartão de confirmação com valores por 100g/100ml.

**SP-31** (`must`) — Cadastro + consumo.
- Foto do rótulo + "comi um pote (170g)" → cria `nutrient_facts` **e** `food_records`/`food_items` referenciando via `catalog_ref_id`.

**SP-32** (`must`) — `basis='per_serving'` sem tamanho.
- Rótulo com `per_serving` sem `serving_size_g`/`serving_size_ml` → **não** persiste; assistente pergunta o tamanho da porção.

**SP-33** (`must`) — Confirmação do usuário.
- `PATCH /nutrient-facts/{id}` aceita ajuste dos valores; seta `verified_by_user=true`.

**SP-34** (`must`) — Micros ausentes.
- Cálcio/ferro/potássio geralmente `null` em rótulos brasileiros (RDC 429/2020). Backend grava `null` + `warnings: {code: "micros_missing_for_product"}` nos snapshots.

**SP-35** (`must`) — Precedência do catálogo.
- Ordem: (1) marca casada; (2) `TBCA_2023` > `label_ocr` > `manual`; (3) `verified_by_user=true` > `false`; (4) mais recente.

### 3.5 Registro de água pura

**SP-40** (`must`) — Volume.
- "500 ml de água", "um copo (250 ml)" → `water_records` com `volume_ml`, `kcal=0`, sem macros.

**SP-41** (`must`) — Anti-dupla-contagem (Constituição Art. IV §14).
- "Água com limão" só entra em `log_water` se `kcal=0` confirmado. `IntentDispatcher` rejeita `log_water` com `kcal>0`.

**SP-42** (`should`) — Unidade estimada.
- "Um copo" → 250 ml estimado; "uma garrafinha" → 500 ml. `is_estimate=true`.

### 3.6 Registro de outros líquidos (bebidas calóricas)

**SP-50** (`must`) — Café, leite, suco, refrigerante, chá adoçado, álcool.
- `beverage_records` com `volume_ml`, macros do catálogo ou estimativa. Total soma em `other_liquids_ml` e `kcal_in`.

**SP-51** (`must`) — Anti-dupla-contagem (Constituição Art. IV).
- Bebida calórica **nunca** contribui para `water_ml`. Água pura **nunca** para `other_liquids_ml`.

**SP-52** (`must`) — Bebida sem catálogo.
- Igual SP-23: cria com macros zerados, `warnings`, assistente pergunta.

### 3.7 Registro de atividade física

**SP-60** (`must`) — Cardio com duração.
- "Corri 40 min moderado" → `activity_records` com `activity_type='cardio_run'`, `duration_minutes=40`, `intensity='moderate'`.
- `kcal_burned = MET × weight_kg × (duration_minutes/60)`. `met_value` gravado; `calc_method='mets_body_weight'`.

**SP-61** (`must`) — Ausência de peso corporal.
- Se `users.weight_kg` for `null`, assistente pergunta antes de gravar. Nada persiste até `weight_kg` estar salvo.

**SP-62** (`should`) — Musculação sem intensidade.
- Default `intensity='moderate'`, `met_value=5.0`, `confidence=0.6`.

**SP-63** (`should`) — Distância sem duração.
- "Caminhei 4 km" → duração estimada por velocidade média (4,5-5,5 km/h). `is_estimate=true` na duração.

**SP-64** (`must`) — Auditabilidade do cálculo.
- `met_value`, `weight_kg` no momento (via cópia em `calc_method`) e fórmula ficam em `activity_records` para recomputo futuro.

### 3.8 Correção de registros

**SP-70** (`must`) — Correção não ambígua.
- "Corrija o frango para 220g" com único item de frango no dia → atualiza `quantity`/`grams`, recalcula macros, recomputa dia, grava `audit_events`.

**SP-71** (`must`) — Correção ambígua.
- Dois "frangos" no dia sem qualificador → **nada** é alterado. Assistente pede desambiguação por horário/refeição.

**SP-72** (`must`) — Correção qualificada.
- "O frango do almoço era 220g" → matching por `normalized_name` + `meal_slot='lunch'`.

**SP-73** (`must`) — Dia encerrado é imutável (Constituição §28).
- Correção em dia `closed` → 409. Assistente sugere criar novo registro no dia atual.

**SP-74** (`must`) — Trilha de auditoria (Constituição §11).
- Toda correção grava `audit_events` com `before`/`after`/`actor`/`message_id`.

### 3.9 Remoção de registros

**SP-80** (`must`) — Remoção via chat.
- "Remova o refrigerante do almoço" → `deleted_at=now()` (soft delete). Snapshot recomputa excluindo `deleted_at IS NOT NULL`.

**SP-81** (`must`) — Remoção via UI.
- `DELETE /records/{tipo}/{id}` idempotente (segunda chamada = 200 sem efeito).

**SP-82** (`must`) — Dia encerrado.
- Igual SP-73: 409.

### 3.10 Consulta do dia

**SP-90** (`must`) — Snapshot do dia atual.
- `GET /days/today` retorna: `{date, status, totals, records, warnings}`.
- `totals` = kcal_in, kcal_out, kcal_balance, protein_g, carbs_g, fat_g, fiber_g, sodium_mg, calcium_mg, iron_mg, potassium_mg, water_ml, other_liquids_ml.

**SP-91** (`must`) — Snapshot de dia passado.
- `GET /days/{yyyy-mm-dd}` → mesmo shape. Se não existe: 404. Se aberto: `status='open'`.

**SP-92** (`must`) — Fuso horário.
- "Dia" = `users.timezone`. Mensagem enviada 23:30 local em 12/jul pertence a `log_date=2026-07-12` mesmo com UTC em 13/jul.

### 3.11 Encerramento do dia

**SP-100** (`must`) — Fechamento por chat.
- "Encerrar dia" → intent `close_day` → `POST /days/{today}/close` internamente.

**SP-101** (`must`) — Idempotência (Constituição §29).
- Já fechado → 200 com snapshot atual, sem regravar `closed_at`.

**SP-102** (`must`) — Recomputo garantido (Constituição §10).
- Ao fechar, recompute completo a partir das tabelas cruas. Warnings agregam itens sem catálogo.

**SP-103** (`must`) — Resposta.
- `GET /days/{date}` shape + `narrative` ~150 palavras gerada pela LLM sobre totais **já calculados**.

**SP-104** (`must`) — Aviso legal (Constituição §26).
- `narrative` sempre termina com o disclaimer.

### 3.12 Relatório semanal

**SP-110** (`must`) — Janela = últimos 7 dias encerrados (Constituição §30).
- `GET /weekly` → 7 `day_logs` mais recentes com `status='closed'`. Ignora dias abertos.
- Menos de 7 dias fechados → retorna disponíveis + `warnings: {code: "insufficient_history", days_available: N}`.

**SP-111** (`must`) — Cálculos determinísticos (Constituição §5).
- Totais e médias vêm de agregação SQL sobre `daily_snapshots`. LLM apenas narrativa.

**SP-112** (`should`) — Idempotência.
- Chamadas repetidas sem mudanças → mesmo `weekly_reports.id`.

**SP-113** (`should`) — Ordenação.
- `per_day` do mais antigo para o mais recente.

---

## 4. Requisitos não-funcionais

### 4.1 Segurança
Ver Constituição, Artigo V. `must`.

### 4.2 Performance
- **P50** de resposta do assistente: ≤ 6s texto puro, ≤ 12s com uma foto. `should`.
- **P99**: ≤ 20s; acima → fallback SP-14.
- `GET /days/today` ≤ 200ms P95. `must`.
- Prompt caching Anthropic ativo. `should`.

### 4.3 Confiabilidade
- Single-VPS, sem HA (aceito). `must`.
- Restart `unless-stopped`. `must`.
- Backup Postgres diário, retenção 14d. Backup MinIO diário. `must`.
- Health check externo a cada 5min (`healthchecks.io` ou similar). `should`.

### 4.4 Privacidade
- Fotos → apenas Anthropic (via base64, não URL). `must`.
- Disclaimer obrigatório (Constituição §26). `must`.

### 4.5 Acessibilidade e i18n
- UI em pt-BR. `must`.
- Contraste WCAG AA. `should`.
- Navegação por teclado no chat. `should`.

---

## 5. Interfaces observáveis

Definições **contratuais** — o `plan.md` mapeia estas para endpoints/schema.

### 5.1 Modelos de dados observáveis (via API)

- **Message.** `{id, role: "user"|"assistant", content, media: [{id, url_thumb}], llm_intent?, llm_confidence?, created_at}`.
- **Day.** `{date, status: "open"|"closed", totals, records, warnings, narrative?}`.
- **FoodItem.** `{id, detected_name, brand?, quantity, unit, grams?, ml?, source, confidence, is_estimate, needs_confirmation, kcal, protein_g, carbs_g, fat_g, fiber_g, sodium_mg, calcium_mg, iron_mg, potassium_mg}`.
- **WaterRecord.** `{id, volume_ml, occurred_at}`.
- **BeverageRecord.** `{id, detected_name, brand?, volume_ml, kcal, macros, micros}`.
- **ActivityRecord.** `{id, detected_name, activity_type, duration_minutes, distance_km?, intensity, kcal_burned, met_value, confidence}`.
- **NutrientFact.** `{id, canonical_name, brand?, basis, kcal, macros, micros, source, verified_by_user, label_media_id?}`.
- **WeeklyReport.** `{window_start, window_end, per_day: [DaySummary], totals, averages, narrative}`.

### 5.2 Códigos de erro estáveis

- `invalid_credentials`, `unauthorized`, `forbidden`, `not_found`, `validation_error`, `rate_limited`, `conflict_closed_day`, `no_catalog_hit`, `insufficient_history`, `micros_missing_for_product`, `low_confidence_item`, `ambiguous_correction_target`, `weight_kg_required`.

---

## 6. Invariantes

Espelham os artigos I-IX da Constituição. Cada um tem teste automatizado obrigatório.

- **INV-1** — Cálculos nutricionais são independentes da LLM (Const. §5).
- **INV-2** — Água pura não contribui para macros/kcal (Const. §12).
- **INV-3** — Bebida calórica não contribui para `water_ml` (Const. §12–14).
- **INV-4** — Recompute sempre from-scratch (Const. §10).
- **INV-5** — Dia fechado é imutável (Const. §28).
- **INV-6** — Reuso de refresh revoga família (Const. §17).
- **INV-7** — Senhas nunca vazam em logs/respostas (Const. §19).
- **INV-8** — `weekly_reports` só considera dias fechados (Const. §30).
- **INV-9** — LLM só via `tool_use` (Const. §7).
- **INV-10** — Toda mutação grava `audit_events` (Const. §11).

---

## 7. Fora do escopo

Registrado aqui para não voltar como dúvida durante execução.

- Cadastro público.
- Recuperação/reset de senha por HTTP (só CLI).
- Reabertura de dias encerrados.
- Multi-usuário, RBAC.
- Notificações (push/e-mail/Telegram).
- Metas de kcal/macros e avaliações qualitativas.
- Integração com wearables, Apple Health, Google Fit.
- Exportação CSV/PDF.
- App nativo, PWA offline.
- Streaming SSE.
- Sugestões dietéticas.
- Persistência agregada de `sugars_g`, `added_sugars_g`, `saturated_fat_g`, `trans_fat_g`.
- Leitura de código de barras (campo `barcode` fica pré-preparado).

---

## 8. Glossário

- **Dia (log day)** — data local do usuário (`users.timezone`).
- **Snapshot** — cache materializado dos totais em `daily_snapshots`.
- **Recompute** — reconstrução do snapshot a partir das tabelas cruas.
- **Encerramento** — fechar o dia; torna-o imutável.
- **Semana** — últimos 7 dias com `status='closed'` (SP-110).
- **Estimativa** — item com `is_estimate=true`.
- **Confiança** — `confidence ∈ [0,1]` da LLM.
- **Catálogo** — tabela `nutrient_facts`.
- **Rótulo (label_ocr)** — entrada de `nutrient_facts` criada por foto de tabela nutricional.
- **Assistente** — mensagem de `role='assistant'`; `narrative` gerada pela LLM sobre dados calculados.
- **Intent** — classificação da mensagem pela LLM (`log_food`, `log_water`, `log_beverage`, `log_activity`, `log_nutrition_label`, `correct_record`, `delete_record`, `query_day`, `close_day`, `weekly_summary`, `clarify`, `unknown`).

---

## Histórico de alterações

- **2026-07-15** — v1.0. Spec inicial extraída de `docs/specs.md`; alinhada com `constitution.md` v1.0.0 e `app_plan.md` 20 seções.
- **2026-07-19** — v1.5. SP-24 detalha chat-side (SP-24a): intent `confirm_items` com scopes `all`/`specific`. Sem novo SP-ID — é implementação faltante do SP-24 original que já previa "aguarda confirmação por chat".
