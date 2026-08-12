> Gerado em: 2026-08-12
> Origem: `specs/001-mvp-registro-diario/spec.md` (SP-01..SP-155) + `specs/002-edicao-inline-day/spec.md` (SP-160..SP-169, INV-14) + implementação em `apps/api/app/` e `apps/web/src/`
> Total de features: 24

# Índice de Features — my-registers

Este índice consolida as features do produto **my-registers** cruzando a especificação spec-kit (`specs/001-mvp-registro-diario/spec.md`, SP-01..SP-155 + INV-1..INV-13), o CHANGELOG (`CHANGELOG.md` até v1.3.0) e o código real em `apps/api/app/` + `apps/web/src/`.

Cada feature tem sua pasta em `specs/features/<slug>/` com os 7 artefatos padrão (`requirements.md`, `specifications.md`, `user-stories.md`, `acceptance-criteria.md`, `test-cases.md`, `architecture.md`, `trade-offs.md`).

Convenções e diferença para `specs/001-mvp-registro-diario/`:
- `specs/001-mvp-registro-diario/` continua sendo a **fonte de verdade contratual** (SDD, spec-kit, constituição). Ninguém edita SP-XX aqui.
- `specs/features/` é uma **visão por feature** — reindexa e detalha o que já existe, com foco em legibilidade, testes e trade-offs. Se um SP-XX evoluir, atualiza-se aqui **depois** de atualizar `spec.md`.

## Legenda de status

- **stable** — Documentada e em produção (`https://myregister.felix.dev.br` v1.3.0).
- **partial** — Implementada em branch feature ou parcialmente entregue; documentação viva.
- **documented-only** — Spec escrita, implementação pendente.
- **deprecated** — Retirada; mantida como registro histórico.

---

## Features por categoria

### 🔐 Autenticação & Sessão

| Feature | SPs | Status | Pasta |
|---|---|---|---|
| [Autenticação e sessão](./authentication-session/requirements.md) | SP-01..SP-06 | stable | `authentication-session/` |
| [Bootstrap de admin via CLI](./admin-bootstrap-cli/requirements.md) | Const. §18, §24 | stable | `admin-bootstrap-cli/` |

### 💬 Chat & Mensagens

| Feature | SPs | Status | Pasta |
|---|---|---|---|
| [Chat e mensagens (núcleo)](./chat-messaging/requirements.md) | SP-10..SP-14 | stable | `chat-messaging/` |
| [Composer do chat — UX (Bloco 1)](./chat-composer-ux/requirements.md) | SP-15..SP-19 | stable | `chat-composer-ux/` |
| [Renderização de assistant messages (Bloco 2)](./assistant-message-rendering/requirements.md) | SP-115..SP-118 | stable | `assistant-message-rendering/` |

### 🍽️ Alimentação

| Feature | SPs | Status | Pasta |
|---|---|---|---|
| [Registro de alimentos](./food-logging/requirements.md) | SP-20..SP-26 | stable | `food-logging/` |
| [Leitura de rótulo nutricional (Fase 4.b)](./nutrition-label-ocr/requirements.md) | SP-30..SP-35 | stable | `nutrition-label-ocr/` |
| [Recuperação manual de itens sem catálogo (Bloco 5)](./manual-catalog-recovery/requirements.md) | SP-140..SP-142 | partial | `manual-catalog-recovery/` |

### 💧 Hidratação & Bebidas

| Feature | SPs | Status | Pasta |
|---|---|---|---|
| [Registro de água pura](./water-tracking/requirements.md) | SP-40..SP-42 (Art. IV) | stable | `water-tracking/` |
| [Registro de bebidas calóricas](./caloric-beverages/requirements.md) | SP-50..SP-52 (Art. IV) | stable | `caloric-beverages/` |

### 🏃 Atividade Física

| Feature | SPs | Status | Pasta |
|---|---|---|---|
| [Registro de atividade cardio](./activity-cardio-logging/requirements.md) | SP-60..SP-64 | stable | `activity-cardio-logging/` |
| [Treino estruturado — sessão/exercícios/séries (Bloco 3)](./workout-session-tracking/requirements.md) | SP-120..SP-127 | documented-only | `workout-session-tracking/` |

### ✏️ Ciclo de Vida de Registros

| Feature | SPs | Status | Pasta |
|---|---|---|---|
| [Correção de registros](./record-correction/requirements.md) | SP-70..SP-74 | stable | `record-correction/` |
| [Remoção de registros (soft delete)](./record-deletion/requirements.md) | SP-80..SP-82 | stable | `record-deletion/` |
| [Edição inline de registros no /day](./inline-record-editing/requirements.md) | SP-160..SP-169, INV-14 | documented-only | `inline-record-editing/` |

### 📅 Consulta e Fechamento de Dias

