# Arquitetura

Este documento tem duas partes: (1) **índice de navegação** para os artefatos SDD que são fonte de verdade, e (2) **análise arquitetural detalhada** derivada desses artefatos + do código atual. Se algo aqui divergir dos SDD, os SDD ganham.

## Fluxo SDD

O projeto segue Spec-Driven Development. A ordem é: **Constituição → Spec → Plan → Tasks → Código**. Alterar código sem passar antes pelos artefatos correspondentes viola o processo.

```
.specify/
  memory/
    constitution.md          # princípios inegociáveis (Art. I-X)

specs/
  001-mvp-registro-diario/
    spec.md                  # O QUÊ (SP-01..SP-113, invariantes)
    plan.md                  # COMO (mapeia SPs, ordem, gates)
    tasks.md                 # tarefas atômicas T-XXX por fase
    research.md              # ADRs (10 decisões arquiteturais)

app_plan.md                  # design técnico canônico (referenciado por plan.md)
```

## Índice rápido

- **Princípios que não posso violar:** [`../.specify/memory/constitution.md`](../.specify/memory/constitution.md).
- **O que o sistema faz (WHAT):** [`../specs/001-mvp-registro-diario/spec.md`](../specs/001-mvp-registro-diario/spec.md).
- **Como implementar (HOW):** [`../specs/001-mvp-registro-diario/plan.md`](../specs/001-mvp-registro-diario/plan.md) + [`../app_plan.md`](../app_plan.md).
- **O que fazer agora:** [`../specs/001-mvp-registro-diario/tasks.md`](../specs/001-mvp-registro-diario/tasks.md).
- **Por que fizemos assim:** [`../specs/001-mvp-registro-diario/research.md`](../specs/001-mvp-registro-diario/research.md).

## Regras de ouro do SDD neste projeto

1. **Nova feature começa pela `spec.md`.** PR isolado, título `spec:`. Nunca implemente sem SP-XX registrado.
2. **`plan.md` só mapeia SPs para arquivos e ordem.** Não invente comportamento aqui — se for novo comportamento, é `spec.md`.
3. **`tasks.md` é executável.** Uma tarefa = 1 PR ≤ 1 dia = commits fechando um ou mais T-XXX.
4. **Emenda constitucional é rara.** Requer PR próprio com prefixo `constitution:`, incremento de versão, cool-off 24h.
5. **ADR novo sempre que trade-off relevante:** append em `research.md`, nunca reescreva ADR aprovado (use `superseded by`).

Detalhes do processo: [`../specs/001-mvp-registro-diario/plan.md`](../specs/001-mvp-registro-diario/plan.md) §6.

---

# Análise arquitetural detalhada

## 1. Panorama e propósito

**Produto.** Web app privada de **uso individual** onde o Felix registra alimentação, hidratação e atividade física por **chat multimodal com IA** (texto + fotos de pratos e rótulos). A LLM apenas **interpreta**; toda soma nutricional/calórica é feita pelo backend. UI mostra tabela consolidada do dia atualizada a cada mensagem, com fechamento diário e resumo semanal.

**Contexto.** MyFitnessPal/FatSecret exigem entrada manual estruturada; modelos multimodais tornam viável interpretar linguagem natural, mas confiar cegamente na LLM para memória e cálculo é frágil. Daí o design em torno de dois princípios: *LLM interpreta / backend calcula* e *Postgres é a única fonte de verdade*.

**Escopo do MVP.** Um só usuário, uma VPS, sem cadastro público, sem reset por HTTP, sem HA, sem PWA, sem notificações, sem exportação. Explícito no §7 da spec.

## 2. Metodologia — Spec-Driven Development (SDD)

Antes de qualquer coisa: o repositório **não** é apenas um monorepo; é um monorepo **governado por artefatos SDD**.

```
Constitution  →  Spec  →  Plan  →  Tasks  →  Código
 (Art. I-X)     (SP-XX)   (map)    (T-XXX)   (feat: SP-XX)
```

