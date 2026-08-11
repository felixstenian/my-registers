# Especificações Técnicas — Encerramento de dia

> **Fontes**: `apps/api/app/services/day_close.py` (~187 linhas), `apps/api/app/api/routes/days.py` (`POST /days/{log_date}/close`), `apps/api/app/services/message_processor.py::_handle_close_day` (~linha 514), `apps/api/app/integrations/anthropic/prompts/narrative_v1.md`.

## Endpoints / Interface

### `POST /days/{yyyy-mm-dd}/close`

- **Auth**: `access_token` válido.
- **Path param**: `log_date: date`.
- **Body**: vazio.
- **Sucesso** (`200 OK`):
  ```json
  {
    "date": "2026-07-28",
    "status": "closed",
    "closed_at": "2026-07-28T23:45:00Z",
    "totals": { ... },
    "records": { ... },
    "warnings": [ ... ],
    "narrative": "Dia positivo com déficit calórico moderado...\n\nAs estimativas nutricionais são aproximações e não substituem acompanhamento médico ou nutricional.",
    "snapshot_version": 12,
    "was_already_closed": false
  }
  ```
- **Idempotente**: 2ª chamada em dia já `closed`:
  - Não regrava `closed_at`.
  - Não regenera narrativa (retorna a já persistida).
  - `was_already_closed=true`.

### Intent `close_day` via chat

- Trigger: LLM classifica mensagem como `intent=close_day` (ex.: "encerrar dia", "fechar dia", "finalizar dia").
- `MessageProcessor._handle_close_day(user_message, result)` chama `DayCloseService.close_today(user, message_id=user_message.id)`.
- Assistant message renderiza a narrativa (com disclaimer).

## Modelo de dados

### Mutações em `day_logs` e `daily_snapshots`

- `day_logs.status`: `open` → `closed`.
- `day_logs.closed_at`: NULL → `datetime.now(UTC)`.
- `daily_snapshots.narrative`: NULL → texto com disclaimer.
- `daily_snapshots.version`: incrementa via recompute.

### Nova entrada em `audit_events`

```python
audit_events(
    user_id=user.id,
    entity_type="day_log",
    entity_id=day_log.id,
    action="close",
    actor="user",
    message_id=<da mensagem de chat, se disparado por chat>,
    before={"status": "open"},
    after={"status": "closed", "closed_at": <iso>, "snapshot_version": <int>}
)
```

## Fluxo de dados

### Path completo (via REST)

```
POST /days/{yyyy-mm-dd}/close
  ├─ Depends(get_current_user, get_session, get_anthropic_client_dep)
  ├─ DayCloseService.close_date(user, log_date, message_id=None):
  │     ├─ day_log = DayLogRepository.get_or_create(user_id, log_date)
  │     ├─ if day_log.status == "closed":       # SP-101 idempotência
  │     │     ├─ snapshot = _require_snapshot(day_log.id)
  │     │     │     ├─ SELECT WHERE day_log_id
  │     │     │     └─ if None (anomalia): recompute forçado
  │     │     └─ return DayCloseResult(day_log, snapshot,
  │     │             narrative=snapshot.narrative or _with_disclaimer(_FALLBACK),
  │     │             was_already_closed=True)
  │     ├─ recompute = DailyRecomputeService.recompute(day_log.id)  # SP-102
  │     ├─ narrative_text = _generate_narrative(day_log, recompute):
  │     │     ├─ if anthropic is None or not is_configured → _FALLBACK_NARRATIVE
  │     │     ├─ payload = _totals_for_narrative(day_log, recompute)
  │     │     │     → {date, kcal_in, ..., water_ml, other_liquids_ml, warning_codes[]}
  │     │     ├─ result = anthropic.call_narrative(totals_payload=payload)
  │     │     └─ result.text or _FALLBACK
  │     ├─ narrative_full = _with_disclaimer(narrative_text)
  │     │     → SP-104: adiciona "\n\n{DISCLAIMER}" se ainda não presente
  │     ├─ recompute.snapshot.narrative = narrative_full
  │     ├─ day_log.status = "closed"
  │     ├─ day_log.closed_at = datetime.now(UTC)
  │     ├─ session.flush()
  │     ├─ AuditEventRepository.record(entity=day_log, action='close', before, after)
  │     └─ return DayCloseResult(..., was_already_closed=False)
  ├─ payload = DayQueryService.get_by_date(user, log_date, allow_recompute=False)
  └─ 200 DayCloseOut
```

