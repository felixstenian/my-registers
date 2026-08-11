# Requisitos — Recuperação manual de itens sem catálogo

> **Rastreabilidade**: SP-140..SP-142 em [`spec.md §3.14`](../../001-mvp-registro-diario/spec.md#314-recuperação-de-itens-sem-catálogo-pós-mvp) · Tasks T-B501..T-B508 em [`tasks.md § Bloco 5`](../../001-mvp-registro-diario/tasks.md) · Depende de [`food-logging`](../food-logging/) (que dispara warnings `no_catalog_hit`) e [`daily-snapshot`](../daily-snapshot/) (que os agrega).
>
> **Status desta feature**: **partial** — spec-kit completo nesta árvore (branch `docs/enhancement`); implementação vive em `feat/bloco-5-catalog-recovery` (fora desta árvore). Todas as tasks T-B501..T-B508 estão `[ ]` unchecked em `tasks.md` — atualizar quando merge no `main`. Cabeçalhos abaixo marcam explicitamente o que ainda **não** está aqui.

## Visão geral

Quando o usuário registra um alimento fora do TBCA seed (`LocalTBCACatalog.lookup(...)` devolve `None`), hoje o item entra em `food_items` com `kcal=0`, `catalog_ref_id=NULL`, `needs_confirmation=True` + warning `no_catalog_hit` (comportamento herdado de [`food-logging`](../food-logging/) SP-23). O usuário tem 3 caminhos de "recuperação": (a) foto do rótulo (Fase 4.b — [`nutrition-label-ocr`](../nutrition-label-ocr/)), (b) descartar via chat, (c) confirmar zerado. Nenhum é intuitivo. Este Bloco cobre duas melhorias: (1) prompt de recuperação claro na assistant message (SP-140) e (2) endpoint `POST /nutrient-facts/manual` com promoção opcional do item legado (SP-141 + SP-142).

## Requisitos funcionais

| ID | Requisito | SP / Task | Prioridade |
|---|---|---|---|
| RF-001 | Ao compor a assistant message de `log_food` que contenha warnings `no_catalog_hit`, o `message_formatter` anexa bloco "Sem catálogo para: {item1, item2}" com 3 CTAs claros: **📸 Enviar foto do rótulo**, **✏️ Cadastrar manualmente**, **❌ Descartar item**. | SP-140, T-B501 | Should Have |
| RF-002 | Prompt SP-140 é apenas UX — não altera cálculos nem persistência. Aviso legal (Const. §26) continua obrigatório. | SP-140 | Should Have |
| RF-003 | Novo endpoint `POST /nutrient-facts/manual` (autenticado) cria linha em `nutrient_facts` com `source='user_manual'`, `verified_by_user=true`, `created_by=user_id`. | SP-141, T-B503 | Should Have |
| RF-004 | Body do endpoint aceita: `canonical_name` (slug `[a-z0-9_]+`), `display_name`, `brand?`, `basis ∈ {per_100g, per_100ml}`, `kcal ≥ 0`, `protein/carbs/fat ≥ 0`, macros/micros opcionais, `aliases?`, `promote_food_item_id?`. | SP-141 | Should Have |
| RF-005 | Response 201 com o `nutrient_facts.id` criado (ou 200 se merge com fact existente do usuário — decisão ADR pendente). | SP-141 | Should Have |
| RF-006 | Migration `0008_nutrient_facts_source_user_manual` adiciona valor `user_manual` ao CHECK constraint de `nutrient_facts.source`. (Hoje o modelo aceita `TBCA_2023, USDA_FDC, manual, label_ocr`.) | T-B502 | Must Have para RF-003 |
| RF-007 | Isolamento por usuário — cada user tem seu próprio fact; não compartilha entre users. `LocalTBCACatalog` já resolve precedência (`user_manual + verified_by_user=true` empata com TBCA_2023; mais recente vence). | SP-141, Const. §21 | Must Have |
| RF-008 | Audit gravado: `entity_type='nutrient_fact', action='create', actor='user', message_id=NULL, after=<payload>`. | SP-141, INV-10 | Must Have |
| RF-009 | Se body inclui `promote_food_item_id`, backend em transação única: (1) cria fact; (2) lookup do item legado; (3) se pertence ao user e não deletado: `catalog_ref_id=novo_fact.id`, recalcula macros via `NutritionCalculator.compute(hit=novo_fact, grams, ml)`, desmarca `needs_confirmation`; (4) audit `action='correct'`, actor='user', before/after; (5) `DailyRecomputeService.recompute(day_log_id)`. | SP-142, T-B504 | Should Have |
| RF-010 | Se `promote_food_item_id` é de outro user ou item já deletado → response 201 do fact criado + warning `"promotion_failed"` no body; **NÃO** faz rollback do fact. | SP-142 | Should Have |
| RF-011 | Se `promote_food_item_id` já tem `catalog_ref_id != NULL` → sobrescreve com o novo fact + audit da mudança. | SP-142 | Should Have |
| RF-012 | Se item pertence a dia fechado (`day_log.status='closed'`) → promoção bloqueia (409 conflict\_closed\_day), mas cadastro do fact prossegue com warning. | SP-142, INV-5, T-B505 (gate) | Should Have |
| RF-013 | Frontend: novo componente `ManualCatalogForm.tsx` (client) — formulário curto acionado pelo CTA "Cadastrar manualmente"; campos obrigatórios (nome + kcal + P/C/G) e opcionais em accordion. Submit inclui `promote_food_item_id` do item que originou o `no_catalog_hit`; revalida `DayTotalsBar` após 201. | T-B506 | Should Have |
| RF-014 | Frontend: `AssistantContent.tsx` detecta bloco de recovery e renderiza CTAs como botões clicáveis (não texto puro): "Cadastrar" abre form; "Enviar foto" foca input file do composer; "Descartar" envia mensagem `apaga {nome}` pré-preenchida. | T-B507 | Should Have |
| RF-015 | Documentação em `docs/manual-catalog.md` (ou seção em `docs/pwa.md`) explicando quando aparece, quando usar cada opção. | T-B508 | Nice to have |

## Requisitos não funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | Endpoint executa em transação única (Postgres); rollback cobre fact + promoção + audit + recompute. | Confiabilidade |
| RNF-002 | Latência `POST /nutrient-facts/manual` sem promoção P95 ≤ 200ms; com promoção ≤ 400ms (recompute domina). | Performance |
| RNF-003 | Cobertura mínima de integração em `tests/test_manual_nutrient_facts.py`: 12 casos (T-B505). | Qualidade |
| RNF-004 | Isolamento cross-user: user A não vê nem promove fact/item de user B. | Segurança (Const. §21) |
| RNF-005 | Validação pydantic estrita: `canonical_name` deve casar `^[a-z0-9_]+$`; qualquer campo negativo → 422. | Correção |

## Restrições e premissas

- **Não é foto de rótulo.** SP-141 é para o caso em que o usuário sabe os valores (do rótulo digitando, de tabela nutricional, de app externo) mas não quer/pode tirar foto. Foto de rótulo continua no fluxo separado ([`nutrition-label-ocr`](../nutrition-label-ocr/) SP-30..35).
- **Não substitui LLM interpretando.** Continua sendo o backend que calcula (INV-1); o form apenas alimenta o catálogo do usuário.
- **Sem sincronização entre users.** Cada usuário mantém seus facts (isolamento). Aceito pra MVP; multi-user compartilhado é v2.
- **Sem delete de fact manual.** Adiar; auditoria preserva histórico.
- **Sem sugestão automática pela LLM.** LLM não pode preencher form sem input humano (viola Const. §5).
- **`canonical_name` é chave de busca.** Se dois users cadastram "pão_de_queijo_congelado", cada um tem sua linha (não conflitam). `LocalTBCACatalog` filtra por `created_by=user_id` para achar o do user.

## Dependências

**Depende de:**
- [`food-logging`](../food-logging/) — emite os warnings `no_catalog_hit` que disparam SP-140.
- [`nutrition-label-ocr`](../nutrition-label-ocr/) — feature "irmã" para o caminho por foto; `LabelCatalogService.upsert_from_label` é referência de shape para SP-141 (T-B503).
- [`daily-snapshot`](../daily-snapshot/) — `DailyRecomputeService.recompute` roda após promoção (SP-142).
- [`authentication-session`](../authentication-session/) — endpoint protegido.
- [`record-correction`](../record-correction/) — audit `action='correct'` reutiliza mesma semântica.
- [`assistant-message-rendering`](../assistant-message-rendering/) — RF-014 estende `AssistantContent.tsx`.

**Requerido por:** — nenhuma feature ainda. É "opcional para o usuário" no fluxo de recuperação.
