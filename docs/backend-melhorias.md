# Levantamento de melhorias — back-end (`apps/api`)

Data: 2026-07-30 · Escopo: `apps/api` (FastAPI + Pydantic v2 + SQLAlchemy 2 async + Alembic + Anthropic + MinIO)

Levantamento estático do back-end em busca de melhorias de código e boas práticas, organizado em **tarefas BE-XX para implementação posterior**. Nenhuma alteração de código foi aplicada neste levantamento (análise read-only por camada + verificação manual dos pontos acusados pelo mypy).

## Baseline executado

| Check | Resultado |
|---|---|
| `uv run ruff check` | ❌ 7 erros `I001` (imports não ordenados) em `alembic/env.py` + 6 migrations — todos auto-corrigíveis com `ruff check --fix` |
| `uv run mypy app` | ❌ 15 erros em 8 arquivos — mix de bugs reais de tipagem e falsos positivos do SDK/stubs (detalhados nas tarefas) |
| Constituição (Art. I-X / INV-N) | 1 violação confirmada (Art. VII §26 — disclaimer ausente em `GET /days`) + 1 bug funcional de cálculo nutricional |

## Convenções deste documento

- **Severidades**: `bloqueante` (viola Constituição/INV ou bug funcional de cálculo/audit/isolamento) · `alta` (bug de runtime provável, race, erro externo não tratado, quebra de contrato de camada) · `média` (manutenibilidade, performance perceptível, DRY, typing) · `baixa` (nitpick, micro-otimização).
- **Risco**: chance de a correção introduzir regressão.
- IDs `BE-XX` são locais deste documento, sem relação com os `T-XXX` do `tasks.md` SDD.
- Tarefas marcadas **🛑 toca INV/Constituição** exigem revisão manual cuidadosa e, em geral,.spec/plan antes do `feat:` (fluxo SDD canônico).

## Restrições que NENHUMA tarefa pode violar

- **Art. II §5**: cálculo nutricional é determinístico no backend; LLM só interpreta. Nenhuma tarefa move soma para a LLM.
- **Art. III §10 / INV-4**: snapshot recomputa do zero (SELECT/SUM sobre `deleted_at IS NULL`), nunca delta. `daily_recompute.py` não é tocado por refactor incremental sem ADR.
- **Art. III §11**: toda mutação em registro de negócio grava `AuditEvent`.
- **Art. IV**: `water_records` (sem kcal) ≠ `beverage_records`. Não unificar.
- **Art. V §21**: `user_id` em toda query de repositório.
- **Art. V §18**: sem endpoints HTTP de cadastro/reset de usuário (só CLI).
- **Art. VI §24**: runtime não roda migrations; senha nunca em migration.
- **Art. VIII / INV-5**: dia `closed` é imutável; reabertura não existe no MVP.
- **Alembic pinado `<1.16`** (ADR-003); backend no host (ADR-008); `B008` ignorado em `app/api/**`.

---

## Prioridade 0 — severidade bloqueante

### BE-01 — 🛑 Aviso legal ausente em `GET /days/today` e `GET /days/{date}` (Art. VII §26)

**Severidade**: bloqueante · **Risco**: baixo

**Achados cobertos**:

```
[bloqueante] app/schemas/days.py:34-43 — DaySnapshotOut não carrega o disclaimer
Problema: GET /days/today e GET /days/{date} retornam totais nutricionais (kcal, macros,
micros) sem o aviso legal obrigatório. O disclaimer só é concatenado ao campo `narrative`
em day_close.py / weekly_report.py / message_formatter.py — e `narrative` é `None` em dias
abertos sem fechamento. Logo a resposta de dia aberto nunca carrega o aviso.
Sugestão: adicionar campo `disclaimer: str` a `DaySnapshotOut` (e `DayCloseOut` herda),
populado na rota a partir de uma constante centralizada (hoje o texto está duplicado em
3 services). Criar `app/core/legal.py` com `NUTRITIONAL_DISCLAIMER` e referenciar.
Risco: baixo — adição de campo, sem mudar lógica de cálculo.
```

**Arquivos**: `app/schemas/days.py`, `app/api/routes/days.py`, `app/api/routes/weekly.py`, `app/schemas/weekly.py` (verificar se `WeeklyReportOut` também expõe disclaimer via `narrative` apenas). Criar `app/core/legal.py`.