| Feature | SPs | Status | Pasta |
|---|---|---|---|
| [Snapshot diário (GET /days/today, /days/{date})](./daily-snapshot/requirements.md) | SP-90..SP-92 | stable | `daily-snapshot/` |
| [Encerramento de dia + narrativa LLM](./day-close/requirements.md) | SP-100..SP-104 | stable | `day-close/` |
| [Visão detalhada do dia — /day (Bloco 6)](./daily-detail-view/requirements.md) | SP-150..SP-155 | stable | `daily-detail-view/` |

### 📊 Relatórios

| Feature | SPs | Status | Pasta |
|---|---|---|---|
| [Relatório semanal](./weekly-report/requirements.md) | SP-110..SP-113 | stable | `weekly-report/` |

### 📱 PWA & Cliente

| Feature | SPs | Status | Pasta |
|---|---|---|---|
| [PWA — instalabilidade + shell offline (Bloco 4)](./pwa-installability-offline/requirements.md) | SP-128..SP-135, INV-11 | stable | `pwa-installability-offline/` |

### 🔌 Integrações Externas

| Feature | SPs | Status | Pasta |
|---|---|---|---|
| [Integração Anthropic (tool_use + fallback)](./anthropic-integration/requirements.md) | Const. Art. II, §7 | stable | `anthropic-integration/` |
| [Storage de mídia (MinIO S3)](./media-storage/requirements.md) | SP-11, Const. §22 | stable | `media-storage/` |

### 🛡️ Cross-cutting

| Feature | SPs | Status | Pasta |
|---|---|---|---|
| [Trilha de auditoria (audit_events)](./audit-trail/requirements.md) | INV-10, Const. §11 | stable | `audit-trail/` |

### 🚀 Infraestrutura & Deploy

| Feature | SPs | Status | Pasta |
|---|---|---|---|
| [Pipeline CI/CD (Fase 10)](./deploy-pipeline-ci-cd/requirements.md) | Fase 10, ADR-012 | stable | `deploy-pipeline-ci-cd/` |

---

## Features por status

### ✅ Stable (20)

- [Autenticação e sessão](./authentication-session/requirements.md)
- [Bootstrap de admin via CLI](./admin-bootstrap-cli/requirements.md)
- [Chat e mensagens (núcleo)](./chat-messaging/requirements.md)
- [Composer do chat — UX (Bloco 1)](./chat-composer-ux/requirements.md)
- [Renderização de assistant messages (Bloco 2)](./assistant-message-rendering/requirements.md)
- [Registro de alimentos](./food-logging/requirements.md)
- [Leitura de rótulo nutricional](./nutrition-label-ocr/requirements.md)
- [Registro de água pura](./water-tracking/requirements.md)
- [Registro de bebidas calóricas](./caloric-beverages/requirements.md)
- [Registro de atividade cardio](./activity-cardio-logging/requirements.md)
- [Correção de registros](./record-correction/requirements.md)
- [Remoção de registros](./record-deletion/requirements.md)
- [Snapshot diário](./daily-snapshot/requirements.md)
- [Encerramento de dia](./day-close/requirements.md)
- [Visão detalhada do dia (Bloco 6)](./daily-detail-view/requirements.md)
- [Relatório semanal](./weekly-report/requirements.md)
- [PWA — instalabilidade + shell offline](./pwa-installability-offline/requirements.md)
- [Integração Anthropic](./anthropic-integration/requirements.md)
- [Storage de mídia (MinIO)](./media-storage/requirements.md)
- [Trilha de auditoria](./audit-trail/requirements.md)
- [Pipeline CI/CD](./deploy-pipeline-ci-cd/requirements.md)

### 🔶 Partial (1)

- [Recuperação manual de itens sem catálogo](./manual-catalog-recovery/requirements.md) — SP-140..142 em `feat/bloco-5-catalog-recovery` (T-B510..T-B513 e T-B520 commitados; fluxo end-to-end ainda em revisão pré-merge).

### 📄 Documented Only (2)

- [Treino estruturado (sessão → exercícios → séries)](./workout-session-tracking/requirements.md) — SP-120..127 (Bloco 3) especificados desde v1.2 mas sem implementação; aguarda decisão de priorização pós Fase 10 e ADR-004.
- [Edição inline de registros no /day](./inline-record-editing/requirements.md) — SP-160..SP-169, INV-14 (Bloco 7) especificados em `specs/features/inline-record-editing/` (+ SDD rascunho em `specs/002-edicao-inline-day/`); estende §3.15 da spec 001 (página `/day`). Backend já tem PATCH food-items + PATCH nutrient-facts; faltam PATCH water/beverage/activity, propagação do nutrient-fact, e UI inline.

### ❌ Deprecated (0)

Nenhuma até o momento. Ver `Histórico de alterações` em `specs/001-mvp-registro-diario/spec.md` para SPs marcados como reformulados (não deprecados).

