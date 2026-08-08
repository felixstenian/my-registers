# Requisitos — Encerramento de dia + narrativa LLM

> **Rastreabilidade**: SP-100..SP-104 em [`spec.md §3.11`](../../001-mvp-registro-diario/spec.md#311-encerramento-do-dia) · Const. Art. VIII §28-29, Art. VII §26 · Invariantes INV-4, INV-5, INV-10 · Aciona chamada [`anthropic-integration.call_narrative`](../anthropic-integration/) e força recompute em [`daily-snapshot`](../daily-snapshot/).

## Visão geral

Encerrar o dia é a única operação que muda `day_log.status` de `open` para `closed` e congela `daily_snapshots.narrative`. Idempotente (Const. §29): 2ª chamada não regrava `closed_at` nem sobrescreve narrativa. Força recompute antes do fechamento (INV-4) e gera narrativa curta via LLM sobre totais **já calculados** (INV-1). Disclaimer legal obrigatório concatenado pelo backend (Const. §26). Após fechado, correção e deleção são bloqueadas em `record-correction`/`record-deletion` (INV-5).

## Requisitos funcionais

| ID | Requisito | SP | Prioridade |
|---|---|---|---|
| RF-001 | `POST /days/{yyyy-mm-dd}/close` endpoint autenticado; aceita hoje ou dias passados. | SP-100 | Must Have |
| RF-002 | Aciona também por chat com intent `close_day` ("Encerrar dia", "fechar o dia") via `MessageProcessor._handle_close_day`. | SP-100 | Must Have |
| RF-003 | Idempotente: 2ª chamada em dia já `closed` retorna `was_already_closed=True` sem regravar `closed_at`, sem regenerar narrativa. | SP-101, Const. §29 | Must Have |
| RF-004 | Antes de congelar: força `DailyRecomputeService.recompute(day_log.id)` para garantir totais atualizados. | SP-102, INV-4 | Must Have |
| RF-005 | Após recompute: gera narrativa via `AnthropicClient.call_narrative(totals_payload)` sobre totais já calculados. LLM não recalcula. | SP-103, INV-1 | Must Have |
| RF-006 | Se LLM falhar (`is_configured=False`, `text=None`, timeout): usar `_FALLBACK_NARRATIVE` textual — nunca deixar `narrative=None` ou "erro". | SP-14, resiliência | Must Have |
| RF-007 | Disclaimer legal concatenado (`"As estimativas nutricionais são aproximações..."`) sempre; nunca duplicar se LLM já incluiu. | SP-104, Const. §26 | Must Have |
| RF-008 | Setar `day_log.status='closed'`, `closed_at=now(UTC)`; salvar `snapshot.narrative` com disclaimer. | SP-100 | Must Have |
| RF-009 | Gravar `audit_events(entity_type='day_log', action='close', actor='user', before={status:open}, after={status:closed, closed_at, snapshot_version})`. | INV-10 | Must Have |
| RF-010 | `get_or_create` do `day_log` — permite fechar dia sem registros (snapshot zerado). | SP-100 | Should Have |
| RF-011 | Dia fechado sem snapshot (situação anômala) → recompute forçado só para devolver totals coerentes ao usuário. | Correção | Should Have |
| RF-012 | Payload da narrativa contém `date, kcal_in, kcal_out, kcal_balance, macros, water_ml, other_liquids_ml, warning_codes[]` — **só códigos** de warning, sem IDs internos. | Privacy | Must Have |
| RF-013 | Endpoint retorna 200 com shape completo do dia (via `DayQueryService.get_by_date(allow_recompute=False)`) + `narrative` + `was_already_closed`. | SP-103 | Must Have |
| RF-014 | Frontend: botão "Encerrar dia" em `/chat` (na `DayTotalsBar`) e em `/day` (SP-155 estende para `/day/[date]` com dia passado aberto). | Fase 7 T-704, SP-155 | Should Have |
| RF-015 | Após close, correção e deleção de records daquele dia retornam 409 `conflict_closed_day` (implementado em [`record-correction`](../record-correction/) e [`record-deletion`](../record-deletion/)). | INV-5, Const. §28 | Must Have |
| RF-016 | Reabertura de dia fechado **não existe** no MVP — sem endpoint, sem intent, sem CLI. | Const. §28 | Must Have |

## Requisitos não funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | Latência de fechamento P95 ≤ 3s (recompute ~10ms + LLM narrative ~2-3s). | Performance |
| RNF-002 | Determinístico: dado o mesmo snapshot final, o disclaimer é sempre igual; narrativa pode variar. | Correção |
| RNF-003 | Cobertura mínima do `DayCloseService`: 90% (crítico para INV-5). | Qualidade |
| RNF-004 | Isolamento por usuário via `Depends(get_current_user)`. | Segurança |
| RNF-005 | LLM não pode escrever nada em `daily_snapshots` além de `narrative` — enforced por design (só o backend seta os campos numéricos). | INV-1 |

## Restrições e premissas

- **`get_or_create` do day_log**: permite fechar dia sem registros (snapshot zerado). UX: "só quero fechar" mesmo sem input.
- **`_generate_narrative` retorna string, não `None`**: fallback textual protege consumidor.
- **Fechamento por chat** e **por REST** compartilham `DayCloseService.close_date`; único ponto de mudança.
- **INV-5 é enforçado em outros services** (correction, deletion), não aqui. `DayCloseService` só produz o `status='closed'`; quem bloqueia mutation é `CorrectionService`, `DeletionService`, etc.
- **Anthropic pode falhar**: cliente já cobre com `error` + `text=None`; service cai no fallback sem levantar exception.
- **Sem "reabrir"**: não existe endpoint, intent, CLI. Const. §28 é literal. Se alguém adicionar, quebrar teste `test_closed_day_blocks_*`.

## Dependências

**Depende de:**
- [`daily-snapshot`](../daily-snapshot/) — `DailyRecomputeService.recompute` obrigatório antes de congelar.
- [`anthropic-integration`](../anthropic-integration/) — `call_narrative` (sem tool_use, temperature=0.3).
- [`authentication-session`](../authentication-session/) — `Depends(get_current_user)`.
- [`chat-messaging`](../chat-messaging/) — quando disparado via intent `close_day`.
- [`daily-detail-view`](../daily-detail-view/) SP-155 — botão em `/day/[date]` para encerramento retroativo.

**Requerido por:**
- [`record-correction`](../record-correction/) — verifica `day_log.status='closed'` → 409.
- [`record-deletion`](../record-deletion/) — idem.
- [`weekly-report`](../weekly-report/) — só considera dias `closed` (INV-8, SP-110).
- [`daily-snapshot`](../daily-snapshot/) — leitura de dia fechado nunca recomputa (INV-5).