- **`.specify/memory/constitution.md`** (v1.0.0) — 10 artigos inegociáveis. Um PR que viole qualquer artigo é rejeitado sem discussão. Emenda requer PR `constitution:`, incremento SemVer, cool-off 24h.
- **`specs/001-mvp-registro-diario/spec.md`** — O QUÊ. 113 requisitos SP-01..SP-113 em Given/When/Then + 10 invariantes INV-1..INV-10 que espelham artigos.
- **`plan.md`** — O COMO. Mapeia SP-XX → arquivos + ordem por fase; define gates (todo SP-`must` verde + checklist constitucional).
- **`tasks.md`** — Tarefas atômicas T-XXX (≤ 1 dia, 1 PR), com `blocked_by`.
- **`research.md`** — ADRs append-only (ADR-001 Argon2id+JWT, ADR-002 MinIO local, ADR-003 Alembic pin, ADR-008 EDEADLK…).
- **`app_plan.md`** — Design técnico canônico completo em 20 seções (raiz do repo).

**Consequência prática:** pular `spec:` → `plan:` → `tasks:` e ir direto para `feat:` não é permitido. Cada commit no corpo referencia os SP-XX cobertos.

## 3. Stack e decisões macro

| Camada | Escolha | Razão principal |
|---|---|---|
| Frontend | Next.js 15 (App Router) + React 19 + TS + Tailwind + shadcn/ui + TanStack Query | Componentes headless copy-paste, ótimo para chat |
| Backend | FastAPI + Pydantic v2 + SQLAlchemy 2 async + Alembic + Uvicorn | Contratos Pydantic casam com `tool_use` da Anthropic |
| Runtime | Python 3.12 (`>=3.12,<3.13`) + `uv` para deps/lock | Instalação rápida, lock determinístico |
| DB | PostgreSQL 16 (JSONB, GIN, `tstzrange`, `citext`, `pgcrypto`) | Única fonte de verdade (Art. I §1) |
| LLM | Anthropic Claude **Sonnet 4.6** default; **Haiku 4.5** fallback | Visão multimodal + `tool_use` estruturado |
| Contrato LLM | `tool_use` obrigatório + Pydantic + retry semântico | Texto livre é descartado (Art. II §7) |
| Storage | MinIO (S3-compatible) local em dev e prod na mesma VPS | Zero egress, backup sob controle (ADR-002) |
| Auth | Argon2id + JWT 15min + refresh opaco 32B rotacionado (14d) | Stateless hot path + revogação real (ADR-001) |
| Reverse proxy | Nginx + Certbot webroot | Previsível para um domínio único |
| Catálogo nutricional | `NutritionCatalog` (Protocol) → `LocalTBCACatalog` (seed CSV ~600 itens) + fallback perguntando ao usuário | Substituível sem tocar em services |
| Fila | `BackgroundTasks` do FastAPI + recompute idempotente | Suficiente para 1 usuário; migra para RQ/Dramatiq depois |
| Observabilidade | Logging JSON stdlib + `X-Request-Id` middleware | Proporcional ao MVP |

**Constantes fixadas por ADR:** Alembic `>=1.14,<1.16` (ADR-003 — auto-discovery de `pyproject.toml` no 1.16 quebra o `alembic.ini` clássico). Backend no host em macOS (ADR-008 — `EDEADLK` no bind mount do Docker Desktop).

## 4. Topologia de deploy

```
┌───────────────────── Browser ─────────────────────┐
│                        HTTPS                       │
└──────────────┬────────────────────────────────────┘
               ▼
        ┌──────────────┐  same-origin  ┌──────────────┐
        │ Nginx + TLS  │ ────/api/*───▶│  FastAPI     │
        │(Let's Encrypt)│               │  (Uvicorn)   │
        └──────┬───────┘               └──────┬───────┘
               │                              │
               ▼                              ▼
         Next.js 15                    PostgreSQL 16
        (standalone)                       MinIO
                                        Anthropic API
```

- Rede pública `web` (só Nginx) + rede privada `internal` (todo o resto).
- Apenas 80/443 expostos. Postgres e MinIO **sem** `ports:` — só acessíveis pela rede interna.
- CORS é essencialmente **same-origin** em prod (`/api/*` proxied). Em dev, allowlist explícita `http://localhost:3000`, `allow_credentials=true`, sem wildcard (Art. V §20).
- Restart `unless-stopped`; logs rotacionados a 10MB × 5 arquivos.
- Migrations **não** rodam no `up`; deploy chama `alembic upgrade head` como passo explícito (Art. VI §25).