### Path via chat

```
POST /chat/messages { text: "encerrar dia" }
  ├─ 202 { message_id }
  ├─ MessageProcessor.process(message.id):
  │   ├─ LLM devolve intent=close_day
  │   └─ _handle_close_day(user_message, result):
  │       ├─ DayCloseService.close_today(user, message_id=user_message.id)
  │       ├─ Assistant text = `narrative` do resultado
  │       └─ INSERT messages(role=assistant, content=narrative, llm_intent='close_day', raw_llm_response.dispatch = {action: 'close_day', was_already_closed})
```

## Regras de negócio

1. **`get_or_create` do day_log**: fechar dia sem registros é OK — resultado é snapshot zerado + narrativa curta.
2. **Idempotência estrita (SP-101)**: `if day_log.status == "closed"` → **NÃO** recomputa, **NÃO** regenera narrativa, **NÃO** grava audit. Retorna estado atual + `was_already_closed=True`.
3. **Recompute obrigatório antes do close (SP-102, INV-4)**: até o momento do close, snapshot pode estar stale (recompute falhou em request anterior?). Fechar é o "commit final" — precisa refletir realidade.
4. **Narrativa sobre totais já calculados (SP-103, INV-1)**: `call_narrative` recebe payload com valores; prompt (`narrative_v1.md`) instrui "use exatos".
5. **Fallback textual**: `_FALLBACK_NARRATIVE = "Dia encerrado com os totais registrados no chat. Se algum item ainda precisar de confirmação, você pode ajustar amanhã, mas hoje já está fechado."` — nunca deixamos `narrative=None`.
6. **Disclaimer via `_with_disclaimer`**:
   - Se já contém o texto exato do disclaimer → não duplica.
   - Se não contém → adiciona `\n\n{DISCLAIMER}` no final.
   - **Sempre** presente na `narrative_full` gravada.
7. **Congelamento em transação única**: `session.flush()` antes do `audit.record()`. `daily_snapshots.narrative` + `day_log.status/closed_at` gravam juntos.
8. **INV-5 fora do escopo desta feature**: bloqueio de correção/deleção acontece nos services correspondentes; aqui só produzimos o estado `closed`.
9. **`warning_codes` na narrativa**: só códigos (`no_catalog_hit`, `needs_confirmation`, ...), sem IDs internos ou nomes. LLM não precisa saber referências para gerar texto.
10. **Sem reabertura**: `status='closed'` é terminal. Const. §28 literal.

## Configurações e variáveis de ambiente

Nenhuma específica; reutiliza `ANTHROPIC_*`.

## Referências de implementação

- **Service**: [`app/services/day_close.py`](../../../apps/api/app/services/day_close.py) (~187 linhas — `DayCloseService`, `DayCloseResult`, `_with_disclaimer`, `_totals_for_narrative`).
- **Rota**: [`app/api/routes/days.py`](../../../apps/api/app/api/routes/days.py) (POST /days/{log_date}/close).
- **Chat integração**: [`app/services/message_processor.py`](../../../apps/api/app/services/message_processor.py) `_handle_close_day` (~linha 514).
- **Prompt**: [`app/integrations/anthropic/prompts/narrative_v1.md`](../../../apps/api/app/integrations/anthropic/prompts/narrative_v1.md).
- **Schema**: [`app/schemas/days.py`](../../../apps/api/app/schemas/days.py) — `DayCloseOut`.
- **Testes**: [`apps/api/tests/test_day_close_report.py`](../../../apps/api/tests/test_day_close_report.py) (13 casos cobrindo idempotência, recompute forçado, disclaimer, bloqueio INV-5, audit).
