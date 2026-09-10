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

**SP-180** (`must`) — Carga inicial do chat restrita ao dia corrente.
- **Given** o usuário abre (ou recarrega) `/chat` sem cursor de paginação.
- **When** `GET /chat/messages?limit=100` (sem `after` nem `before`).
- **Then** a resposta devolve apenas as mensagens cujo `created_at` pertence ao **dia local corrente** do usuário (`users.timezone`, convertido para UTC no servidor), da mais antiga para a mais recente, limitada ao `limit`.
- A resposta inclui `has_more_before=true` quando existem mensagens mais antigas que a janela devolvida (dia corrente truncado por `limit`, ou dias anteriores).

**SP-181** (`must`) — Paginação para trás (scroll para o topo do chat).
- **Given** a última resposta devolveu `has_more_before=true`.
- **When** o usuário rola o chat até o topo.
- **Then** o cliente chama `GET /chat/messages?before=<id_mais_antigo>&limit=50`, **sem** filtro de dia (atravessa dias anteriores), e **prepende** o resultado mantendo a posição de scroll.
- A resposta devolve as mensagens imediatamente anteriores à âncora, da mais antiga para a mais recente, e `has_more_before=false` quando o histórico terminou — o cliente para de buscar.

**SP-13** (`must`) — Mensagem ambígua.
- Given "hoje foi puxado" (sem info registrável)
- Then assistente pede esclarecimento; **nenhum** registro é criado.

**SP-14** (`must`) — Timeout ou erro da LLM.
- >60s ou erro após 2 retries → assistente responde "Não consegui interpretar; pode reformular?" e grava `messages.raw_llm_response.error`. **Nada** persistido.

**SP-15** (`may`) — Envio por tecla Enter.
- **Given** o usuário está com foco na textarea do chat.
- **When** aperta `Enter` sem `Shift`.
- **Then** a mensagem é enviada — mesmo caminho do clique em "Enviar" (SP-10/SP-11).
- `Shift+Enter` **MUST** inserir quebra de linha em vez de enviar.
- Textarea vazia e sem mídia anexada → a tecla é ignorada (sem envio, sem erro).
- Enquanto uma requisição de envio anterior está em curso, a tecla é ignorada para evitar duplo envio.

**SP-16** (`may`) — Captura direta pela câmera em mobile.
- **Given** o usuário acessa `/chat` em um dispositivo com câmera (celular ou tablet).
- **When** aciona o seletor de arquivos para anexar imagem.
- **Then** o sistema operacional oferece "Tirar foto" além de "Escolher da galeria" — habilitado via atributo `capture="environment"` no `<input type="file">` (câmera traseira preferida por padrão para foto de prato/rótulo).
- Em desktop, o comportamento continua sendo o seletor de arquivo padrão (o `capture` é ignorado pelo navegador). Nenhuma requisição de permissão é feita se o usuário não abrir o seletor.
- A imagem capturada segue o mesmo fluxo do SP-11 (validação de MIME/tamanho, decode probe, MinIO).

**SP-17** (`may`) — Limite client-side de 4 imagens por mensagem, com feedback por nome de arquivo.
- **Given** o usuário seleciona (ou solta) N arquivos no seletor/dropzone do chat.
- **When** N > 4.
- **Then** a UI **MUST** aceitar apenas os 4 primeiros (por ordem de seleção) **e** exibir uma mensagem listando o **nome de cada arquivo rejeitado** com o motivo (ex.: *"5 arquivos selecionados. `foto5.png` não foi anexada — limite de 4 por mensagem."*).
- Se por algum motivo (ex.: bypass programático) mais de 4 `media_ids` chegarem no `POST /chat/messages`, o backend continua rejeitando com 422 (comportamento atual do SP-11); a UI **MUST** exibir na mensagem de erro o nome de cada arquivo excedente com base no cálculo local (não depende do backend nomear).
- A contagem inclui arquivos já pré-anexados em uma mensagem ainda não enviada (o usuário não consegue passar de 4 anexos no compositor).

**SP-18** (`may`) — Mensagens de erro amigáveis para rejeições de upload de mídia.
- **Given** o usuário anexa um arquivo que o backend rejeita em `POST /media`.
- **When** o erro é `file_too_large` (> 8MB, SP-11) **ou** `invalid_image` (decode probe falha, Const. §22) **ou** `unsupported_media_type`.
- **Then** a UI **MUST** exibir uma mensagem contextual em pt-BR **citando o nome do arquivo** e o motivo em linguagem natural. Exemplos:
  - `file_too_large` → *"`selfie_grande.jpg` é maior que 8 MB e não pode ser enviada. Reduza a qualidade ou tire outra."*
  - `invalid_image` → *"`documento.png` não parece ser uma imagem válida."*
  - `unsupported_media_type` → *"Formato de `arquivo.gif` não suportado. Envie JPEG, PNG ou WEBP."*
- Cada arquivo rejeitado gera uma linha própria na mensagem de erro; envios em lote não são abortados por falha de um único arquivo (os demais válidos são anexados normalmente).
- O compositor não fecha nem perde o texto digitado ao mostrar o erro.

**SP-19** (`may`) — Drag-and-drop na área de anexo do chat.
- **Given** o usuário arrasta um ou mais arquivos sobre o compositor do chat.
- **When** solta os arquivos.
- **Then** a UI **MUST** adicioná-los ao anexo da mensagem em preparo, aplicando as mesmas regras do input file (allowlist de MIME, SP-17 para o cap de 4, SP-18 para erros).
- **MUST** haver feedback visual enquanto o arquivo é arrastado por cima da área (ex.: borda tracejada, mudança de cor de fundo). Ao sair ou soltar, o feedback é removido.
- Se algum arquivo arrastado for de um tipo não suportado, a UI aplica a mesma mensagem do SP-18.
- Em desktop, drag-and-drop convive com o botão de seleção; em mobile, o comportamento padrão do sistema (touch) prevalece — o drop é opcional e não obrigatório.

**SP-115** (`may`) — Balão de `log_food` com cards estruturados no chat.
- **Given** `intent=log_food` foi processado com sucesso (SP-20) e a assistant message correspondente vai renderizar.
- **Then** o balão **MUST NOT** ser apenas texto corrido; deve renderizar cada `food_items` como um **card estruturado**, com:
  - Nome do alimento em destaque tipográfico.
  - Quantidade formatada (`150g` / `250ml` / `1 concha`).
  - Kcal + macros em linha compacta (`186 kcal · P 4.6g · C 38.7g · G 1.5g · Fibra 2.4g`).
  - Badges/ícones para `is_estimate=true` e `needs_confirmation=true` — visualmente distintos entre si (a estimativa é "quantidade aproximada", a confirmação é "precisa de sua validação").
- Um "footer" do balão **MUST** exibir os totais do dia (kcal_in + macros agregados) tipograficamente separado dos itens individuais.
- O aviso legal (Const. Art. VII §26) continua ao final do balão, em fonte reduzida mas ainda legível (não pode virar tooltip).
- Em telas pequenas, os cards podem virar linhas verticais empilhadas; a distinção item vs total precisa se manter.

**SP-116** (`may`) — Barra fixa de totais do dia na página do chat.
- **Given** o usuário está autenticado em `/chat`.
- **Then** um componente fixo (abaixo do header, acima da lista de mensagens) **MUST** exibir sempre:
  - `kcal_in` acumulado do dia, com destaque tipográfico.
  - Macros agregados (P/C/G/fibra em g).
  - `water_ml` e `other_liquids_ml` (a partir da Fase 5).
  - Contador de warnings do snapshot (ex.: "2 itens precisam de confirmação") clicável — abre painel/modal com a lista.