## 5. Estrutura do monorepo e camadas do backend

```
my-registers/
├─ .specify/memory/constitution.md
├─ specs/001-mvp-registro-diario/{spec,plan,tasks,research}.md
├─ app_plan.md                       # design canônico
├─ apps/
│  ├─ api/                           # FastAPI
│  │  ├─ app/
│  │  │  ├─ api/{routes/, deps.py, middleware.py}   # HTTP
│  │  │  ├─ services/                                # regras de negócio
│  │  │  ├─ repositories/                            # acesso a dados
│  │  │  ├─ models/                                  # SQLAlchemy
│  │  │  ├─ schemas/                                 # Pydantic v2
│  │  │  ├─ integrations/{anthropic,storage,nutrition}/
│  │  │  ├─ core/{config,security,logging,exceptions}.py
│  │  │  ├─ db/{session,base}.py
│  │  │  ├─ cli/main.py             # typer
│  │  │  └─ main.py                 # create_app + lifespan
│  │  ├─ alembic/{env.py, versions/}
│  │  └─ tests/
│  └─ web/                           # Next.js 15 (skeleton)
├─ infra/{nginx,certbot,postgres}/
├─ scripts/{dev-infra.sh, backup-*, deploy.sh}
├─ docker-compose.local.yml          # tudo em Docker (alternativo)
└─ docker-compose.production.yml     # prod
```

**Camadas do backend** (uma pasta por camada, dependência unidirecional):

```
route (HTTP) → service (regra) → repository (SQL) → model (schema)
                     │
                     ▼
        integrations/{anthropic, storage, nutrition}
```

Regras que decorrem disso:
- **Repositories não vazam `Session` para as rotas.** A dependência FastAPI de `get_session()` (em `db/session.py`) monta uma `AsyncSession` que o service consome via repository.
- **Erros de domínio** herdam de `AppError` (`core/exceptions.py` — `NotFoundError`, `UnauthorizedError`, `ForbiddenError`, `ValidationAppError`). Um handler global em `main.py` converte para JSON `{code, message}` com o status correto.
- **Middleware `RequestContextMiddleware`** injeta `X-Request-Id` na request state e loga `latency_ms` + `route` em JSON — é a raiz da observabilidade.
- **Config Pydantic Settings** em `core/config.py` carrega `.env` (`extra=ignore`) — tudo tipado incluindo `Literal["development","production","test"]` e listas derivadas (`allowed_origins_list`).

## 6. Modelo de dados — as escolhas que carregam a arquitetura

Convenções globais: `UUID PK` via `gen_random_uuid()` (extensão `pgcrypto`), `created_at`/`updated_at` com trigger, soft delete via `deleted_at TIMESTAMPTZ NULL` + índice parcial `WHERE deleted_at IS NULL`, FKs `ON DELETE RESTRICT` como default.

### Tabelas por domínio

| Grupo | Tabelas |
|---|---|
| Auth | `users` (`citext` email UNIQUE, `password_hash`, `weight_kg` opcional…), `refresh_tokens` (`token_hash` SHA-256, `expires_at`, `revoked_at`, `replaced_by` → cadeia de rotação) |
| Chat | `messages` (`role`, `llm_intent`, `llm_prompt_version`, `raw_llm_response JSONB`, tokens), `media` (`storage_key` UNIQUE, `checksum_sha256`, `content_type`), `message_media` (n:n) |
| Registros crus | `food_records` (a refeição) → `food_items` (unitário, com macros/micros **materializados**), `water_records`, `beverage_records`, `activity_records` |
| Catálogo | `nutrient_facts` (`canonical_name`, `aliases TEXT[]`, `source`, `basis`, valores por 100g/ml, `verified_by_user`, `label_media_id`) |
| Derivados | `daily_snapshots` (cache dos totais + `version`), `weekly_reports` |
| Governança | `day_logs` (uma linha por dia do usuário, `status open/closed`), `audit_events` (before/after/actor/message_id) |

### Decisões de modelagem que importam

