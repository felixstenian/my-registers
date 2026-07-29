# Requisitos — Integração Anthropic

> **Rastreabilidade**: Const. Art. II §5-7 · INV-1, INV-9 · Uso primário em [`food-logging`](../food-logging/), [`water-tracking`](../water-tracking/), [`caloric-beverages`](../caloric-beverages/), [`activity-cardio-logging`](../activity-cardio-logging/), [`nutrition-label-ocr`](../nutrition-label-ocr/), [`record-correction`](../record-correction/), [`record-deletion`](../record-deletion/) · Segunda chamada (narrativa) em [`day-close`](../day-close/) e [`weekly-report`](../weekly-report/) · ADR-002 em [`research.md`](../../001-mvp-registro-diario/research.md) · Otimizações em [`docs/token-optimization-plan.md`](../../../docs/token-optimization-plan.md).

## Visão geral

Camada única de integração com a Anthropic Claude para todas as chamadas de LLM do sistema. **A LLM só interpreta e narrativa; nunca calcula** (Const. Art. II §5, INV-1). Três chamadas típicas por operação de negócio:

1. **`call_record_intent`** — classifica a mensagem do usuário e extrai payload estruturado via `tool_use` forçado com JSON schema Pydantic. Retorno em texto livre é **descartado** (INV-9). Usa Sonnet 4.6 quando há foto ou texto longo; Haiku 4.5 (~4× mais barato) para texto curto puro.
2. **`call_narrative`** — segunda chamada em `POST /days/{date}/close` (SP-103): sem `tool_use`, `temperature=0.3`, sobre **totais já calculados** pelo backend. Sempre Sonnet.
3. **`call_weekly_narrative`** — análoga para `GET /weekly` (SP-111): 7 dias fechados agregados.

Otimizações Tier 1 do plano de tokens: cache ephemeral (system prompt + tool schema), compressão de imagem (Pillow 1024px + JPEG q=75), roteamento Sonnet vs. Haiku, 1 retry semântico (ao invés de 2).

## Requisitos funcionais

