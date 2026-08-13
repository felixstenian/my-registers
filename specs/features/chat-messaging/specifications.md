# Especificações Técnicas — Chat e mensagens

> **Fontes**: `apps/api/app/api/routes/chat.py`, `apps/api/app/services/chat.py` (`ChatService`, `local_today`), `apps/api/app/services/message_processor.py` (~1274 linhas — orquestra LLM + dispatch + recompute + formatter), `apps/api/app/services/intent_dispatcher.py`, `apps/api/app/models/message.py`, `apps/api/app/schemas/chat.py`, `apps/web/src/app/(app)/chat/**` (frontend).

## Endpoints

### `POST /chat/messages`

- **Auth**: `access_token` válido.
- **Body** ([`PostMessageRequest`](../../../apps/api/app/schemas/chat.py)):
  ```json
  { "text": "150g arroz e 90g feijão", "media_ids": ["uuid1", "uuid2"] }
  ```
  - `text?`: `str | null`, `max_length=8000`.
  - `media_ids`: `list[UUID]`, default `[]`, `max_length=4`.
- **Response** (`202 Accepted`):
  ```json
  { "message_id": "user-msg-uuid", "status": "processing" }
  ```
- **Erros**:
  - `422 empty_message` — text vazio/None + sem media_ids.
  - `422 too_many_media` — > 4 IDs.
  - `422 unknown_media` — media não existe ou não é do current user.
  - `401 unauthorized` — sem cookie.

### `GET /chat/messages`

- **Auth**: mesma.
- **Query**:
  - `after?: UUID` — devolve messages com `id > after` (mensagens novas).
  - `before?: UUID` — devolve messages com `id < before` (paginação para histórico).
  - `limit: int = 50`, `[1..200]`.
- **Headers de resposta**: `Cache-Control: no-store` (obrigatório — polling da mesma URL era cacheado por browser sem esse header).
- **Response** (`200`):
  ```json
  {
    "messages": [
      {
        "id": "...",
        "role": "user" | "assistant",
        "content": "150g arroz e 90g feijão",
        "llm_intent": "log_food" | "clarify" | null,
        "llm_confidence": 0.85,
        "media": [{ "id": "...", "content_type": "image/jpeg", "url": "<presigned MinIO>" }],
        "created_at": "2026-07-28T15:30:00Z",
        "nutrient_fact_id": null
      }
    ]
  }
  ```

## Modelo de dados

### `messages`

Modelo: [`apps/api/app/models/message.py`](../../../apps/api/app/models/message.py)

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | UUID | PK |
| `user_id` | UUID FK users(id) ON DELETE CASCADE | Owner |
| `day_log_id` | UUID FK day_logs(id) ON DELETE SET NULL, NULL | Nulo pra mensagens legadas; SET NULL preserva histórico |
| `role` | text CHECK IN (`user`, `assistant`, `system`) | |
| `content` | text NULL | Texto (usuário digitou ou assistente gerou); `NULL` só em user com só media |
| `llm_intent` | text NULL | Preenchido em assistant messages (`log_food`, `clarify`, etc.) |
| `llm_model` | text NULL | Ex.: `claude-sonnet-4-6` |
| `llm_prompt_version` | text NULL | Ex.: `system_v2` |
| `llm_confidence` | numeric(3,2) NULL | 0..1 |
| `raw_llm_response` | JSONB NULL | Envelope + dispatch metadata para debug/auditoria |
| `tokens_input`, `tokens_output` | integer NULL | Uso |
| `created_at` | timestamptz DEFAULT now() | Ordem cronológica |

### `message_media` (association)

Modelo: [`apps/api/app/models/message_media.py`](../../../apps/api/app/models/message_media.py) — tabela associativa `(message_id, media_id)`. Ordem preservada pela criação.

## Fluxo de dados

### `POST /chat/messages` — path completo

```
POST /chat/messages { text, media_ids }
  ├─ Depends(get_current_user, get_session, get_anthropic_client_dep,
  │           get_storage_dep, get_session_factory_dep, BackgroundTasks)
  ├─ ChatService.post_user_message(user, text, media_ids):
  │     ├─ text_stripped = (text or "").strip() or None
  │     ├─ if text_stripped is None and not media_ids → 422 empty_message
  │     ├─ if len(media_ids) > 4 → 422 too_many_media
  │     ├─ if media_ids: resolved = MediaRepository.list_by_ids(ids, user_id=user.id)
  │     │   └─ len mismatch → 422 unknown_media (Const. §21)
  │     ├─ day_log = DayLogRepository.get_or_create(user_id, log_date=local_today(user.timezone))
  │     ├─ message = MessageRepository.create(user_id, day_log_id, role='user', content)
  │     └─ if media_ids: MessageRepository.link_media(message.id, deduped_ids)
  ├─ await session.commit()      # OBRIGATÓRIO antes de agendar background
  ├─ background_tasks.add_task(
  │     run_processor_in_background,
  │     message.id,
  │     session_factory=session_factory,     # nova sessão para o worker
  │     anthropic_client=..., storage=...
  │   )
  └─ 202 { message_id, status: "processing" }
```

### `run_processor_in_background` (~1274 linhas em `message_processor.py`)

Sequência aproximada (referência: `MessageProcessor.process(message_id)`):

