# Requisitos — Registro de água pura

> **Rastreabilidade**: SP-40..SP-42 em [`specs/001-mvp-registro-diario/spec.md`](../../001-mvp-registro-diario/spec.md#35-registro-de-agua-pura) · Fase 5 em [`plan.md`](../../001-mvp-registro-diario/plan.md) · Invariantes: INV-2, INV-4, INV-10 · Constituição Art. IV §12-14 · T-501, T-502, T-506, T-508 em [`tasks.md`](../../001-mvp-registro-diario/tasks.md).

## Visão geral

Registrar consumo de **água pura** por chat (texto), com persistência em `water_records` — tabela que **por estrutura** não tem colunas de kcal/macros/micros (INV-2 estrutural). A LLM apenas extrai `volume_ml` via `tool_use`; o backend valida que o resumo não sugere bebida calórica e grava o registro. Cada criação dispara recomputo from-scratch do snapshot do dia (INV-4) e grava `audit_events` (INV-10).

## Requisitos funcionais

| ID | Requisito | SP | Prioridade |
|---|---|---|---|
| RF-001 | Aceitar "500 ml de água", "um copo (250 ml)" → `water_records` com `volume_ml`, `kcal=0` (ausente por schema), sem macros. | SP-40 | Must Have |
| RF-002 | Rejeitar `intent=log_water` quando o `user_text_summary` da própria LLM contém hints de bebida calórica (café, leite, suco, refrigerante, chá, cerveja, vinho, açúcar, mel, leite_condensado) — levanta `ValidationAppError(code="water_intent_rejected")` e nada persiste. `MessageProcessor` traduz em `clarify`. | SP-41, Art. IV §14 | Must Have |
| RF-003 | Estimar volume a partir de unidade doméstica ("um copo" → 250 ml, "uma garrafinha" → 500 ml) marcando `is_estimate=true`. A estimativa é feita pela LLM no envelope; o backend apenas persiste o flag. | SP-42 | Should Have |
| RF-004 | Recomputar `daily_snapshots` do dia inteiro from-scratch após cada criação — `water_ml = SUM(water_records.volume_ml) WHERE deleted_at IS NULL`. | INV-4 | Must Have |
| RF-005 | Gravar `audit_events(actor='llm', action='create', entity_type='water_record')` referenciando `message_id` de origem; `after={volume_ml, occurred_at}`. | INV-10 | Must Have |

## Requisitos não funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | Isolamento por usuário: `WaterRecordRepository.create` recebe `user_id` obrigatório (Const. §21). | Segurança |
| RNF-002 | INV-2 garantido por **schema**, não por validação runtime: `water_records` não tem colunas `kcal`/`protein_g`/… — impossível registrar caloria em água por engano. | Confiabilidade |
| RNF-003 | `volume_ml > 0` enforced por `CheckConstraint("volume_ml > 0")` no Postgres. | Integridade |
| RNF-004 | `source` restrito a `('manual','llm','user_corrected')` por `CheckConstraint`. | Integridade |
| RNF-005 | Determinismo: dado o mesmo `LLMEnvelope.water.volume_ml`, `HydrationService.create_from_llm` gera registro idêntico (sem cálculo, só persistência). | Confiabilidade |
| RNF-006 | Aviso legal obrigatório em toda resposta do assistente (Const. Art. VII §26). | Compliance |

## Restrições e premissas

- **Água pura apenas** (Const. Art. IV §12): "água com limão", "água com gás adoçada" etc. não cabem aqui — se a LLM classificar como `log_water` mas o resumo denunciar caloria, o backend rejeita (SP-41). Bebidas calóricas vão para a feature `caloric-beverages`.
- **Sem catálogo**: água não tem lookup nutricional — sempre volume direto. Não existe `catalog_ref_id` em `water_records`.
- **Sem foto no MVP**: SP-40..42 cobrem só texto. Fotos de copo/garrafa não são interpretadas para volume.
- **LLM não estima kcal**: mesmo se a LLM devolver `kcal` em texto livre, é descartado (INV-1, INV-9) — só `tool_use.input.water.volume_ml` é consumido.
- **`confidence` Decimal(3,2)**: gravado mas não dispara `needs_confirmation` em água (sem macros para confirmar).

## Dependências

**Depende de:**
- [`anthropic-integration`](../anthropic-integration/requirements.md) — `LLMEnvelope` via `tool_use` forçado; `WaterIn` é sub-schema do envelope.
- [`chat-messaging`](../chat-messaging/requirements.md) — pipeline `POST /chat/messages` → `MessageProcessor` → `IntentDispatcher._handle_log_water` → `HydrationService.create_from_llm`.
- [`daily-snapshot`](../daily-snapshot/requirements.md) — `DailyRecomputeService.recompute(day_log_id)` agrega `water_ml` ao final.

**Requerido por:**
- [`daily-snapshot`](../daily-snapshot/requirements.md) — snapshot lê `water_records` vivos (`deleted_at IS NULL`).
- [`day-close`](../day-close/requirements.md) — encerramento usa `water_ml` do snapshot.
- [`weekly-report`](../weekly-report/requirements.md) — soma `water_ml` entre dias fechados.
- [`record-correction`](../record-correction/requirements.md) e [`record-deletion`](../record-deletion/requirements.md) — mutam `water_records` posteriormente.
- [`caloric-beverages`](../caloric-beverages/requirements.md) — complementar: o que não é água pura cai lá (INV-2/INV-3).
