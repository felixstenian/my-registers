# Requisitos — Snapshot diário

> **Rastreabilidade**: SP-90..SP-92 em [`spec.md §3.10`](../../001-mvp-registro-diario/spec.md#310-consulta-do-dia) · Const. Art. III §10 · Invariantes INV-2, INV-3, INV-4, INV-5.

## Visão geral

`daily_snapshots` é o **cache materializado** dos totais nutricionais e hídricos do dia — kcal, macros, micros, água pura, outros líquidos, atividade. Toda leitura de dia (`GET /days/today` ou `GET /days/{date}`) devolve este snapshot; toda mutação que altera registros do dia dispara `DailyRecomputeService.recompute(day_log_id)` que **sempre reconstrói from-scratch** via SQL `SUM` sobre tabelas cruas com `deleted_at IS NULL`. Dia fechado (`status='closed'`) é imutável e nunca recomputado.

## Requisitos funcionais

| ID | Requisito | SP | Prioridade |
|---|---|---|---|
| RF-001 | `GET /days/today` retorna snapshot do dia atual no fuso horário do usuário (`users.timezone`) com `{date, status, closed_at, totals, records, warnings, narrative, snapshot_version}`. | SP-90 | Must Have |
| RF-002 | Se não existir `day_log` para hoje, criar vazio (com `status='open'`) para responder totais zerados em vez de 404. | SP-90 | Must Have |
| RF-003 | `GET /days/{yyyy-mm-dd}` retorna mesmo shape para data passada. Se não existir `day_log` → 404 com `code=day_not_found`. | SP-91 | Must Have |
| RF-004 | Determinar "dia" pelo `users.timezone` — mensagem 23:30 local em 12/jul pertence a `log_date=2026-07-12` mesmo que UTC diga 13/jul. | SP-92 | Must Have |
| RF-005 | Recomputar sempre from-scratch a partir de tabelas cruas (`SUM` com `deleted_at IS NULL`); nunca delta incremental. | INV-4, Const. §10 | Must Have |
| RF-006 | `kcal_in = SUM(food_items.kcal) + SUM(beverage_records.kcal)` (Const. Art. IV §13). | INV-2, INV-3 | Must Have |
| RF-007 | `water_ml = SUM(water_records.volume_ml)` — só água pura, nunca de bebidas calóricas. | INV-2 | Must Have |
| RF-008 | `other_liquids_ml = SUM(beverage_records.volume_ml)` — separado de `water_ml`. | INV-3 | Must Have |
| RF-009 | `kcal_out = SUM(activity_records.kcal_burned)`; `kcal_balance = kcal_in - kcal_out`. | SP-90 | Must Have |
| RF-010 | Cada recompute incrementa `daily_snapshots.version` (upsert via `INSERT ... ON CONFLICT`). | Auditoria | Must Have |
| RF-011 | Agregação inclui warnings agregados: `no_catalog_hit` e `needs_confirmation` por item de comida/bebida, `activity_estimated` para atividade sem `calc_method='mets_body_weight'`. | SP-24, SP-23 | Must Have |
| RF-012 | Dia fechado (`status='closed'`) **NUNCA** recomputa — snapshot congelado é sempre a resposta. | INV-5, Const. §28 | Must Have |
| RF-013 | Dia aberto sem snapshot ainda materializado → recomputa on-read para não devolver totais desalinhados. | Correção | Must Have |
| RF-014 | Payload de `records` agrupa por categoria: `food` (por `food_records` + `items` embarcados), `water`, `beverage`, `activity`, todos ordenados por `occurred_at`. | SP-90 | Must Have |
| RF-015 | Somas são exatas em `Decimal(10,2)`; volumes em `Integer` (ml). | INV-1 | Must Have |

## Requisitos não funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | Latência de `GET /days/today` P95 ≤ 200ms. | Performance (SP-90 §4.2) |
| RNF-002 | Recompute é atômico: `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` em transação; conflito por `UNIQUE(day_log_id)`. | Confiabilidade |
| RNF-003 | `execution_options(populate_existing=True)` no `RETURNING` para evitar snapshot cacheado no SQLAlchemy identity map (bug pego na Fase 4). | Correção |
| RNF-004 | Isolamento por usuário — `user_id` verificado no `day_log` antes de retornar. | Segurança (Const. §21) |
| RNF-005 | Consultas de agregação usam `func.coalesce(SUM, 0)` para nunca devolver `NULL`. | Correção |

## Restrições e premissas

- **Snapshot é derivado, não fonte de verdade.** Toda vez que o usuário vê um número em `/chat` ou `/day`, o snapshot foi calculado por SQL agregado sobre `food_items`, `water_records`, `beverage_records`, `activity_records`. Se o cache divergir, recompute resolve.
- **Recompute é caro em O(N_registros_do_dia)** — mas N é ordem de 10-30 no MVP single-user. Aceito.
- **`daily_snapshots.warnings` é JSONB append**: cada recompute reescreve; warnings do dia refletem estado atual dos itens vivos.
- **Fuso horário via `zoneinfo`**: `local_today(user.timezone)` em `app/services/chat.py`. Nunca `datetime.utcnow().date()` direto.
- **Sem RLS**: isolamento por `user_id` em application-layer (padrão do projeto).
- **`narrative` é preenchida no fechamento** ([`day-close`](../day-close/)), nunca no recompute normal.

## Dependências

**Depende de:**
- [`food-logging`](../food-logging/) — grava `food_items` que são somados.
- [`water-tracking`](../water-tracking/) — grava `water_records`.
- [`caloric-beverages`](../caloric-beverages/) — grava `beverage_records`.
- [`activity-cardio-logging`](../activity-cardio-logging/) — grava `activity_records`.
- [`authentication-session`](../authentication-session/) — `Depends(get_current_user)` fornece `user_id` + `timezone`.

**Requerido por:**
- [`day-close`](../day-close/) — encerramento re-executa recompute antes de congelar (INV-4 + INV-5).
- [`weekly-report`](../weekly-report/) — semanal agrega sobre `daily_snapshots` (só `closed`).
- [`daily-detail-view`](../daily-detail-view/) — rota `/day` no Next lê deste endpoint.
- [`chat-messaging`](../chat-messaging/) — barra de totais SP-116 (`assistant-message-rendering`) revalida via `GET /days/today` a cada nova assistant message.
- [`record-correction`](../record-correction/) e [`record-deletion`](../record-deletion/) — disparam recompute após mutação.
