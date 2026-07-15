# Plano Técnico — MVP de Registro Diário por Chat com IA

## 1. Resumo executivo e decisões de arquitetura

**Produto.** Aplicação web privada, uso individual no MVP, em que o usuário conversa por chat (texto + imagens) para registrar alimentação, hidratação e atividades físicas. A LLM da Anthropic interpreta a entrada, o backend calcula e persiste, e a interface mostra tabela atualizada a cada interação.

**Decisões-chave.**

| Área | Decisão | Justificativa curta |
|---|---|---|
| Frontend | Next.js 15 (App Router) + React 19 + TypeScript + Tailwind + shadcn/ui + TanStack Query | Padrão estável, componentes prontos e headless-compatible, ótimo para chat com streaming |
| Backend | FastAPI + Pydantic v2 + SQLAlchemy 2.x (async) + Alembic + Uvicorn | Ergonomia Pydantic com contratos LLM, docs automáticas, async por padrão |
| Runtime Python | Python 3.12 + `uv` para deps/lock | Instalações rápidas, lockfile determinístico |
| Banco | PostgreSQL 16 | Requerido; suporta JSONB, GIN, `tstzrange` úteis |
| LLM | Anthropic Claude **Sonnet 4.6** (`claude-sonnet-4-6`) como default multimodal; **Haiku 4.5** (`claude-haiku-4-5-20251001`) opcional para intenções leves | Sonnet 4.6 tem melhor visão para alimentos + JSON estruturado a custo razoável |
| Contrato JSON | `tool_use` da Anthropic (schema JSON forçado) + validação Pydantic + retry com feedback | Mais robusto do que texto livre + regex |
| Storage | MinIO local no dev; **MinIO hospedado na própria VPS** como recomendação inicial para prod (alternativa: Cloudflare R2) | Zero custo de egress, um único operador, backup simples |
| Autenticação | Local, e-mail + senha, **Argon2id**, cookies **HttpOnly** com **JWT access curto (15 min)** + **refresh token opaco rotacionado** | Sem serviço externo; sem cadastro, sem reset (fora do MVP) |
| Reverse proxy | **Nginx + Certbot (webroot)** | Configuração transparente, ampla documentação; Traefik é uma alternativa aceitável mas Nginx é mais previsível quando só há um domínio |
| Base nutricional | Camada `NutritionCatalog` com implementação local (seed TBCA) + fallback estimativa da LLM marcada `source=llm_estimate` | Permite substituir a fonte sem tocar em serviços |
| Cálculos | 100% no backend, com engine `NutritionCalculator` e `ActivityCalculator` (METs) | LLM não soma, apenas extrai |
| Confiança | Todo item extraído carrega `confidence ∈ [0,1]` e `is_estimate`; ⬍ threshold dispara pedido de confirmação | Aderente ao princípio 7/8 |
| Semana | **Últimos 7 dias encerrados** (janela do último dia fechado para trás) | Simples, sem dependência de timezone/calendário; alternativas discutidas |
| Fila | `BackgroundTasks` do FastAPI + recompute idempotente | Suficiente para 1 usuário; se crescer, migra para RQ/Dramatiq |
| Observabilidade | Logging estruturado JSON (stdlib), correlation-id por request, `pg_dump` diário, `mc mirror` para MinIO | Simples e proporcional ao MVP |

**Aviso ao usuário obrigatório** (renderizado no rodapé do chat e no relatório diário): *"As estimativas nutricionais e calóricas obtidas por imagem ou descrição são aproximações e não substituem acompanhamento médico ou nutricional."*

---

## 2. Premissas e pontos que precisam ser confirmados

Placeholders seguros já assumidos, mas listados como perguntas de confirmação:

1. **Peso corporal do usuário** — necessário para METs. *Assumido: campo obrigatório no perfil do admin, editável na primeira sessão.*
2. **Altura, idade e sexo** — se quiser refinamento futuro do gasto basal (BMR). *Assumido: opcionais no MVP.*
3. **Fuso horário** — assumido `America/Maceio` (ou `America/Sao_Paulo`). O "dia" é sempre local do usuário.
4. **Unidades preferidas** — assumido SI (g, ml, km, min).
5. **Idioma** — assumido pt-BR na UI e no prompt da LLM.
6. **Fonte nutricional oficial** — assumida a **TBCA (USP/FoRC)** para primeira seed; USDA FDC como fallback. Confirmar se há licença/preferência.
7. **Semana** — recomendação: *últimos 7 dias encerrados*. Confirmar se prefere segunda→domingo.
8. **Retenção de imagens** — assumido: manter enquanto o registro existir; sem expiração automática no MVP.
9. **Domínio de produção** — placeholder `app.example.com` no `.env.example`.
10. **Backup off-VPS** — sugestão: `rclone` semanal para Backblaze B2 ou Google Drive. Confirmar destino.

Se algum item for essencial (peso, timezone), o backend bloqueia o primeiro registro relevante e o chat solicita a informação.

---

## 3. Arquitetura da solução

```
┌───────────────────────────────────────────────────────────────────┐
│                          Browser (usuário)                        │
└──────────────┬──────────────────────────────────┬─────────────────┘
               │ HTTPS                            │ HTTPS
               ▼                                  ▼
        ┌──────────────┐                    ┌──────────────┐
        │  Next.js 15  │   fetch (proxy)    │  FastAPI     │
        │  (SSR + CSR) │◀──────────────────▶│  (Uvicorn)   │
        └──────────────┘                    └──────┬───────┘
               ▲                                   │
               │ mesma origem via Nginx            │
               │                                   │
      ┌────────┴────────┐              ┌───────────┼────────────┐
      │   Nginx + TLS   │              │           │            │
      │  (Let's Encrypt)│              ▼           ▼            ▼
      └─────────────────┘         PostgreSQL     MinIO       Anthropic
                                  (interno)   (interno)    Messages API
```

**Camadas no backend** (uma pasta por camada):

- `api/` — rotas FastAPI, dependências, middleware, autenticação.
- `schemas/` — Pydantic v2 (request/response, DTOs, contratos LLM).
- `services/` — regras de negócio (`ChatService`, `MealService`, `HydrationService`, `ActivityService`, `DailyReportService`, `WeeklyReportService`, `CorrectionService`, `NutritionCalculator`, `ActivityCalculator`).
- `repositories/` — acesso a dados via SQLAlchemy async; retornam models, nunca vazam `Session` para as rotas.
- `models/` — SQLAlchemy declarative.
- `integrations/anthropic/` — cliente, prompt loader, schema loader, retries, telemetria de tokens.
- `integrations/storage/` — cliente MinIO/S3 (upload, URL assinada).
- `integrations/nutrition/` — `NutritionCatalog` (interface) + `LocalTBCACatalog` + `LLMFallbackCatalog`.
- `core/` — config (Pydantic Settings), logging, segurança, exceções.
- `cli/` — comandos administrativos (`bootstrap`, `create-admin`, `seed-nutrition`, `recompute-day`).

Um request de chat passa por: `route → auth dep → ChatService → (upload já persistido) → AnthropicService → validador Pydantic → IntentDispatcher → *RecordService → NutritionCalculator → DailyRecomputeService → response`.

---

## 4. Fluxo completo de uma mensagem com foto

1. **Frontend** — usuário anexa foto e digita "Este é meu almoço". A UI:
   - `POST /api/media` (multipart) → recebe `{ media_id, storage_key }`.
   - `POST /api/chat/messages` com `{ text, media_ids: [...] }`.
2. **API `POST /media`**:
   - Valida MIME (`image/jpeg|png|webp|heic`) e tamanho (≤ 8 MB).
   - Faz *decode probe* (Pillow) para descartar arquivos maliciosos.
   - Gera `storage_key = users/{uid}/media/{yyyy}/{mm}/{uuid}.{ext}`.
   - Faz PUT no MinIO com Content-Type e `ObjectLock` desabilitado.
   - Insere linha em `media` (status `uploaded`).
3. **API `POST /chat/messages`**:
   - Autoriza usuário.
   - Cria `messages` (`role='user'`) e associa `media_ids` via `message_media`.
   - Garante `day_logs` para a data local do usuário (cria se não existir, `status='open'`).
   - Enfileira `BackgroundTasks.process_user_message(message_id)`; responde 202 com `message_id` e `pending=true` para que a UI mostre skeleton.
4. **Worker (BackgroundTasks)**:
   - Baixa a mídia do MinIO (bytes em memória) e monta o payload multimodal para Anthropic.
   - Chama Anthropic com `tool_use` (função `record_intent`, JSON schema estrito), `max_tokens=1024`, `temperature=0.2`, `system=<prompt versionado>`, `betas=['prompt-caching-2024']` no cabeçalho do system message para cache.
   - Recebe `tool_use.input`, valida com Pydantic (`LLMEnvelope`). Em erro, faz **até 2 retries** enviando o erro de validação de volta ao modelo ("O JSON anterior falhou em X, corrija").
   - Após validado, dispara `IntentDispatcher`:
     - `intent='log_food'` → `MealService.create_from_llm(...)` → resolve cada item em `NutritionCatalog` (lookup por nome normalizado); se não encontrar, usa valores da LLM marcados como estimativa.
     - Insere `food_records` + `food_items` com `confidence`, `is_estimate`, `source='llm'`.
   - `DailyRecomputeService.recompute(day_id)` — agrega tudo do dia a partir das tabelas cruas (não usa snapshot antigo).
   - Cria `messages` (`role='assistant'`) com resposta textual amigável (gerada por uma segunda chamada rápida à LLM, alimentando o **snapshot já calculado** — a LLM apenas explica, não soma).
   - Anota `audit_events` (payload bruto da LLM, versão do prompt, tokens usados).