---

## Rastreabilidade — SP-XX → feature

Ordem numérica dos SPs para busca rápida a partir da spec canônica:

| SP-XX | Feature |
|---|---|
| SP-01..SP-06 | [authentication-session](./authentication-session/) |
| SP-10..SP-14 | [chat-messaging](./chat-messaging/) |
| SP-15..SP-19 | [chat-composer-ux](./chat-composer-ux/) |
| SP-20..SP-26 | [food-logging](./food-logging/) |
| SP-30..SP-35 | [nutrition-label-ocr](./nutrition-label-ocr/) |
| SP-40..SP-42 | [water-tracking](./water-tracking/) |
| SP-50..SP-52 | [caloric-beverages](./caloric-beverages/) |
| SP-60..SP-64 | [activity-cardio-logging](./activity-cardio-logging/) |
| SP-70..SP-74 | [record-correction](./record-correction/) |
| SP-80..SP-82 | [record-deletion](./record-deletion/) |
| SP-90..SP-92 | [daily-snapshot](./daily-snapshot/) |
| SP-100..SP-104 | [day-close](./day-close/) |
| SP-110..SP-113 | [weekly-report](./weekly-report/) |
| SP-115..SP-118 | [assistant-message-rendering](./assistant-message-rendering/) |
| SP-120..SP-127 | [workout-session-tracking](./workout-session-tracking/) |
| SP-128..SP-135 | [pwa-installability-offline](./pwa-installability-offline/) |
| SP-140..SP-142 | [manual-catalog-recovery](./manual-catalog-recovery/) |
| SP-150..SP-155 | [daily-detail-view](./daily-detail-view/) |
| SP-160..SP-169 | [inline-record-editing](./inline-record-editing/) |

## Invariantes globais → feature primária

| INV | Feature primária | Enforça em |
|---|---|---|
| INV-1 (LLM não faz cálculo) | [anthropic-integration](./anthropic-integration/) | food-logging, water-tracking, activity-cardio-logging |
| INV-2 (água ≠ macros) | [water-tracking](./water-tracking/) | caloric-beverages |
| INV-3 (bebida ≠ water_ml) | [caloric-beverages](./caloric-beverages/) | water-tracking |
| INV-4 (recompute from-scratch) | [daily-snapshot](./daily-snapshot/) | day-close, record-correction, record-deletion |
| INV-5 (dia fechado imutável) | [day-close](./day-close/) | record-correction, record-deletion |
| INV-6 (refresh reuse revoga família) | [authentication-session](./authentication-session/) | — |
| INV-7 (senhas nunca vazam) | [authentication-session](./authentication-session/) | admin-bootstrap-cli |
| INV-8 (semanal só dias fechados) | [weekly-report](./weekly-report/) | day-close |
| INV-9 (LLM só via tool_use) | [anthropic-integration](./anthropic-integration/) | — |
| INV-10 (audit total) | [audit-trail](./audit-trail/) | record-correction, record-deletion, food-logging, water-tracking, caloric-beverages, activity-cardio-logging |
| INV-11 (SW não cacheia /api/*) | [pwa-installability-offline](./pwa-installability-offline/) | — |
| INV-12/13 (workout invariantes) | [workout-session-tracking](./workout-session-tracking/) | — |
| INV-14 (edição de fact propaga a registros vivos) | [inline-record-editing](./inline-record-editing/) | record-correction, daily-snapshot |

---

## Próximos passos operacionais

1. Escolher a feature a documentar em cada rodada; começar por **stable** de maior valor (sugestões: `chat-messaging` como âncora do fluxo, `food-logging` por ser o coração do produto, `authentication-session` por ser o portal de entrada).
2. Ao gerar cada pasta, referenciar os arquivos-fonte de `apps/api/app/` e `apps/web/src/` para rastreabilidade.
3. Ao encerrar Bloco 3 (workout) ou nova feature, adicionar linha nova aqui e mover status.

## Referências cruzadas

- **Fonte contratual**: [`specs/001-mvp-registro-diario/spec.md`](../001-mvp-registro-diario/spec.md), [`plan.md`](../001-mvp-registro-diario/plan.md), [`tasks.md`](../001-mvp-registro-diario/tasks.md), [`research.md`](../001-mvp-registro-diario/research.md).
- **Constituição**: [`.specify/memory/constitution.md`](../../.specify/memory/constitution.md) — arts. I-X.
- **Design técnico canônico**: [`app_plan.md`](../../app_plan.md).
- **Runbook**: [`docs/deploy.md`](../../docs/deploy.md), [`docs/vps-digitalocean.md`](../../docs/vps-digitalocean.md), [`docs/pwa.md`](../../docs/pwa.md).
- **CHANGELOG**: [`CHANGELOG.md`](../../CHANGELOG.md).