**Notas**: confirmar com a spec se o disclaimer em dia fechado (via `narrative`) atende §26 ou se o campo dedicado deve aparecer em toda resposta. Recomendado: campo dedicado sempre presente, independente de `narrative`.

---

### BE-02 — 🛑 PATCH de food-item sem catálogo zera os macros e marca como confirmado

**Severidade**: bloqueante · **Risco**: médio

**Achados cobertos**:

```
[bloqueante] app/api/routes/records.py:180-203 — PATCH sem hit de catálogo sobrescreve macros com 0
Problema: ao corrigir `grams`/`ml` de um item cujo `catalog_ref_id` é NULL (estimativa da
LLM sem catálogo), `NutritionCalculator.compute(hit=None, ...)` retorna todos os macros
zerados (nutrition_calculator.py:65-66). O loop das linhas 191-202 sobrescreve kcal/
protein_g/etc. do item com zeros e a linha 203 baixa `needs_confirmation` incondicionalmente.
A estimativa original é perdida e o recompute (linha 233) propaga os zeros ao snapshot.
O usuário corrige uma quantidade e o item fica com 0 kcal "confirmado".
Sugestão: só aplicar o `computed` e baixar a flag quando `hit is not None`:
    if hit is not None:
        if item.catalog_ref_id is None:
            item.catalog_ref_id = uuid.UUID(hit.fact_id)
        computed = NutritionCalculator.compute(hit=hit, grams=item.grams, ml=item.ml)
        ...setattr loop...
        item.needs_confirmation = False
    # hit None: manter valores atuais (ou escalar pela razão novo/velho grams)
Risco: médio — precisa definir o comportamento esperado do item sem catálogo no PATCH
(zerar é claramente errado; manter / escalar são opções — alinhar com a spec SP-XX).
```

**Arquivos**: `app/api/routes/records.py` (linhas ~180-203). Indireto: `app/services/nutrition_calculator.py` (apenas leitura — não alterar a calculadora).

**Notas**: esta tarefa está entrelaçada com BE-03 (a lógica está na rota). Recomenda-se extrair para `CorrectionService.patch_food_item` (BE-03) e lá corrigir o `hit None`, com teste de service + integração cobrindo o cenário "item sem catálogo". 🛑 Toca cálculo nutricional (Art. II) — definir comportamento com a spec antes de codar.

---

## Prioridade 1 — severidade alta

### BE-03 — Regra de negócio e SQL direto dentro de rotas (`patch_food_item`, `confirm_food_item`, `nutrient_facts` PATCH)

**Severidade**: alta · **Risco**: médio

**Achados cobertos**:

```
[alta] app/api/routes/records.py:126-240 — route executa query SQLAlchemy, lookup de
catálogo, cálculo nutricional, auditoria e recompute
Problema: viola o layering canônico (route fina → service). `patch_food_item` faz
`select(...)` direto (linhas 140-145, 154), lookup de catálogo (186-189),
NutritionCalculator.compute (190-203), AuditEvent (223-232) e recompute (233). O mesmo
padrão se reparte em `confirm_food_item` (278-314) e `nutrient_facts.py:47-87`. A
checagem de dia fechado é reimplementada manualmente em vez de reusar `DayClosedError`.
Sugestão: extrair para services (`CorrectionService.patch_food_item`,
`NutrientFactService.patch`), deixando a route só com parse de payload + tradução de
AppError → HTTP. Isso torna o bug BE-02 testável em unit de service e alinha com o
resto das mutações (meal/correction/deletion já são services).
Risco: médio — mover lógica entre camadas exige testes de integração ponta-a-ponta
para garantir paridade de comportamento.
```

**Arquivos**: `app/api/routes/records.py`, `app/api/routes/nutrient_facts.py`, novos `app/services/correction.py` / `app/services/nutrient_fact.py`.

**Notas**: não alterar `daily_recompute.py` nem `nutrition_calculator.py`. Após extrair, manter o mapeamento `DayClosedError → ConflictError(code="conflict_closed_day")` na borda da rota (padrão `records.py:69`). Esta tarefa desbloqueia a correção segura do BE-02.

---

### BE-04 — Erros externos do MinIO (boto3) sem tratamento, timeout ou mapeamento para domínio