5. **Frontend** — polling curto (ou SSE se desejado) em `GET /chat/messages?after=<id>` até a mensagem do assistant estar pronta; então atualiza chat + a "table view" do dia via `GET /days/today`.

Se `confidence < 0.5` em qualquer item ou faltarem campos (quantidade, unidade), a resposta do assistant é do tipo **pergunta de confirmação** e o registro é criado com flag `needs_confirmation=true` (ou não é criado, dependendo da severidade — decisão no dispatcher). Todos os itens sinalizados aparecem destacados na UI.

---

## 5. Estrutura de monorepo

```
my-registers/
├── apps/
│   ├── web/                          # Next.js 15
│   │   ├── src/
│   │   │   ├── app/
│   │   │   │   ├── (auth)/login/page.tsx
│   │   │   │   ├── (app)/
│   │   │   │   │   ├── layout.tsx
│   │   │   │   │   ├── chat/page.tsx
│   │   │   │   │   ├── days/[date]/page.tsx
│   │   │   │   │   └── weekly/page.tsx
│   │   │   │   ├── api/               # rotas proxy para o backend, se necessário
│   │   │   │   └── layout.tsx
│   │   │   ├── components/
│   │   │   │   ├── chat/
│   │   │   │   ├── summary/
│   │   │   │   └── ui/                # shadcn
│   │   │   ├── lib/
│   │   │   │   ├── api-client.ts
│   │   │   │   ├── auth.ts
│   │   │   │   └── format.ts
│   │   │   └── middleware.ts          # gate por cookie
│   │   ├── public/
│   │   ├── next.config.mjs
│   │   ├── tsconfig.json
│   │   ├── tailwind.config.ts
│   │   ├── package.json
│   │   └── Dockerfile
│   └── api/                           # FastAPI
│       ├── app/
│       │   ├── api/
│       │   │   ├── deps.py
│       │   │   ├── routes/
│       │   │   │   ├── auth.py
│       │   │   │   ├── chat.py
│       │   │   │   ├── media.py
│       │   │   │   ├── days.py
│       │   │   │   ├── weekly.py
│       │   │   │   └── records.py
│       │   │   └── middleware.py
│       │   ├── core/
│       │   │   ├── config.py
│       │   │   ├── logging.py
│       │   │   ├── security.py
│       │   │   └── exceptions.py
│       │   ├── models/
│       │   ├── schemas/
│       │   ├── services/
│       │   ├── repositories/
│       │   ├── integrations/
│       │   │   ├── anthropic/
│       │   │   │   ├── client.py
│       │   │   │   ├── prompts/
│       │   │   │   │   └── system_v2.md
│       │   │   │   └── schema.py
│       │   │   ├── storage/
│       │   │   └── nutrition/
│       │   ├── cli/
│       │   │   └── main.py            # typer app
│       │   ├── db/
│       │   │   ├── session.py
│       │   │   └── base.py
│       │   └── main.py
│       ├── alembic/
│       │   ├── env.py
│       │   ├── script.py.mako
│       │   └── versions/
│       ├── tests/
│       ├── pyproject.toml
│       ├── uv.lock
│       └── Dockerfile
├── infra/
│   ├── nginx/
│   │   ├── nginx.conf
│   │   └── conf.d/app.conf
│   ├── certbot/
│   │   └── README.md
│   └── postgres/
│       └── init/                       # scripts opcionais
├── scripts/
│   ├── backup-postgres.sh
│   ├── backup-minio.sh
│   ├── restore-postgres.sh
│   └── bootstrap.sh
├── docs/
│   ├── architecture.md
│   ├── prompts.md
│   └── nutrition-catalog.md
├── docker-compose.local.yml
├── docker-compose.production.yml
├── .env.example
├── .gitignore
├── package.json                        # pnpm workspaces
├── pnpm-workspace.yaml
└── README.md
```

**Responsabilidades por diretório:** `apps/web` = UI; `apps/api` = backend inteiro; `infra` = arquivos de configuração de runtime (Nginx, etc.); `scripts` = shell scripts operacionais; `docs` = decisões e prompts versionados.

---

## 6. Modelagem de banco de dados

Convenções: todas as tabelas têm `id UUID PK` (`gen_random_uuid()` via `pgcrypto`), `created_at`, `updated_at` (default `now()`, `trigger` para update). Exclusão lógica onde indicado via `deleted_at TIMESTAMPTZ NULL` + índice parcial `WHERE deleted_at IS NULL`. FKs `ON DELETE RESTRICT` salvo indicação contrária.

### `users`
| Coluna | Tipo | Notas |
|---|---|---|
| id | UUID PK | |
| email | CITEXT UNIQUE NOT NULL | |
| password_hash | TEXT NOT NULL | Argon2id |
| display_name | TEXT | |
| timezone | TEXT NOT NULL DEFAULT 'America/Sao_Paulo' | IANA |
| weight_kg | NUMERIC(5,2) | opcional inicialmente, exigido para METs |
| height_cm | NUMERIC(5,2) | opcional |
| birthdate | DATE | opcional |
| sex | TEXT CHECK IN ('m','f','o','n') | opcional |
| is_active | BOOLEAN NOT NULL DEFAULT true | |
| created_at / updated_at | TIMESTAMPTZ | |
Índices: `UNIQUE(email)`.

### `refresh_tokens`
| Coluna | Tipo | Notas |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK users(id) ON DELETE CASCADE | |
| token_hash | TEXT NOT NULL | SHA-256 do token opaco |
| issued_at | TIMESTAMPTZ NOT NULL | |
| expires_at | TIMESTAMPTZ NOT NULL | |
| revoked_at | TIMESTAMPTZ | rotação |
| replaced_by | UUID FK refresh_tokens(id) | rotação encadeada |
| user_agent | TEXT | |
| ip | INET | |
Índices: `UNIQUE(token_hash)`, `(user_id, expires_at)`.

### `day_logs`
| Coluna | Tipo | Notas |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK users(id) | |
| log_date | DATE NOT NULL | data local do usuário |
| status | TEXT CHECK IN ('open','closed') NOT NULL DEFAULT 'open' | |
| closed_at | TIMESTAMPTZ | |
| notes | TEXT | |
| created_at / updated_at | TIMESTAMPTZ | |
Índices: `UNIQUE(user_id, log_date)`, `(user_id, status)`.

### `messages`
| Coluna | Tipo | Notas |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK users(id) | |
| day_log_id | UUID FK day_logs(id) | pode ser NULL antes de resolver |
| role | TEXT CHECK IN ('user','assistant','system') | |
| content | TEXT | resposta textual amigável ou input |
| llm_intent | TEXT | ex.: `log_food`, `close_day` |
| llm_model | TEXT | ex.: `claude-sonnet-4-6` |
| llm_prompt_version | TEXT | ex.: `system_v2` |
| llm_confidence | NUMERIC(3,2) | agregada |
| raw_llm_response | JSONB | payload completo para auditoria |
| tokens_input / tokens_output | INT | |
| created_at | TIMESTAMPTZ | |
Índices: `(user_id, created_at DESC)`, GIN em `raw_llm_response`.

### `media`
| Coluna | Tipo | Notas |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK users(id) | |
| storage_key | TEXT NOT NULL | caminho no bucket |
| content_type | TEXT NOT NULL | |
| size_bytes | INT NOT NULL | |
| width / height | INT | |
| checksum_sha256 | TEXT | |
| status | TEXT CHECK IN ('uploaded','failed') | |
| created_at | TIMESTAMPTZ | |
Índices: `(user_id, created_at DESC)`, `UNIQUE(storage_key)`.

### `message_media` (n:n)
`message_id UUID FK`, `media_id UUID FK`, PK `(message_id, media_id)`.

### `food_records` (a refeição)
| Coluna | Tipo | Notas |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK users(id) | |
| day_log_id | UUID FK day_logs(id) | |
| message_id | UUID FK messages(id) | origem |
| meal_slot | TEXT CHECK IN ('breakfast','lunch','snack','dinner','other','unspecified') | |
| occurred_at | TIMESTAMPTZ NOT NULL | |
| notes | TEXT | |
| deleted_at | TIMESTAMPTZ | |
| created_at / updated_at | TIMESTAMPTZ | |
Índices: `(user_id, day_log_id)`, `(user_id, occurred_at)`.

### `food_items` (unitário)
| Coluna | Tipo | Notas |
|---|---|---|
| id | UUID PK | |
| food_record_id | UUID FK food_records(id) ON DELETE CASCADE | |
| detected_name | TEXT NOT NULL | como veio da LLM/usuário |
| normalized_name | TEXT NOT NULL | slug canonical |
| brand | TEXT | |
| quantity | NUMERIC(10,3) | |
| unit | TEXT | ex.: `g`,`ml`,`unidade`,`concha`,`fatia` |
| grams | NUMERIC(10,3) | quando aplicável |
| ml | NUMERIC(10,3) | quando aplicável |
| source | TEXT CHECK IN ('manual','llm','user_corrected','catalog') NOT NULL | |
| confidence | NUMERIC(3,2) | |
| is_estimate | BOOLEAN NOT NULL DEFAULT false | |
| catalog_ref_id | UUID FK nutrient_facts(id) | pode ser NULL |
| kcal | NUMERIC(10,2) | *cache dos macros calculados* |
| protein_g / carbs_g / fat_g / fiber_g | NUMERIC(10,2) | |
| sodium_mg / calcium_mg / iron_mg / potassium_mg | NUMERIC(10,2) | |
| deleted_at | TIMESTAMPTZ | |
| created_at / updated_at | TIMESTAMPTZ | |
Índices: `(food_record_id)`, `(normalized_name)`.

