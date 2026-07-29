# Trade-offs — Snapshot diário

## Decisão 1 — Snapshot materializado + recompute from-scratch (INV-4)

### Contexto

Duas dimensões cruzadas: *cache?* e *como recomputar?* Cache reduz latência de leitura; from-scratch reduz complexidade de manutenção. O cruzamento gera 4 quadrantes; escolhemos "materializado + from-scratch".

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Materializado + from-scratch (escolhida) | Leitura O(1) em cliente; escrita reconstrói tudo (simples, sem drift) | Escrita custa O(N_registros_do_dia) — 10-30 SUMs |
| B — Materializado + delta incremental | Escrita rápida | Drift silencioso; race conditions horríveis; soft delete quebra |
| C — Não materializar (derive on-read) | Sem cache pra invalidar | Cada leitura roda 4 SUMs; polling do chat multiplica load |
| D — Não materializar + view Postgres | "Simples" | Views não fecham dia (INV-5); performance idem C |

### Decisão tomada

**Opção A.** N por dia é ordem de 10-30 no MVP; custo de recompute é ~10ms em Docker local.

### Consequências

- **Positivas**: raciocínio trivial; teste "delete e verifica se some do total" é 3 linhas; auditoria via `snapshot.version` monotônico.
- **Negativas**: cada mutação carrega custo de recompute — em multi-user com centenas de items/dia, seria proibitivo. Aceito para MVP.

---

## Decisão 2 — Water e Beverage em tabelas separadas (Const. Art. IV, INV-2, INV-3)

### Contexto

Poderia unificar em uma tabela `liquid_records` com campo `kind ∈ {water, beverage}`. Argumento: "líquido é líquido".

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Tabelas separadas: `water_records`, `beverage_records` (escolhida) | Impossível somar água em `kcal_in` por engano; INV-2/3 enforced pelo schema | 2 tabelas quase iguais |
| B — Tabela única com `kind` | 1 model | Cada query precisa lembrar do filtro `kind`; risco de bug quando alguém esquece |

### Decisão tomada

**Opção A.** Constituição Art. IV §12-14 é literal: "água ≠ outros líquidos".

### Consequências

- **Positivas**: `_aggregate_water(day_log_id)` só olha `water_records` — inequívoco; `IntentDispatcher` rejeita `log_water` com `kcal > 0` (SP-41).
- **Negativas**: mais duas repos, mais dois models — aceito.

---

## Decisão 3 — `populate_existing=True` no `RETURNING`

### Contexto

Regressão vista na Fase 4: após `UPSERT ... RETURNING DailySnapshot`, chamar `snapshot.kcal_in` devolvia valor antigo. Culpado: identity map do SQLAlchemy.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — `execution_options(populate_existing=True)` (escolhida) | 1 linha; corrige o comportamento | Levemente exótico; futuro dev pode remover sem saber por quê |
| B — `session.expire(snapshot)` explícito após retorno | Comum em SQLAlchemy | Dobra código; frágil se caller esquece |
| C — Fetch fresh: nova query pós-UPSERT | Sempre correto | Duas queries (custo) |

### Decisão tomada

**Opção A.** Documentada em comment do service (linha 115 de `daily_recompute.py`).

### Consequências

- **Positivas**: transparente pro caller.
- **Negativas**: precisa de comment permanente pra evitar regressão futura ("por que essa flag existe?"). Feito.

---

## Decisão 4 — Snapshot on-read em dia aberto sem snapshot materializado

### Contexto

Cenário: bug/imprevisto grava `food_records` sem chamar `recompute`. Dia fica sem snapshot atualizado. Leitura falha ou devolve valor antigo.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Auto-recompute on-read em dia aberto (escolhida) | Self-heal; cliente sempre vê estado correto | Custo extra se snapshot já existe — mitigado por check `snapshot is None` |
| B — 500 se snapshot inexiste | Explícito | UX ruim; obriga runbook |
| C — Zeros silenciosos | Simples | Total errado passa despercebido |

### Decisão tomada

**Opção A.** Só recomputa se snapshot é NULL, dia aberto e `allow_recompute=True`.

