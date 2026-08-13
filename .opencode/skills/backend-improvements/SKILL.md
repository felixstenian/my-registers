---
name: backend-improvements
description: Use when reviewing, auditing, or refactoring the FastAPI + SQLAlchemy 2 async backend in apps/api (app/ and tests/). Covers architectural layering (routes → services → repositories), async correctness, SQLAlchemy 2 patterns, LLM/determinism boundaries, error handling, and test coverage per the Constitution. Triggers on requests like "review the backend", "find improvements in apps/api", "audit services/repositories", or when touching .py files under apps/api/app.
---

# Back-end improvements (apps/api)

Aplica-se apenas ao back-end em `apps/api` (FastAPI + Pydantic v2 + SQLAlchemy 2 async + Alembic + Anthropic + MinIO). **Não use** para o front-end `apps/web` nem para configuração do próprio opencode.

## Quando ativar

- O usuário pede revisão/auditoria/refatoração do back-end, ou cita `apps/api`, `services`, `repositories`, `routes`, `models`, "melhorias no backend", ou arquivos `.py` sob `apps/api/app`.
- O usuário está editando arquivos sob `apps/api/app` (ou `apps/api/tests`) e pede sugestões de melhoria.
- **Não ativar** para: front-end Next.js, infra Docker/Nginx puramente, docs SDD sem código, ou config do opencode.

## Escopo de categorias (priorize nesta ordem)

1. **Arquitetura & camadas** — fluxo routes → services → repositories → models, isolamento de domínio.
2. **Constituição & invariantes** — Art. I-X e INV-N (a maior fonte de bugs neste repo).
3. **Async / SQLAlchemy 2** — patterns async/await, sessões, queries, N+1.
4. **LLM vs determinismo** — fronteira LLM interpreta / backend calcula (Art. II).
5. **Erros, validação & edge cases** — `AppError`, handler global, status codes, 401/403/409.
6. **Testes** — cobertura por SP-XX/INV-N, mocks Anthropic, fixtures Postgres real.

## Stack e regras fixas (não inventar)

Confirmar lendo o código antes de sugerir — não assumir bibliotecas não presentes em `apps/api/pyproject.toml`:

- **FastAPI ≥0.115**, **Pydantic v2 ≥2.9**, **SQLAlchemy 2 async ≥2.0.36** (`asyncpg`), **Alembic ≥1.14,<1.16** (pin ADR-003 — não sugerir 1.16+), **Anthropic ≥0.39**, **boto3/MinIO**, **Pillow**, **Typer** (CLI), **httpx**.
- **Python 3.12** (`>=3.12,<3.13`) — não sugerir features de 3.13+.
- Lint/format: `ruff` (line-length 100, target py312; regras `E,F,I,UP,B,SIM`; `B008` ignorado em `app/api/**/*.py` porque FastAPI usa `Depends/Cookie/Query` como default). Type check: `mypy app`.
- Testes: `pytest` com `asyncio_mode = "auto"`, Postgres real (`registers_test`), `conftest.py` roda migrations em subprocess. **INV-N → integração com Postgres real, nunca mock. SP-XX must → unit + integração.**
- Modelo Anthropic padrão: `claude-sonnet-4-6`; fallback: `claude-haiku-4-5-20251001`. Não trocar sem ADR.
- Layering canônico: `api/routes/` (HTTP) → `services/` (regras de negócio) → `repositories/` (acesso ao DB) → `models/` (SQLAlchemy). Integrações externas em `integrations/{anthropic,storage,nutrition}/`. Config via `pydantic-settings` em `app/core/config.py`.
- Código/comentários em **inglês**; docs SDD e commits em **pt-BR** (regra do repo). Não adicionar comentários ao código a menos que o usuário peça.
- `pyproject.toml` declara `[tool.uv] package = false` — o `app/` é importável como `app.*` mas não é um pacote distribuível.

## Princípios da Constituição que mudam decisões de código

Estes são **não-negociáveis** — uma melhoria que os viola é na verdade um bug:

- **LLM interpreta, backend calcula** (Art. II §5). LLM só classifica intenção, extrai itens estruturados (via `tool_use` com JSON schema Pydantic) e gera narrativa **sobre números já calculados**. Toda soma nutricional é determinística no backend (`nutrition_calculator.py`, `activity_calculator.py`, `daily_recompute.py`). Texto livre da LLM é descartado. Um teste deve continuar verde ao trocar o cliente Anthropic por mock que devolve lixo.
- **Snapshots recomputam do zero** (Art. III §10, INV-4). Ao criar/corrigir/deletar registro, o snapshot do dia é `SELECT`/`SUM` completo sobre tabelas cruas (`deleted_at IS NULL`) e recomputa — nunca delta incremental. Cada recompute incrementa `version`. Se vir lógica "somar delta ao snapshot anterior", é bug.
- **Auditoria total** (Art. III §11). Toda mutação em registro de negócio grava linha em `audit_events` com `before`, `after`, `actor`, `message_id`. Se um service muta sem gravar audit, é bug.
- **Água ≠ outros líquidos** (Art. IV §12-14, INV-2/INV-3). `water_records` só água pura (sem kcal); bebidas calóricas vão em `beverage_records`. `IntentDispatcher` valida essa separação. Não sugerir unificar as tabelas.
- **`user_id` em toda query de repositório** (Art. V §21). Não existe query que ignore isolamento por usuário. Se um repo method não recebe/filtra `user_id`, é bug.
- **Sem endpoints HTTP de cadastro/reset de usuário** (Art. V §18). Criação/reset de usuário é exclusivamente CLI (`app/cli`). Não sugerir `POST /users`.
- **Bootstrap é CLI idempotente** (Art. VI §24). Runtime da API **não** roda migrations; deploy chama `alembic upgrade head` como passo explícito. Senha nunca em migration; admin default lido do ambiente pelo `app.cli bootstrap`. Não sugerir rodar migrations no `lifespan` do FastAPI.
- **Dia `status='closed'` é imutável** (Art. VIII §28, INV-5). Mutação em dia fechado → `ConflictError(code="conflict_closed_day")`. Reabertura não existe no MVP; encerrar dia já fechado retorna snapshot atual sem regravar `closed_at`.
- **Aviso legal obrigatório** (Art. VII §26) em toda resposta de dia/semana. Se um route/serializer de dia ou semana não incluir, é bug.
- `Decimal` para macros/micros/kcal — não `float` (precisão de cálculo nutricional). Exceções pontuais documentadas.

## Checklist de análise

Para cada arquivo sob revisão, percorra:

### Arquitetura & camadas
- Route deve ser fino: parse de payload (`Depends`, modelos Pydantic), chamar service, mapear `AppError` → HTTP. Não conter regras de negócio nem SQL direto.
- Service orquestra repositórios + calculadoras, aplica invariantes, dispara recompute/auditoria. Não conhece HTTP (sem `Request`/`Response`/status codes diretos — só via `AppError`).
- Repository emite queries SQLAlchemy, retorna models. Não contém regras de domínio. Todo método recebe `user_id` (Art. V §21).
- `models/` só definição SQLAlchemy + `__init__` reexport — sem lógica.
- `integrations/` encapsula Anthropic/MinIO/TBCA; service consome via client injetado (`get_anthropic_client_dep`, `get_storage_dep`). Não importar `anthropic`/`boto3` diretamente em service.
- Tarefas de background não podem usar a sessão de request (já fechada) — usar `get_session_factory_dep()` (`deps.py:31`).
- Evitar `Any` em schemas/respostas; preferir tipos Pydantic espelhando o domínio. Se aparecer `dict[str, Any]` em resposta de route, sugerir model concreto.

### Constituição & invariantes
- Toda mutação em `food_records`/`food_items`/`water_records`/`beverage_records`/`activity_records` dispara `DailyRecomputeService.recompute(day_log_id)` (Art. III §10).
- Toda mutação grava `AuditEvent` com `before`/`after` (Art. III §11).
- Queries de repositório sempre filtram por `user_id`. Conferir `delete`, `update`, `get_by_id` — não só `list`.
- `water_records` sem kcal/macros; `beverage_records` pode ter kcal (Art. IV). Se vir `kcal` em `WaterRecord`, é bug.
- Dia `closed` → mutação rejeitada com `ConflictError(code="conflict_closed_day")` (Art. VIII).
- Resposta de dia (`/days/...`) e semana (`/weekly/...`) inclui disclaimer (Art. VII §26).