> Os campos nutricionais em `food_items` são **materializações**. A cada correção, o item é reprocessado pelo backend (buscando no `NutritionCatalog` ou reaproveitando os valores já resolvidos) e o `DailyRecomputeService` recalcula o snapshot lendo apenas dos registros vivos (`deleted_at IS NULL`).

### `water_records`
| Coluna | Tipo | Notas |
|---|---|---|
| id | UUID PK | |
| user_id / day_log_id / message_id | UUID FK | |
| occurred_at | TIMESTAMPTZ | |
| volume_ml | INT NOT NULL CHECK (volume_ml > 0) | |
| source / confidence / is_estimate | | |
| deleted_at | TIMESTAMPTZ | |

### `beverage_records` (outros líquidos)
| Coluna | Tipo | Notas |
|---|---|---|
| id | UUID PK | |
| user_id / day_log_id / message_id | FK | |
| detected_name / normalized_name / brand | TEXT | |
| volume_ml | INT NOT NULL | |
| kcal / protein_g / carbs_g / fat_g / fiber_g | NUMERIC | *itens calóricos: sim, entram em macros/calorias* |
| sodium_mg / calcium_mg / iron_mg / potassium_mg | NUMERIC | |
| source / confidence / is_estimate | | |
| catalog_ref_id | UUID | |
| deleted_at | TIMESTAMPTZ | |

**Regra para evitar dupla contagem** (crítica): bebidas *não-água* (café, leite, suco, refrigerante, café com leite, chá com açúcar, álcool) **só** entram em `beverage_records` e contam para o resumo em: (a) volume `outros líquidos` e (b) macros/calorias. **Água pura** (mesmo saborizada sem calorias) entra em `water_records` e conta somente em "água" (sem macros). O `IntentDispatcher` toma essa decisão baseado no schema `intent` da LLM, que expõe explicitamente `beverage_kind ∈ {water, other}` e o backend valida: se `kcal>0` ou `carbs_g>0` mas veio como `water`, é rejeitado/reclassificado.

### `activity_records`
| Coluna | Tipo | Notas |
|---|---|---|
| id | UUID PK | |
| user_id / day_log_id / message_id | FK | |
| detected_name / normalized_name | TEXT | |
| activity_type | TEXT | `cardio_run`, `cardio_walk`, `strength`, `bike`, etc. |
| duration_minutes | NUMERIC(6,2) NOT NULL | |
| distance_km | NUMERIC(6,3) | |
| intensity | TEXT CHECK IN ('light','moderate','vigorous','unknown') | |
| met_value | NUMERIC(4,2) | valor MET usado |
| kcal_burned | NUMERIC(10,2) NOT NULL | |
| calc_method | TEXT CHECK IN ('mets_body_weight','llm_estimate','user_manual') | |
| confidence | NUMERIC(3,2) | |
| notes | TEXT | |
| deleted_at | TIMESTAMPTZ | |

### `nutrient_facts` (catálogo)
| Coluna | Tipo | Notas |
|---|---|---|
| id | UUID PK | |
| canonical_name | TEXT NOT NULL | |
| aliases | TEXT[] | busca |
| brand | TEXT | |
| source | TEXT | `TBCA_2023`, `USDA_FDC`, `manual`, `label_ocr` |
| serving_grams | NUMERIC(10,2) | 100 g de referência normalmente |
| kcal / protein_g / carbs_g / fat_g / fiber_g | NUMERIC(10,2) | por 100 g ou por 100 ml |
| sodium_mg / calcium_mg / iron_mg / potassium_mg | NUMERIC(10,2) | |
| basis | TEXT CHECK IN ('per_100g','per_100ml') NOT NULL | |
| barcode | TEXT | opcional; útil para futura leitura de código de barras |
| label_media_id | UUID FK media(id) | foto do rótulo que originou o registro (auditável); nulo para entradas do seed TBCA |
| verified_by_user | BOOLEAN NOT NULL DEFAULT false | usuário confirmou os valores no cartão de confirmação |
| created_at | TIMESTAMPTZ | |
Índices: `GIN(aliases)`, `GIN(to_tsvector('portuguese', canonical_name))`, `(barcode) WHERE barcode IS NOT NULL`.

**Precedência do lookup**: quando `NutritionCatalog.lookup(name, brand)` retornar múltiplos hits, o desempate segue esta ordem: (1) marca casada exata; (2) `source='TBCA_2023'` (curado) sobre `source='label_ocr'` (OCR) sobre `source='manual'`; (3) `verified_by_user=true` sobre falso; (4) mais recente. Isso impede que uma leitura ruim de rótulo sobreponha o catálogo curado; ao mesmo tempo, um rótulo verificado da marca X tem preferência sobre o item genérico da TBCA quando o usuário registrar "iogurte X".

### `daily_snapshots`
| Coluna | Tipo | Notas |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK | |
| day_log_id | UUID FK UNIQUE | |
| kcal_in / kcal_out / kcal_balance | NUMERIC(10,2) | |
| protein_g / carbs_g / fat_g / fiber_g | NUMERIC(10,2) | |
| sodium_mg / calcium_mg / iron_mg / potassium_mg | NUMERIC(10,2) | |
| water_ml / other_liquids_ml | INT | |
| computed_at | TIMESTAMPTZ NOT NULL | |
| warnings | JSONB | ex.: itens estimados, campos ausentes |
| version | INT NOT NULL DEFAULT 1 | invalida cache |

O snapshot é **sempre** reconstruído a partir das tabelas cruas por `DailyRecomputeService.recompute(day_id)`, chamado após qualquer INSERT/UPDATE/DELETE de registros e no fechamento do dia. Nenhum código incrementa o snapshot delta-a-delta.

### `weekly_reports`
| Coluna | Tipo | Notas |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK | |
| window_start / window_end | DATE | inclusivos |
| totals | JSONB | somas por métrica |
| averages | JSONB | médias diárias |
| per_day | JSONB | array de `daily_snapshots` reduzidos |
| llm_narrative | TEXT | explicação amigável |
| generated_at | TIMESTAMPTZ | |
Índices: `UNIQUE(user_id, window_start, window_end)`.

### `audit_events`
| Coluna | Tipo | Notas |
|---|---|---|
| id | UUID PK | |
| user_id | UUID | |
| entity_type | TEXT | `food_record`, `activity_record`, etc. |
| entity_id | UUID | |
| action | TEXT | `create`,`update`,`delete`,`correct` |
| before | JSONB | |
| after | JSONB | |
| actor | TEXT | `user` ou `llm` |
| message_id | UUID FK messages(id) | origem |
| created_at | TIMESTAMPTZ | |
Índices: `(entity_type, entity_id)`, `(user_id, created_at DESC)`.

**Estratégia de recomputo (essencial):** todo agregado é derivado. Snapshots servem apenas para leitura rápida. Correções nunca alteram totais diretamente; alteram registros e disparam `recompute`. Fechamento do dia grava snapshot com `version+=1`, garantindo que relatórios semanais que consumiram uma versão antiga possam identificar mudanças.

---

## 7. Estratégia de autenticação e bootstrap do administrador

**Hash.** Argon2id via `argon2-cffi` (`memory_cost=64MB`, `time_cost=3`, `parallelism=2`). Rehash oportunístico em cada login se parâmetros mudarem.

**Sessão.** Duas credenciais em cookies separados, ambos `HttpOnly; Secure; SameSite=Lax; Path=/`:
- `access_token` — JWT HS256, `exp=15min`, claims `sub=user_id`, `sid=session_id`.
- `refresh_token` — string aleatória de 32 bytes (URL-safe), armazenada **hasheada** (SHA-256) em `refresh_tokens`, `exp=14 dias`, rotação obrigatória a cada uso (revoga o anterior e emite novo; `replaced_by` preenchido). Reuso de token já revogado → invalida toda a família (revoga todos os refresh do usuário).

**Justificativa JWT + refresh (vs. sessão pura):** com JWT curto o backend não precisa consultar o banco em cada request (é stateless), o que simplifica o hot path do chat e mantém boa segurança (janela pequena, revogação via cookie clear + blacklist opcional por `sid`). O refresh opaco mantém o poder de revogação real.

**Endpoints:** `POST /auth/login` (rate-limited 5/min/IP), `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me`.

**CORS.** Em produção o Nginx serve web + api no mesmo domínio (`/api/*` → backend), portanto CORS é essencialmente same-origin. Em dev, `ALLOWED_ORIGINS=http://localhost:3000` explícito, `allow_credentials=True`, sem wildcard.

**Sem cadastro público, sem reset.** Endpoints inexistentes. A criação/reset de senha é feita **fora da API HTTP**, via CLI (`app.cli reset-password`) executado no container do backend por um humano com SSH na VPS.

### Bootstrap do admin

Comando `app.cli bootstrap` invocado manualmente após `alembic upgrade head`. Ele:

1. Lê `DEFAULT_ADMIN_EMAIL` e `DEFAULT_ADMIN_PASSWORD` do ambiente. Se ausentes, aborta com erro.
2. Faz `SELECT` por email (idempotente). Se existe, apenas informa "already exists" e sai `0`.
3. Faz hash Argon2id da senha; insere `users` com `is_active=true`.
4. Seed do catálogo nutricional (se vazio).
5. **Nunca** loga a senha; nem em stdout, nem em `raw_llm_response`, nem em `audit_events`. Zera a variável em memória após uso.