**Severidade**: alta · **Risco**: baixo

**Achados cobertos**:

```
[alta] app/integrations/storage/minio.py:59-94 — put_object/get_object/presigned_get_url
propagam exceções crus do botocore (ClientError, EndpointConnectionError)
Problema: só AppError tem handler global (main.py:54); exceção do boto3 vira 500
genérico sem `code`. Timeout existe só implicitamente (default ~60s). Em routes/chat.py:87
(presigned por mídia) e services/media.py:73 (upload), MinIO fora do ar/lento derruba o
request sem erro de domínio e pode pendurar o event loop ~60s na thread pool.
Sugestão: no próprio MinioStorage, capturar (BotoCoreError, ClientError) e traduzir:
    raise AppError("storage unavailable", code="storage_unavailable", status_code=502) from exc
e endurecer o Config (linha 53): connect_timeout=5, read_timeout=15,
retries={"max_attempts": 2}. boto3 síncrono já está em asyncio.to_thread (correto).
Risco: baixo — confinar o tratamento no integration não muda contratos de service.
```

**Arquivos**: `app/integrations/storage/minio.py`. Adicionar testes com mock do cliente S3 (não precisa Postgres).

**Notas**: alinhar com o padrão já usado pelo `AnthropicClient` (Traduz exceção do SDK em códigos de domínio). Adicionar `boto3-stubs[s3]` em dev-deps (BE-14) para mypy ver os métodos.

---

### BE-05 — Race de refresh sem lock de linha (rotação de refresh token)

**Severidade**: alta · **Risco**: médio

**Achados cobertos**:

```
[alta] app/repositories/refresh_token.py:37-39 + app/services/auth.py:73-92 —
get_by_hash é SELECT simples (read-committed); dois POST /auth/refresh concorrentes
com o mesmo token leem revoked_at IS NULL antes de qualquer revoke() commitar, e ambos
emitem pares novos — a garantia de rotação única é quebrada sem disparar a detecção
de reuso.
Sugestão: travar a linha no fluxo de refresh:
    stmt = select(RefreshToken).where(...).with_for_update()
Risco: médio — for_update adiciona contenção; em app single-user o impacto é mínimo,
mas a janela de race é real (mesmo dispositivo com retries paralelos).
```

**Arquivos**: `app/repositories/refresh_token.py` (`get_by_hash`), `app/services/auth.py`.

**Notas**: a detecção de reuso (`revoke_family`) continua válida; o lock só previne a janela em que dois refreshes válidos coexistem. Teste de integração com dois coroutines concorrentes.

---

## Prioridade 2 — severidade média

### BE-06 — `dict[str, Any]` em respostas de rotas (dia/semana) without contrato Pydantic

**Severidade**: média · **Risco**: baixo

```
[média] app/schemas/days.py:27-31,40 + app/schemas/weekly.py —
DayRecordsOut.food/water/beverage/activity e warnings são list[dict[str, Any]];
WeeklyReportOut.totals/averages/per_day/warnings idem. Typos de chave e mudanças de
shape passam sem validação e geram OpenAPI sem contrato útil para o frontend.
Sugestão: modelos concretos por categoria (FoodRecordOut, WaterRecordOut,
BeverageRecordOut, ActivityRecordOut, WarningOut{code, message, ...}, WeeklyTotalsOut,
PerDayOut) espelhando o que os services emitem.
```

**Arquivos**: `app/schemas/days.py`, `app/schemas/weekly.py`, `app/services/day_query.py`, `app/services/weekly_report.py` (preenchem os dicts).

**Notas**: coordenar com o front-end (`docs/frontend-melhorias.md`) — o cliente consome shape implícito. Mudança é aditiva se o frontend já lê por chave.

---

### BE-07 — Claim `sid` do access token nunca é conferido (janela pós-revogação/logou嚼t)

**Severidade**: média · **Risco**: médio

```
[média] app/api/deps.py:72-78 + app/core/security.py:54 — encode_access_token emite
`sid` (id do refresh token), mas get_current_user só valida `sub`. Após logout ou
revoke_family por reuso, o access token roubado continua válido até o exp (até 15 min).
Sugestão: verificar que o refresh `sid` existe e não está revogado — custo baixo, pois
a request já faz query ao banco para o user. Ou adicionar denylist de `sid` em memória/
redis para logout imediato (avaliação de custo vs. janela aceitável).
Risco: médio — adiciona uma query por request autenticada; medir impacto.
```

