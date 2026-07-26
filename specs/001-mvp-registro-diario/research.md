# Research & ADRs — MVP: Registro Diário por Chat com IA

**Feature ID:** 001-mvp-registro-diario
**Escopo:** decisões arquiteturais e técnicas com trade-offs. Serve como memória "por que fizemos assim". Alterações requerem novo ADR (não editar histórico).

Formato de cada ADR:
```
## ADR-NNN — Título curto
Status: proposed | accepted | superseded by ADR-MMM
Data: yyyy-mm-dd

Contexto: por que a decisão precisou ser tomada.
Decisão: o que fica escolhido.
Consequências: efeitos (bons e ruins).
Alternativas descartadas: com motivo objetivo.
```

---

## ADR-001 — Argon2id + JWT curto com refresh token opaco

**Status:** accepted
**Data:** 2026-07-15

**Contexto.** Precisamos armazenar senha localmente e manter sessão. Constituição §15-17 exige hash resistente a GPU e cookies HttpOnly.

**Decisão.** Argon2id (`time_cost=3, memory_cost=64MB, parallelism=2`). Sessão em dois cookies: JWT HS256 curto (15min) para access + refresh opaco de 32 bytes (14 dias) armazenado hasheado (SHA-256) em `refresh_tokens`, com rotação obrigatória a cada uso.

**Consequências.**
- ✔ Backend não precisa consultar banco por request (JWT stateless).
- ✔ Revogação real via refresh opaco.
- ✔ Reuso de refresh revogado detectável; invalida família.
- ✘ Duas credenciais para gerenciar; mais complexidade no logout.

**Alternativas descartadas.**
- **Session pura server-side.** Simples, mas cada request consulta banco; sem benefício para MVP com 1 usuário mas piora ergonomia futura.
- **bcrypt.** OK mas não resistente a GPU moderno; Argon2id é o recomendado atual.
- **PBKDF2.** Mais fraco que Argon2 na mesma faixa de custo.

---

## ADR-002 — MinIO local na VPS como default de storage de produção

**Status:** accepted
**Data:** 2026-07-15

**Contexto.** Fotos precisam ir para storage S3-compatible (Constituição §3). Escolha entre auto-hospedar (MinIO na VPS) ou terceirizar (Cloudflare R2, Backblaze B2, Wasabi).

**Decisão.** MinIO na mesma VPS para o MVP (rede interna, sem exposição pública). Trocável por R2/B2 via variáveis `S3_*`.

**Consequências.**
- ✔ Zero custo de egress; sem risco de spike inesperado.
- ✔ Backup e migração sob controle total.
- ✘ Se a VPS morrer, perdemos storage junto com o banco. Mitigado por `scripts/backup-minio.sh` + espelhamento off-VPS via rclone.
- ✘ Overhead de operação (renovar buckets, monitorar disco).

**Alternativas descartadas.**
- **R2.** Ótimo custo/benefício e sem egress, mas adiciona dependência externa; deixado como plug-and-play via env vars.
- **B2.** Idem, com egress cobrado a partir de 3× ingest — pouco preocupante no MVP.

---

## ADR-003 — Alembic pinado `>=1.14,<1.16`

**Status:** accepted
**Data:** 2026-07-15

**Contexto.** Fase 0. Alembic 1.16+ introduziu auto-discovery de `pyproject.toml` como fonte de configuração. Como nosso `pyproject.toml` (do uv) não tem seção `[tool.alembic]`, o Alembic 1.16 falha com "No 'script_location' key found" ao invés de cair para `alembic.ini`.

**Decisão.** Pinar em `alembic>=1.14,<1.16`. Passar `-c alembic.ini` explicitamente em todos os comandos (defensa em profundidade).

**Consequências.**
- ✔ Comportamento estável e testado.
- ✘ Perdemos features 1.16+ (auto-generate melhorado, formatos alternativos). Aceitável no MVP.

**Alternativas descartadas.**
- **Migrar para `[tool.alembic]` no `pyproject.toml`.** Espalha config em dois formatos entre versões; documentação oficial ainda usa `.ini`.
- **Aceitar 1.16+ e criar `[tool.alembic]` vazio para desviar.** Frágil; próximo release pode mudar semântica.

---

## ADR-004 — Recompute-from-scratch em vez de delta

**Status:** accepted
**Data:** 2026-07-15

**Contexto.** Snapshots diários (`daily_snapshots`) podem ficar inconsistentes se acumularmos deltas em cima de valores antigos após correção/exclusão de registros.

**Decisão.** Toda mutação (create/update/delete/correct) em food/water/beverage/activity chama `DailyRecomputeService.recompute(day_id)`, que faz `SELECT SUM(...) WHERE deleted_at IS NULL` e regrava o snapshot. Snapshots incrementam `version`.

**Consequências.**
- ✔ Sempre correto por construção; nenhum bug de estado stale.
- ✔ Simples de raciocinar.
- ✘ Custo de escrita a cada mutação; aceitável até dezenas de refeições/dia. Para escala futura, materialized view + refresh assíncrono.