**Por que bootstrap e não senha na migration Alembic:** migrations são versionadas, revisáveis por qualquer pessoa com acesso ao repositório e reproduzidas em qualquer ambiente. Colocar uma senha (mesmo "temporária") ali significa: (a) ela vai para o histórico Git permanentemente; (b) todos os ambientes iniciam com a mesma senha; (c) alterar a senha exige nova migration, o que é semanticamente errado (schema vs. dado). O bootstrap desacopla schema de dado, lê o segredo do ambiente (que fica só no `.env` no host, fora do Git) e é idempotente sem poluir histórico.

---

## 8. Contrato de integração com Anthropic

### 8.1 Estratégia de chamada

- Endpoint `messages.create` da SDK oficial (`anthropic` Python).
- Modelo default `ANTHROPIC_MODEL=claude-sonnet-4-6`; fallback configurável para `claude-haiku-4-5-20251001` em intents leves.
- `max_tokens=1024`, `temperature=0.1`.
- **`tool_use` obrigatório** com uma tool `record_intent` cujo `input_schema` é o JSON schema abaixo. Isso força o modelo a retornar dados que respeitam o schema; simplifica a validação enorme.
- **Prompt caching:** o system prompt + schema são marcados como `cache_control: {type: 'ephemeral'}` — reduz custo e latência quando o usuário conversa em sequência.
- Timeout HTTP 60s. Retries: 2 em erros 5xx/429 com backoff exponencial (`1s → 3s`). Retries semânticos (JSON inválido): 2 tentativas com feedback do erro Pydantic anexado como user message.
- Imagens enviadas como `type: 'image'`, `source: { type: 'base64', media_type, data }` (baixadas do MinIO para memória, não expor URL externa à Anthropic).

### 8.2 Schema JSON (input_schema da tool `record_intent`)

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["intent", "user_text_summary", "confidence"],
  "properties": {
    "intent": {
      "type": "string",
      "enum": [
        "log_food", "log_nutrition_label", "log_water", "log_beverage", "log_activity",
        "correct_record", "delete_record",
        "query_day", "close_day", "weekly_summary",
        "clarify", "unknown"
      ]
    },
    "confidence": { "type": "number", "minimum": 0, "maximum": 1 },
    "user_text_summary": { "type": "string" },
    "needs_clarification": { "type": "boolean" },
    "clarification_question": { "type": ["string", "null"] },
    "occurred_at_hint": { "type": ["string", "null"], "description": "ISO 8601 se explicitamente dito pelo usuário" },
    "meal_slot": { "type": ["string", "null"], "enum": [null, "breakfast", "lunch", "snack", "dinner", "other", "unspecified"] },
    "food_items": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["detected_name", "confidence"],
        "properties": {
          "detected_name": { "type": "string" },
          "normalized_name": { "type": ["string", "null"] },
          "brand": { "type": ["string", "null"] },
          "quantity": { "type": ["number", "null"] },
          "unit": { "type": ["string", "null"] },
          "grams_estimate": { "type": ["number", "null"] },
          "ml_estimate": { "type": ["number", "null"] },
          "confidence": { "type": "number", "minimum": 0, "maximum": 1 },
          "is_estimate": { "type": "boolean" }
        }
      }
    },
    "water": {
      "type": ["object", "null"],
      "additionalProperties": false,
      "properties": {
        "volume_ml": { "type": "number", "minimum": 1 },
        "confidence": { "type": "number" }
      }
    },
    "beverage": {
      "type": ["object", "null"],
      "additionalProperties": false,
      "properties": {
        "detected_name": { "type": "string" },
        "brand": { "type": ["string", "null"] },
        "volume_ml": { "type": "number", "minimum": 1 },
        "beverage_kind": { "type": "string", "enum": ["other"] },
        "confidence": { "type": "number" }
      }
    },
    "activity": {
      "type": ["object", "null"],
      "additionalProperties": false,
      "properties": {
        "detected_name": { "type": "string" },
        "activity_type": { "type": "string" },
        "duration_minutes": { "type": "number", "minimum": 1 },
        "distance_km": { "type": ["number", "null"] },
        "intensity": { "type": "string", "enum": ["light", "moderate", "vigorous", "unknown"] },
        "confidence": { "type": "number" }
      }
    },
    "correction": {
      "type": ["object", "null"],
      "additionalProperties": false,
      "properties": {
        "target_hint": { "type": "string", "description": "descrição textual do alvo, o backend faz o matching" },
        "changes": { "type": "object", "description": "pares campo→novo valor" },
        "confidence": { "type": "number" }
      }
    },
    "deletion": {
      "type": ["object", "null"],
      "additionalProperties": false,
      "properties": {
        "target_hint": { "type": "string" },
        "confidence": { "type": "number" }
      }
    },
    "nutrition_label": {
      "type": ["object", "null"],
      "additionalProperties": false,
      "required": ["product_name", "basis"],
      "properties": {
        "product_name": { "type": "string" },
        "brand": { "type": ["string", "null"] },
        "barcode": { "type": ["string", "null"] },
        "basis": { "type": "string", "enum": ["per_100g", "per_100ml", "per_serving"] },
        "serving_size_g": { "type": ["number", "null"] },
        "serving_size_ml": { "type": ["number", "null"] },
        "servings_per_pack": { "type": ["number", "null"] },
        "kcal": { "type": ["number", "null"] },
        "protein_g": { "type": ["number", "null"] },
        "carbs_g": { "type": ["number", "null"] },
        "sugars_g": { "type": ["number", "null"] },
        "added_sugars_g": { "type": ["number", "null"] },
        "fat_g": { "type": ["number", "null"] },
        "saturated_fat_g": { "type": ["number", "null"] },
        "trans_fat_g": { "type": ["number", "null"] },
        "fiber_g": { "type": ["number", "null"] },
        "sodium_mg": { "type": ["number", "null"] },
        "calcium_mg": { "type": ["number", "null"] },
        "iron_mg": { "type": ["number", "null"] },
        "potassium_mg": { "type": ["number", "null"] },
        "confidence_per_field": {
          "type": "object",
          "description": "mapa <nome_do_campo> → number 0..1 com a confiança de leitura por campo"
        },
        "also_consumed": {
          "type": ["object", "null"],
          "additionalProperties": false,
          "description": "presente quando o usuário indicar consumo na mesma mensagem",
          "properties": {
            "quantity": { "type": "number" },
            "unit": { "type": "string" },
            "grams": { "type": ["number", "null"] },
            "ml": { "type": ["number", "null"] },
            "servings": { "type": ["number", "null"] }
          }
        }
      }
    }
  }
}
```

> **Nota de escopo.** Os campos `sugars_g`, `added_sugars_g`, `saturated_fat_g` e `trans_fat_g` aparecem no schema para não descartar dados que o rótulo brasileiro traz por obrigação (RDC 429/2020, IN 75/2020), mas **não são persistidos** em `nutrient_facts`/`food_items`/`daily_snapshots` nesta fase — extensão futura listada na §20.

### 8.3 Prompt de sistema (v2) — `apps/api/app/integrations/anthropic/prompts/system_v2.md`

```
Você é o assistente de registro pessoal de alimentação, hidratação e atividade física
do usuário. Você opera dentro de um sistema onde o BACKEND é a fonte de verdade e
executa TODOS os cálculos. Seu papel é apenas interpretar mensagens (texto e imagens)
e devolver dados estruturados usando a ferramenta `record_intent`.

Regras absolutas:
1. Você nunca soma calorias, macros ou totais do dia ou da semana. Você não mantém
   memória de registros passados; se o usuário perguntar sobre totais, use a intent
   `query_day` ou `weekly_summary` e deixe o backend calcular.
2. Você retorna EXCLUSIVAMENTE via chamada da tool `record_intent`. Não escreva
   texto livre fora da ferramenta.
3. Não invente marcas, quantidades ou nutrientes. Se algo faltar, use null e
   preencha `needs_clarification=true` com uma `clarification_question` curta em pt-BR.
4. Sempre inclua `confidence` por item e no envelope. Confiança reflete quão certo
   você está da identificação, não do valor nutricional.
5. Estimativas de porção a partir de imagem devem sempre ter `is_estimate=true` e
   `confidence<=0.7`.
6. Diferencie explicitamente:
   - Água pura → `intent=log_water`, campo `water`.
   - Café, leite, sucos, refrigerantes, chás adoçados, bebidas alcoólicas →
     `intent=log_beverage`, campo `beverage`, `beverage_kind='other'`.
   - Alimentos sólidos ou semisólidos → `intent=log_food`, `food_items`.
   - Exercícios → `intent=log_activity`, campo `activity`.
7. Se o usuário disser "corrija", "ajuste", "na verdade", "mude", use
   `intent=correct_record` com `correction.target_hint` descrevendo em linguagem
   natural o item afetado (o backend fará o matching contra registros do dia).
8. Se disser "remova", "apague", "esqueça", use `intent=delete_record`.
9. Se disser "encerrar dia", "fechar dia", "finalizar hoje", use `intent=close_day`.
10. Se pedir "resumo da semana", "como foi minha semana", use `intent=weekly_summary`.
11. Se a mensagem for ambígua ou fora de escopo, use `intent=clarify` ou `unknown`.
12. Nunca dê conselho médico, nutricional prescritivo ou diagnóstico. Você pode
    descrever o que foi registrado, não recomendar dieta, tratamento ou remédio.
13. Idioma da comunicação com o usuário via `user_text_summary` e
    `clarification_question`: português do Brasil, tom cordial e conciso.
14. Ao interpretar imagens, priorize identificar itens visíveis; se houver múltiplos
    alimentos no prato, liste cada um em `food_items`.
15. Se o usuário informar unidade não-métrica (colher, concha, xícara), preencha
    `unit` com o termo original e `grams_estimate` ou `ml_estimate` com sua melhor
    aproximação marcada como estimativa.