**Arquivos**: `app/api/deps.py`, `app/core/security.py`, `app/repositories/refresh_token.py`.

**Notas**: decisões de security OIDC — registrar ADR se mudar estratégia derevogação.

---

### BE-08 — Sem fail-fast de configuração insegura em produção

**Severidade**: média · **Risco**: baixo

```
[média] app/core/config.py:30-44 — defaults sensíveis (jwt_secret="dev-only-secret-...",
cookie_secure=False, anthropic_api_key="", s3_*="") são aceitos silenciosamente mesmo
com app_env="production". Um deploy mal configurado sobe "funcionando" com segredo JWT
público.
Sugestão: model_validator no Settings que aborta o boot se app_env == "production" e
jwt_secret for o default/curto, cookie_secure for False, ou chaves Anthropic/S3 vazias.
Risco: baixo — só afeta boot em produção; desenvolvimento não é tocado.
```

**Arquivos**: `app/core/config.py`.

---

### BE-09 — Upload de mídia lido integralmente em memória antes da checagem de tamanho

**Severidade**: média · **Risco**: baixo

```
[média] app/api/routes/media.py:31 — await file.read() materializa o arquivo inteiro
antes de MediaService rejeitar >8MB (services/media.py:65). Cliente autenticado pode
enviar centenas de MB e estressar RAM do processo.
Sugestão: rejeitar cedo por file.size (Starlette ≥0.36 popula) ou Content-Length na
borda da route e/ou ler em chunks com abort acima de MAX_SIZE_BYTES + ε.
Risco: baixo — a validação de MIME/probe/8MB no service fica; só adianta a rejeição.
```

**Arquivos**: `app/api/routes/media.py`, `app/services/media.py`.

---

### BE-10 — Envelope de erro inconsistente fora de `AppError` (validation/5xx)

**Severidade**: média · **Risco**: baixo

```
[média] app/main.py:54-59 — apenas AppError vira {"code","message"}. RequestValidationError
(payload inválido) cai no formato default do FastAPI {"detail": [...]} e exceções não
tratadas caem no 500 texto-puro do Starlette — o cliente precisa de 2-3 parsers de erro.
Sugestão: registrar handler para RequestValidationError (→ code="validation_error",
status 422) e Exception (→ code="internal_error", mensagem genérica, sem stack trace —
o middleware já loga o traceback com request_id).
Risco: baixo — sem vazamento de stack trace hoje (app sem debug=True); ganho de contrato.
```

**Arquivos**: `app/main.py`.

**Notas**: manter o handler de `Exception` sem logar stack trace na resposta (já logado pelo middleware). Validar que testes de erro 422 não quebram.

---

### BE-11 — PATCH deNutrientFact sem escopo de usuário sobre catálogo compartilhado

**Severidade**: média · **Risco**: médio

```
[média] app/api/routes/nutrient_facts.py:47 — select(NutrientFact).where(id == entity_id)
não filtra por usuário. nutrient_facts é tabela global (sem user_id) e facts
label_ocr entram na precedência do LocalTBCACatalog para todos os usuários — um
usuário autenticado pode editar um fact que altera recomputes de itens de outro.
Sugestão: restringir a edição a facts do próprio usuário (via label_media_id →
media.user_id) ou documentar a decisão de catálogo colaborativo com actor bem
registrado (já feito). No mínimo, restringir PATCH a source IN ('manual','label_ocr')
para proteger o seed TBCA.
Risco: médio — depende da intenção da spec do Bloco 5 (catálogo colaborativo vs.
privado). Confirmar antes de codar.
```

**Arquivos**: `app/api/routes/nutrient_facts.py`, `app/models/nutrient_fact.py` (eventual `created_by`), `app/repositories/` (Nova query com escopo). 🛑 Se adicionar `created_by`, **precisa migration** — criar teste que valide o schema/estado.

**Notas**: hoje o MVP é efetivamente single-user (sem cadastro HTTP), mas é uma brecha de isolamento latente (Art. V §21 em espírito).

---