- Consulta `GET /days/today` (SP-90) no primeiro render e **MUST** revalidar sempre que uma assistant message nova for detectada pelo polling do chat (mesmo signal já usado).
- Em telas pequenas (mobile), colapsa em uma única linha rolável horizontalmente, mantendo `kcal_in` sempre visível.
- Se ainda não houver registros no dia, exibe estado vazio explicativo (ex.: "Nenhum registro hoje — mande sua primeira mensagem").

**SP-117** (`may`) — Highlight e confirmação inline de itens pendentes.
- Estende SP-24 (que já pede "destaque na tabela" para `needs_confirmation=true`) fixando **como** o destaque acontece e **o fluxo de confirmação**.
- **Given** um `food_items` tem `needs_confirmation=true` (por SP-24 confidence baixa ou SP-23 sem catálogo).
- **Then** na barra de totais (SP-116) e no card do chat (SP-115), o item **MUST** aparecer visualmente marcado (ex.: borda amarela + ícone ⚠️ padronizado com o resto da UI).
- **When** o usuário clica em "Confirmar" no card do item.
- **Then** abre um modal com os campos editáveis pré-preenchidos (`grams`, `kcal`, macros principais, `catalog_ref_id` se identificável). Ao submeter, dispara `PATCH /records/food-items/{id}` (endpoint da Fase 6, spec §3.8 correção). Ao sucesso, o snapshot é recomputado no backend (INV-4) e a UI revalida a barra de totais.
- Se o usuário fechar o modal sem submeter, o item permanece com o destaque até ele confirmar ou descartar.
- Botão adicional "Descartar" no modal dispara `DELETE /records/food-items/{id}` (soft delete, SP-80/SP-81).

**SP-118** (`may`) — Formato tabular padronizado da assistant message após qualquer registro.
- Substitui o texto solto atual dos `_compose_*_summary` do `MessageProcessor` por **duas tabelas** dirigidas ao usuário.
- **Given** qualquer intent de registro (`log_food`, `log_water`, `log_beverage`, `log_activity`) foi processado com sucesso.
- **Then** a assistant message **MUST** conter, nesta ordem:
  1. **Cabeçalho curto** identificando o que foi registrado (ex.: "Registrei o almoço.", "Registrei 500 ml de água.", "Registrei 40 min de corrida.").
  2. **Tabela "Total da refeição/registro"** com título contextual em pt-BR:
     - `log_food` → *"Total da refeição — {meal_slot_pt_br}"* (Café da manhã / Almoço / Lanche / Jantar / Refeição). **MUST** conter as linhas `Calorias`, `Proteínas`, `Carboidratos`, `Gorduras`, `Fibras` somadas apenas dos `food_items` recém-criados nesta mensagem.
     - `log_beverage` → *"Total da bebida — {detected_name}"*. Mesmas 5 linhas nutricionais + linha `Volume` (ml).
     - `log_water` → *"Total do registro"* com uma única linha `Água` = X ml (sem macros — INV-2 estrutural).
     - `log_activity` → *"Total do exercício — {detected_name}"* com linhas `Duração` (min) e `Calorias gastas` (kcal).
  3. **Tabela "Total acumulado — {DD/MM/YYYY}"** com a data local do usuário no cabeçalho e **MUST** conter, nesta ordem:
     - `Calorias Consumidas` (kcal_in do snapshot)
     - `Calorias Gastas` (kcal_out — só aparece se > 0)
     - `Saldo Calórico` (kcal_balance — só aparece se `kcal_out > 0`)
     - `Proteínas` / `Carboidratos` / `Gorduras` / `Fibras` (g)
     - `Água Pura` (ml, do `water_ml`)
     - `Líquidos Totais` (ml, `water_ml + other_liquids_ml`) — asterisco no rótulo (`*`) se `other_liquids_ml > 0`, com nota abaixo da tabela: *"* inclui café, leite, sucos e outras bebidas calóricas."*
- **Formatação e conteúdo:**
  - Tabelas em **markdown** (renderizáveis pela UI do chat) com colunas `Nutriente|Indicador` × `Total`.
  - Números com separador decimal **vírgula** e milhar **ponto** (pt-BR): `≈ 977 kcal`, `≈ 1.200 ml`.
  - Prefixo `≈` (aproximadamente) **MUST** aparecer em qualquer linha nutricional cuja origem tenha pelo menos 1 item com `is_estimate=true` ou `needs_confirmation=true`. Se todos os itens têm quantidade exata + catálogo, o `≈` **MUST NOT** aparecer.
  - Água pura e volume nunca recebem `≈` (são medidas diretas).
  - Aviso legal (Const. Art. VII §26) continua ao final, separado por linha em branco.
- **Warnings de itens sem catálogo** (`no_catalog_hit`) aparecem em card estruturado (SP-140, revisão 2026-07-28) com botões clicáveis por item. Warning `needs_confirmation` deprecated junto com o fluxo de confirmação (ver SP-24).
- Este SP substitui o formato livre gerado hoje pelos `_compose_meal_summary` / `_compose_water_summary` / `_compose_beverage_summary` / `_compose_activity_summary` em `services/message_processor.py`.

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
- `confidence < 0.5` → item marcado como estimativa (`is_estimate=true`) para o prefixo `≈` no display. Correção continua via chat (`corrija X 100g`) ou `PATCH /records/food-items/{id}`.
- ~~**Chat-side (SP-24a):**~~ **DEPRECATED em 2026-07-28 (v1.11)** — intent `confirm_items` + `ConfirmationService` + fluxo "confirmo esses itens" removidos junto com toda a UX de confirmação. Ver §3.14 (revisão) para o motivador. Item sem catálogo agora tem 3 botões diretos no card (Cadastrar manual, Foto do rótulo, Descartar) — não precisa mais "confirmar".

> **Nota histórica sobre `needs_confirmation`.** O campo permanece no schema (evita migration destrutiva) mas nunca mais é setado como `true`. `MealService.create_from_llm` e `BeverageService.create_from_llm` não usam mais o campo pra sinalizar "pendente". O sinal de "item sem catálogo" no frontend passou a ser `has_catalog=false` (derivado de `catalog_ref_id IS NULL`).

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

### 3.13 Registro estruturado de treino (pós-MVP)

**Não faz parte do MVP.** Toda esta seção está marcada `may` — implementação após Fase 9 concluída. Rastreia treinos de força de forma granular (sessão → exercícios → séries), coexistindo com o `log_activity` genérico.

> **Expansão de módulo (v1.13):** a seção **3.16** adiciona o módulo de treino como produto (templates, chat dedicado, `/workouts`, fluxo guiado, imagem, seção no `/day` — SP-170..SP-179) sobre este núcleo, que permanece inalterado. Invariantes de treino renumeradas: INV-11→INV-15, INV-12→INV-16, INV-13→INV-17.

**Modelo mental:** o usuário abre uma sessão de treino ("iniciando treino de push"), lista o exercício que vai fazer ("supino reto com barra") e reporta cada série ("20 kg da barra + 20 kg de cada lado × 10 reps"). Ao mandar outro nome de exercício, o anterior é implicitamente encerrado. Ao mandar "finalizar treino" ou encerrar o dia, a sessão inteira é consolidada em um `activity_record` com kcal totais estimados.