1. **Snapshots são cache, não fonte de verdade** (Art. III §10). `daily_snapshots` **sempre** é reconstruído por `DailyRecomputeService.recompute(day_id)` fazendo `SELECT` sobre as tabelas cruas com `deleted_at IS NULL`. Nenhum código incrementa delta-a-delta. Cada recompute incrementa `version` para permitir que `weekly_reports` detecte inconsistências.
2. **Materialização com auditabilidade** — `food_items` guarda kcal/macros/micros calculados **e** `catalog_ref_id` para a linha do `nutrient_facts` usada. Correção reprocessa o item; snapshot recomputa do zero.
3. **Separação estrutural água ↔ bebidas** (Art. IV §12-14). `water_records` **não tem** colunas de kcal/macros — impossível gravar caloria em água por engano. `beverage_records` tem todas. O `IntentDispatcher` rejeita `log_water` com `kcal>0`.
4. **Precedência do catálogo** — quando `NutritionCatalog.lookup` retorna múltiplos hits: (1) marca casada exata; (2) `TBCA_2023` > `label_ocr` > `manual`; (3) `verified_by_user=true`; (4) mais recente. Impede que OCR ruim de rótulo sobreponha item curado.
5. **Auditoria universal** (Art. III §11) — toda mutação de negócio grava `audit_events` com `before`, `after`, `actor` (`user` ou `llm`), `message_id`.
6. **Dia = data local do usuário** (`users.timezone`, IANA). Uma mensagem enviada 23:30 local em 12/jul pertence a `log_date=2026-07-12` mesmo com UTC em 13/jul (SP-92). Único enforcement: `UNIQUE(user_id, log_date)`.
7. **Índices calibrados para leitura barata** — GIN em `messages.raw_llm_response`, GIN em `nutrient_facts.aliases` e `to_tsvector('portuguese', canonical_name)`, `(user_id, created_at DESC)` em quase tudo. Bom para o hot path `GET /days/today ≤ 200ms P95`.

## 7. Fluxo de uma mensagem multimodal

```
Browser ──POST /media (multipart)──▶ API
         ◀── {media_id, storage_key}
         ──POST /chat/messages {text, media_ids}──▶ API
         ◀── 202 {message_id, status: "processing"}
                                        │
                                        ▼ BackgroundTasks
                                    process_user_message
                                        │
                                        ▼
         ┌──────────────────────────────┴──────────────────────────────┐
         │  1. baixa mídia do MinIO (bytes em memória, base64)         │
         │  2. Anthropic messages.create(tool_use=record_intent)       │
         │  3. valida LLMEnvelope (Pydantic)                            │
         │     → falhou? retry semântico (até 2x) com erro no prompt   │
         │  4. IntentDispatcher                                         │
         │     • log_food → MealService.create_from_llm                │
         │     • log_water/log_beverage/log_activity → *Service         │
         │     • correct_record → CorrectionService (matching)         │
         │     • close_day → DailyReportService.close                  │
         │  5. resolve items via NutritionCatalog                       │
         │  6. NutritionCalculator/ActivityCalculator (determinístico)  │
         │  7. DailyRecomputeService.recompute(day_id) — from scratch  │
         │  8. cria messages(role='assistant') com narrative           │
         │     ← segunda chamada rápida à LLM sobre totais JÁ calculados│
         │  9. grava audit_events + tokens                              │
         └─────────────────────────────────────────────────────────────┘
Browser ──GET /chat/messages?after=<id> (polling 1.5s, cap 30s)──▶ API
```

**Handshake da confiança.** Se `confidence < 0.5` ou faltarem campos essenciais, a resposta do assistant é **pergunta de confirmação** e o registro entra com `needs_confirmation=true` (ou não é criado, decisão do dispatcher por severidade). Itens sinalizados são destacados na UI.

**Timeout/erro.** `>60s` ou erro após 2 retries HTTP → assistant responde "não consegui interpretar" e grava `raw_llm_response.error`. Nada persiste (SP-14).

## 8. Contrato com a Anthropic

Este é o **coração** da separação LLM/backend.