16. Se a imagem mostrar uma TABELA NUTRICIONAL (verso de embalagem), use
    `intent=log_nutrition_label` e preencha `nutrition_label`. Diferencie
    explicitamente `basis='per_100g'` de `per_serving`. Se ambas as colunas
    aparecerem na tabela, PREFIRA `per_100g` (deixe os campos por porção como
    contexto no `user_text_summary` se relevante). Para `basis='per_serving'`,
    preencha obrigatoriamente `serving_size_g` OU `serving_size_ml`.
17. Se o usuário também disser quanto consumiu na mesma mensagem ("comi um pote",
    "500 ml", "duas porções"), preencha `also_consumed`. Caso contrário, deixe
    `null` — o backend apenas cadastra o produto no catálogo.
18. NÃO invente campos ausentes da tabela. Cálcio, ferro e potássio geralmente
    NÃO aparecem em rótulos brasileiros (não obrigatórios pela RDC 429/2020);
    deixe `null` nesses casos. Sódio é lido em mg — nunca converta sal em sódio.
    Preencha `confidence_per_field` para cada campo lido (ex.: `{"kcal": 0.95,
    "sodium_mg": 0.6}`).
```

### 8.4 Exemplos de entrada e saída válidas

**Entrada** (texto): *"150 g de arroz branco, uma concha de feijão preto e 180 g de peito de frango grelhado no almoço."*

**Saída (tool_use.input):**
```json
{
  "intent": "log_food",
  "confidence": 0.92,
  "user_text_summary": "Almoço: arroz branco, feijão preto e peito de frango.",
  "needs_clarification": false,
  "meal_slot": "lunch",
  "food_items": [
    { "detected_name": "arroz branco cozido", "normalized_name": "arroz_branco_cozido",
      "quantity": 150, "unit": "g", "grams_estimate": 150,
      "confidence": 0.95, "is_estimate": false },
    { "detected_name": "feijão preto cozido", "normalized_name": "feijao_preto_cozido",
      "quantity": 1, "unit": "concha", "grams_estimate": 90,
      "confidence": 0.75, "is_estimate": true },
    { "detected_name": "peito de frango grelhado", "normalized_name": "frango_peito_grelhado",
      "quantity": 180, "unit": "g", "grams_estimate": 180,
      "confidence": 0.94, "is_estimate": false }
  ]
}
```

**Entrada** (texto): *"corrija o frango para 220 g".*

**Saída:**
```json
{
  "intent": "correct_record",
  "confidence": 0.88,
  "user_text_summary": "Correção do peito de frango do último registro para 220 g.",
  "needs_clarification": false,
  "correction": {
    "target_hint": "peito de frango do último registro alimentar de hoje",
    "changes": { "quantity": 220, "unit": "g", "grams_estimate": 220 },
    "confidence": 0.88
  }
}
```

### 8.5 Validação Pydantic + retry

```python
class FoodItemIn(BaseModel):
    detected_name: str
    normalized_name: str | None = None
    brand: str | None = None
    quantity: float | None = None
    unit: str | None = None
    grams_estimate: float | None = None
    ml_estimate: float | None = None
    confidence: float = Field(ge=0, le=1)
    is_estimate: bool = False

class LLMEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Literal["log_food","log_water","log_beverage","log_activity",
                    "correct_record","delete_record","query_day","close_day",
                    "weekly_summary","clarify","unknown"]
    confidence: float = Field(ge=0, le=1)
    user_text_summary: str
    needs_clarification: bool = False
    clarification_question: str | None = None
    meal_slot: Literal["breakfast","lunch","snack","dinner","other","unspecified"] | None = None
    food_items: list[FoodItemIn] = []
    water: WaterIn | None = None
    beverage: BeverageIn | None = None
    activity: ActivityIn | None = None
    correction: CorrectionIn | None = None
    deletion: DeletionIn | None = None
    nutrition_label: NutritionLabelIn | None = None
```

**Validações adicionais no `NutritionLabelIn`:** `basis` obrigatório; se `basis == 'per_serving'`, exigir pelo menos um de `serving_size_g`/`serving_size_ml` (validador de modelo Pydantic). Se ausentes, o `IntentDispatcher` não persiste no catálogo e responde ao usuário pedindo o tamanho da porção — o item ainda pode ser aproveitado depois de a informação chegar.

**Retry semântico:** se `LLMEnvelope.model_validate(...)` levantar, capturamos `ValidationError`, formatamos as mensagens e enviamos como `role="user"` numa segunda chamada: *"O JSON anterior falhou na validação com: `<erros>`. Retorne apenas via `record_intent` com o schema correto."*. Máximo 2 retries; se persistir, o intent vira `clarify` com uma mensagem padrão pedindo para o usuário reformular.

---

## 9. Estratégia da base nutricional

Interface `NutritionCatalog`:

```python
class NutritionCatalog(Protocol):
    async def lookup(self, name: str, brand: str | None = None) -> CatalogHit | None: ...
    async def bulk_lookup(self, items: list[LookupQuery]) -> list[CatalogHit | None]: ...
```

Implementações:

1. **`LocalTBCACatalog`** — tabela `nutrient_facts` populada por seed a partir de um dump curado da TBCA (~600 itens brasileiros comuns), incluído no repositório como CSV (`apps/api/app/integrations/nutrition/seed_tbca.csv`). Lookup por full-text search em `canonical_name` + `aliases`.
2. **`LLMFallbackCatalog`** — se não houver hit e `confidence` da LLM for suficiente, aceita os valores nutricionais estimados pela LLM (não pedimos à LLM que calcule totais, mas ela pode devolver kcal/macros por 100g com `is_estimate=true` num *tool call* separado se necessário). Alternativa mais conservadora recomendada para o MVP: **não** pedir kcal à LLM; se não achou no catálogo, marcar o item como `needs_confirmation` e perguntar ao usuário (mais alinhado com o princípio 8).

Escolha inicial para o MVP: **catálogo local TBCA + fallback perguntando ao usuário** (opção conservadora). A `LLMFallbackCatalog` fica pronta atrás de uma feature flag para ativar posteriormente.

Normalização: função `normalize(name) → slug` (remove acentos, lowercase, singular). Aliases populados manualmente no seed. Índice GIN em `aliases`.

Cálculo final por item (`NutritionCalculator.compute(item, hit)`):
- Se `hit.basis == 'per_100g'` e `item.grams` conhecido: `kcal = hit.kcal * grams/100` (idem macros/micros).
- Se `basis == 'per_100ml'`: usa `ml`.
- Determinístico, testado unitariamente. LLM nunca aparece nesse cálculo.

---

## 10. Endpoints da API

Prefixo `/api`. Tudo autenticado exceto `/auth/login`. Content-Type `application/json` salvo `multipart/form-data` no upload.

| Método | Rota | Auth | Objetivo |
|---|---|---|---|
| POST | `/auth/login` | ❌ | Login por email/senha; seta cookies |
| POST | `/auth/refresh` | 🔄 refresh cookie | Rota rota (rotação) |
| POST | `/auth/logout` | ✅ | Revoga refresh e limpa cookies |
| GET | `/auth/me` | ✅ | Perfil do usuário logado |
| POST | `/media` | ✅ | Upload de imagem (multipart) |
| POST | `/chat/messages` | ✅ | Envia mensagem (com media_ids opcional) |
| GET | `/chat/messages` | ✅ | Lista mensagens (paginado, `?after=id`) |
| GET | `/days/today` | ✅ | Snapshot do dia atual |
| GET | `/days/{date}` | ✅ | Snapshot de um dia |
| POST | `/days/{date}/close` | ✅ | Encerra o dia (idempotente se já fechado) |
| GET | `/weekly` | ✅ | Relatório dos últimos 7 dias encerrados |
| PATCH | `/records/food-items/{id}` | ✅ | Edição direta (UI) |
| DELETE | `/records/food-items/{id}` | ✅ | Exclusão lógica |
| DELETE | `/records/water/{id}` | ✅ | Idem |
| PATCH/DELETE | `/records/beverage/{id}` | ✅ | Idem |
| PATCH/DELETE | `/records/activity/{id}` | ✅ | Idem |
| PATCH | `/nutrient-facts/{id}` | ✅ | Usuário confirma/edita valores lidos de um rótulo; seta `verified_by_user=true` |
| GET | `/health` | ❌ | Healthcheck |

> **Observação.** O cadastro de produto por leitura de tabela nutricional **não** exige endpoint próprio — o fluxo entra por `POST /chat/messages` como qualquer outra mensagem com imagem. O `PATCH /nutrient-facts/{id}` existe apenas para o cartão de confirmação da UI editar/confirmar valores após a leitura.

### Exemplos

**POST `/auth/login`**
```json
// req
{ "email": "felix@example.com", "password": "•••" }
// 204, Set-Cookie: access_token=...; refresh_token=...
```

**POST `/media`** (multipart)
```
file=@almoco.jpg
```
```json
// 201
{ "id": "9c3d…", "content_type": "image/jpeg", "size_bytes": 512300 }
```

**POST `/chat/messages`**
```json
// req
{ "text": "Este é meu almoço", "media_ids": ["9c3d…"] }
// 202
{ "message_id": "e1a2…", "status": "processing" }
```

**GET `/chat/messages?after=<id>`**
```json
{
  "messages": [
    { "id":"e1a2…","role":"user","content":"Este é meu almoço","created_at":"…","media":[…]},
    { "id":"e1a3…","role":"assistant","content":"Registrei arroz (150g), feijão (≈90g, estimativa) e frango (180g). Confirma o feijão?","llm_intent":"log_food","llm_confidence":0.86,"created_at":"…"}
  ]
}
```

**GET `/days/today`**
```json
{
  "date": "2026-07-13",
  "status": "open",
  "totals": {
    "kcal_in": 1420.5, "kcal_out": 310.0, "kcal_balance": 1110.5,
    "protein_g": 78.2, "carbs_g": 165.4, "fat_g": 42.1, "fiber_g": 18.0,
    "sodium_mg": 1820, "calcium_mg": 420, "iron_mg": 6.2, "potassium_mg": 2140,
    "water_ml": 1750, "other_liquids_ml": 250
  },
  "records": { "food": [...], "water": [...], "beverage": [...], "activity": [...] },
  "warnings": [
    { "code":"low_confidence_item","item_id":"…","message":"Feijão estimado por porção genérica." }
  ]
}
```

**POST `/days/2026-07-13/close`** → recalcula, grava snapshot, muda `status='closed'`, retorna o mesmo shape de `/days/{date}` + narrativa textual.

**GET `/weekly`** → retorna:
```json
{
  "window_start":"2026-07-06", "window_end":"2026-07-12",
  "per_day": [ {…snapshot resumido por dia…}, ... ],
  "totals": {...}, "averages": {...},
  "narrative": "Nesta semana você consumiu em média 1980 kcal/dia, com equilíbrio positivo…"
}
```

---

## 11. Estratégia de frontend

**Rotas.** Grupos `(auth)` (login) e `(app)` (protegido). `middleware.ts` intercepta rotas `(app)` e redireciona para `/login` se `access_token` inválido/ausente (chama `/api/auth/me` server-side via cookies encaminhados).

**UI.** Tailwind + shadcn/ui (Radix): escolhido por ser copy-paste de componentes (sem lock-in de estilos) e por acelerar botões/dialog/toast/table sem estilizar do zero. Justificativa: um usuário só, tempo curto, boa acessibilidade. Ícones: `lucide-react`.

**Estado.** TanStack Query para queries do dia/semana. Cache-first + revalidação a cada nova mensagem confirmada. Sem Redux/Zustand nesse MVP.

**Chat.** Componente `ChatShell` com:
- lista virtualizada (não crítica para 1 usuário mas cortesia futura),
- input com drop de imagens (React Dropzone),
- pré-visualização + botão remover,
- envio dispara mutation → 202 → polling em `/chat/messages?after=lastId` a cada 1.5s até chegar a assistant message (com retry cap 30s),
- toast em erro.

**Summary.** Componente `DayTable` renderiza a tabela do `/days/today`. Barra fixa no topo mostra "Saldo calórico: X" e botão "Encerrar dia".

**Uploads.** Sempre via `/api/media` do backend (não expor MinIO). Compressão client-side opcional com `browser-image-compression` antes do upload para reduzir custos de LLM.

**Alerta obrigatório.** Rodapé com aviso legal fixo.

---

## 12. Docker e ambiente local

**Portas locais** (documentadas no README):
- `3000` → Next.js (dev server com hot reload).
- `8000` → FastAPI (Uvicorn `--reload`).
- `5432` → Postgres.
- `9000` → MinIO S3.
- `9001` → MinIO Console (browser).

**Hot reload.** Volumes montados em `apps/web` e `apps/api`. `node_modules` em volume anônimo para não sobrescrever com o do host. Backend usa `uvicorn --reload` observando mudanças em `/app`.

**Healthchecks** em todos os serviços; backend só sobe quando Postgres e MinIO estão `healthy`.

**Sem Nginx** local (frontend fala direto com backend via `http://localhost:8000`; `NEXT_PUBLIC_API_URL=http://localhost:8000` no `.env.local`).