**Design de coexistência com `log_activity` (SP-60..SP-64):**
- Cardio genérico e atividades sem séries (corrida, natação, caminhada) continuam usando `log_activity` como hoje.
- Treinos de força/musculação usam este novo módulo. No encerramento da sessão, o backend **agrega** os dados estruturados em 1 `activity_record` (com `calc_method='workout_session'`, `activity_type='strength'`) — o snapshot diário e o relatório semanal enxergam como qualquer outra atividade. Ver ADR-004 em `research.md`.

**Estado conversacional:** a única fonte de "sessão ativa" e "exercício atual" é o banco (`workout_sessions.status='active'`, exercício mais recente da sessão). Nenhum estado em memória — o LLM não precisa "lembrar" do contexto entre mensagens; o backend consulta o DB a cada mensagem.

**SP-120** (`may`) — Início de sessão de treino.
- **Given** usuário sem `workout_sessions.status='active'`.
- **When** LLM detecta `intent=workout_start` (ex.: "iniciando treino de push", "vou treinar leg", "começando treino").
- **Then** cria `workout_sessions` com `started_at=now()`, `status='active'`, `workout_type` classificado pela LLM em enum canônico (`push`, `pull`, `legs`, `upper`, `lower`, `full_body`, `cardio`, `other`) e `detected_name` livre para o usuário.
- Se já existe sessão ativa, **encerra a anterior automaticamente** (INV-15) com `ended_at=now()`, `end_reason='auto_new_session'` — assistente avisa e mostra resumo curto.
- Backend responde com cabeçalho + "Nenhum exercício ainda — mande o nome do primeiro".

**SP-121** (`may`) — Adicionar exercício + histórico contextual.
- **Given** sessão ativa existente.
- **When** LLM detecta `intent=workout_add_exercise` com `exercise_name` extraído (ex.: "supino reto com barra", "agachamento livre 4x8", "leg press").
- **Then** cria `workout_exercises` ligado à sessão ativa, com `sequence_index` auto-incrementado. `normalized_name` para lookup histórico.
- Backend consulta histórico via `normalized_name` (fuzzy match; ex.: "supino reto" casa com "supino reto barra" e "supino reto halteres") e devolve na assistant message:
  - **Última sessão** que teve esse exercício: data + todas as séries no formato "peso × reps".
  - **PR pessoal** (Personal Record): maior peso registrado × maior número de reps naquele peso, com data.
  - Se nunca fez, mensagem neutra: "Primeira vez registrando esse exercício."
- Se a sessão ativa já tem outro exercício em andamento, ele é implicitamente considerado encerrado (não muda estado, só semântica — SP-123).

**SP-122** (`may`) — Registro de séries.
- **Given** sessão ativa com pelo menos um exercício.
- **When** LLM detecta `intent=workout_log_set` com payload contendo `weight_kg`, `reps` e opcionalmente `notes`.
- **Then** cria `workout_sets` ligado ao último exercício da sessão ativa (INV-16), com `sequence_index` auto-incrementado.
- Parser de peso em pt-BR (feito pela LLM, backend só valida `weight_kg > 0`):
  - "20 kg" → 20
  - "20 kg da barra + 20 kg de cada lado" → 20 + 2×20 = 60
  - "60 kg" → 60
  - "só a barra" → 20 (default olympic bar; se ambíguo, LLM confirma)
- Parser de reps:
  - "10 reps" / "10 repetições" / "10x" → 10
  - Múltiplas séries em uma mensagem: "3×8 60 kg" → cria 3 sets iguais.
- Se `weight_kg` ou `reps` estiver ambíguo, LLM emite `clarify` — nenhum set é criado.
- Resposta do assistant: "Série 3 registrada: 60 kg × 10 (última vez você fez 55 kg × 10)".

**SP-123** (`may`) — Encerramento implícito de exercício.
- **Given** sessão ativa com exercício A em andamento.
- **When** usuário adiciona novo exercício B (SP-121).
- **Then** A é considerado encerrado (nenhuma mudança de estado explícita — o simples fato de B existir e ter `sequence_index > A.sequence_index` estabelece isso). Séries subsequentes ligam-se ao B (SP-122).
- Nenhum `ended_at` no exercício — a sessão inteira que tem `started_at/ended_at`.

**SP-124** (`may`) — Encerramento explícito de sessão.
- **Given** sessão ativa.
- **When** LLM detecta `intent=workout_end` (ex.: "finalizar treino", "encerrar treino", "acabou o treino").
- **Then** marca `workout_sessions.status='ended'`, `ended_at=now()`, `end_reason='user'`. Dispara **SP-125** (consolidação em `activity_record`).
- Assistant devolve resumo: "Treino de push encerrado (58 min). 4 exercícios · 14 séries · ~380 kcal estimados." + tabela markdown com exercícios e séries totais por exercício.

**SP-125** (`may`) — Encerramento automático ao fechar dia.
- **Given** sessão ativa quando `intent=close_day` (SP-100) é processado.
- **Then** antes do recompute do snapshot, sessão é encerrada com `end_reason='auto_close_day'` e SP-125 (consolidação) roda.
- Isso garante que o `activity_record` gerado apareça no snapshot do dia que está sendo fechado.

**SP-126** (`may`) — Consolidação em `activity_record`.
- **Given** sessão sendo encerrada (SP-124 ou SP-125).
- **Then** backend calcula:
  - `duration_minutes = ended_at - started_at` (em minutos, sem contar pausas — MVP simples).
  - `kcal_burned` estimado via MET fixo por tipo de treino (`push/pull/upper` → 5.0 MET; `legs/lower` → 6.0; `full_body` → 5.5) × `weight_kg` (do perfil) × horas.
- Cria 1 `activity_record` com `activity_type='strength'`, `calc_method='workout_session'`, `met_value=<usado>`, `detected_name="Treino de {workout_type}"`, `notes=` JSON com IDs dos exercícios e séries.
- Se o usuário não tem `weight_kg` no perfil, `activity_record` é criado com `kcal_burned=NULL` e warning `weight_kg_required_for_kcal` — treino é registrado, kcal fica pendente.

**SP-127** (`may`) — Consulta de histórico via chat.
- **When** LLM detecta `intent=workout_history` com `exercise_name` (ex.: "qual peso fiz no supino reto?", "meu histórico de agachamento", "PR do deadlift").
- **Then** backend responde com as **últimas 3 sessões** que continham o exercício + **PR pessoal**, mesmo formato do SP-121 mas sem criar registro novo.
- Se `exercise_name` ausente, LLM emite `clarify` pedindo qual exercício.

**Invariantes adicionais:**
- **INV-15** — No máximo uma `workout_sessions` por usuário com `status='active'`. Adicionar nova sessão auto-encerra a anterior.
- **INV-16** — Todo `workout_sets` pertence ao **último** `workout_exercises` da sessão ativa (por `sequence_index`). Não existe "adicionar série ao exercício X que já não é o último".
- **INV-17** — `activity_record` gerado por SP-126 tem `calc_method='workout_session'` — nunca é criado manualmente por outro fluxo. Correção/deleção desse `activity_record` NÃO afeta os `workout_sessions/exercises/sets` associados (idem: apagar séries não apaga o `activity_record` já gerado; consistência é responsabilidade de recompute manual, fora do MVP).