- Endpoint `messages.create` da SDK oficial. `max_tokens=1024`, `temperature=0.1`.
- **`tool_use` obrigatório.** Uma tool `record_intent` com `input_schema` JSON estrito (§8.2 do `app_plan.md`). Modelo é forçado a devolver dados que respeitam o schema; texto livre é descartado (Art. II §7).
- **Prompt caching** (`cache_control: {type: 'ephemeral'}`) no system + schema — reduz custo/latência em sessão contínua.
- **Retry HTTP:** 2 tentativas em 5xx/429 com backoff `1s → 3s`. **Retry semântico:** se Pydantic falhar validação, envia o `ValidationError` formatado como `role=user` numa segunda chamada ("O JSON anterior falhou em X, corrija"). Máx 2 tentativas; se persistir, vira `intent=clarify`.
- **Imagens** enviadas como `type: image, source: {type: base64, media_type, data}`. Baixadas do MinIO para memória — **não** expor URL externa à Anthropic (Art. IV, privacidade).
- **Modelos:** `ANTHROPIC_MODEL=claude-sonnet-4-6` default; `claude-haiku-4-5-20251001` como fallback para intents leves.

### Envelope Pydantic

```python
class LLMEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Literal["log_food","log_water","log_beverage","log_activity",
                    "log_nutrition_label","correct_record","delete_record",
                    "query_day","close_day","weekly_summary","clarify","unknown"]
    confidence: float = Field(ge=0, le=1)
    user_text_summary: str
    needs_clarification: bool = False
    clarification_question: str | None = None
    meal_slot: Literal[...] | None = None
    food_items: list[FoodItemIn] = []
    water: WaterIn | None = None
    beverage: BeverageIn | None = None
    activity: ActivityIn | None = None
    correction: CorrectionIn | None = None
    deletion: DeletionIn | None = None
    nutrition_label: NutritionLabelIn | None = None
```

Prompt de sistema (`system_v2.md`) tem 18 regras que codificam a Constituição em linguagem para o modelo — inclusive "não invente marcas", "diferencie água pura de bebida calórica", "não dê conselho médico", "cálcio/ferro/potássio geralmente `null` em rótulos brasileiros pela RDC 429/2020".

### Rótulos nutricionais como caso especial

A intent `log_nutrition_label` **cadastra `nutrient_facts` sem gerar consumo**. Se a mesma mensagem trouxer "comi um pote (170g)", o campo `also_consumed` também cria `food_records`/`food_items` referenciando o novo item do catálogo. `basis='per_serving'` **sem** `serving_size_g/ml` **não** persiste — o assistente pergunta o tamanho.

## 9. Segurança e bootstrap

**Hash.** Argon2id (`time_cost=3, memory_cost=64MB, parallelism=2`) via `argon2-cffi`. Rehash oportunístico no login.

**Sessão dupla em cookies HttpOnly:**
- `access_token` — JWT HS256, 15 min, claims `sub=user_id, sid=session_id`. Stateless: hot path do chat não consulta banco por request.
- `refresh_token` — 32 bytes aleatórios URL-safe, **armazenado hasheado (SHA-256)** em `refresh_tokens`, TTL 14 dias, **rotação obrigatória a cada uso** (`replaced_by` encadeia). **Reuso de refresh revogado → invalida a família inteira** (Art. V §17).

**Cookies sempre `HttpOnly; Secure; SameSite=Lax; Path=/`** em prod. Em dev, `Secure=false`.

**Sem cadastro público, sem reset por HTTP** (Art. V §18). `POST /auth/register`, `/forgot-password`, `/reset-password` **MUST NOT existir** — retornam 404 sem hint. Criação/reset é **exclusivamente CLI** (`app.cli create-admin`, `app.cli reset-password`) rodado por humano com SSH.

**Bootstrap idempotente.** `python -m app.cli bootstrap` (Typer) lê `DEFAULT_ADMIN_EMAIL` e `DEFAULT_ADMIN_PASSWORD` do ambiente, faz hash Argon2id, insere se não existir. Nunca ecoa a senha (Art. VI §24). Motivo de não pôr senha em migration: schema ≠ dado + histórico Git é público.

**Uploads.** `POST /media` valida MIME server-side, tamanho ≤ 8 MB, faz *decode probe* com Pillow (rejeita arquivo com extensão falsa), gera `storage_key = users/{uid}/media/{yyyy}/{mm}/{uuid}.{ext}` — nome nunca vem do cliente (Art. V §22).

**Rate limiting.** `POST /auth/login`: 5/min/IP + 10 falhas/15min por email (SP-02). Token bucket em memória (single-instance, MVP-adequado).