### Async / SQLAlchemy 2
- Toda chamada DB é `await`. `session.execute()`, `session.flush()`, `session.commit()` — nunca esquecer `await` (silencioso em alguns casos).
- Não usar `session.query(...)` (estilo 1.x) — usar `select(...)` + `session.execute()`.
- `AsyncSession` via `get_session()` em routes; commit no fim do yield, rollback em exceção (`deps.py:37`). Não chamar `commit()` dentro de service (quebra o contrato do yield).
- `populate_existing=True` em `RETURNING` de upsert para evitar snapshot cacheado no identity map (padrão já em `daily_recompute.py:115`).
- N+1: se um service loopa sobre rows e dispara query por item, sugerir `selectinload`/`joinedload` ou query em batch (ex.: `load_media_map` em `chat.py:93`).
- `Decimal` from DB: conferir conversão — `Decimal(value or 0)`, não `float(value)`.
- Transações explícitas só em backgrounds; no request, a sessão do `get_session()` já é a transação.

### LLM vs determinismo
- `nutrition_calculator.py` e `activity_calculator.py` não chamam LLM. Se vir import de `anthropic` nesses arquivos, é bug (Art. II).
- Clientes LLM em `integrations/anthropic/` retornam `LLMEnvelope` (Pydantic) via `tool_use`; texto livre é descartado. Se um service usar `anthropic` texto direto, é bug.
- Mock de Anthropic em testes: fixtures em `tests/fixtures/anthropic/*.json`. Um teste que bateria no cliente real deve mockar. Se um teste `test_*.py` que depende de LLM não está mockando, flag.
- Fallbacks de intent (`intent_dispatcher.py`) são mensagens em 2ª pessoa dirigidas ao usuário; `user_text_summary` é 3ª pessoa para auditoria — não vazar como conteúdo do assistant.

### Erros, validação & edge cases
- Erros de domínio herdam de `AppError` (`core/exceptions.py`), nunca `HTTPException` direto em service. Handler global em `main.py:47` traduz para JSON `{"code","message"}`.
- Mapear `DayClosedError` → `ConflictError(code="conflict_closed_day")` na borda da route (padrão `records.py:69`).
- `NotFoundError` para IDs inexistentes; `ForbiddenError` para acesso a recurso de outro user (embora isolamento por `user_id` deva evitar chegar aqui); `ValidationAppError` para invariantes de payload.
- `get_current_user` (`deps.py:58`) levanta `UnauthorizedError` se token faltar/inválido/user inativo. Não duplicar essa checagem em routes.
- 401 vs 403: falta token → 401; token válido mas recurso de outro user → 403 (ou 404 se não quiser vazar existência — o repo já filtra por `user_id`, então 404 é o efeito comum).
- `DELETE` idempotente (SP-81): 2ª chamada retorna 200 com `already_deleted: true`, não 404. Padrão em `records.py:75`.
- `get_client_ip`/`get_user_agent` em `deps.py` para rate limit/auditoria — não reimplementar.

### Testes
- INV-N → integração com Postgres real (conftest já sobe `registers_test` + migrations). Nunca mockar DB para INV.
- SP-XX must → unit de service + integração ponta-a-ponta (route → service → repo → DB).
- LLM → sempre mockar `anthropic`; fixtures em `tests/fixtures/anthropic/*.json`.
- Cobertura mínima MVP: 80% em `app/services/`; 90% em `nutrition_calculator.py` e `activity_calculator.py`. Se uma melhoria adicionar comportamento, sugerir testes para manter a cobertura.
- Toda nova migration precisa de teste que valide o schema/estado — não sugerir migration sem teste.
- `conftest.py` roda migrations em subprocess para isolar `asyncio.run` do env.py do event loop do pytest-asyncio — não sugerir rodar migrations no mesmo loop.

## Como reportar (sempre em pt-BR)

Para cada melhoria encontrada, liste:

```
[severidade] arquivo:linha — título
Problema: <o que está errado, em 1-2 frases>
Sugestão: <como corrigir, com snippet se útil>
Risco: <baixo/médio/alto + por que>
```