**Dependências de dados:**
- Novas tabelas: `workout_sessions`, `workout_exercises`, `workout_sets`. Alembic migration nova.
- Estende `Intent` enum do `LLMEnvelope` com `workout_start`, `workout_add_exercise`, `workout_log_set`, `workout_end`, `workout_history`.
- Prompt `system_v2.md` ganha nova regra 19 explicando os 5 novos intents.
- Reutiliza `MessageProcessor` + `IntentDispatcher` — cada intent vira um novo `_handle_workout_*` handler.

---

### 3.13 Progressive Web App (pós-MVP, escopo básico)

Feature de instalabilidade + shell offline. Não cobre fila offline (B-08), push (B-05) nem cache de dados de negócio.

**SP-128** (`must`) — Manifest publicado em `/manifest.webmanifest`.
- Campos obrigatórios: `name`, `short_name` (≤12 chars), `icons` (192, 512, maskable), `theme_color`, `background_color`, `display: standalone`, `start_url: /chat`, `scope: /`, `orientation: portrait`.
- MIME type correto (`application/manifest+json`) — Next.js já resolve via convenção de arquivo em `src/app/manifest.ts`.

**SP-129** (`must`) — Meta tags para instalação em iOS Safari.
- `apple-mobile-web-app-capable=yes`, `apple-mobile-web-app-status-bar-style=default`, `apple-mobile-web-app-title=my-registers`, `apple-touch-icon` 180×180.
- Sem essas tags, iOS Safari não trata a app como instalável em standalone.

**SP-130** (`must`) — Service worker com estratégia por rota.
- Shell estático (`/_next/static/*`, ícones, manifest, fonts): **cache-first** com revalidação em background.
- HTML de rotas (`/chat`, `/login`, `/weekly`): **network-first** com fallback pra cache offline.
- API (`/api/*`): **network-only, nunca cachear.** Ver `INV-11`.
- Registro no client após hidratação (não bloqueia render inicial).

**SP-131** (`must`) — Assets de ícone em 4 tamanhos mínimos.
- `192×192` (Android padrão), `512×512` (Android hi-res / splash), `180×180` (apple-touch), `512×512 maskable` (Android adaptativo).
- Formato PNG. Cor de fundo compatível com `background_color` do manifest.

**SP-132** (`should`) — Update flow visível.
- Quando SW detecta versão nova disponível (`updatefound` + `installed` state), exibir toast persistente "Nova versão disponível" com botão "Recarregar" que dispara `postMessage({type: 'SKIP_WAITING'})` seguido de `window.location.reload()`.
- Sem esse fluxo, usuário fica preso em versão antiga até fechar todas as abas.

**SP-133** (`should`) — Botão "Instalar" no header.
- Escuta `beforeinstallprompt` (Chrome/Edge Android+desktop), guarda evento, exibe botão que chama `.prompt()`.
- Oculto em navegadores sem o evento (Safari desktop/iOS — nesses, install é via "Adicionar à tela de início" do menu do browser).
- Após install (`appinstalled` event), botão some.

**SP-134** (`may`) — Splash iOS via `apple-touch-startup-image`.
- Set mínimo: iPhone SE/8, iPhone 15/16 Pro (3 sizes). iPad opcional.
- Sem isso, iOS mostra tela branca de ~500ms na abertura standalone.

**SP-135** (`must`) — Comportamento offline previsível.
- Rota carregada offline (sem cache do dia) exibe página `/offline` com mensagem: "Sem conexão. Algumas ações ficam indisponíveis até você reconectar." + link "Tentar novamente".
- Aviso legal (Constituição Art. VII §26) presente na `/offline`.

---

### 3.14 Recuperação de itens sem catálogo (pós-MVP)

Quando `catalog.lookup()` devolve `None` para um `food_item`, o item entra no diário com `kcal=0` e `catalog_ref_id=NULL` (Const. §5-6, INV-1). Sem intervenção, o item fica zerado no snapshot pra sempre. Esta seção dá ao usuário **três ações objetivas por item** direto na assistant message, todas como botões clicáveis.

**Decisão de escopo (revisão 2026-07-28):** o fluxo de "confirmação de item" (`PendingItemsModal`, `POST /records/food-items/{id}/confirm`, `ConfirmItemButton` no `/day`, intent LLM `confirm_items`, `ConfirmationService`) foi **removido**. Motivação: sobreposição semântica confusa — item sem catálogo NÃO precisa de "confirmação", precisa de ação (cadastrar valores OU descartar). O campo `needs_confirmation` permanece no schema (evita migration), mas o backend **nunca mais** o seta como `true` e o frontend ignora completamente.

**SP-140** (`should`) — Card de recuperação por item na assistant message.
- Quando `log_food` retorna warnings com `code='no_catalog_hit'`, o `message_formatter.compose_meal` anexa um marcador estruturado que o frontend transforma em card com **três botões por item afetado**:
  1. **✏️ Cadastrar manualmente** — abre `ManualCatalogForm` (modal). Ver SP-141.
  2. **📸 Cadastrar com foto do rótulo** — abre file picker; ao selecionar imagem, upload + envio automático de uma mensagem no chat com `promote_food_item_id={item.id}` associado. Ver SP-143.
  3. **❌ Descartar item** — dispara `DELETE /records/food-items/{item.id}` e re-renderiza. Sem confirmação extra.
- Cada botão opera **em um item específico** — usuário resolve um por vez.
- Não altera cálculo. Aviso legal (Art. VII §26) continua obrigatório na assistant message.

**SP-141** (`should`) — Endpoint de cadastro manual de `nutrient_facts`.
- `POST /nutrient-facts/manual` autenticado. Body:
  ```json
  {
    "canonical_name": "pao_de_queijo_congelado",
    "display_name": "Pão de queijo congelado",
    "brand": "Forno de Minas",   // opcional
    "basis": "per_100g",          // "per_100g" ou "per_100ml"
    "kcal": 320,
    "protein_g": 8,
    "carbs_g": 40,
    "fat_g": 14,
    "fiber_g": 0.5,              // demais macros/micros opcionais
    "sodium_mg": 380,
    "calcium_mg": null,
    "iron_mg": null,
    "potassium_mg": null,
    "aliases": ["pao de queijo", "pao_queijo"],  // opcional
    "promote_food_item_id": "uuid"               // opcional (SP-142)
  }
  ```
- Response 201 com o `nutrient_facts.id` criado.
- Persiste com `source='manual'`, `verified_by_user=true`, `created_by=user_id`.
- Validação: `basis ∈ {per_100g, per_100ml}`; `kcal ≥ 0`; `protein/carbs/fat ≥ 0`; `canonical_name` slug-like (`[a-z0-9_]+`).
- Isolamento: cada usuário tem seu próprio fact (Const. §21).

**SP-142** (`should`) — Promoção de `food_item` legado no cadastro manual.
- Se `POST /nutrient-facts/manual` incluir `promote_food_item_id`, o backend, na mesma transação:
  1. Cria o `nutrient_fact` (SP-141).
  2. Se o item pertence ao usuário e não está deletado e o dia não está fechado:
     - Atualiza `catalog_ref_id` pro novo fact.
     - Recalcula macros via `NutritionCalculator.compute(hit=new_fact, grams=item.grams, ml=item.ml)`.
     - Grava audit `action='correct'`, `actor='user'`, before/after.
     - Chama `DailyRecomputeService.recompute(item.food_record.day_log_id)` — snapshot reflete novo valor.