**Autorização.** `user_id` no filtro de **toda** query de repositório (Art. V §21). Não há query que ignore isolamento.

**Segredos.** Anthropic API key, JWT secret, S3 keys **nunca** aparecem em: código versionado, migrations, respostas HTTP, logs, `raw_llm_response`, `audit_events` (Art. V §19, INV-7).

## 10. Frontend

Skeleton mínimo hoje (`layout.tsx`, `page.tsx`, `globals.css`); UI real chega na Fase 1+.

- **Grupos de rota:** `(auth)/login` público, `(app)/*` protegido por `middleware.ts` que valida cookie access via `/api/auth/me`. 401 → redirect `/login`.
- **UI:** Tailwind + shadcn/ui (Radix headless) + `lucide-react`.
- **Estado:** TanStack Query. Cache-first, revalidação após cada mensagem confirmada. Sem Redux/Zustand.
- **Chat (`ChatShell`):** lista virtualizada, drop de imagens (React Dropzone), envio via mutation → 202 → polling `GET /chat/messages?after=lastId` a cada 1.5s até a assistant message, retry cap 30s.
- **`DayTable`:** tabela do `/days/today` com barra fixa "Saldo calórico" e botão "Encerrar dia".
- **Uploads:** sempre via `POST /api/media` do backend (MinIO nunca é exposto). Compressão client-side opcional (`browser-image-compression`) para reduzir custo Anthropic.
- **Rodapé com aviso legal fixo** (Art. VII §26).

## 11. Ambiente de dev

**Duas topologias:**

1. **Recomendada (macOS):** infra em Docker + apps no host. `pnpm infra:up` sobe só Postgres + MinIO + `minio-init` (cria bucket `registers-media`); backend com `uv run uvicorn --reload` no host; frontend com `pnpm dev`. **Motivo (ADR-008):** bind mount do Docker Desktop dispara `EDEADLK` no `mmap` de imports Python.
2. **Alternativa:** tudo em Docker via `pnpm compose:up` (`docker-compose.local.yml`) — só se seu Docker não sofrer com o bug.

**Portas:** web 3000, api 8000 (`/docs`, `/health`), Postgres 5432, MinIO S3 9000, MinIO Console 9001. Credenciais dev MinIO: `minio_dev` / `minio_dev_secret`. Admin default: `admin@example.com` / `adminadmin` (Fase 1+).

**Fase 0 (concluída, commit `c29bcbc`):**
- `alembic upgrade head` roda contra schema vazio (nenhuma migration ainda) — não falha.
- `python -m app.cli bootstrap` é placeholder idempotente que só valida env var.
- `/health` responde `{status: "ok", service: "my-registers-api"}` — único endpoint por ora.

## 12. Roadmap por fases (do `plan.md` §2)

| Fase | Nome | SPs entregues | Est. |
|---|---|---|---|
| 0 ✅ | Fundação | (esqueleto executável) | 2-3d |
| 1 | Autenticação + bootstrap admin | SP-01..06 | 1-2d |
| 2 | Mensagens e upload de mídia | SP-10..12, SP-92 | 2d |
| 3 | Integração Anthropic | SP-13, SP-14, INV-9 | 3d |
| 4 | Registro de alimentos | SP-20..26, INV-1 | 3d |
| 4.b | Leitura de tabela nutricional | SP-30..35 | 1-2d |
| 5 | Hidratação + atividades | SP-40..64, INV-2, INV-3 | 2d |
| 6 | Correções e remoções | SP-70..82, INV-4, INV-10 | 2d |
| 7 | Encerramento + relatório diário | SP-90..104, INV-5 | 1d |
| 8 | Relatório semanal | SP-110..113, INV-8 | 1d |
| 9 | Hardening + deploy | (segurança, backup, HTTPS) | 2d |

Total: ~20-21 dias úteis. **Gate de cada fase:** todos SPs `must` verdes + checklist constitucional + `git log` referenciando SPs + `app_plan.md` atualizado se decisão mudou.

## 13. Características arquiteturais que definem o produto

Estas são as ideias que, se removidas, não sobra "my-registers". Elas atravessam camadas.