O arquivo completo está na seção 14.

---

## 13. Docker e deploy de produção em VPS

Uma única VPS Linux (Ubuntu 24.04 LTS recomendado). Instalar apenas Docker Engine + Compose plugin + `ufw` + `fail2ban`.

**Camadas.**
- Rede pública `web` (só o Nginx participa) e rede privada `internal` (todos os demais).
- Volumes nomeados: `pgdata`, `minio_data`, `letsencrypt`, `certbot_www`.
- Portas expostas ao host: apenas `80` e `443` do Nginx.
- Postgres e MinIO **sem** `ports:` (só acessíveis pela rede `internal`).
- Frontend Next.js roda em `output: 'standalone'` para imagem menor.

**HTTPS.** Nginx faz TLS. Certbot em modo `webroot`: um container `certbot` executa `certbot certonly` na inicialização e é acionado por um cronjob no host (`docker compose run --rm certbot renew`) semanalmente. Alternativa: Traefik com ACME embutido (menos arquivos a gerir, mas menos previsível). Escolha do MVP: **Nginx + Certbot** por transparência.

**Restart policy.** `unless-stopped` em todos os serviços.

**Migrations no deploy.** Script `scripts/deploy.sh`:
1. `git pull`;
2. `docker compose -f docker-compose.production.yml build`;
3. `docker compose -f docker-compose.production.yml run --rm api alembic upgrade head`;
4. `docker compose -f docker-compose.production.yml run --rm api python -m app.cli bootstrap`;
5. `docker compose -f docker-compose.production.yml up -d`.

**Recomendação de storage.** MinIO local na mesma VPS (bucket `registers-media`, TLS via Nginx *não* necessária pois só é acessado internamente). Alternativa: Cloudflare R2 (sem egress) ou Backblaze B2 — troca controle por menor operação. Para o MVP: MinIO local.

**Firewall (`ufw`).** Só liberar `22/tcp` (SSH), `80/tcp`, `443/tcp`. SSH ideal em porta customizada ou detrás de VPN, mas isso está fora do escopo do MVP; recomendação mínima: bloquear login por senha, usar chave.

**Backups.** Cronjob no host:
- `0 3 * * * /home/felix/my-registers/scripts/backup-postgres.sh` → `pg_dump -Fc` para `/var/backups/pg/`, retenção 14 dias.
- `0 4 * * * /home/felix/my-registers/scripts/backup-minio.sh` → `mc mirror` para pasta local ou remote (`rclone`).

**Rotação de logs.** No `docker-compose.production.yml`, `logging.driver=json-file` com `max-size=10m`, `max-file=5`.

---

## 14. Conteúdo completo dos arquivos obrigatórios

### 14.1 `.env.example`

```dotenv
# --- Aplicação ---
APP_ENV=production
APP_URL=https://app.example.com
API_URL=https://app.example.com/api
FRONTEND_ORIGIN=https://app.example.com

# --- Postgres ---
POSTGRES_DB=registers
POSTGRES_USER=registers_app
POSTGRES_PASSWORD=change-me-strong
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
DATABASE_URL=postgresql+asyncpg://registers_app:change-me-strong@postgres:5432/registers

# --- Anthropic ---
ANTHROPIC_API_KEY=sk-ant-REPLACE_ME
ANTHROPIC_MODEL=claude-sonnet-4-6
ANTHROPIC_FALLBACK_MODEL=claude-haiku-4-5-20251001
ANTHROPIC_MAX_TOKENS=1024
ANTHROPIC_TEMPERATURE=0.1

# --- Autenticação ---
JWT_SECRET=change-me-64-random-bytes-base64
JWT_ACCESS_TTL_SECONDS=900
REFRESH_TTL_SECONDS=1209600
COOKIE_DOMAIN=app.example.com
COOKIE_SECURE=true
COOKIE_SAMESITE=lax

# --- Admin bootstrap ---
DEFAULT_ADMIN_EMAIL=admin@example.com
DEFAULT_ADMIN_PASSWORD=change-me-strong

# --- Storage (S3 / MinIO) ---
S3_ENDPOINT=http://minio:9000
S3_REGION=us-east-1
S3_BUCKET=registers-media
S3_ACCESS_KEY=change-me-minio-key
S3_SECRET_KEY=change-me-minio-secret
S3_FORCE_PATH_STYLE=true
S3_PUBLIC_BASE_URL=

# --- MinIO server ---
MINIO_ROOT_USER=change-me-minio-key
MINIO_ROOT_PASSWORD=change-me-minio-secret

# --- Nginx / Let's Encrypt ---
DOMAIN=app.example.com
LETSENCRYPT_EMAIL=felix@example.com

# --- Timezone ---
TZ=America/Sao_Paulo

# --- CORS / segurança ---
ALLOWED_ORIGINS=https://app.example.com
RATE_LIMIT_LOGIN_PER_MIN=5

# --- Logging ---
LOG_LEVEL=INFO
LOG_FORMAT=json
```

### 14.2 `docker-compose.local.yml`