- Se qualquer validação falhar (item de outro user, deletado, dia fechado), endpoint retorna 201 do fact criado + `promotion_warning='promotion_failed:{motivo}'` no body (não faz rollback).

**SP-143** (`should`) — Cadastro por foto de rótulo com promoção acoplada.
- `POST /chat/messages` aceita novo campo opcional `promote_food_item_id: uuid`. Body existente + o campo novo:
  ```json
  { "text": "...", "media_ids": ["..."], "promote_food_item_id": "uuid" }
  ```
- Backend valida no momento do envio que `promote_food_item_id` pertence ao usuário (isolamento). Se inválido, ignora silenciosamente (não bloqueia o envio da mensagem).
- Processo normal: `MessageProcessor` roda LLM → se intent for `log_nutrition_label` (Fase 4.b) → `LabelCatalogService.upsert_from_label` cria/atualiza fact.
- **Novo passo**: depois do `upsert_from_label` retornar com sucesso, se `promote_food_item_id` foi passado E o item é válido (ownership + não deletado + dia aberto), backend faz a mesma promoção do SP-142 (atualiza `catalog_ref_id`, recomputa macros, recompute snapshot, audit).
- Se intent detectado ≠ `log_nutrition_label` (usuário mandou foto que não é rótulo), `promote_food_item_id` é ignorado e a mensagem segue o fluxo normal.
- Se a promoção falhar após o fact ter sido criado, backend grava audit_event `action='promotion_failed'` mas não bloqueia o fluxo de chat.

**Fora do escopo desta feature:**
- Migration removendo `needs_confirmation` do schema (adia; sem impacto porque backend nunca mais seta e frontend ignora).
- Formulário completo com micros (fica opcional; accordion).
- Delete de fact manual (adiar).
- Sugestão de cadastro automática por LLM (viola Const. §5).

**Removidos por esta revisão:**
- `PendingItemsModal.tsx` no chat.
- `POST /records/food-items/{id}/confirm` (endpoint deletado).
- `ConfirmItemButton.tsx` no `/day` (deletado).
- Intent LLM `confirm_items` no `system_v2.md` + tool_schema + dispatcher + `ConfirmationService`.
- Warning `needs_confirmation` no block do `message_formatter._warnings_block` (chamado "Confirma estes itens?"); substituído pelo card SP-140.
- Badges "confirmar" e ícones amarelos em `DayTotalsBar`, `FoodItemRow`, etc.
- SP-24a (SP-24 chat-side) fica marcada como deprecated na spec — implementação removida junto com o intent.

---

### 3.15 Visão detalhada do dia — página `/day` (pós-MVP)

**Motivador.** `DayTotalsBar` só mostra totais agregados; `/weekly` mostra 7 dias agregados. Nenhum lugar hoje mostra **item por item** do dia com macros/micros específicos — o usuário precisa confiar no total sem conseguir validar se cada alimento foi persistido com o valor esperado. Em prod isso ficou explícito no bug do catálogo vazio (item aparece com kcal=0 no total, mas usuário só descobre indiretamente). Uma página de detalhamento fecha esse loop de confiança.

Revive parcialmente a intenção do T-409 original ("DayTable renderiza totals + records"), que foi conscientemente deixado de fora do MVP. Não substitui `/weekly`; complementa.

**Escopo v1:** leitura. Ações (editar, deletar, corrigir) continuam via chat na v1 — mantém a interface de mutação única e simplifica esta feature.

