# Critérios de Aceitação — Encerramento de dia

## AC-001 — Fechamento via REST (SP-100)

**Dado que** dia atual está `open` com food_items registrados
**Quando** `POST /days/2026-07-28/close`
**Então** 200 com body:
- `status: "closed"`
- `closed_at` timestamp UTC
- `narrative` termina com o disclaimer legal
- `snapshot_version` incrementado (recompute rodou)
- `was_already_closed: false`
**E** DB: `day_log.status='closed'`, `day_log.closed_at != NULL`, `daily_snapshots.narrative` populada

---

## AC-002 — Fechamento via chat (SP-100)

**Dado que** LLM devolve `intent=close_day`
**Quando** `_handle_close_day` roda
**Então** `DayCloseService.close_today(user, message_id)` executa
**E** assistant message criada com:
- `content = <narrative com disclaimer>`
- `llm_intent = 'close_day'`
- `raw_llm_response.dispatch = { action: 'close_day', was_already_closed: false }`

**Notas**: `test_day_close_report.py::test_close_day_via_chat_intent`.

---

## AC-003 — Idempotência (SP-101)

**Dado que** dia já está `closed` (`closed_at=T`, narrative gravada)
**Quando** `POST /days/{date}/close` de novo
**Então**:
- 200 com `was_already_closed: true`
- `day_log.closed_at` **inalterado** (ainda T)
- `daily_snapshots.narrative` **inalterada** (não chama LLM)
- Nenhum novo `audit_events` gravado

**Notas**: `test_close_day_idempotent_second_call_does_not_change_state`.

---

## AC-004 — Recompute forçado antes do close (SP-102, INV-4)

**Dado que** snapshot v3 existe mas está stale (algum recompute anterior falhou — teste manipula via UPDATE direto)
**Quando** close roda
**Então** recompute é chamado antes de setar `status='closed'`
**E** snapshot v4 refletindo estado real dos records
**E** `snapshot.version = 4`

**Notas**: `test_close_forces_recompute_before_freezing`.

---

## AC-005 — Narrativa recebe totais pré-calculados (SP-103, INV-1)

**Dado que** snapshot final tem `kcal_in=1750, water_ml=2000`
**Quando** `call_narrative` é invocada
**Então** `totals_payload` inclui exatamente esses valores (não a LLM adivinhando)
**E** `warning_codes` inclui só códigos (`no_catalog_hit`, `needs_confirmation`), não IDs

**Notas**: `test_narrative_receives_precomputed_totals`.

---

## AC-006 — Disclaimer sempre presente (SP-104)

**Dado que** LLM devolve texto simples sem disclaimer
**Quando** `_with_disclaimer` roda
**Então** narrativa final termina com `\n\nAs estimativas nutricionais são aproximações e não substituem acompanhamento médico ou nutricional.`

**Notas**: `test_narrative_always_ends_with_disclaimer`.

---

## AC-007 — Disclaimer não duplica (SP-104)

**Dado que** LLM já incluiu o texto exato do disclaimer
**Quando** `_with_disclaimer` roda
**Então** narrativa **não** duplica; retorna a string sem alteração.

**Notas**: `test_disclaimer_not_duplicated_if_llm_returns_it`.

---

## AC-008 — Disclaimer em erro de LLM

**Dado que** `AnthropicClient.call_narrative` devolve `text=None` (erro)
**Quando** `_generate_narrative` roda
**Então** retorna `_FALLBACK_NARRATIVE`
**E** `_with_disclaimer` adiciona disclaimer
**E** `snapshot.narrative` final termina com disclaimer.

**Notas**: `test_narrative_disclaimer_present_even_on_llm_error`.

---

## AC-009 — Correção em dia fechado bloqueada (INV-5)

**Dado que** dia D está `closed`
**Quando** user envia "corrija arroz do dia D para 200g" via chat
**Então** `CorrectionService` retorna erro (dia fechado)
**E** assistant devolve "Dia já fechado; crie novo registro hoje" ou similar

**Notas**: `test_closed_day_blocks_new_food_correction`.

---

## AC-010 — Deleção em dia fechado bloqueada (INV-5)

**Dado que** dia D está `closed`
**Quando** user tenta deletar item de D
**Então** `DeletionService` bloqueia; 409 ou fallback

**Notas**: `test_closed_day_blocks_deletion`.

---

## AC-011 — Snapshot de dia fechado é congelado (INV-5)

**Dado que** dia D fechado com `snapshot.kcal_in=1000`
**Quando** algo altera valores no DB (ex.: seed catálogo muda kcal do arroz)
**Então** `GET /days/{D}` continua retornando `kcal_in=1000`
**E** recompute NÃO é chamado on-read

**Notas**: `test_closed_day_snapshot_reads_are_frozen`.

---

## AC-012 — Audit event no fechamento (INV-10)

**Dado que** dia é fechado
**Então** exatamente 1 linha em `audit_events` com:
- `entity_type='day_log'`
- `entity_id=day_log.id`
- `action='close'`
- `actor='user'`
- `before={"status": "open"}`
- `after={"status": "closed", "closed_at": <iso>, "snapshot_version": <int>}`

**Notas**: `test_close_records_audit_event`.

---

## AC-013 — Query day retorna totais via chat

**Dado que** user manda "totais de hoje" (`intent=query_day`)
**Quando** processor roda
**Então** assistant message retorna tabela SP-118 com totais + status atual (open/closed)

**Notas**: `test_query_day_intent_returns_totals_via_chat`.

---

## AC-014 — Aproximação (≈) quando itens pendentes

**Dado que** snapshot tem items com `needs_confirmation=true`
**Quando** narrativa/tabela é composta
**Então** prefixo `≈` aparece nos totais (SP-118).

**Notas**: `test_query_day_shows_approx_when_pending_items`.

---

## AC-015 — Encerramento retroativo (SP-155 v1.11)

**Dado que** hoje é 28/jul e dia 27/jul está `open`
**Quando** `POST /days/2026-07-27/close`
**Então** 200 (backend não restringe a "hoje")
**E** dia 27 fica `closed`.

---

## Cenários de borda

| Cenário | Comportamento esperado |
|---|---|
| Dia sem records + close | Snapshot zerado; narrativa curta ou fallback; disclaimer presente |
| LLM configurada mas API key inválida | `call_narrative` devolve `error='anthropic_status_401'`; fallback textual |
| Anthropic returns whitespace-only text | Trata como `text=None`; fallback |
| Dia fechado sem snapshot (anomalia) | `_require_snapshot` faz recompute forçado só para devolver totals coerentes |
| POST em data futura | `get_or_create` cria day_log com `log_date=futuro`; snapshot vazio; feche mesmo assim. UX preveniu no frontend (`/day/[date]` bloqueia futuro em SP-155) |
| Concorrência: 2 requests simultâneos de close | 1º ganha (marca closed); 2º pega `status='closed'` no reload e vira idempotência |
| `snapshot.narrative` já existente + `was_already_closed=true` mas string vazia | `snapshot.narrative or _FALLBACK` cobre |

## Critérios de não-funcionalidade

| Critério | Threshold | Fonte |
|---|---|---|
| Latência P95 close (com narrative LLM) | ≤ 3s | RNF-001 |
| Latência idempotente 2ª chamada | ≤ 100ms | RNF-001 |
| Cobertura `DayCloseService` | ≥ 90% | RNF-003 |
| Disclaimer presente | 100% dos casos | RF-007 |
| INV-5 enforce em outras features | 100% (correção, deleção) | RF-015 |
