# Requisitos — Correção de registros

> **Rastreabilidade**: SP-70..SP-74 em [`spec.md §3.8`](../../001-mvp-registro-diario/spec.md#38-correção-de-registros) · Const. Art. III §11 · Invariantes INV-4, INV-5, INV-10.

## Visão geral

Corrigir registros (food_items, water, beverage, activity) de dia aberto por duas superfícies: **chat** (intent `correct_record` → LLM extrai `target_hint` + `changes` → `TargetMatcher` + `CorrectionService`) e **REST** (`PATCH /records/food-items/{id}` — só food; UI usada em SP-117). Toda correção com mudança de quantidade dispara recompute de macros (via `NutritionCalculator` para food/beverage, `ActivityCalculator` para activity), grava `audit_events(action='correct')` com `before/after`, promove `source='user_corrected'` em food/beverage, e re-executa `DailyRecomputeService.recompute` (INV-4). Dia `closed` bloqueia (INV-5) com `DayClosedError` no chat ou 409 no REST.

## Requisitos funcionais

| ID | Requisito | SP | Prioridade |
|---|---|---|---|
| RF-001 | Correção não ambígua via chat: "corrija o frango para 220g" com **único** item de frango no dia → atualiza `quantity`/`grams`, recalcula macros, recomputa snapshot, grava audit. | SP-70 | Must Have |
| RF-002 | Correção ambígua via chat: 2+ itens "frango" no dia sem qualificador → **nada** persiste; assistant devolve `clarify` pedindo desambiguação por horário/refeição. `AmbiguousTarget` propaga. | SP-71 | Must Have |
| RF-003 | Correção qualificada: "o frango do almoço era 220g" → matching por `normalized_name` + `meal_slot='lunch'` (+5 pontos de score). | SP-72 | Must Have |
| RF-004 | Correção em dia `status='closed'` levanta `DayClosedError` (chat) ou retorna 409 `code=conflict_closed_day` (REST); nada muda. | SP-73, INV-5 | Must Have |
| RF-005 | Toda correção grava linha em `audit_events` com `before/after/actor/message_id`. `actor='llm'` via chat, `actor='user'` via REST. | SP-74, INV-10 | Must Have |
| RF-006 | Suporta 4 tipos: FOOD, WATER, BEVERAGE, ACTIVITY (via `TargetKind`). Cada um com regras próprias de recompute. | SP-70 | Must Have |
| RF-007 | Ao mudar `grams`/`ml`/`volume_ml`, macros/kcal são recomputados via `NutritionCalculator.compute(hit, grams, ml)`. | SP-70, INV-1 | Must Have |
| RF-008 | Activity: `kcal_burned_reported` sobrescreve o cálculo MET → `calc_method='user_manual'`. Sem reported: recompute via `ActivityCalculator` se `user.weight_kg` presente; senão warning `missing_weight_kg`. | SP-70 | Must Have |
| RF-009 | Após correção de food com sucesso: `source='user_corrected'`, `needs_confirmation=false` (se catalog hit) — SP-24 revalidada. | SP-24, SP-70 | Must Have |
| RF-010 | Após correção de beverage: `source='user_corrected'`. | SP-70 | Should Have |
| RF-011 | `PATCH /records/food-items/{id}` — endpoint REST usado por SP-117 (confirmação inline). Aceita `grams`/`ml`/`quantity`/`unit`. Retroativamente resolve `catalog_ref_id=NULL` (bug de seed vazio). | SP-117 | Must Have |
| RF-012 | `DailyRecomputeService.recompute(day_log_id)` roda ao fim de qualquer correção com efeito real (INV-4). | INV-4 | Must Have |
| RF-013 | Se `changes` não produz mudança real (mesmo valor) → `ValidationAppError code=correction_no_effect`. | Correção | Must Have |
| RF-014 | `TargetMatcher` detecta kind por keywords (agua, cafe, corri, treino, etc.) — quando presente no hint, filtra busca. | SP-72 | Must Have |
| RF-015 | Snapshot para audit `before/after` inclui campos relevantes por kind (grams/ml/kcal para food; volume_ml para water; duration_minutes/intensity/met_value/calc_method para activity). | INV-10 | Must Have |

## Requisitos não funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | Recompute atômico: correção + audit + snapshot em transação única. Rollback preserva estado se qualquer parte falhar. | Confiabilidade |
| RNF-002 | Isolamento por user — `TargetMatcher` só busca em `day_log_id` do current user; PATCH filtra por `FoodRecord.user_id`. | Segurança (Const. §21) |
| RNF-003 | Latência P95 correção via chat (com LLM classificando intent) ≤ 6s; via REST PATCH ≤ 200ms. | Performance |
| RNF-004 | Cobertura mínima `CorrectionService` + `TargetMatcher`: 90% (crítico para INV-5). | Qualidade |
| RNF-005 | LLM continua sem calcular — `changes` da LLM só passa quantidade/unidade; macros vêm do backend. | INV-1 |

## Restrições e premissas

- **Sem correção retroativa em dia fechado**: bloqueio explícito. Const. §28 é literal.
- **Sem "recorrer" via chat**: se `AmbiguousTarget` acontecer, o assistant fala qual desambiguação precisa; user reenvia mensagem com qualificador. Sem estado conversacional.
- **`changes` da LLM é permissivo**: schema é `dict[str, float|int|str|bool|None]` (`CorrectionIn` em `schemas/llm.py`). Backend extrai campos conhecidos (`grams`, `ml`, `quantity`, `unit`, `duration_minutes`, `intensity`, `kcal_burned`, `kcal_burned_reported`, `volume_ml`), ignora o resto.
- **Score do matcher**: soma tokens em comum. Empate no top → `AmbiguousTarget`. Sem "confidence threshold" — só ordem.
- **PATCH REST não usa LLM**: usuário digita valores no modal SP-117; audit `actor='user'` (não `'llm'`).
- **Confirmação (SP-24a `confirm_items`)** é feature separada — ver [`food-logging`](../food-logging/) e futuro spec de confirm.
- **Sem histórico versionado dos records** — audit é a única fonte de "o que era antes".

## Dependências

**Depende de:**
- [`anthropic-integration`](../anthropic-integration/) — extrai `intent=correct_record` com `correction: {target_hint, changes, confidence}`.
- [`chat-messaging`](../chat-messaging/) — routing via `IntentDispatcher._handle_correct_record`.
- [`food-logging`](../food-logging/) — items a corrigir vêm de lá.
- [`water-tracking`](../water-tracking/), [`caloric-beverages`](../caloric-beverages/), [`activity-cardio-logging`](../activity-cardio-logging/) — outros kinds.
- [`daily-snapshot`](../daily-snapshot/) — recompute pós-correção.
- [`day-close`](../day-close/) — produz `status='closed'` que bloqueia mutation.
- [`audit-trail`](../audit-trail/) — `AuditEventRepository.record`.
- [`authentication-session`](../authentication-session/) — `Depends(get_current_user)`.

**Requerido por:**
- [`assistant-message-rendering`](../assistant-message-rendering/) — SP-117 modal de confirmação inline chama `PATCH /records/food-items/{id}`.
- [`manual-catalog-recovery`](../manual-catalog-recovery/) — promoção via `promote_food_item_id` reutiliza a mesma semântica audit `action='correct'`.