1. **LLM interpreta, backend calcula.** Um teste automatizado deve substituir o cliente Anthropic por mock devolvendo lixo e ainda assim produzir totais corretos (Art. II §5, INV-1). Cobertura mínima de 90% em `nutrition_calculator.py` e `activity_calculator.py`.
2. **Postgres é a única memória.** A LLM não guarda estado; toda "memória" que ela aparente é dado que o backend recuperou do banco para a chamada atual (Art. I §2).
3. **Snapshots recomputam do zero, sempre.** Correções e deleções nunca alteram totais diretamente — alteram registros crus e disparam `recompute` completo (Art. III §10, INV-4).
4. **`tool_use` estruturado; texto livre da LLM é lixo.** Contrato JSON validado por Pydantic, com retry semântico que devolve o `ValidationError` para o modelo (Art. II §7, INV-9).
5. **Água ≠ bebida calórica, estrutural.** Separação em tabelas distintas, sem colunas equivalentes; `IntentDispatcher` rejeita `log_water` com kcal>0 (Art. IV, INV-2, INV-3).
6. **Dia fechado é imutável, sem reabertura no MVP.** Correção/exclusão retornam 409 (Art. VIII §28, INV-5).
7. **Semana = últimos 7 dias com `status='closed'`.** Dias abertos ignorados. Sem seg→dom nesse escopo (Art. IX §30, INV-8).
8. **Zero endpoint de cadastro ou reset.** CLI-only, executado por humano com SSH (Art. V §18).
9. **Confiança sempre presente.** `confidence ∈ [0,1]` e `is_estimate: bool` persistidos por item (Art. III §8). Item baixo dispara pergunta ou entra com `needs_confirmation=true`.
10. **Auditoria universal.** `audit_events` para toda mutação de negócio, com before/after/actor/message_id (Art. III §11, INV-10).
11. **Aviso legal obrigatório em todo relatório** (Art. VII §26): "As estimativas nutricionais são aproximações e não substituem acompanhamento médico ou nutricional."

## 14. Trade-offs assumidos

**O que se pagou pela simplicidade do MVP:**

| Escolha | Custo | Por que aceitar |
|---|---|---|
| `BackgroundTasks` do FastAPI em vez de RQ/Dramatiq | Não sobrevive a crash entre chamada Anthropic e persist | 1 usuário, `unless-stopped`, aceitável |
| MinIO na mesma VPS | Se a VPS morrer, storage vai junto | Mitigado por `mc mirror` off-VPS via rclone (ADR-002) |
| Single-VPS, sem HA | Downtime durante deploy/backup | Explícito no §4.3 da spec, `must` |
| JWT stateless + refresh opaco | Duas credenciais para gerenciar | Ganho de latência no hot path do chat (ADR-001) |
| Sem streaming SSE | Polling 1.5s até 30s | Simples; SSE fica para depois |
| Catálogo local TBCA + pergunta ao usuário se não achou | UX pede confirmação frequente | Mais alinhado com princípio 8 (confiança) que aceitar chute da LLM |
| Alembic pinado `<1.16` | Bloqueia updates ordinários | Auto-discovery do 1.16 quebra `alembic.ini` clássico (ADR-003) |
| Backend no host em macOS | Fluxo dev diferente entre macOS e Linux | Sem `EDEADLK` (ADR-008); ganho de dev loop |
| `sugars_g`, `saturated_fat_g`, `trans_fat_g` **não** persistidos | Perde dado obrigatório do rótulo BR (RDC 429/2020) | Schema já prevê; migração incremental depois |

## Estado atual em uma linha

Fase 0 concluída (`c29bcbc`): monorepo pnpm + `apps/api` FastAPI com `/health`, config Pydantic Settings, logging JSON, middleware de request-id, `AppError` handler, Typer CLI placeholder, Alembic pronto sem migrations, `apps/web` Next.js skeleton, `docker-compose.local.yml`, `scripts/dev-infra.sh`. Nada de negócio implementado — a próxima peça é **Fase 1** (T-101..T-110): migration inicial com `users` + `refresh_tokens`, Argon2id + JWT em `core/security.py`, `AuthService`, rotas `/auth/{login,refresh,logout,me}`, `middleware.ts` no Next, bootstrap real e teste provando que `/register` e `/forgot-password` retornam 404.