**Alternativas descartadas.**
- **Delta incremental.** Rápido mas frágil; qualquer race ou falha parcial produz totais errados.
- **Compute on-read.** Elimina o snapshot mas piora `GET /days/today` P95.

---

## ADR-005 — Semana = últimos 7 dias encerrados

**Status:** accepted
**Data:** 2026-07-15

**Contexto.** "Semana" pode significar segunda-domingo, janela móvel de 7 dias, ou últimos 7 dias fechados.

**Decisão.** Últimos 7 dias com `status='closed'`. Se houver menos, retornar os disponíveis + `warnings: insufficient_history`.

**Consequências.**
- ✔ Simples de comunicar ("os últimos 7 que você fechou").
- ✔ Sem dependência de fuso horário além do que já usamos em `day_logs`.
- ✔ Sem viés de "meio de semana" quando o usuário começa a usar numa quinta.
- ✘ Se o usuário deixar de encerrar dias, o semanal atrasa. Aceitável para único usuário.

**Alternativas descartadas.**
- **Segunda-domingo.** Requer decidir cutoff timezone; adiciona lógica de "semana atual vs. anterior".
- **Janela móvel de 7 dias com dias abertos incluídos.** Viola Constituição §30 e mistura dados provisórios com fechados.

---

## ADR-006 — Catálogo local TBCA + fallback "pergunte ao usuário"

**Status:** accepted
**Data:** 2026-07-15

**Contexto.** Precisamos de fonte de dados nutricionais para alimentos in natura e industrializados. Opções: catálogo local (TBCA), API externa (USDA FDC, Open Food Facts), ou pedir à LLM os macros por 100g.

**Decisão.** MVP usa `LocalTBCACatalog` (~50-100 itens seed) + fallback conservador: se não achou, marcar `catalog_ref_id=null` e pedir os valores ao usuário. Extensão futura: `LLMFallbackCatalog` atrás de feature flag.

**Consequências.**
- ✔ Zero dependência externa em cold path.
- ✔ Valores da TBCA são de referência brasileira, confiáveis.
- ✔ Aderente à Constituição §5 (LLM não gera macros).
- ✘ Seed limitado; muitos alimentos comuns podem faltar. Mitigado pelo fluxo de rótulo (SP-30) que cadastra dinamicamente.

**Alternativas descartadas.**
- **USDA FDC como fonte principal.** Valores em inglês, alimentos americanos; menos relevante para pt-BR.
- **LLM devolvendo macros no `log_food`.** Viola Const. §5; testes automatizados falhariam.

---

## ADR-007 — `tool_use` obrigatório na Anthropic

**Status:** accepted
**Data:** 2026-07-15

**Contexto.** LLM pode devolver texto livre + JSON, apenas JSON, ou via tool call estruturado. Precisamos garantir schema estrito e retry robusto.

**Decisão.** Toda chamada usa `tool_use` da SDK Anthropic com uma única tool `record_intent` cujo `input_schema` é o JSON schema versionado. Textos livres da LLM são descartados. Retry semântico: 2 tentativas mandando o `ValidationError` do Pydantic como user message.

**Consequências.**
- ✔ Schema enforced pela SDK; menos parseamento manual.
- ✔ Reduz alucinação de campos.
- ✔ Fácil versionar (system prompt + schema versionados juntos).
- ✘ Custo ligeiramente maior (tool overhead), compensado por prompt caching.

**Alternativas descartadas.**
- **JSON mode + regex.** Frágil; JSON malformado exige retry manual.
- **Multi-tool com uma tool por intent.** Adiciona complexidade sem benefício claro para MVP.

---

## ADR-008 — Backend no host em macOS (Caminho A)

**Status:** accepted
**Data:** 2026-07-15

**Contexto.** Fase 0 do dev: Docker Desktop no macOS falha com `OSError: [Errno 35] Resource deadlock avoided` quando Python importa arquivos via bind mount (`./apps/api:/app`). Bug reproduzido em `EDEADLK` durante `alembic upgrade head` e `import env.py`.

**Decisão.** Padrão de dev em macOS é rodar Postgres+MinIO no Docker e backend+frontend no host via `pnpm dev:api` / `pnpm dev:web`. Docker de produção segue funcionando normalmente (não usa bind mount).

**Consequências.**
- ✔ Sem `EDEADLK`; loop de dev estável.
- ✔ Debugger nativo funciona.
- ✔ I/O 10-50× mais rápido no APFS.
- ✘ Exige `brew install uv` no host.
- ✘ Divergência entre "dev macOS" e "dev Linux" (Linux pode rodar tudo em Docker sem problema).

**Alternativas descartadas.**
- **Toggle VirtioFS/gRPC-FUSE.** Testado; intermitente. Não confiável.
- **Anonymous volume no lugar do bind mount.** Perde hot reload; loop insuportável.
- **Rebuild a cada mudança.** Mesmo problema, com espera maior.

