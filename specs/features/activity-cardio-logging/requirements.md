# Requisitos — Registro de atividade física (cardio)

> **Rastreabilidade**: SP-60..SP-64 em [`specs/001-mvp-registro-diario/spec.md`](../../001-mvp-registro-diario/spec.md#37-registro-de-atividade-fisica) · Fase 5 em [`plan.md`](../../001-mvp-registro-diario/plan.md) · Invariantes: INV-4, INV-10 · Constituição Art. III §10 · T-501, T-506, T-508 em [`tasks.md`](../../001-mvp-registro-diario/tasks.md).

## Visão geral

Registrar atividade física por chat (texto), com `kcal_burned` calculado deterministicamente no backend pela fórmula MET: `kcal = met × weight_kg × (duration_minutes / 60)`. A LLM apenas extrai `activity_type`, `duration_minutes`, `intensity`, `distance_km` e opcionalmente `kcal_burned_reported` (de print de smartwatch). `met_value` e `calc_method` são gravados para auditoria e recomputo futuro. Cada criação dispara recompute from-scratch do snapshot (INV-4) e grava `audit_events` (INV-10).

## Requisitos funcionais

| ID | Requisito | SP | Prioridade |
|---|---|---|---|
| RF-001 | Aceitar "corri 40 min moderado" → `activity_records` com `activity_type='cardio_run'`, `duration_minutes=40`, `intensity='moderate'`, `kcal_burned = MET × weight_kg × (duration/60)`, `met_value` gravado, `calc_method='mets_body_weight'`. | SP-60, SP-64 | Must Have |
| RF-002 | Se `users.weight_kg` é `null` e o envelope **não** trouxe `kcal_burned_reported`, levantar `WeightRequired` — nada persiste; assistente pede peso (SP-61). Se há `kcal_burned_reported`, peso não é necessário (dispositivo já resolveu). | SP-61 | Must Have |
| RF-003 | Musculação (`activity_type='strength'`) sem intensidade (`unknown`) → usar `moderate` no cálculo (`met=5.0`), mas persistir `intensity='unknown'` para auditoria. | SP-62 | Should Have |
| RF-004 | Distância sem duração ("caminhei 4 km") → estimar duração por velocidade média (`_SPEED_KMH`); se estimativa falhar, duration=0 e warning. | SP-63 | Should Have |
| RF-005 | Gravar `met_value`, `kcal_burned`, `calc_method` em `activity_records` para recomputo futuro (Const. Art. III §10). `calc_method ∈ ('mets_body_weight','llm_estimate','user_manual')`. | SP-64 | Must Have |
| RF-006 | Se o envelope traz `kcal_burned_reported` (LLM extraiu de foto de smartwatch/app), esse valor é **fonte de verdade**: `calc_method='user_manual'`, `met_value` ainda gravado para contexto. | [Inferido do código] | Must Have |
| RF-007 | Aceitar `activity_type` em pt-BR e EN ("corrida", "run", "running", "musculação", "strength") via `_ACTIVITY_TYPE_ALIASES` — canonicaliza antes do lookup MET. | [Inferido do código] | Must Have |
| RF-008 | Recomputar `daily_snapshots` do dia inteiro from-scratch — `kcal_out = SUM(activity_records.kcal_burned) WHERE deleted_at IS NULL`, `kcal_balance = kcal_in - kcal_out`. | INV-4 | Must Have |
| RF-009 | Gravar `audit_events(actor='llm', action='create', entity_type='activity_record')` com `after={activity_type, duration_minutes, kcal_burned, calc_method, occurred_at}`. | INV-10 | Must Have |

## Requisitos não funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | Isolamento por usuário: `ActivityRecordRepository.create` recebe `user_id` obrigatório (Const. §21). | Segurança |
| RNF-002 | Determinismo: dados os mesmos `activity_type`, `intensity`, `duration_minutes`, `weight_kg`, `ActivityCalculator.compute` gera `kcal_burned` idêntico (Decimal quantize `0.01`). | Confiabilidade |
| RNF-003 | Cobertura mínima em `ActivityCalculator`: 90% (plan.md §5.3). | Qualidade |
| RNF-004 | `duration_minutes > 0` e `intensity`/`calc_method` restritos por `CheckConstraint` no Postgres. | Integridade |
| RNF-005 | Aviso legal obrigatório em toda resposta do assistente (Const. Art. VII §26). | Compliance |
| RNF-006 | LLM não calcula kcal: se a LLM emitir `kcal_burned` em texto livre, é descartado; só `kcal_burned_reported` (campo estruturado) é aceito como atalho (INV-1). | Confiabilidade |

## Restrições e premissas

- **Tabela MET `_MET_TABLE`** cobre `cardio_run`, `cardio_walk`, `bike`, `swim`, `strength`, `yoga`, `cardio` × 4 intensidades (`light`, `moderate`, `vigorous`, `unknown`). Par não mapeado → `calc_method='llm_estimate'`, `kcal_burned=0`, warning `unknown_activity_or_intensity`.
- **`kcal_burned_reported` sobrescreve cálculo MET**: se a LLM extrai kcal de print de smartwatch, esse valor é autoritativo (`calc_method='user_manual'`) — não recalculamos. Const. Art. III §10: recompute mantém o valor materializado.
- **`weight_kg` vem de `users`**: não é passado no envelope. Se `null` e sem `kcal_burned_reported`, `WeightRequired` é levantada.
- **Sem `needs_confirmation` para activity** no MVP (`confirmation.py` linha 236: "Water/activity não têm needs_confirmation no MVP"). Apenas `low_confidence_item` warning se `confidence < 0.5`.
- **Aliases pt-BR/EN**: LLM escorrega em "corrida", "run", "musculação"; `_ACTIVITY_TYPE_ALIASES` canonicaliza antes do lookup.
- **Sem foto de atividade interpretada no MVP**: fotos de smartwatch são tratadas como `kcal_burned_reported` extraído pela LLM, não como OCR do print.

## Dependências

**Depende de:**
- [`anthropic-integration`](../anthropic-integration/requirements.md) — `LLMEnvelope` via `tool_use`; `ActivityIn` é sub-schema.
- [`chat-messaging`](../chat-messaging/requirements.md) — pipeline `POST /chat/messages` → `MessageProcessor` → `IntentDispatcher._handle_log_activity` → `ActivityService.create_from_llm`.
- [`authentication-session`](../authentication-session/requirements.md) — `users.weight_kg` é lido do perfil do usuário.
- [`daily-snapshot`](../daily-snapshot/requirements.md) — `DailyRecomputeService._aggregate_activity` roda ao final.

**Requerido por:**
- [`daily-snapshot`](../daily-snapshot/requirements.md) — snapshot lê `activity_records` vivos.
- [`day-close`](../day-close/requirements.md) — encerramento usa `kcal_out` do snapshot.
- [`weekly-report`](../weekly-report/requirements.md) — soma `kcal_out` entre dias fechados.
- [`record-correction`](../record-correction/requirements.md) e [`record-deletion`](../record-deletion/requirements.md) — mutam `activity_records` posteriormente; correção recalcula kcal via `ActivityCalculator`.