**SP-150** (`should`) — Rota `/day` renderiza o dia atual (fuso do usuário — SP-92).
- Server component protegido. Fetch server-side de `GET /days/today` via `INTERNAL_API_URL` (padrão do PR #25 hotfix).
- Header: data formatada em pt-BR (`domingo, 27 de julho de 2026`), badge `status='open'|'closed'`, link "Encerrar dia" (dispara mesmo modal do `CloseDayModal` do chat) — só quando `status='open'`.
- Link "Semana" no header do `(app)/layout` ganha peer "Detalhes" apontando pra `/day`.

**SP-151** (`should`) — Refeições agrupadas por `meal_slot`.
- Seções na ordem: `breakfast` → `lunch` → `snack` → `dinner` → `unspecified`. Slots vazios não são renderizados.
- Cada seção tem: cabeçalho com nome pt-BR do slot + kcal parcial do slot. Lista de `food_items` como linhas de tabela.
- Colunas: **Item** (`detected_name` + brand em cinza se houver) · **Quantidade** (`{grams}g` ou `{ml}ml` ou `{quantity} {unit}`) · **Calorias** · **P** · **C** · **G** · **Fibras**.
- Badge amarelo "confirmar" quando `needs_confirmation=true` (link abre `PendingItemsModal` ou envia pra `/chat` — decisão de implementação).
- Badge "sem catálogo" quando `catalog_ref_id=null` — indica item que veio zerado do bug do seed vazio (recuperável via chat).

**SP-152** (`should`) — Detalhamento por item via expansão.
- Cada linha de food_item pode ser expandida (`<details>` ou click) revelando micros básicos: sódio (mg), cálcio (mg), ferro (mg), potássio (mg).
- Valores zero → renderiza `—` em vez de `0` (menos ruído visual).
- Também mostra `source` (`llm`, `user_corrected`, `label_ocr`, `user_manual`) e `confidence` (LLM) — útil pra saber a origem do valor.

**SP-153** (`should`) — Seções auxiliares: hidratação, bebidas, atividade.
- **Hidratação (água pura):** lista com horário + volume; totalizador `Água: N ml`.
- **Bebidas calóricas:** mesma tabela reduzida das refeições (item, volume, kcal + macros; sem micros — mais raro cadastrar).
- **Atividade:** linha por registro com tipo pt-BR, duração, intensidade, kcal gastas + método (`met_estimate`, `reported_by_device`, `workout_session` quando Bloco 3 chegar).

**SP-154** (`may`) — Rota `/day/[date]` para dias passados.
- Server component idêntico ao `/day`, com `GET /days/{date}` em vez de `/today`.
- 404 amigável se `day_log` não existe (nenhum registro naquele dia).
- Edição de records (correção/exclusão) continua exclusivamente via chat — a página `/day/[date]` não expõe botões de mutar item (evita confusão sobre "data efetiva" da correção).
- **Encerramento retroativo**: se o dia estiver `status='open'`, o botão "Encerrar dia" aparece igual ao `/day`. Caso comum: o usuário esqueceu de encerrar o dia anterior e quer resolver agora. `POST /days/{date}/close` funciona em qualquer data com `day_log` aberto (backend não restringe a "hoje").
- Fica `may` porque uso primário é o dia atual; historico via `/weekly` já cobre visão agregada.

**SP-155** (`should`) — Navegação temporal a partir do `/day` e do `/weekly`.
- Header do `/day` (e do `/day/[date]`) ganha três controles logo abaixo da data:
  - Botão **← Dia anterior** aponta pra `/day/[date-1]`. Sempre presente.
  - Botão **Próximo dia →** aponta pra `/day/[date+1]` **quando** `date+1 <= hoje`. Escondido no dia atual (não faz sentido "próximo" existir).
  - Botão **Hoje** aponta pra `/day` quando `date != hoje`. Escondido no dia atual.
  - Input HTML nativo `<input type="date">` com `max` no dia atual — submit navega pra `/day/[selecionada]`.
- Coluna **Dia** da tabela de `per_day` no `/weekly` vira link pra `/day/[date]` (para cada linha).
- Data no futuro (`date > hoje` no fuso do usuário) → renderiza mensagem amigável "Não é possível ver o futuro" + link "Voltar para hoje". Não chama backend.
- Datas anteriores ao primeiro `day_log` do usuário → cai no 404 amigável de SP-154 (não é caso especial).

**Fora do escopo desta feature:**
- Edição/deleção inline (v2 — hoje é via chat).
- Filtros/ordenação (só a ordem natural: meal_slot → occurred_at).
- Exportação CSV/PDF do dia (feature B-06 do backlog).
- Gráficos de distribuição de macros (v2+).
- Comparação com dias anteriores (v2+).

---

### 3.16 Módulo de treino — expansão do cliente (SP-170..SP-179)

**Estende §3.13** (núcleo de sessão estruturada, SP-120..SP-127, aceito e inalterado). O cliente refez o escopo de treino como **módulo de produto**: treinos reutilizáveis (`workout_templates`), chat de treino dedicado no **mesmo pool de `messages`** com filtro por `messages.via='workout'`, tela `/workouts` com abas Ativos/Inativos/Histórico, fluxo guiado de execução com cronômetro, registro por imagem e seção de treinos no `/day`. Tudo `pós-MVP` — implementação após Fase 9. As invariantes de treino foram renumeradas na v1.13 (INV-11→15, INV-12→16, INV-13→17) para liberar a faixa INV-18..21 abaixo.

**SP-170** (`must`) — Módulo `/workouts`.
- **Then** existe a rota `/workouts` protegida (em `PROTECTED_PREFIXES`/matcher do `proxy.ts`) com 3 abas: *Ativos*, *Inativos*, *Histórico*.
- Aba *Ativos* lista `workout_templates` com `active=true`; *Inativos* lista `active=false`; *Histórico* é o log de sessões finalizadas (SP-177).
- Navegação mobile (SP-NM) **não** ganha tab nova — acesso via link/CTA (decisão fixada nos trade-offs da feature).

**SP-171** (`must`) — Cadastro de treino reutilizável por texto.
- **Given** usuário no chat de treino.
- **When** clica em "Cadastrar treino".
- **Then** assistant envia mensagem amigável com **template de exemplo**: tipo (ex. `Musculação`/`Força`/`LPO`), agrupamento muscular para musculação (ex. `Peito + ombro + triceps`) e séries/repetições por exercício.
- **When** usuário envia o texto do treino.
- **Then** LLM lê (intent novo `workout_register_template`, payload `WorkoutTemplateIn`) e **cadastra** um novo `workout_templates` com `created_at` = data de cadastro, `active=true`, exercícios-alvo em `workout_template_exercises`.
- Ambiguidade (agrupamento/frequência) → `clarify`; nenhum template é criado até confirmar.

**SP-172** (`must`) — Status ativo/inativo de treino.
- **Given** `workout_templates` existente.
- **When** usuário inativa/reativa na listagem `/workouts` (PATCH `active`).
- **Then** `active` inverte; aba *Ativos*/*Inativos* refletem; sessões **já finalizadas** permanecem no histórico (INV-19). Audit gravado (INV-10).

**SP-173** (`must`) — Chat de treino dedicado.
- **Given** rota `/workouts/chat` protegida.
- **Then** reusa **exatamente** o padrão do chat de alimentação (composer + upload de mídia + polling `GET /chat/messages?after=` + `AssistantContent` + respostas pt-BR) no **mesmo pool de `messages`**: coluna nova `messages.via` (`'food'` default, `'workout'` para treino), `GET /chat/messages` e `MessageProcessor` filtram por `via`, prompt `system_v2.md` selecionado pela `via`. Migration `ALTER TABLE messages ADD COLUMN via TEXT NOT NULL DEFAULT 'food'` + índice `idx_messages_user_via ON messages(user_id, via, created_at)`.
- **Header** do chat de treino exibe as **atividades realizadas no dia + calorias gastas** (variante do `DayTotalsBar` com foco em atividades).
- **Then** no lugar do botão "Encerrar dia", dois botões: **"Cadastrar treino"** (→ SP-171) e **"Iniciar treino"** (→ SP-178). Com sessão ativa, o botão da direita vira **"Finalizar treino"** (mesma posição; conclui a sessão ativa). "Encerrar dia" continua disponível no chat de alimentação/modal.

**SP-174** (`must`) — Registro de treino por imagem.
- **Given** usuário envia imagem de atividade realizada no chat de treino.
- **Then** LLM extrai da imagem **título**, **atividade**, **intensidade** (se houver) e **calorias gastas durante a atividade** (se houver); sem imagem/título, extrai do texto. Cria sessão/registro estruturado com `kcal_burned_reported` quando o valor veio na imagem/texto (INV-21); senão kcal estimada via MET no encerramento (SP-126). Imagem trafega por `POST /media` e segue as regras de CSP/media de `docs/deploy.md`.

**SP-175** (`must`) — Edição de peso, séries e calorias gastas.
- **Given** sessão de treino (ativa ou encerrada) e seus `workout_sets`/`activity_record` consolidado.
- **When** usuário corrige via chat (intent `workout_correct`) **ou** via formulários inline na seção de treinos do `/day` (padrão `EditActivityForm`/inline editing SP-160..169).
- **Then** PATCH em `workout_sets` (`weight_kg`, `reps`, `notes`) e/ou em `workout_sessions` (`kcal_burned_reported`, `duration_minutes`). Se a sessão está encerrada, **reconsolida** o `activity_record` da própria sessão (INV-20) para o `/day` refletir a correção. Dia fechado → 409 (INV-5). Audit gravado (INV-10).

**SP-176** (`should`) — Seção de treinos no `/day`.
- **Given** dia com treinos (sessões consolidadas em `activity_record`).
- **Then** novo bloco **"Treinos"** lista os treinos do dia (nome, duração, kcal gastas; para força, exercícios com cargas/séries/reps). **Calorias gastas** entram no resumo do dia sempre que houver (reportadas ou consolidadas). Reusa `ActivitySection`/`AuxiliarySections` do `/day` (SP-150..154).

**SP-177** (`must`) — Histórico de treinos paginado.
- **Then** aba *Histórico* do `/workouts` lista sessões finalizadas: nome da atividade, data, hora inicial (se houver), calorias gastas; para musculação/variantes com carga inclui cargas, séries e reps por exercício. Paginação determinística (`page`/`page_size` ou cursor); sem duplicação/omissão entre páginas (RNF).

**SP-178** (`must`) — Fluxo guiado "Iniciar treino".
- **Given** botão "Iniciar treino" (SP-173).
- **Then** backend busca `workout_templates` com `active=true` (INV-19) e lista como **botões**; escolhido, chat lista **todos os exercícios** do template (também botões); escolhido um exercício, busca no histórico a **última realização** daquele exercício e lista **carga por série e repetições** (SP-121). A sessão é criada com `workout_sessions.template_id` (INV-20).
- **Then** o usuário conclui séries enviando texto com carga/reps (SP-122/`workout_log_set`). **A partir da primeira série**, o chat confirma o registro e **recapitula o último treino realizado** + exibe botão **"Ir para o próximo exercício"**, que re-lista os exercícios e repete a sequência.

**SP-179** (`must`) — Cronômetro de treino.
- **Given** treino iniciado no fluxo guiado (SP-178) ou sessão livre (SP-120).
- **Then** cronômetro visível na tela do chat de treino; parado ao encerrar (via botão "Finalizar treino" ou `workout_end`). **Tempo do treino registrado** como `duration_minutes` da sessão (SP-126).

**Invariantes adicionais (módulo):**
- **INV-18** — `workout_templates` sempre filtrados por `user_id`; nunca existe query de template sem isolamento (Art. V §21).
- **INV-19** — Template `active=false` não aparece na aba *Ativos* nem no seletor do fluxo guiado (SP-172/SP-178); sessões já finalizadas permanecem no histórico independente do status do template.
- **INV-20** — Sessão guiada referencia o template escolhido (`workout_sessions.template_id`); inativar/alterar template **não** afeta sessões finalizadas (snapshot congelado). Edição de weight/reps/kcal em sessão encerrada reconsolida o `activity_record` da própria sessão.
- **INV-21** — kcal de treino: quando o usuário informa kcal (texto/imagem/edição), `kcal_burned_reported` é a fonte (consolidada em `activity_record`, `met_value=NULL`, `calc_method` reflete origem); senão, estimativa MET fixa por `workout_type` pelo backend. LLM nunca calcula (Art. II).

**Dependências de dados:**
- Coluna `messages.via` (+ índice `idx_messages_user_via`) e tabelas `workout_templates`, `workout_template_exercises`. Alembic migration nova. `workout_sessions` ganha `template_id` FK opcional e `kcal_burned_reported`.
- `Intent` enum ganha `workout_register_template` e `workout_correct` (além dos 5 do núcleo). Payloads novos `WorkoutTemplateIn`, `WorkoutCorrectSetIn`. Prompt `system_v2.md`: seleção por `via` e regras novas.
- Endpoints novos: `GET/PATCH /workouts/templates[/{id}]`, `GET /workouts/templates/{id}/exercises`, `GET /workouts/history`, `PATCH /records/workout-sets/{id}`, `PATCH /records/workout-sessions/{id}`. Chat de treino reusa `POST/GET /chat/messages` com `via:'workout'`.

---

### 3.17 Edição total no `/day` e registro retroativo (pós-MVP)

> **Contexto:** o Bloco 7 (edição inline, spec 002, SP-160..169) entregou edição inline, mas dois buracos ficaram: (a) macros de itens do catálogo canônico (TBCA/USDA) são "não editáveis" (SP-35), e (b) registro de dia passado não existe — o chat grava sempre no dia corrente (`local_today`). Esta seção fecha os dois: edição de **qualquer** valor no `/day` e registro em dia **passado aberto**.

**SP-182** (`must`) — Override de macros de item do catálogo canônico (clone por usuário).
- **Given** um item cujo `catalog_ref_id` aponta para fact `source ∈ {TBCA_2023, USDA_FDC}` (catálogo compartilhado), em dia aberto.
- **When** o usuário edita valores por 100 g/ml no `/day`.
- **Then** o backend **não** muta o fact canônico: cria um fact `source='manual'` com `created_by=user_id` clonando os valores atuais, aplica a edição no clone, reponta o `catalog_ref_id` do item para o clone, recomputa os macros do item (Art. II §5) e o snapshot do dia.
- Edições subsequentes nesse item seguem o caminho normal de fact `manual` (SP-167, INV-14).

**SP-183** (`must`) — Edição de metadados de registro no `/day`.
- **Given** qualquer registro (comida/água/bebida/atividade) em dia aberto.
- **When** o usuário edita `detected_name`, `meal_slot` (comida), `occurred_at`, `quantity`/`unit` (comida).
- **Then** o valor persiste com auditoria (`action='correct'`, Art. III §11) e o snapshot recomputa do zero (Art. III §10).
- **When** o dia está fechado → nenhum campo editável; backend devolve 409 `conflict_closed_day` (INV-5).

**SP-184** (`must`) — Registro retroativo via chat (data reconhecida).
- **Given** o usuário envia mensagem com data passada explícita (ex.: "ontem comi X", "no dia 03/09 almocei Y"), e aquele dia não está fechado.
- **When** o `MessageProcessor` processa a mensagem.
- **Then** o registro é criado contra o `day_log` daquela data (criando-o via `get_or_create` se não existir), o snapshot daquele dia recomputa e a assistant message confirma a data usada.
- **When** o dia está `closed` → resposta amigável (`conflict_closed_day`), nada persistido. **When** a data é futura → `validation_error`, nada persistido.

**SP-185** (`must`) — Registro retroativo via formulário em `/day/[data]`.
- **Given** o usuário abre `/day/[data]` de um dia passado com `status='open'`.
- **When** usa o formulário de adição da página.
- **Then** cria comida/água/bebida/atividade naquele dia com recompute + auditoria (mesma semântica do chat, porém valores entram estruturados, sem LLM).
- Dia fechado ou data futura → formulário ausente (mantém `/day/[data]` read-only, SP-154).

**INV-24** — Fato canônico é imutável por usuário: editar macros de item com fact `TBCA_2023`/`USDA_FDC` sempre produz um fact `manual` clone (`created_by=user`); o row compartilhado do catálogo nunca é modificado por nenhum endpoint.
**INV-25** — Registro/edição retroativa respeita Art. VIII: dia `closed` → 409 `conflict_closed_day` (chat e `/day`); data futura → `validation_error`. Nunca se cria ou edita registro em dia fechado ou futuro.

**Dependências de dados:**
- Nenhuma migration obrigatória: o clone reusa `NutrientFact` (`source='manual'`, `created_by` já existem) e o registro retroativo reusa `DayLogRepository.get_or_create(log_date=...)`.
- O envelope da LLM passa a aceitar `target_date` opcional (`YYYY-MM-DD`) para resolver o `day_log` alvo no registro via chat.
- PATCHs de `/records/*` estendem os campos editáveis (metadados), e surgem endpoints de criação estruturada (sem LLM) consumidos pelo form de `/day/[data]`.

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
- **INV-11** — Service Worker nunca cacheia respostas de `/api/*`. Dados de negócio (kcal, água, atividade) precisam ser sempre frescos; cache SW dos totais do dia contradiz Art. III §10 (snapshots vêm sempre do DB).
- **INV-22** — Carga inicial do chat (sem `after`/`before`) retorna apenas mensagens do dia local corrente do usuário; mensagens de dias anteriores só aparecem via `before`.
- **INV-23** — Paginação por cursor é determinística: ordenação por `(created_at, id)` e âncoras exclusivas garantem que nenhuma mensagem é omitida nem duplicada entre páginas (carga inicial, `after` e `before`).

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
- App nativo. **PWA básico está no escopo (seção 3.13);** offline de dados de negócio e fila de mensagens continuam fora.
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

- **2026-07-18** — v1.4. Adicionado SP-118 (formato tabular padronizado da assistant message após qualquer registro, com "Total da refeição/registro" + "Total acumulado do dia"). Substitui o texto solto atual dos `_compose_*_summary` do `MessageProcessor` — output previsível, com pt-BR (`≈`, vírgula decimal, milhar), asterisco explicando `Líquidos Totais`.
- **2026-07-17** — v1.3. Adicionados SP-115 (balão de `log_food` com cards estruturados no chat), SP-116 (barra fixa de totais do dia) e SP-117 (highlight + fluxo de confirmação inline dos itens pendentes, estende SP-24) como `may`. Formalizam o `DayTable` mencionado no `app_plan.md` §11 e o "destaque na tabela" da SP-24.
- **2026-07-16** — v1.2. Adicionados SP-17 (limite client-side de 4 imagens com feedback por nome), SP-18 (mensagens de erro amigáveis para rejeições de upload citando o nome do arquivo) e SP-19 (drag-and-drop na área de anexo do chat) como `may`. Todos entram no mesmo backlog de UX do chat pós-MVP.
- **2026-07-16** — v1.1. Adicionados SP-15 (envio por Enter) e SP-16 (captura direta pela câmera em mobile) como `may` (pós-MVP). Melhorias de UX no chat que não bloqueiam o MVP; entram no backlog para depois da Fase 9.
- **2026-07-15** — v1.0. Spec inicial extraída de `docs/specs.md`; alinhada com `constitution.md` v1.0.0 e `app_plan.md` 20 seções.
- **2026-07-19** — v1.5. SP-24 detalha chat-side (SP-24a): intent `confirm_items` com scopes `all`/`specific`. Sem novo SP-ID — é implementação faltante do SP-24 original que já previa "aguarda confirmação por chat".
- **2026-07-26** — v1.6. Adicionada seção 3.13 "Registro estruturado de treino" com SP-120..SP-127 (todos `may`, pós-MVP). Modelo hierárquico sessão → exercícios → séries, coexistência com `log_activity` via consolidação em `activity_record` no encerramento (ADR-004 em `research.md`). Novos invariantes INV-11, INV-12, INV-13. Não bloqueia MVP; implementação após Fase 9.
- **2026-07-27** — v1.7. Nova seção 3.13: PWA básico (SP-128..SP-135). Escopo: instalabilidade + shell offline, sem fila de mensagens nem cache de dados de negócio. Nova INV-11 proíbe SW de cachear `/api/*`. Item correspondente removido de "Fora do escopo". (Se PR de workout-tracking mergear primeiro, essa seção vira 3.14 no rebase; sem conflito de SP porque as faixas SP-120..127 e SP-128..135 são disjuntas.)
- **2026-07-27** — v1.9. Nova seção 3.15 "Visão detalhada do dia" (SP-150..SP-154, todos `should`/`may`): página `/day` server-rendered com refeições agrupadas por meal_slot, food_items com macros + micros expansíveis, seções auxiliares de hidratação/bebidas/atividade, rota opcional `/day/[date]` para dias passados. Motivador: bug do catálogo vazio em prod expôs que faltava lugar pro usuário validar item-por-item. Revive parcialmente a intenção do T-409 original. Escopo v1 é read-only; mutações continuam via chat. Faixa SP-150..154 escolhida pra reservar espaço acima de SP-140..142 (§3.14 de recuperação de catálogo, ainda em PR aberta) — sem conflito.
- **2026-07-27** — v1.10. Adicionado SP-155 (`should`) à seção 3.15: navegação temporal a partir do `/day` (botões prev/next/hoje + input date HTML nativo) e do `/weekly` (coluna "Dia" da tabela `per_day` vira link pra `/day/[date]`). Datas no futuro bloqueadas com mensagem amigável, sem bater no backend. Motivador: `/day/[date]` já existia (SP-154) mas só era acessível via URL manual.
- **2026-07-28** — v1.11. SP-154 esclarecido: `/day/[date]` NÃO é read-only universal — quando o dia passado ainda está `status='open'`, o botão "Encerrar dia" aparece pra permitir encerramento retroativo (usuário esqueceu de encerrar). Só edição de records fica exclusiva do chat. Motivador: comportamento anterior `allowClose={false}` bloqueava indevidamente esse fluxo.
- **2026-07-28** — v1.12. **§3.14 (Bloco 5) reformulado.** SP-140 agora produz card com 3 botões clicáveis por item (Cadastrar manual, Foto do rótulo com promoção acoplada, Descartar). Nova SP-143 (`should`): `POST /chat/messages` aceita `promote_food_item_id` para acoplar upload de rótulo → promoção do item legado numa única viagem. Removidos: `PendingItemsModal`, endpoint `POST /records/food-items/{id}/confirm`, `ConfirmItemButton` do `/day`, intent LLM `confirm_items`, `ConfirmationService`, e SP-24a deprecated. Campo `needs_confirmation` fica no schema mas nunca mais é setado — frontend usa `has_catalog` como único sinal. Motivador: sobreposição semântica confusa entre "confirmar" e "resolver item sem catálogo".
- **2026-07-27** — v1.8. Nova seção 3.14 "Recuperação de itens sem catálogo" (SP-140..SP-142, todos `should`, pós-MVP): prompt de recuperação na assistant message quando há `no_catalog_hit`, endpoint `POST /nutrient-facts/manual` para cadastro sem foto, promoção opcional de `food_item` legado no mesmo cadastro. Também: limpeza de duplicação em §3.13 (bloco PWA aparecia duas vezes idênticas por artefato de merge).
- **2026-09-05** — v1.15. Adicionada §3.17 — **edição total no `/day` + registro retroativo** (SP-182..SP-185). SP-182 (`must`, override de macros de item do catálogo canônico via clone `manual` por usuário — nunca muta o fact compartilhado TBCA/USDA); SP-183 (`must`, edição de metadados `detected_name`/`meal_slot`/`occurred_at`/`quantity`/`unit`); SP-184 (`must`, registro retroativo via chat com data reconhecida); SP-185 (`must`, registro retroativo via formulário em `/day/[data]` aberto). Novos invariantes INV-24 (fato canônico imutável por usuário) e INV-25 (registro retroativo respeita dia fechado/futuro). Decisões de design em ADR-014.
- **2026-09-04** — v1.14. Adicionados SP-180 (`must`, carga inicial do chat restrita ao dia corrente + `has_more_before`) e SP-181 (`must`, paginação para trás via `before` ao rolar o chat para o topo, sem filtro de dia — atravessa dias anteriores). Amplia §3.2 (Chat). Novos invariantes INV-22 (carga inicial só do dia corrente) e INV-23 (cursor determinístico `(created_at, id)` sem omissão/duplicação). Resposta de `GET /chat/messages` ganha campo `has_more_before`. Decisão de design em ADR-013 (`research.md`).
- **2026-08-14** — v1.13. **Renumeração de invariantes de treino + módulo de treino (SP-170..SP-179).** (1) Colisão de numeração: v1.6 (workout) e v1.7 (PWA/SW) definiram ambos INV-11. Como o SW INV-11 já está em produção (CI `verify:sw`, `T-1002`, teste em `verify-sw.mjs`), a faixa de treino foi renumerada: **INV-11→INV-15**, **INV-12→INV-16**, **INV-13→INV-17**. §6 mantém INV-11 = SW. Corrigidos em conjunto: `tasks.md` (Bloco 3), `research.md` (ADR-011), `specs/features/INDEX.md` e docs da feature `workout-session-tracking`. (2) Nova **§3.16** formaliza a expansão do cliente: módulo de treino com `workout_templates` (SP-171 cadastro por texto, SP-172 ativo/inativo), chat dedicado no mesmo pool de `messages` via `messages.via='workout'` (SP-173) — decisão "pool único com filtro" fixada, tela `/workouts` com abas Ativos/Inativos/Histórico (SP-170/SP-177), fluxo guiado com botões e "Ir para o próximo exercício" (SP-178) + cronômetro (SP-179), registro por imagem (SP-174), edição de peso/séries/kcal via chat e `/day` (SP-175), seção de treinos no `/day` (SP-176). Novos invariantes **INV-18..INV-21**. Núcleo §3.13 (SP-120..127, `may`) permanece inalterado.