```yaml
# Ambiente LOCAL de desenvolvimento.
# Portas expostas ao host:
#   3000  -> web (Next.js hot reload)
#   8000  -> api (FastAPI hot reload)
#   5432  -> postgres
#   9000  -> minio S3
#   9001  -> minio console
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: registers
      POSTGRES_USER: registers_app
      POSTGRES_PASSWORD: dev_password
      TZ: America/Sao_Paulo
    ports:
      - "5432:5432"
    volumes:
      - pgdata_local:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U registers_app -d registers"]
      interval: 5s
      timeout: 3s
      retries: 10

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minio_dev
      MINIO_ROOT_PASSWORD: minio_dev_secret
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio_data_local:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 10s
      timeout: 3s
      retries: 6

  minio-init:
    image: minio/mc:latest
    depends_on:
      minio:
        condition: service_healthy
    entrypoint: >
      /bin/sh -c "
      mc alias set local http://minio:9000 minio_dev minio_dev_secret &&
      mc mb -p local/registers-media || true &&
      mc anonymous set none local/registers-media
      "

  api:
    build:
      context: ./apps/api
      dockerfile: Dockerfile
      target: dev
    environment:
      APP_ENV: development
      DATABASE_URL: postgresql+asyncpg://registers_app:dev_password@postgres:5432/registers
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      ANTHROPIC_MODEL: claude-sonnet-4-6
      JWT_SECRET: dev-only-secret-do-not-use-in-prod
      COOKIE_SECURE: "false"
      COOKIE_SAMESITE: lax
      S3_ENDPOINT: http://minio:9000
      S3_BUCKET: registers-media
      S3_ACCESS_KEY: minio_dev
      S3_SECRET_KEY: minio_dev_secret
      S3_FORCE_PATH_STYLE: "true"
      DEFAULT_ADMIN_EMAIL: admin@example.com
      DEFAULT_ADMIN_PASSWORD: adminadmin
      ALLOWED_ORIGINS: http://localhost:3000
      TZ: America/Sao_Paulo
      LOG_LEVEL: DEBUG
    volumes:
      - ./apps/api:/app
      - api_venv:/app/.venv
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      minio:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 3s
      retries: 6
    command: >
      sh -c "
      alembic upgrade head &&
      python -m app.cli bootstrap &&
      uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
      "

  web:
    build:
      context: ./apps/web
      dockerfile: Dockerfile
      target: dev
    environment:
      NEXT_PUBLIC_API_URL: http://localhost:8000
      NEXT_TELEMETRY_DISABLED: "1"
    volumes:
      - ./apps/web:/app
      - web_node_modules:/app/node_modules
      - web_next:/app/.next
    ports:
      - "3000:3000"
    depends_on:
      api:
        condition: service_healthy
    command: pnpm dev

volumes:
  pgdata_local:
  minio_data_local:
  api_venv:
  web_node_modules:
  web_next:
```

### 14.3 `docker-compose.production.yml`

```yaml
# Ambiente de PRODUÇÃO em VPS.
# Somente `nginx` expõe portas ao host (80/443).
# Postgres e MinIO ficam na rede interna, sem acesso público.
services:
  nginx:
    image: nginx:1.27-alpine
    restart: unless-stopped
    depends_on:
      - web
      - api
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./infra/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./infra/nginx/conf.d:/etc/nginx/conf.d:ro
      - letsencrypt:/etc/letsencrypt:ro
      - certbot_www:/var/www/certbot:ro
    networks: [web, internal]
    logging:
      driver: json-file
      options: { max-size: "10m", max-file: "5" }

  certbot:
    image: certbot/certbot:latest
    entrypoint: >
      /bin/sh -c "trap exit TERM;
      while :; do certbot renew --webroot -w /var/www/certbot --quiet;
      sleep 12h & wait $${!}; done"
    volumes:
      - letsencrypt:/etc/letsencrypt
      - certbot_www:/var/www/certbot
    networks: [internal]
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      TZ: ${TZ}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 3s
      retries: 10
    networks: [internal]
    logging:
      driver: json-file
      options: { max-size: "10m", max-file: "5" }

  minio:
    image: minio/minio:latest
    restart: unless-stopped
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
    volumes:
      - minio_data:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 15s
      timeout: 3s
      retries: 6
    networks: [internal]

  api:
    build:
      context: ./apps/api
      dockerfile: Dockerfile
      target: runtime
    restart: unless-stopped
    env_file: .env
    depends_on:
      postgres: { condition: service_healthy }
      minio:    { condition: service_healthy }
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 15s
      timeout: 3s
      retries: 6
    networks: [internal]
    logging:
      driver: json-file
      options: { max-size: "10m", max-file: "5" }

  web:
    build:
      context: ./apps/web
      dockerfile: Dockerfile
      target: runtime
    restart: unless-stopped
    environment:
      NEXT_PUBLIC_API_URL: /api
      NEXT_TELEMETRY_DISABLED: "1"
      NODE_ENV: production
    depends_on:
      api: { condition: service_healthy }
    networks: [internal]
    logging:
      driver: json-file
      options: { max-size: "10m", max-file: "5" }

networks:
  web:
  internal:
    internal: true

volumes:
  pgdata:
  minio_data:
  letsencrypt:
  certbot_www:
```

### 14.4 `apps/api/Dockerfile`

```dockerfile
# ---- base ----
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl libpq-dev && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.5.*
WORKDIR /app

# ---- dev ----
FROM base AS dev
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---- builder for runtime ----
FROM base AS builder
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .

# ---- runtime ----
FROM python:3.12-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl libpq5 && rm -rf /var/lib/apt/lists/* \
 && groupadd -r app && useradd -r -g app app
WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=6 CMD curl -f http://localhost:8000/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

### 14.5 `apps/web/Dockerfile`

```dockerfile
# ---- base ----
FROM node:20-alpine AS base
RUN corepack enable
WORKDIR /app

# ---- dev ----
FROM base AS dev
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
EXPOSE 3000
CMD ["pnpm", "dev"]

# ---- builder ----
FROM base AS builder
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