### Consequências

- **Positivas**: código resiliente a bugs upstream.
- **Negativas**: mascara bugs (feature vs. anti-pattern). Aceito por confiabilidade > alertabilidade em MVP.

---

## Decisão 5 — `daily_snapshots.user_id` redundante com `day_logs.user_id`

### Contexto

Poderia derivar `user_id` sempre via JOIN — normalizado.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Redundante (escolhida) | Weekly report faz `SELECT WHERE user_id AND status='closed'` sem JOIN | Denormalizado |
| B — Só em `day_logs` | Normal | JOIN em toda query |

### Decisão tomada

**Opção A.** Denormalização barata.

### Consequências

- **Positivas**: queries agregadas simples.
- **Negativas**: `user_id` de `daily_snapshots` fica órfão se `day_log.user_id` mudar — impossível na prática (FK CASCADE).

---

## Decisão 6 — `local_today` via `zoneinfo`

### Contexto

Alternativas: `pytz`, `dateutil`, offset manual.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — `zoneinfo` (stdlib desde 3.9) (escolhida) | Zero dep; correto | Nada |
| B — `pytz` | Legado | Dep extra |
| C — Offset manual (`user.utc_offset_minutes`) | Simples | Ignora DST |

### Decisão tomada

**Opção A.** `python 3.12` já vem com `zoneinfo`.

### Consequências

- Corretude com DST automática (Brasil não usa mais DST, mas queremos suporte extensível).

---

## Dívida técnica conhecida

| Item | Impacto | Prioridade |
|---|---|---|
| Sem métrica de "tempo médio de recompute" — não sabemos quando começa a incomodar | Baixo (single-user) | Baixa; adicionar quando abrir pra multi-user |
| Race de dois recomputes simultâneos incrementa `version` 2x pra "mesma operação lógica" | Baixo | Aceito |
| Dia fechado sem snapshot devolve zeros silenciosamente em vez de erro | Baixo | Documentado no comment |
| `_load_records` faz N+1 subtil: 1 query por categoria (4 queries totais) | Baixo | Aceito; consolidação com JSONB no futuro |
| Warnings JSONB sem constraint no shape (pode virar bagunça se dev adicionar campo diferente) | Médio | Adicionar schema JSON validation (pgcrypto?) no futuro |
| Sem TTL/limpeza de `daily_snapshots` — cresce indefinido | Muito baixo (1 linha/dia × user) | Ignorar |

## Riscos identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| Novo campo em snapshot é adicionado mas `_snapshot_to_totals(None)` esquece o default | Média (evolução) | Médio (KeyError no cliente) | Teste que valida shape exato de `_snapshot_to_totals(None)` |
| Migração altera Numeric precision e recompute retro-modifica valores | Baixa | Alto | Fase 10 CI valida; snapshot de dia fechado nunca é tocado (INV-5) |
| Timezone do user muda; leitura de `today` retorna dia diferente do "hoje" que o user vê | Baixa (users não mudam TZ) | Baixo | Aceito; próximo `today` alinha |
| Recompute concurrent em multi-instance (cluster) causa lost update | Média (se escalar) | Alto | Advisory lock por `day_log_id` — futuro |
| `populate_existing=True` removido em refactor | Baixa (comment explica) | Alto (regressão silenciosa Fase 4) | Comment permanente + teste que quebra sem a flag |

## Alternativas para pós-MVP

- **Trigger no DB** que recompute snapshot on `INSERT/UPDATE/DELETE` das 4 tabelas — reduziria acoplamento (services não precisam chamar `recompute` explicitamente). Trade-off: lógica de negócio no DB, mais difícil de testar.
- **JSONB `records` inteiros no snapshot** — devolveria payload completo em 1 query. Trade-off: dado duplicado; audit fica mais complexo.
- **Version-based cache no cliente** (SWR) — cliente cacheia snapshot por versão. Trade-off: complexidade extra.
- **Materialized view** do Postgres — nativo. Trade-off: refresh manual ou trigger; menos flexível que service Python.
- **Warnings type-safe** — Pydantic model para cada warning, serializado como JSONB. Menos "stringly typed".