### BE-12 — Drift de índices: 13 índices só nas migrations, não nos models (armadilha do autogenerate)

**Severidade**: média · **Risco**: baixo

```
[média] models vs migrations — ix_messages_user_created, ix_messages_raw_llm_response
(GIN), ix_day_logs_user_status, ix_media_user_created, ix_food_records_user_day,
ix_food_records_user_occurred, ix_food_items_record, ix_food_items_normalized_name,
ix_{water,beverage,activity}_records_user_day, ix_audit_events_{entity,user_created},
ix_nutrient_facts_*, ix_weekly_reports_user_generated existem só via op.create_index
nas migrations 0002/0003/0004/0007 — nenhum model declara Index em __table_args__.
Consequência: o próximo `alembic revision --autogenerate` vai emitir op.drop_index(...)
para todos eles — quem gerar migration sem revisar derruba todos os índices do banco.
Sugestão: declarar os índices nos __table_args__ de cada model (espelhar o que já existe
no DB; sem migration nova, pois os índices físicos já existem — só alinha o metadata).
Risco: baixo — não afeta runtime; alinha metadata para o autogenerate não mentir.
```

**Arquivos**: todos os `app/models/*.py` relevantes. Sem migration (só alinha `__table_args__`).

**Notas**: o único model que já faz isso é `refresh_token.py:13` (servir de padrão). Após a tarefa, rodar `alembic revision --autogenerate` (sem aplicar) e confirmar que o diff de índices fica vazio.

---

### BE-13 — Singularização de plural "-es" divergente (miss de catálogo em alimentos comuns)

**Severidade**: média · **Risco**: baixo

```
[média] app/integrations/nutrition/normalize.py:33-34 — "lanche" → "lanche", mas
"lanches" → regra endswith("es") → "lanch". Idem "leite"/"leites" → "leit". Query e seed
em formas diferentes não casam, e o lookup falha silenciosamente (cai no fluxo "sem
catálogo"). A exceção "des" existe mas "-che/-te" não.
Sugestão: tratar plural "-es" removendo só o "s" quando o singular termina em
vogal+"e" (se token[:-2] termina em consoante, tentar token[:-1]); ou garantir que o
seed inclua o alias plural já normalizado (seed.py:48 passa pela mesma função).
Risco: baixo — melhora hit-rate do catálogo sem mudar estrutura; adicionar testes de
unidade para a normalização com casos comuns (arroz, lanche, leite, ovos, pães).
```

**Arquivos**: `app/integrations/nutrition/normalize.py`, `tests/` (casos de normalização).

**Notas**: impacto em precisão nutricional sem erro visível —属 erro silencioso de qualidade de dado (Art. II em espírito: o cálculo é correto, mas o input do catálogo falha).

---

### BE-14 — Erros de mypy reais (typing) que mascaram regressões + stubs boto3 ausentes

**Severidade**: média · **Risco**: baixo

**Achados cobertos**:

```
[média] app/integrations/anthropic/client.py:188 — overload de messages.create não casa:
payload correto em runtime, mas system/tool_choice/tools como dicts literais inferem
tipos que o SDK espera como TypedDicts. Erros reais ficam escondidos entre os 15 do
mypy. Converter para MessageParam/TextBlockParam/ToolChoiceToolParam/ToolParam.

[média] app/integrations/anthropic/client.py:297 — list[ErrorDetails] vs list[dict]:
usar from pydantic_core import ErrorDetails e tipar LLMCallResult.validation_errors.

[média] app/integrations/nutrition/local_tbca.py:41 — .any() em ARRAY: FALSO POSITIVO
confirmado (gera "value = ANY(aliases)"; stubs resolvem como PropComparator). Silenciar
com type: ignore[arg-type] + comentário, ou trocar por aliases.contains([normalized]).
Não trocar sem medir (usa @> vs = ANY; GIN index difere).

[média] app/api/routes/chat.py:97,107 — # type: ignore no lugar errado + str onde
schema espera UUID. Runtime OK (Pydantic coage), mas o ignore está morto. Converter
nutrient_fact_id = uuid.UUID(fid) de verdade.

[baixa] app/integrations/anthropic/client.py:588 — Image vs ImageFile: usar img_rgb =
img.convert("RGB") ou anotar img: Image.Image.

[baixa] app/repositories/refresh_token.py:57 — result.rowcount: NÃO é bug de runtime
(update() retorna CursorResult com rowcount); tipar com cast(CursorResult[Any], ...).

[baixa] app/services/deletion.py:154-156 — entity.day_log_id = ...: runtime OK (atribui
atributo de instância, não persiste); mypy reclama pois FoodItem não tem essa coluna.
Documentar o "campo transitório" ou usar dataclass auxiliar em vez de atribuir no model.
```