# ---- runtime (Next standalone) ----
FROM node:20-alpine AS runtime
RUN addgroup -S app && adduser -S app -G app
WORKDIR /app
ENV NODE_ENV=production PORT=3000
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
USER app
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=3s --retries=6 CMD wget -qO- http://localhost:3000/ || exit 1
CMD ["node", "server.js"]
```

O `next.config.mjs` do web precisa de `output: 'standalone'`.

### 14.6 `infra/nginx/nginx.conf` + `infra/nginx/conf.d/app.conf`

`nginx.conf`:
```nginx
user  nginx;
worker_processes auto;
events { worker_connections 1024; }
http {
  include /etc/nginx/mime.types;
  default_type application/octet-stream;
  sendfile on;
  tcp_nopush on;
  keepalive_timeout 65;
  server_tokens off;
  client_max_body_size 15m;
  gzip on;
  gzip_types text/plain text/css application/json application/javascript image/svg+xml;
  log_format main '$remote_addr - $request_id - "$request" $status $body_bytes_sent';
  access_log /var/log/nginx/access.log main;
  include /etc/nginx/conf.d/*.conf;
}
```

`conf.d/app.conf`:
```nginx
server {
  listen 80;
  server_name app.example.com;
  location /.well-known/acme-challenge/ { root /var/www/certbot; }
  location / { return 301 https://$host$request_uri; }
}
server {
  listen 443 ssl http2;
  server_name app.example.com;

  ssl_certificate     /etc/letsencrypt/live/app.example.com/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/app.example.com/privkey.pem;
  ssl_protocols TLSv1.2 TLSv1.3;
  ssl_ciphers HIGH:!aNULL:!MD5;

  add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
  add_header X-Content-Type-Options nosniff always;
  add_header X-Frame-Options DENY always;
  add_header Referrer-Policy strict-origin-when-cross-origin always;
  add_header Content-Security-Policy "default-src 'self'; img-src 'self' data: blob:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; font-src 'self' data:; frame-ancestors 'none'" always;

  location /api/ {
    proxy_pass http://api:8000/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_read_timeout 120s;
  }

  location / {
    proxy_pass http://web:3000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
  }
}
```

### 14.7 `scripts/bootstrap.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
docker compose -f docker-compose.production.yml run --rm api alembic upgrade head
docker compose -f docker-compose.production.yml run --rm api python -m app.cli bootstrap
```

### 14.8 `scripts/backup-postgres.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
STAMP=$(date +%Y%m%d-%H%M)
OUT=/var/backups/pg
mkdir -p "$OUT"
docker compose -f /home/felix/my-registers/docker-compose.production.yml \
  exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc \
  > "$OUT/registers-$STAMP.dump"
find "$OUT" -name 'registers-*.dump' -mtime +14 -delete
```

### 14.9 `scripts/backup-minio.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
STAMP=$(date +%Y%m%d)
docker run --rm --network my-registers_internal \
  -v /var/backups/minio:/backup minio/mc \
  sh -c "mc alias set src http://minio:9000 $MINIO_ROOT_USER $MINIO_ROOT_PASSWORD && \
         mc mirror --overwrite src/registers-media /backup/$STAMP"
find /var/backups/minio -maxdepth 1 -mindepth 1 -type d -mtime +14 -exec rm -rf {} +
```

---

## 15. Estratégia de migrations, seed e bootstrap

1. **Alembic** com autogeração habilitada. Cada migration versionada e revisada em PR.
2. Migração inicial cria pgcrypto (para `gen_random_uuid()`), CITEXT extension, todas as tabelas.
3. Seed do catálogo nutricional (`nutrient_facts`) via CLI (`app.cli seed-nutrition`), lendo o CSV do repositório. Idempotente por `UNIQUE(canonical_name, source, brand)`.
4. **Bootstrap admin** via CLI (`app.cli bootstrap`), como descrito na §7. Idempotente. A CLI *sempre* zera `os.environ['DEFAULT_ADMIN_PASSWORD']` após consumir.
5. Deploy chama, em ordem: `alembic upgrade head` → `python -m app.cli bootstrap` → `up -d`. Falhar em qualquer passo aborta o deploy.
6. Runtime da API **não** executa migrations sozinho (evita race entre replicas ou operações não intencionais).

---

## 16. Segurança — checklist

- [ ] Senhas com Argon2id, `time_cost=3, memory_cost=64MB, parallelism=2`.
- [ ] Segredos (`ANTHROPIC_API_KEY`, `JWT_SECRET`, etc.) só no `.env` no host, `chmod 600`, dono `root` ou `felix`.
- [ ] Cookies `HttpOnly; Secure; SameSite=Lax; Path=/`.
- [ ] Access token de 15 min, refresh de 14 dias com rotação e detecção de reuso.
- [ ] CORS: allowlist explícita, `allow_credentials=true`, sem wildcard.
- [ ] Rate limit no `POST /auth/login` (5/min por IP + backoff). Bloqueio temporário após 10 tentativas por email.
- [ ] Upload: valida MIME server-side, tamanho ≤ 8 MB, `Pillow` para *decode probe*, gera nome novo (jamais reutiliza nome do cliente), armazena `checksum_sha256`.
- [ ] Autorização: toda rota protegida verifica `user_id` no path/query contra o `sub` do JWT. Repositórios exigem `user_id` em toda query.
- [ ] Logs: filtro que remove `Authorization`, `Cookie`, `password`, `token` e o corpo do login. Nunca logar imagens ou payload da Anthropic com credenciais.
- [ ] Backups criptografados quando off-VPS (`rclone crypt` ou GPG).
- [ ] Dependências: Dependabot/renovate; `pip-audit` e `pnpm audit` no CI.
- [ ] Postgres: usuário `registers_app` sem `SUPERUSER`, dono apenas do schema `public`. Sem porta pública.
- [ ] MinIO: rede interna, sem acesso público. URLs pré-assinadas (SigV4, TTL 5 min) para downloads no frontend quando necessário.
- [ ] HTTPS forçado, HSTS. Cabeçalhos definidos no Nginx conforme §14.6.
- [ ] MinIO console `9001` nunca exposto em produção.
- [ ] Verificação de content-type real (não confiar em extensão) e sanitização de nomes.

---

## 17. Observabilidade, logs e backups

- **Logging.** JSON estruturado (stdlib `logging` + formatter customizado). Campos: `ts`, `level`, `service`, `request_id`, `user_id`, `route`, `latency_ms`, `event`, `payload`. `request_id` injetado por middleware; propagado no cabeçalho `X-Request-Id`.
- **Métricas** (fase 2, não obrigatória no MVP): `/metrics` Prometheus com contagem de intents, latência de LLM, taxa de retry.
- **Alertas mínimos** (MVP): script cron que verifica se `/health` responde 200 e envia email/Telegram em caso de falha (`healthchecks.io` gratuito é uma opção).
- **Backups.** §14.8 e §14.9. Retenção 14 dias local; sugerir espelhamento semanal off-VPS (rclone + Backblaze B2 recomendado por custo).
- **Restore.** Script `scripts/restore-postgres.sh` documenta o procedimento.
- **Auditoria.** `messages.raw_llm_response` + `audit_events` cobrem "quem alterou o quê e por quê". Retido enquanto o registro existir.

---

## 18. Roadmap de implementação em fases

**Fase 0 — Fundação (2–3 dias).** Monorepo, Dockerfiles, docker-compose local, esqueleto FastAPI + Next.js, health, `alembic init`, config Pydantic Settings, logging.

**Fase 1 — Autenticação e admin bootstrap (1–2 dias).** Tabelas `users` + `refresh_tokens`, endpoints `/auth/*`, middleware do frontend, CLI `bootstrap`.

**Fase 2 — Camadas de mensagem + upload (2 dias).** Tabelas `messages`, `media`, `message_media`, `day_logs`. Rotas `/media`, `/chat/messages`. Cliente MinIO com URLs assinadas.

**Fase 3 — Integração Anthropic (3 dias).** Cliente Anthropic com `tool_use`, `LLMEnvelope`, retries, prompt v1, testes com fixtures.

**Fase 4 — Registro de alimentos (3 dias).** Tabelas `food_records`, `food_items`, `nutrient_facts`. Seed TBCA. `MealService`, `NutritionCalculator`, `DailyRecomputeService`. UI: `DayTable`.

**Fase 4.b — Leitura de tabela nutricional (1–2 dias).** Migração das três colunas novas em `nutrient_facts` (`barcode`, `label_media_id`, `verified_by_user`) e do enum `source`. Extensão do schema LLM e prompt v2 com as regras 16–18. `LabelCatalogService.upsert_from_label` (normaliza `per_serving` → `per_100g|ml` deterministicamente). Cartão de confirmação no chat + `PATCH /nutrient-facts/{id}`. Fluxo `also_consumed` reaproveitando `MealService` e o `catalog_ref_id` recém-criado.

**Fase 5 — Hidratação e atividades (2 dias).** `water_records`, `beverage_records`, `activity_records`, `ActivityCalculator` (METs + peso do usuário).

**Fase 6 — Correções e exclusões (2 dias).** `CorrectionService` (matching por descrição textual usando o mais recente, com heurística por normalização de nome), `audit_events`.

**Fase 7 — Encerramento e relatório diário (1 dia).** `POST /days/{date}/close`, geração de narrativa amigável via LLM alimentada pelo snapshot já calculado.

**Fase 8 — Relatório semanal (1 dia).** `WeeklyReportService`, endpoint, tabela `weekly_reports`, UI.

**Fase 9 — Hardening + deploy (2 dias).** Nginx + Certbot, docker-compose.production, scripts de backup, testes end-to-end.

Total estimado: ~20–21 dias úteis em ritmo focado, um dev.

---

## 19. Critérios de aceite do MVP

1. Um único admin (`DEFAULT_ADMIN_EMAIL`) consegue logar. Cadastro público não existe.
2. Enviar texto **ou** foto ou ambos gera mensagens do usuário e do assistant, com registro persistido no Postgres.
3. Alimentos, água, outros líquidos e atividades são reconhecidos e persistidos em tabelas distintas.
4. A tabela do dia atualiza a cada nova mensagem relevante e mostra: calorias in/out/balanço, macros, micros (Na/Ca/Fe/K), água e outros líquidos.
5. Correções via chat modificam o registro correto e são refletidas na tabela; `audit_events` registra a mudança.
6. `Encerrar dia` fecha, calcula, salva snapshot e devolve tabela + resumo textual.
7. Relatório semanal considera os **7 últimos dias encerrados**, apresenta tabela diária + totais + médias + narrativa gerada apenas a partir dos números.
8. Nenhum cálculo de kcal/macros/micros vem da LLM (verificável por testes unitários que substituem o cliente Anthropic por um mock devolvendo qualquer valor: os totais dependem apenas da tabela `nutrient_facts` e das quantidades).
9. Imagens ficam no MinIO; banco só guarda `storage_key`.
10. Todas as respostas incluem `confidence`; itens com `confidence<0.5` disparam pedido de confirmação ou marcação visível.
11. Aviso legal presente no rodapé e no relatório diário.
12. Ao enviar foto de uma tabela nutricional, o produto é cadastrado em `nutrient_facts` com `source='label_ocr'` e `label_media_id` preenchido, e passa a ser reutilizável em registros futuros por nome/marca. Se a mensagem indicar consumo (`also_consumed`), um `food_record`/`food_items` é criado no mesmo ciclo, usando o `catalog_ref_id` recém-criado. O usuário consegue confirmar/editar os valores via cartão de confirmação (`PATCH /nutrient-facts/{id}`), setando `verified_by_user=true`.
13. Deploy reprodutível em VPS limpa via `scripts/bootstrap.sh` + `docker compose up -d`.
14. HTTPS válido, HSTS, sem MinIO ou Postgres expostos publicamente.
15. Backups automáticos rodam e um `restore` dry-run funciona.

---

## 20. Riscos, limitações e próximos passos

**Riscos.**
- **Precisão nutricional por foto** é intrinsecamente estimativa. Mitigação: catálogo local + confidence + aviso obrigatório + facilidade de correção.
- **Custo e latência da Anthropic** com muitas imagens. Mitigação: prompt caching, compressão de imagem no cliente (≤1024px), Haiku para intents leves.
- **Matching de correções** ("corrija o frango") é ambíguo se houver múltiplos itens semelhantes. Mitigação: no matching, se ambíguo, o backend responde pedindo desambiguação (`needs_clarification=true` no lado do backend também).
- **Deriva do schema JSON.** Mitigação: `tool_use` + Pydantic + retries + monitor de erros de parse.
- **Single-VPS.** Sem HA. Aceito para MVP; ganho de simplicidade compensa.

**Limitações conscientes do MVP.**
- Sem cadastro nem reset por design.
- Sem versionamento avançado de porções por unidade doméstica além da tabela seed.
- Sem integração com wearables/Apple Health/Google Fit.
- Sem streaming SSE do chat (polling curto é suficiente para 1 usuário).

**Próximos passos naturais.**
1. Multi-usuário (o schema já suporta; falta cadastro, isolamento e políticas de plano).
2. Integração com Apple Health/Google Fit para calorias gastas mais precisas.
3. Fila real (RQ ou Dramatiq) e observabilidade Prometheus + Grafana.
4. Refinamento da base nutricional com UI de edição do catálogo e importação por código de barras (Open Food Facts).
5. Testes end-to-end automatizados (Playwright) e CI (GitHub Actions) com deploy por SSH.
6. Modo offline-friendly no PWA para registrar por voz quando sem sinal.
7. Persistir e agregar `sugars_g`, `added_sugars_g`, `saturated_fat_g` e `trans_fat_g` em `nutrient_facts`, `food_items` e `daily_snapshots`; expor no relatório diário/semanal (hoje só chegam do rótulo pela LLM e são descartados).
8. Leitura de código de barras (via biblioteca `zxing`/`quagga` no cliente ou pela própria LLM na imagem) para acelerar cadastro por marca, usando o campo `barcode` já existente.

---

**Observação final.** Este plano assume as premissas listadas na §2. Antes de implementar, confirme: timezone do usuário, peso corporal (necessário para METs) e a preferência entre MinIO local vs. R2/B2 para storage de produção. Nada além disso bloqueia o início da Fase 0.