Severidades:
- **bloqueante** — viola Constituição (Art. I-X) ou INV-N, ou bug funcional que quebra snapshot/auditoria/isolamento.
- **alta** — bug de runtime provável, race async, N+1 gritante, erro não tratado, quebra de contrato de camada.
- **média** — manutenibilidade, query ineficiente sem ser N+1, DRY gritante, falta de teste para novo comportamento.
- **baixa** — nitpick de estilo, micro-otimização sem medição, typing mais estrito.

Se a melhoria tocar um **Artigo da Constituição ou INV-N**, citar explicitamente (ex.: "viola Art. III §10 / INV-4 — snapshot deve recomputar do zero").

## Aplicação de fixes (fluxo "Relatar + propor fix")

1. Rode `uv run ruff check && uv run mypy app` antes de sugerir qualquer fix para ter baseline.
2. Relate **todas** as melhorias (não apenas as que vai aplicar).
3. Proponha fixes apenas para melhorias **triviais e seguras** (ex.: `await` faltando, `user_id` faltando em filtro, falta de `AuditEvent` em mutação pontual, query que carrega relação desnecessária).
4. **Não aplique** automaticamente:
   - Mudanças em `daily_recompute.py` (lógica de snapshot, Art. III §10).
   - Mudanças em `nutrition_calculator.py`/`activity_calculator.py` (determinismo, Art. II).
   - Mudanças em `intent_dispatcher.py` que alterem fallbacks de UX (SP-13).
   - Novas migrations Alembic (precisam de teste + revisão manual).
   - Mudanças em `conftest.py` (risco de quebrar todos os testes).
   - Mudanças que toquem invariantes (INV-N) ou separação água/bebida (Art. IV).
   - Refactors que movem lógica entre camadas (route ↔ service ↔ repo).
5. Antes de aplicar, mostre o diff proposto e aguarde confirmação.
6. Após aplicar, rode `uv run ruff check && uv run mypy app && uv run pytest` (ou o subconjunto relevante: `uv run pytest tests/test_daily_recompute.py -q`).
7. Nunca commitar — o usuário decide. Nunca rodar `alembic revision --autogenerate` sem confirmação explícita.

## Armadilhas conhecidas deste repo

- `daily_recompute.py` usa `pg_insert.on_conflict_do_update` com `RETURNING + populate_existing=True` — não trocar por "select-then-update" (race + identity map staleness).
- `get_session()` faz commit no yield exit; service que chama `session.commit()` internamente quebra o rollback automático.
- `DayClosedError` é de `services/correction.py`, mapeado para `ConflictError` na route — não lançar `ConflictError` dentro de service (acopla domínio a HTTP).
- `IntentDispatcher._STRUCTURED_INTENTS` está vazio por design (Fase 4.b cobre tudo no `MessageProcessor`) — não preencher sem ADR.
- `conftest.py` seta env vars antes de importar `app` (porque `get_settings` é `@lru_cache`) — não reordenar imports.
- Alembic pinado `<1.16` (ADR-003) — não sugerir upgrade.
- `B008` ignorado em `app/api/**` (FastAPI `Depends` como default) — não "corrigir".
- `pyproject.toml` declara `package = false` sob `[tool.uv]` — não sugerir empacotar.
- Backend roda no host (não no Docker) por causa do bug `EDEADLK` no bind mount do macOS (ADR-008) — não sugerir migrar backend para Docker.

## Referências rápidas

- `apps/api/app/main.py` — `create_app()`, middlewares, exception handler global.
- `apps/api/app/api/deps.py` — `get_session`, `get_current_user`, `get_storage_dep`, `get_anthropic_client_dep`, `get_session_factory_dep` (backgrounds).
- `apps/api/app/core/exceptions.py` — `AppError` + subclasses (`NotFound`, `Unauthorized`, `Forbidden`, `ValidationApp`, `RateLimited`, `Conflict`).
- `apps/api/app/services/daily_recompute.py` — snapshot from-scratch (Art. III §10).
- `apps/api/app/services/nutrition_calculator.py` — cálculo determinístico (Art. II).
- `apps/api/app/services/intent_dispatcher.py` — fallbacks UX (SP-13).
- `apps/api/tests/conftest.py` — Postgres real + migrations subprocess.
- `.specify/memory/constitution.md` — fonte canônica dos Artigos I-X e INV-N.
- `specs/001-mvp-registro-diario/spec.md` — SP-01..SP-113 + invariantes.