**Arquivos**: `app/integrations/anthropic/client.py`, `app/integrations/nutrition/local_tbca.py`, `app/api/routes/chat.py`, `app/repositories/refresh_token.py`, `app/services/deletion.py`, `pyproject.toml` (`boto3-stubs[s3]` em dev-deps + override `ignore_missing_imports` para boto3).

**Notas**: objetivo é zerar os 15 erros do mypy sem mascarar bugs. Depois de BE-14 + BE-16 (ruff), manter `mypy app` e `ruff check` limpos no CI.

---

### BE-15 — N+1 no `bulk_lookup` do catálogo TBCA local

**Severidade**: média · **Risco**: baixo

```
[média] app/integrations/nutrition/local_tbca.py:65-66 — bulk_lookup faz loop sequencial
de lookup — uma mensagem com 6 itens = 6 round-trips ao Postgres, cada um com
ORDER BY/CASE.
Sugestão: query única com NutrientFact.canonical_name.in_(names) |
NutrientFact.aliases.overlap(names) e ranking/dedup em Python (mesma precedência já
expressa em _SOURCE_RANK). Não usar asyncio.gather na mesma session (não é
concurrency-safe).
Risco: baixo — latência por mensagem de chat; sem erro funcional.
```

**Arquivos**: `app/integrations/nutrition/local_tbca.py`.

**Notas**: Medir latência antes/depois com fixture de N itens. O `local_tbca.py:41` (BE-14) deve ser resolvido junto (mesmo arquivo/stubs).

---

### BE-16 — Ruff: 7 imports não ordenados (alembic env + migrations) — auto-corrigível

**Severidade**: baixa · **Risco**: trivial

```
[baixa] alembic/env.py + alembic/versions/0001..0007 — I001 unsorted-imports (7 erros).
Sugestão: uv run ruff check --fix; commit separado.
Risco: trivial — autoformatação sem mudança semântica.
```

**Arquivos**: `alembic/env.py`, `alembic/versions/000{1,2,3,4,5,7}_*.py`.

**Notas**: fazer primeiro, isolado, para limpar o baseline do ruff antes das demais tarefas.

---

## Prioridade 3 — severidade baixa

### BE-17 — Repositórios: queries sem `user_id` e padrões inconsistentes (defesa em profundidade)

```
[média] app/repositories/food.py:97-107 — list_alive_for_day não recebe/filtra user_id.
Hoje é código morto (zero callers — daily_recompute faz sua própria query), mas é uma
violação-em-espera do Art. V §21. Remover ou endurecer a assinatura com user_id + join
em FoodRecord.user_id.
[média] app/repositories/message.py:99-111 — load_media_map retorna Media (com user_id)
sem filtrar Media.user_id no join. Sem caminho de vazamento ativo hoje (caller já escopa
por user), mas defesa em profundidade ausente. Adicionar .where(Media.user_id == user_id).
[baixa] app/repositories/message.py:83-94 — paginação keyset só por created_at, sem
desempate por id. Colisão de timestamp pode pular mensagem no polling after_id.
Keyset composto: (created_at, id).
```

**Arquivos**: `app/repositories/food.py`, `app/repositories/message.py`.

**Notas**: `load_media_map` é o padrão positivo de batch (BE-15 se inspira nele). A paginação keyset tem história de bug no poll do chat (2026-07-19) — priorizar o desempate por id.

---

### BE-18 — Cosméticos e nitpicks (erros de tipagem menores, knobs mortos, higiene de logs)

