# Arquitetura — Renderização de assistant messages (Bloco 2)

> **Rastreabilidade**: SP-115..SP-118 · Backend `apps/api/app/services/{message_formatter,message_processor}.py` · Frontend `apps/web/src/app/(app)/chat/{AssistantContent,DayTotalsBar,PendingItemsModal,page}.tsx`.

## Visão geral

O Bloco 2 é um contrato markdown entre backend determinístico e frontend renderizador:

- **Backend** (`message_formatter`) converte o resultado determinístico de cada intent (já calculado por `nutrition_calculator`/`activity_calculator` — Art. II) em duas tabelas markdown pt-BR + disclaimer + warnings opcionais. O texto gerado é salvo como `assistant_message.content`.
- **Frontend** (`AssistantContent`) faz parse mínimo do markdown (dialecto conhecido: bold, tabelas 2-cols, parágrafos) e renderiza como cards — sem biblioteca externa.
- **Barra** (`DayTotalsBar`) consulta `/days/today` e revalida via `revalidateKey` propagado pelo poll do `ChatPage`.
- **Modal** (`PendingItemsModal`) torna a confirmação/descarte de itens pendentes inline.

Sem estado de cálculo no frontend — toda aritmética é backend (INV-1, Art. II).

## Componentes envolvidos

| Componente | Responsabilidade | Tecnologia |
|---|---|---|
| `message_formatter.py` | Gerar markdown pt-BR determinístico das assistant messages | Python, `Decimal` |
| `MessageProcessor._handle_registration` | Delegar à `compose_*` correta após intent | Python |
| `AssistantContent.tsx` | Parser + render do markdown em cards | React 19 client |
| `DayTotalsBar.tsx` | Barra fixa de totais; revalida via `revalidateKey` | React 19 client |
| `PendingItemsModal.tsx` | Modal confirm/discard de itens pendentes | React 19 client |
| `ChatPage` (host) | Integra componentes; propaga `totalsRevalidateKey`/`pendingItems` | React 19 client |
| `CorrectionService` (route `/confirm`) | Desmarca `needs_confirmation`; grava audit | Python |
| `DeletionService` (`DELETE /records/food-items/{id}`) | Soft delete + recompute + audit | Python |
| `nutrition_calculator`/`activity_calculator` | Cálculos determinísticos (Art. II) | Python |
| `days.py` route | `GET /days/today` — fonte dos totais da barra | FastAPI |
| `api-client.ts` (`api<T>`) | Wrapper fetch com cookie, erros tipados | TypeScript |

## Diagrama de contexto

```mermaid
graph TD
    User[Felix] --> Chat[ChatPage client]
    Chat -->|POST /chat/messages| API[FastAPI chat-messaging]
    API --> MP[MessageProcessor]
    MP --> Fmt[message_formatter compose_*]
    Fmt -->|grava assistant_message.content| DB[(Postgres)]
    Chat -->|poll GET /chat/messages?after=| API
    API --> DB
    Chat --> AssistantContent[render do content markdown]
    Chat --> Bar[DayTotalsBar]
    Bar -->|GET /days/today| API
    Bar -->|revalidateKey incrementado pelo poll| Chat
    Bar -. badge pendentes .-> Modal[PendingItemsModal]
    Modal -->|POST /confirm| RecordsAPI[FastAPI records routes]
    Modal -->|DELETE /food-items/{id}| RecordsAPI
```

## Diagrama de sequência — registro + barra + confirmação inline

```mermaid
sequenceDiagram
    actor User
    participant Chat as ChatPage
    participant API as FastAPI
    participant Fmt as message_formatter
    participant Bar as DayTotalsBar
    participant Modal as PendingItemsModal
    User->>Chat: envia mensagem
    Chat->>API: POST /chat/messages
    API->>Fmt: compose_meal(meal, recompute, log_date)
    Fmt-->>API: markdown pt-BR
    API->>API: persiste assistant_message
    API-->>Chat: { message_id }
    Chat->>Chat: startPolling
    poll loop 1500ms
        Chat->>API: GET /chat/messages?after=
        API-->>Chat: assistant message
    end
    Chat->>Chat: totalsRevalidateKey++
    Chat->>Bar: revalidateKey mudou
    Bar->>API: GET /days/today
    API-->>Bar: totals + records.food
    Bar-->>User: kcal_in/macros + badge pendentes
    User->>Bar: clica badge
    Bar->>Modal: onPendingClick(items)
    User->>Modal: Confirma item
    Modal->>API: POST /food-items/{id}/confirm
    API-->>Modal: 200 {already_confirmed}
    Modal->>Chat: onChanged()
    Chat->>Bar: totalsRevalidateKey++
    Bar->>API: GET /days/today
    Bar-->>User: badge some
```