```
process(message_id):
  ├─ session = session_factory()
  ├─ message = SELECT messages WHERE id
  ├─ user = SELECT users WHERE id = message.user_id
  ├─ Carregar histórico curto (últimas N msgs do user) para dar contexto à LLM
  ├─ Baixar mídias vinculadas via storage.get_object(media.storage_key)
  ├─ Chamar AnthropicClient.call_record_intent(user_text=message.content, images=[...])
  │   → LLMCallResult (envelope | error)
  ├─ Gravar em message: llm_model, llm_prompt_version, tokens_*, raw_llm_response
  ├─ if error: assistant message fallback SP-14
  │   → INSERT messages(role=assistant, content="Não consegui interpretar...")
  ├─ else if envelope.needs_clarification (SP-13) ou intent=clarify/unknown:
  │   → assistant clarify
  ├─ else: IntentDispatcher.handle(envelope, user, day_log, message):
  │       ├─ intent=log_food → MealService.create_from_llm
  │       ├─ intent=log_water → HydrationService
  │       ├─ intent=log_beverage → BeverageService
  │       ├─ intent=log_activity → ActivityService
  │       ├─ intent=log_nutrition_label → LabelCatalogService
  │       ├─ intent=correct_record → CorrectionService
  │       ├─ intent=delete_record → DeletionService
  │       ├─ intent=confirm_items → ConfirmationService
  │       ├─ intent=close_day → DayCloseService.close_date
  │       └─ etc.
  ├─ DailyRecomputeService.recompute(day_log_id) → snapshot atualizado
  ├─ MessageFormatter.compose_meal / _water / _beverage / _activity / _close ...
  │   → assistant text (SP-118 markdown)
  ├─ INSERT messages(role=assistant, content=text, llm_intent, llm_confidence, dispatch data)
  └─ session.commit()
```

Cliente polling faz `GET /chat/messages?after=<user_msg_id>` até assistant chegar.

### `GET /chat/messages`

```
GET /chat/messages?after=<id>&limit=50
  ├─ Header Cache-Control: no-store (bug prevention)
  ├─ ChatService.list_messages(user, after_id, before_id, limit):
  │   ├─ MessageRepository.list_messages(user_id, after_id, before_id, limit)
  │   │   └─ ordenação cronológica ASC
  │   └─ load_media_map([m.id for m in rows])
  ├─ Para cada message:
  │   ├─ Para cada media: storage.presigned_get_url(media.storage_key)
  │   ├─ Se llm_intent='log_nutrition_label' e raw_llm_response.dispatch.nutrient_fact_id:
  │   │     nutrient_fact_id = valor (SP-33 — inline confirm de rótulo)
  │   └─ construir MessageOut
  └─ 200 { messages: [...] }
```

## Regras de negócio

1. **`text` só vale trimmed**: espaços em branco puros contam como vazio. Texto vazio + mídia é OK.
2. **Media ownership**: `MediaRepository.list_by_ids(ids, user_id=user.id)` — se count mismatch, erro genérico `unknown_media` (não vaza se existe pra outro user).
3. **Deduplicação de media_ids**: `list(dict.fromkeys(media_ids))` preserva ordem, remove duplicatas.
4. **`day_log` criado sob demanda**: primeira mensagem do dia dispara `get_or_create`. Nunca vem 404 pra "hoje".
5. **Commit antes de agendar background**: FastAPI `BackgroundTasks` roda **após** response ser enviada mas **dentro** do request. Sessão do request pode ainda commitar; mas para segurança, `session.commit()` explícito antes de `add_task` garante que o worker (com sua própria sessão) veja a mensagem.
6. **`day_log_id` em message é opcional**: FK `SET NULL` — mensagens de dias historicamente deletados sobrevivem como registro.
7. **Assistant message NÃO tem media**: por design; só texto (markdown SP-118).
8. **Presigned URL da média** é gerada por request de listagem (~1h TTL). Não faz cache.
9. **`raw_llm_response` inclui `dispatch` custom** para intents que precisam expor IDs ao cliente (ex.: `nutrient_fact_id` do SP-33 para o botão de confirmação inline).
10. **Isolamento estrito**: `user_id` obrigatório em toda query (MessageRepository, MediaRepository, DayLogRepository).

## Configurações e variáveis de ambiente

Nenhuma específica; reutiliza `DATABASE_URL`, `MINIO_*`, `ANTHROPIC_*` de outras features.

## Referências de implementação

- **Rotas**: [`app/api/routes/chat.py`](../../../apps/api/app/api/routes/chat.py) (~110 linhas).
- **Service HTTP**: [`app/services/chat.py`](../../../apps/api/app/services/chat.py) (~94 linhas — `ChatService`, `MessageWithMedia`, `local_today`).
- **Processor**: [`app/services/message_processor.py`](../../../apps/api/app/services/message_processor.py) (~1274 linhas — orquestra tudo depois do 202).
- **Dispatcher**: [`app/services/intent_dispatcher.py`](../../../apps/api/app/services/intent_dispatcher.py) (~74 linhas — roteia envelope pra service).
- **Formatter**: [`app/services/message_formatter.py`](../../../apps/api/app/services/message_formatter.py) — compõe assistant text por intent.
- **Modelo message**: [`app/models/message.py`](../../../apps/api/app/models/message.py).
- **Modelo message_media**: [`app/models/message_media.py`](../../../apps/api/app/models/message_media.py).
- **Schemas**: [`app/schemas/chat.py`](../../../apps/api/app/schemas/chat.py) — `PostMessageRequest`, `PostMessageResponse`, `MediaRef`, `MessageOut`, `MessagesListResponse`.
- **Testes**: [`apps/api/tests/test_chat.py`](../../../apps/api/tests/test_chat.py) (13 casos — POST, GET, paginação, ownership de media).
