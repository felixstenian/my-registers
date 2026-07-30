# Arquitetura — Correção de registros

## Visão geral

Duas superfícies convergindo em mutação atômica + recompute + audit. **Chat**: LLM extrai intent, `TargetMatcher` resolve `target_hint` por scoring, `CorrectionService` aplica changes por kind com re-cálculo via `NutritionCalculator` (food/beverage) ou `ActivityCalculator` (activity), e persiste `audit_events(action='correct')` + `DailyRecomputeService.recompute`. **REST**: `PATCH /records/food-items/{id}` (só food) — usuário já sabe o ID; sem matcher; mesmo recompute + audit.

Design filosófico: **ambiguidade nunca muta**. Backend prefere `AmbiguousTarget` (que vira `clarify`) a adivinhar. Const. §5 puxa isso — LLM não pode desambiguar por conta própria.

## Componentes envolvidos

| Componente | Papel |
|---|---|
| `records.router` | `PATCH /records/food-items/{id}` (REST) e DELETEs (feature `record-deletion`) |
| `CorrectionService` | Aplica changes; audit; helpers por kind (`_apply_food_changes`, etc.) |
| `TargetMatcher` | Resolve `target_hint` string → `Candidate` UUID por scoring |
| `TargetKind` (StrEnum) | FOOD, WATER, BEVERAGE, ACTIVITY |
| `AmbiguousTarget`, `NoTargetFound`, `MatchError` | Exceptions do matcher |
| `DayClosedError` | Exception INV-5 |
| `NutritionCalculator.compute` | Recompute macros food/beverage |
| `ActivityCalculator.compute` | Recompute kcal_burned em activity |
| `AuditEventRepository.record` | Grava INV-10 |
| `DailyRecomputeService.recompute` | Recompute snapshot INV-4 |
| `MessageProcessor._handle_correct_record` | Wire-up chat → service |
| `normalize_name` (integrations/nutrition) | Tokenização + slugificação |

## Diagrama de contexto

```mermaid
graph TD
    U[Felix] -->|chat: "corrija arroz p/ 200g"| Chat[chat router]
    U -->|PATCH /records/food-items/ID| REST[records router]

    Chat --> MP[MessageProcessor]
    MP -->|intent=correct_record| HR[_handle_correct_record]
    HR --> CS[CorrectionService]
    CS --> TM[TargetMatcher]
    TM -->|tokenize + score| DB[(Postgres)]
    TM -->|Candidate | Ambiguous| CS
    CS -->|by kind| APP[_apply_*_changes helpers]
    APP -->|food/beverage| NC[NutritionCalculator]
    APP -->|activity| AC[ActivityCalculator]
    APP --> DB
    CS --> AUD[AuditEventRepository]
    AUD --> DB
    HR --> DR[DailyRecomputeService]
    DR --> DB

    REST -->|SELECT + ownership| DB
    REST -->|PATCH mutation| DB
    REST -->|catalog lookup| CAT[LocalTBCACatalog]
    REST --> NC
    REST --> AUD
    REST --> DR
```

## Diagrama de sequência — Correção via chat (happy path)

```mermaid
sequenceDiagram
    actor U as Felix
    participant MP as MessageProcessor
    participant AI as AnthropicClient
    participant CS as CorrectionService
    participant TM as TargetMatcher
    participant NC as NutritionCalculator
    participant AUD as AuditEvent
    participant DR as DailyRecomputeService
    participant DB as Postgres

    U->>MP: POST /chat/messages "corrija arroz do almoço p/ 200g"
    MP->>+AI: call_record_intent
    AI-->>-MP: envelope{intent=correct_record, correction:{target_hint, changes}}
    MP->>+CS: apply_from_llm(user, day_log_id, message_id, envelope)
    CS->>DB: session.get(DayLog, day_log_id)
    alt day_log.status='closed'
        CS-->>MP: raise DayClosedError
        MP->>DB: assistant fallback
    else open
        CS->>+TM: resolve(day_log_id, target_hint="arroz almoço")
        TM->>TM: _tokenize → {arroz, almoco}
        TM->>TM: _detect_kind → None (nenhuma keyword)
        TM->>TM: _detect_meal_slot → "lunch"
        TM->>DB: SELECT FoodItem JOIN FoodRecord WHERE day_log_id
        TM->>DB: SELECT water/beverage/activity (paralelo)
        TM->>TM: score por token overlap; +5 se meal_slot bate
        alt Ambíguo
            TM-->>CS: raise AmbiguousTarget
            CS-->>MP: propaga
        else Único winner
            TM-->>-CS: Candidate(kind=FOOD, entity=food_item)
            CS->>CS: before = _snapshot(entity, FOOD)
            CS->>CS: _apply_food_changes(changes={grams:200})
            CS->>+NC: compute(hit=lookup(catalog), grams=200)
            NC-->>-CS: ComputedNutrition
            CS->>DB: UPDATE food_items SET grams, kcal, macros, source='user_corrected', needs_confirmation=False
            CS->>CS: after = _snapshot(entity, FOOD)
            CS->>+AUD: record(action='correct', actor='llm', before, after)
            AUD->>DB: INSERT audit_events
            AUD-->>-CS: ok
            CS-->>-MP: CorrectionResult
        end
        MP->>+DR: recompute(day_log_id)
        DR->>DB: UPSERT daily_snapshots (version++)
        DR-->>-MP: snapshot novo
        MP->>DB: INSERT messages(assistant, content=confirmação SP-118)
    end
```