## Decisões de design

1. **Backend gera markdown, frontend só renderiza**: garante que valores numéricos (kcal/g/ml) são sempre determinísticos (Art. II). UI não formata números — o faz só backend `_fmt_*`. A barra usa `Intl.NumberFormat('pt-BR')` apenas porque não recebe markdown da API (recebe JSON cru de totais).

2. **Dialeto markdown controlado**: parser client minimalista, sem `react-markdown`/`marked`. Justificativa: o conteúdo sempre vem do `message_formatter`, então o subconjunto suportado é fixo (bold, tabelas 2-cols, parágrafos). Bundle enxuto, sem NPM dependency.

3. **`revalidateKey` prop pattern em vez de SWR/React Query state**: o poll do `ChatPage` já sabe quando a assistant chegou; incrementando um int no parent e passando como prop, evita bibliotecas de fetch/state. Simples e suficiente.

4. **`POST /confirm` dedicado (não PATCH)**: SP-117 original previa `PATCH /records/food-items/{id}` re-enviando valores, mas items só com `quantity` viravam no-op. Endpoint dedicado só desmarca `needs_confirmation` sem recompute de macros (item já tem valores quando criado), idempotente. Referência: comment no topo do `PendingItemsModal.tsx`.

5. **Modais (PendingItems, CloseDay) reusados**: `PendingItemsModal` de Bloco 2 e `CloseDayModal` de T-704 são hospedados em `ChatPage`; `CloseDayButton`/`CloseDayModal` são reusados em `/day` (Bloco 6). Decisão de co-localização evita duplicar overlay/trap.

6. **Nenhum cálculo no `compose_*` além de somas de items da mensagem**: as tabelas "Total da refeição" somam apenas os items desta mensagem (não o dia); a tabela "Total acumulado" vem do `snapshot` já recomputeado. Espelha INV-4 (recompute do zero antes da resposta).

7. **`_warnings_block` dedup preservando ordem**: garante "feijão, sushi ninja" sem repetir "feijão" se aparece em multiple warnings.

## Padrões utilizados

- **Backend**: funções puras (`_fmt_*`, `_table`) — testáveis isoladamente; `_has_approx_food_items` centraliza regra do `≈`.
- **Frontend**: componentes client controlados via props (`revalidateKey`, callbacks); state local só em `ChatPage` (host pattern).
- **Markdown**: variantpt restrito (2 cols, header fixo `Indicador|Total`).
- **Acessibilidade**: `role="dialog"`/`aria-modal`/`aria-label` no modal; `aria-live`/`aria-label` implícito no `TypingIndicator` do Bloco 1.

## Segurança e autenticação

- **Cookie `access_token`** em todas as chamadas client (`api` wrapper, `credentials: 'include'` implícito).
- **Isolamento por usuário** (Art. V §21): `GET /days/today`, `POST /confirm`, `DELETE /food-items/{id}` todas filtram por `user_id` no repositório.
- **INV-5 (dia fechado imutável)**: backend rejeita mutate em `status='closed'`; a UI não dispara action porque a barra não mostra botão "Confirmar/Descartar" (item ainda aparece como pendente mas bloqueado — fluxo via chat responder "dia já encerrado").
- **Audit (INV-10)**: confirm e discard gravam `audit_events` com before/after/actor/message_id no backend.

## Observabilidade

- **Logs**: backend loga requests via `X-Request-Id` (middleware global); front não propaga o header explicitamente.
- **Métricas**: nenhuma client-side; backend instrumenta routes.
- **Traces**: [Inferido do código] — sem telemetria dedicated para Latência de render; polling cap 60s visível em `POLL_CAP_MS`. <!-- TODO: adicionar Sentry/analytics front _anganese -->
- **Erros**: `api-client` retorna `{ ok: false, error }`; modal seta `busyId` para feedback visual; usuário fecha/reabre manualmente.