| ID | Requisito | Referência | Prioridade |
|---|---|---|---|
| RF-001 | Chamar Anthropic via `tool_use` forçado (`tool_choice={type:tool, name:record_intent}`). Se resposta não contém bloco `tool_use` de nome esperado, tratar como `no_tool_use` e responder ao usuário genericamente. | INV-9, Const. §7 | Must Have |
| RF-002 | Payload da tool validado por `LLMEnvelope.model_validate(tool_input)` (Pydantic v2). Falha de validação dispara retry semântico com feedback (até `max_semantic_retries=1`). | Const. §5 | Must Have |
| RF-003 | Após esgotar retries semânticos → `error=validation_exhausted`, `envelope=None`, `raw_tool_input` preservado para debug. | Robustez | Must Have |
| RF-004 | Roteamento por complexidade: fotos ou texto > 500 chars → `model` (Sonnet); texto curto puro → `fallback_model` (Haiku). Fallback é ~4× mais barato. | Custo | Should Have |
| RF-005 | Sem `api_key` configurado → `is_configured=False`; callers devolvem `error='anthropic_not_configured'` sem bater na rede (útil em CI/dev). | Dev-UX | Must Have |
| RF-006 | Timeouts HTTP: SDK Anthropic com `timeout=60s`, `max_retries=2` (5xx/429 backoff). Timeout expirado → `error='anthropic_timeout'`. | Confiabilidade | Must Have |
| RF-007 | `APIStatusError` (4xx) → log estruturado com body + `error='anthropic_status_{code}'`. `APIError` genérico → `anthropic_error`. | Observabilidade | Must Have |
| RF-008 | Compressão de imagem: qualquer bloco de foto passa por `PIL.Image` → longest-side ≤ 1024px + JPEG q=75. Se falhar, envia original (não trava). | Custo | Should Have |
| RF-009 | Cache ephemeral (`cache_control={"type":"ephemeral"}`) no system prompt e no tool schema — reduz input tokens em chamadas subsequentes na mesma conversa. | Custo | Should Have |
| RF-010 | Log estruturado por chamada com `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `model`, `attempt`, `images` — permite medir hit rate do cache. | Observabilidade | Should Have |
| RF-011 | Retry semântico envia de volta o `tool_use` limpo (`_clean_content_for_retry`) + `tool_result` com `is_error=True` explicando falhas de validação. Haiku 4.5 rejeita metadata `caller` do SDK — remoção obrigatória. | Correção | Must Have |
| RF-012 | `call_narrative` (SP-103): sem `tool_use`, `temperature=0.3`, `max_tokens=400`, Sonnet fixo. Payload = `{totals_calculated}`. Sem tokens output = `empty_narrative`. | SP-103 | Must Have |
| RF-013 | `call_weekly_narrative` (SP-111): mesma forma; `max_tokens=500`, prompt `weekly_narrative_v1.md`. | SP-111 | Must Have |
| RF-014 | Prompts como arquivos versionados (`prompts/system_v2.md`, `narrative_v1.md`, `weekly_narrative_v1.md`), carregados com `@lru_cache`. | Manutenibilidade | Must Have |
| RF-015 | `PROMPT_VERSION` exposto em cada `LLMCallResult` — auditoria de qual prompt gerou qual resposta. | Auditabilidade | Must Have |

## Requisitos não funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | Cliente é substituído por fake em testes via `app.dependency_overrides`. Fixtures em `tests/fixtures/anthropic/*.json` (CLAUDE.md convenção). | Testabilidade |
| RNF-002 | Cobertura de contrato: qualquer teste de service (`test_meal_service`, `test_hydration_beverage_activity`, `test_day_close_report`) continua verde ao substituir o cliente por mock que devolve JSON lixo — INV-1 estrutural. | Qualidade |
| RNF-003 | Latência ponta-a-ponta P50: texto puro ≤ 6s, foto ≤ 12s; P99 ≤ 20s (SP §4.2). | Performance |
| RNF-004 | `anthropic_api_key` nunca em log ou em resposta HTTP (Const. §19, INV-7). | Segurança |
| RNF-005 | Fotos enviadas em base64, nunca URL (Const. §26, privacidade). | Privacidade |
| RNF-006 | Zero fallback silencioso quando LLM falha semanticamente — resposta ao usuário é sempre "Não consegui interpretar; pode reformular?" (SP-14). | UX previsível |

## Restrições e premissas

- **Modelos pinados**: `ANTHROPIC_MODEL=claude-sonnet-4-6` (padrão), `ANTHROPIC_FALLBACK_MODEL=claude-haiku-4-5-20251001`. Ver `research.md` ADR-002.
- **`tool_choice` forçado** — texto livre da LLM é sempre descartado (Const. §7).
- **Fotos ≤ 8MB pré-compressão** (SP-11). Compressão típica reduz 5-11K tokens → 500-1500.
- **`extra="ignore"`** em sub-payloads (`FoodItemIn`, `BeverageIn`, `ActivityIn`) — LLM inventa campos comuns; permitimos.
- **Single request user** — sem streaming SSE no MVP. Backend responde `assistant_message` completo via polling (SP-10).
- **Single Anthropic account/API key** — nenhuma feature de multi-tenancy.

## Dependências

**Depende de:**
- `anthropic` SDK oficial (`AsyncAnthropic`).
- `Pillow` para compressão de imagem.
- `pydantic` para validação estrita do envelope.
- Config em [`app/core/config.py`](../../../apps/api/app/core/config.py) (chaves `anthropic_*`).

**Requerido por:**
- Todas as features de log (food/water/beverage/activity/label).
- [`chat-messaging`](../chat-messaging/) — `MessageProcessor` chama `call_record_intent`.
- [`day-close`](../day-close/) — `DayCloseService` chama `call_narrative`.
- [`weekly-report`](../weekly-report/) — `WeeklyReportService` chama `call_weekly_narrative`.
- [`record-correction`](../record-correction/), [`record-deletion`](../record-deletion/) — dispatchers routing por `intent`.