## Decisões de design

1. **Ambiguidade nunca muta**.
   - **Justificativa**: LLM pode achar que sabe qual item é, mas errar. Backend força desambiguação explícita.
   - **Consequência**: user pode precisar reformular; UX aceitável — melhor que mutação silenciosa errada.

2. **Score simples (token overlap + meal_slot bônus)**.
   - **Justificativa**: heurística barata que resolve maioria dos casos.
   - **Alternativa**: embedding similarity. Rejeitada — overkill para MVP; texto pt-BR simples.
   - **Consequência**: casos exóticos ("comida da hora do jogo") caem em ambiguo → user reformula.

3. **`_KIND_HINTS` filtra busca antes do score**.
   - **Justificativa**: user diz "corrija a água" → não faz sentido buscar em food. Filtro reduz falsos positivos.

4. **Empate no top score → `AmbiguousTarget` (não desambigua por kind)**.
   - **Justificativa**: se score empata entre food "cafe" e beverage "cafe", provavelmente user quer o que ele registrou mais recente / meal_slot específico. Sem info, aborta.

5. **Recompute obrigatório após correção com efeito real (INV-4)**.
   - **Justificativa**: sem recompute, `DayTotalsBar` mostra valores stale.

6. **Audit `action='correct'` com `_snapshot` por kind** (INV-10).
   - **Justificativa**: shape adaptado ao kind reduz campos irrelevantes (water não tem macros).

7. **`source='user_corrected'` só em FOOD/BEVERAGE**.
   - **Justificativa**: water não tem "fonte de dado" (é sempre volume); activity tem `calc_method` que já cobre.

8. **PATCH REST **também** faz `LocalTBCACatalog.lookup`** ao invés de assumir `catalog_ref_id`.
   - **Justificativa**: bug histórico do seed vazio deixou items órfãos. PATCH resolve retroativamente.
   - **Documentação**: `docs/pos-deploy-macros-fix.md`.

9. **PATCH sem mudança real → 200 sem audit**.
   - **Justificativa**: idempotência HTTP. Não polui audit.

10. **Chat sem mudança real → erro** (`correction_no_effect`).
    - **Justificativa**: assistant deve dizer "isso já está assim"; sinal de misinterpretation.

11. **Activity `kcal_burned_reported` como escape hatch**.
    - **Justificativa**: usuário confia mais no relógio dele que no cálculo MET. `calc_method='user_manual'` audita.

12. **weight_kg missing → warning, sem erro fatal**.
    - **Justificativa**: activity ainda pode ter duration/intensity mudados; kcal fica pendente.

## Padrões utilizados

- **Strategy por kind** (`_apply_food_changes`, `_apply_water_changes`, etc.).
- **Result object**: `CorrectionResult(kind, entity_id, changed_fields, warnings)`.
- **Exception hierarchy**: `MatchError > NoTargetFound | AmbiguousTarget`; `DayClosedError` separada.
- **DI**: `TargetMatcher(session)`, `CorrectionService(session)`.
- **Snapshot serialization**: `_snapshot(entity, kind)` produz dict para audit before/after.

## Segurança e autenticação

- **Auth**: `Depends(get_current_user)`.
- **Ownership**:
  - PATCH: `SELECT ... WHERE record.user_id = current_user.id` (JOIN garante).
  - Chat: `TargetMatcher` já filtra por `day_log_id` (que é do user).
- **Cross-user leak**: 404 genérico no PATCH; matcher nunca vê items de outros users.
- **INV-5 enforced antes de mutação**: `_ensure_day_open` no chat, `if status='closed'` no PATCH.

## Observabilidade

- **`audit_events`** é a fonte primária de "quem mudou o quê quando".
- **`snapshot.version`** cresce após cada correção com efeito.
- **Métricas potenciais** (não implementadas): rate de `AmbiguousTarget` (sinal de UX ruim), rate de `correction_no_effect` (sinal de misinterpretation).

## Ganchos com outras features

- **[`chat-messaging`](../chat-messaging/)**: entrada via `intent=correct_record`.
- **[`anthropic-integration`](../anthropic-integration/)**: envelope com `correction: CorrectionIn`.
- **[`food-logging`](../food-logging/), [`water-tracking`](../water-tracking/), [`caloric-beverages`](../caloric-beverages/), [`activity-cardio-logging`](../activity-cardio-logging/)**: kinds a corrigir.
- **[`daily-snapshot`](../daily-snapshot/)**: recompute pós-correção.
- **[`day-close`](../day-close/)**: produz `status='closed'` que bloqueia.
- **[`audit-trail`](../audit-trail/)**: consome `AuditEventRepository`.
- **[`assistant-message-rendering`](../assistant-message-rendering/)**: SP-117 modal usa PATCH endpoint.
- **[`manual-catalog-recovery`](../manual-catalog-recovery/)**: promoção reutiliza audit `action='correct'`.