```
[baixa] app/core/rate_limit.py:25-29 — _prune mantém chave com lista vazia; leak lento
proporcional a identidades distintas. Adicionar self._events.pop(key, None) ao final.
[baixa] app/main.py:25 + app/api/routes/health.py:15 — version="0.0.0" hardcoded; release
atual é v1.3.0. Ler de importlib.metadata ou setting injetado no pipeline de release.
[baixa] app/api/routes/auth.py — cookie_domain configurável mas nunca usado; passar
domain= quando aplicável ou remover a setting.
[baixa] app/api/deps.py:55-59 — get_client_ip confia X-Forwarded-For incondicionalmente;
honrar só atrás de proxy confiável (uvicorn --proxy-headers + trusted hosts) ou
documentar que a API nunca é exposta diretamente.
[baixa] app/api/routes/days.py:42-43 — imports dentro da função (DayLogRepository,
local_today); mover para o topo do módulo.
[baixa] app/api/routes/weekly.py:30 + days.py — GET com efeitos colaterais (gera relatório
com INSERT + eventual chamada LLM paga; /days/today cria day_log). Sem Cache-Control.
Adicionar no-store; considerar POST para geração de relatório no futuro.
[baixa] app/repositories/refresh_token.py:46-57 — revoke_family conta tokens expirados
como "revogados" (WHERE só exclui já-revogados). Adicionar expires_at > now ou ajustar
docstring.
[baixa] app/repositories/message.py:78-79 — anchor inexistente/alheio degrada
silenciosamente para "load inicial". Se after_id foi passado mas não resolveu, retornar
[] (polling não traz nada) em vez das N mensagens mais recentes.
[baixa] app/repositories/message.py:26 vs food.py/beverage.py — llm_confidence: float vs
confidence: Decimal; alinhar para Decimal | None.
[baixa] app/repositories/media.py:4 + refresh_token.py:6 + integrations/nutrition/* —
from sqlalchemy.future import select (legado 1.4); trocar por from sqlalchemy import select.
[baixa] app/integrations/anthropic/client.py:117-118,656-665 — timeout_seconds /
max_http_retries aceitos no construtor mas nunca passados (knobs mortos). Expor em
Settings ou remover.
[baixa] app/integrations/anthropic/client.py:222,231 — log de exc.response.text sem
truncar; truncar para 500 chars.
[baixa] app/services/message_processor.py:792-803 — _record_error loga raw_tool_input
completo (PII nutricional/saúde) e validation_errors. Persistir no DB é por design
(auditoria, Art. III §11); duplicar em log WARNING é excesso (LGPD). Logar só error,
model e count de validation_errors.
[baixa] app/integrations/anthropic/client.py:314,629-653 — retry semântico quebra com
múltiplos tool_use blocks (_find_tool_use_id retorna o primeiro; _clean_content_for_retry
reenvia todos mas só anexa um tool_result → 400). Filtrar para manter só o block
record_intent.
[baixa] app/integrations/anthropic/client.py:365 vs 451 — assimetria de assinatura
call_weekly_narrative (posicional) vs call_narrative (keyword-only); alinhar ambos
keyword-only.
[baixa] app/integrations/nutrition/seed.py:30-34 — _parse_dec aborta o seed sem contexto
em valor sujo; incluir reader.line_num no erro.
[baixa] app/integrations/storage/minio.py:88-93 — rewrite de host descarta path prefix
de S3_PUBLIC_BASE_URL; validar no boot que public_base_url não tem path.
[baixa] app/api/deps.py:35 — TestAnthropicClient injetado com type: ignore[return-value];
o fake não herda de AnthropicClient, escondendo drift de interface. Extrair um Protocol
AnthropicClientLike e tipar a dep com ele.
[baixa] app/api/routes/records.py:38 — FoodItemPatch.unit sem max_length; adicionar
Field(default=None, max_length=32).
[baixa] app/api/routes/nutrient_facts.py:55 — 422 para fact não editável (TBCA/USDA);
semanticamente é 409 ou 403. Usar ConflictError(code="not_editable").
[baixa] app/services/message_processor.py:109-117 — sentinela de teste (no_queued_result)
em código de produção; aceitar como trade-off documentado ou mover a no-op para wrapper
do client em ambiente test.
[baixa] app/schemas/days.py:12-22 + schemas/nutrient_facts.py — float para kcal/macros
nos schemas de saída (DayTotalsOut, NutrientFactOut/Patch). O cálculo no backend é
Decimal; a coerção para float ocorre na borda do JSON. Trocar para Decimal (Pydantic
serializa como number) ou documentar a exceção.
[baixa] app/integrations/anthropic/client.py:382,476 — import json dentro dos métodos
(×2); mover para o topo.
```