---

## ADR-009 — Fila leve com `BackgroundTasks` do FastAPI

**Status:** accepted
**Data:** 2026-07-15

**Contexto.** Chamadas à Anthropic levam segundos; não podem bloquear o handler HTTP. Opções: `BackgroundTasks` (fila in-process), RQ (Redis-based), Dramatiq, Celery.

**Decisão.** `BackgroundTasks` para o MVP single-user. Recompute idempotente cobre eventual crash antes do término.

**Consequências.**
- ✔ Zero dependência adicional (sem Redis).
- ✔ Suficiente para 1 usuário.
- ✘ Sem persistência da fila; se o processo cair no meio, a mensagem "assistant" nunca é gerada (mas o `messages(user)` está salvo — o usuário pode reenviar).
- ✘ Não escala; migrar para RQ/Dramatiq no B-09.

**Alternativas descartadas.**
- **RQ + Redis.** Adiciona container e complexidade; overhead injustificado para 1 usuário.
- **Anthropic streaming inline.** Bloqueia o handler; UI ainda precisaria de polling.

---

## ADR-010 — Nginx + Certbot no lugar de Traefik

**Status:** accepted
**Data:** 2026-07-15

**Contexto.** Reverse proxy com TLS automático. Opções: Nginx + Certbot webroot, Traefik com ACME embutido, Caddy.

**Decisão.** Nginx + Certbot webroot. Um único domínio, config estática, documentação vasta.

**Consequências.**
- ✔ Config transparente e diagnóstico direto.
- ✔ HSTS, CSP e cabeçalhos de segurança definidos explicitamente.
- ✘ Mais arquivos a gerir vs. Traefik.

**Alternativas descartadas.**
- **Traefik.** Ótimo para múltiplos serviços e labels; overkill para um domínio.
- **Caddy.** Automatiza tudo mas menos previsível em edge cases.

---

## ADR-011 — Registro estruturado de treino agrega ao `log_activity`

**Data:** 2026-07-26
**Status:** aceito
**Contexto:** SP-120..SP-127 (seção 3.13 da spec) introduzem um novo modelo hierárquico para treinos de força — sessão → exercícios → séries — que é fundamentalmente mais granular que o `log_activity` atual (uma linha em `activity_records` = uma atividade inteira).

**Decisão:** manter as duas representações. `log_activity` continua sendo o registro flat para cardio genérico ("corri 40 min moderado", "natação 30 min"). O novo módulo (`workout_sessions`, `workout_exercises`, `workout_sets`) rastreia treinos de força com detalhamento. **No encerramento da sessão (SP-124 ou SP-125), o backend consolida o treino em 1 `activity_record`** com `activity_type='strength'`, `calc_method='workout_session'`, kcal estimados via MET fixo por `workout_type`. Assim:

- Snapshot diário e relatório semanal continuam agnósticos — enxergam `activity_record` como fonte única de `kcal_out`.
- Detalhamento (peso × reps por exercício) fica nas novas tabelas, consultável para histórico (SP-121, SP-127) mas não impacta os totais nutricionais.
- Correção/deleção do `activity_record` gerado **não** propaga para as tabelas de treino — INV-13. Se um dia isso incomodar (usuário apaga séries e espera kcal recalcular), abrir feature nova; fora do MVP-de-treino.

**Alternativas descartadas:**
- **Substituir `log_activity` por sessão para tudo.** Complexidade desnecessária para cardio simples ("corri 40 min" não precisa de sessão + exercício + série).
- **Duas tabelas totalmente separadas, sem consolidação.** Snapshot e semanal precisariam saber sobre duas fontes de `kcal_out`, adicionando complexidade ao recompute e ao formatter — quebra INV-1 (única fonte de verdade para totais).
- **Consolidação em tempo real (a cada série adicionada).** Cada série disparando recompute é caro; o dado só faz sentido total quando a sessão fecha. Consolidar no encerramento é o momento natural.

**Consequências:**
- Migration nova cria 3 tabelas + FK opcional `activity_records.workout_session_id` para trilha reversa (dado `activity_record`, achar a sessão original).
- MET fixo por tipo é aproximado (musculação varia muito com carga/descanso). Aceito como MVP; refinamento pode vir com "volume total × densidade" no futuro.
- Sessões que ficam abertas por dias (usuário esqueceu de encerrar) são fechadas automaticamente por SP-125 quando o dia é fechado. Se o usuário nunca fechar o dia, sessão fica órfã indefinidamente — aceito por ora.

---

## Histórico

- **2026-07-15** — v1.0. 10 ADRs iniciais registrando decisões da Fase 0 e do plano.
- **2026-07-26** — v1.1. ADR-011 aceito: registro estruturado de treino agrega ao `log_activity` via consolidação no encerramento (contexto da seção 3.13 da spec).