**Arquivos**: vários (ver cada item).

**Notas**: agrupar os itens triviais em poucos PRs pequenos (ex.: "ruff/imports legados", "higiene de logs", "tipagem de repos"). O de PII em logs (message_processor.py:792) merece prioridade média por LGPD mesmo sendo "baixa" —推进 a critério do operador.

---

## Tarefas explicitamente NÃO cobertas (exigem fluxo SDD `spec/plan`)

Os itens abaixo foram detectados mas **não são tarefas de melhoria de código** — precisam de `spec:`/`plan:` antes de qualquer `feat:`:

- **Índices com `day_log_id` na posição líder** (servir as queries mais quentes do recompute que filtram só por `day_log_id`): precisa migration + revisão manual + teste de schema. Não codar como "nitpick" — é decisão de performance com impacto em INV-4.
- **`nutrient_facts.created_by`** (ownership de entradas OCR no catálogo compartilhado): depende da decisão de catálogo colaborativo vs. privado (Bloco 5) — confirmar spec antes.
- **Refactor grande do `message_processor.py`** (1274 linhas, baixa coesão): dívida real (média), mas a tarefa correta é divisão incremental em serviços menores com ADR — fora do escopo de "melhoria pontual".

---

## Pontos positivos constatados (não exigem ação)

1. **Fronteira Art. II exemplar**: `tool_use` forçado + envelope Pydantic estrito (`extra="forbid"`) + descarte de texto livre + narrativa só sobre totais já calculados; services 100% isolados do SDK (`import anthropic`/`boto3` em `app/services` = vazio). O retry semântico via `tool_result` é solução madura.
2. **Concorrência tratada nos pontos críticos**: `DayLogRepository.get_or_create` com `INSERT ... ON CONFLICT DO NOTHING` + re-select; upserts de snapshot/weekly com `RETURNING` + `populate_existing=True`; recompute from-scratch (INV-4) sem delta.
3. **Invariantes embutidas no schema, não só em código**: água sem kcal (Art. IV), CHECKs de volume/duração, UNIQUE(`user_id`, `log_date`), UNIQUE(`day_log_id`) no snapshot, FKs com `ondelete` coerentes.
4. **N+1 por lazy load é impossível**: nenhum model declara `relationship()` — todo carregamento é explícito e em batch (`load_media_map` como padrão).
5. **Test hooks duplamente protegidos** (router só registrado em `app_env=="test"` + guard 404 em cada handler) — defesa em profundidade.
6. **DELETE idempotente com `already_deleted`** (SP-81) e `DayClosedError → 409 conflict_closed_day` mapeado na borda.
7. **Auditoria presente em toda mutação de service** (`meal`, `correction`, `deletion`, `hydration`, `beverage`, `activity`, `confirmation`, `label_catalog`, `day_close`).

---

## Ordem sugerida de execução

1. **BE-16** (ruff `--fix`, isolado) — limpa o baseline.
2. **BE-01** (disclaimer em `GET /days`) — 🛑 Constituição, baixo risco, pequena.
3. **BE-03 + BE-02** (extrair `patch_food_item`/`confirm_food_item` para service e corrigir o `hit None`) — juntos, com testes de service + integração.
4. **BE-04** (MinIO errors → domínio) — baixo risco, alto ganho de robustez.
5. **BE-05** (lock de refresh) — security, com teste de race.
6. **BE-10**, **BE-08**, **BE-09** (contrato de erro, config fail-fast, upload DoS) — hardening operacional.
7. **BE-06**, **BE-11**, **BE-13** (contratos de schema, escopo de catálogo, normalização) — средней качество.
8. **BE-12** (índices nos models) — previne armadilha de autogenerate; sem migration.
9. **BE-14**, **BE-15**, **BE-07** (mypy limpo, N+1 catálogo, `sid` claim) — typing/perf/security.
10. **BE-17**, **BE-18** (repositórios + nitpicks) — dívida técnica, em PRs pequenos agrupados.

Após cada tarefa: `uv run ruff check && uv run mypy app && uv run pytest` (ou o subconjunto relevante). Não commitar — o operador decide.