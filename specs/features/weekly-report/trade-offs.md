# Trade-offs — Relatório semanal

## Decisão 1 — Idempotência por fingerprint `snapshot_versions` (SP-112)

### Contexto

`GET /weekly` pode ser chamado muitas vezes. Chamar `call_weekly_narrative` toda vez seria custoso e lento.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Fingerprint `[{day_log_id, version}]` (escolhida) | Preciso: só regenera se dado mudou | Comparação de JSONB list pode ser frágil |
| B — TTL fixo (ex.: regenerar 1x/hora) | Simples | Pode cachear dados stale; pode regenerar desnecessário |
| C — Sempre regenerar | Sempre atualizado | Custo LLM em toda requisição |

### Decisão tomada

**Opção A.** SP-112 pede idempotência de `id` quando os dados não mudam — fingerprint é a semântica correta.

### Consequências

- **Positivas**: zero custo LLM em chamadas repetidas sem novo fechamento.
- **Negativas**: ordenação da `snapshot_versions` precisa ser determinística — resolve ordenando por `day_log_id.bytes`. Se essa ordenação mudar, falsifica "mudança" e gera desnecessariamente.

---

## Decisão 2 — `Decimal` para somas, `float`/`int` na saída

### Contexto

`SUM(daily_snapshots.kcal_in)` em Python pode usar `float` (rápido, impreciso) ou `Decimal` (preciso, mais lento).

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — `Decimal` interno, `float` no output (escolhida) | Exatidão de bits na soma | Overhead de `Decimal` |
| B — `float` puro | Rápido | Erro de representação em somas de N dias |
| C — Agregar no Postgres (SELECT SUM) | Exato no banco | N+1 queries ou CTE complexa |

### Decisão tomada

**Opção A.** Const. §5 (INV-1) pede determinismo. `float(Decimal("1750.07"))` é bit-idêntico entre chamadas.

### Consequências

- **Positivas**: `test_totals_and_averages_are_deterministic` é trivial.
- **Negativas**: overhead de `Decimal` sobre N snapshots (~7) é nanosegundos. Irrelevante.

---

## Decisão 3 — JSONB para todos os campos agregados

### Contexto

`totals`, `averages`, `per_day`, `snapshot_versions` poderiam ser colunas tipadas.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — JSONB (escolhida) | Schema flexível; adicionar campo novo em snapshot não exige migration no `weekly_reports` | Sem constraint de shape; queries por campo interno são strings |
| B — Colunas tipadas | Type-safe | Migration toda vez que `_TOTAL_FIELDS` crescer |

### Decisão tomada

**Opção A.** `_TOTAL_FIELDS` pode crescer (novos micros); JSONB absorve.

### Consequências

- **Positivas**: evolução sem migration.
- **Negativas**: se campo esperado sumir do JSONB, serialização devolve `None` sem aviso.

---

## Decisão 4 — Relatório transiente para zero dias

### Contexto

Zero dias fechados → `window_start=None`, `window_end=None`. Constraint `UNIQUE(user_id, NULL, NULL)` não funciona em Postgres (NULL != NULL em constraints).

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Objeto em memória, sem persistir (escolhida) | Correto semanticamente; sem colisão de PK | `id` gerado não é referenciável depois |
| B — Gerar UUID especial sentinel (ex.: UUID zeros) | Persistível | Semântica esquisita |
| C — 404 quando sem histórico | Explícito | Quebra UX — melhor devolve dados zerados |

### Decisão tomada

**Opção A.** Zero dias é estado válido — frontend renderiza "Nenhum dia fechado ainda" com `days_included=0`.

### Consequências

- **Positivas**: UX não quebra; frontend recebe shape consistente.
- **Negativas**: `id` não é referenciável. Aceito.

---

## Decisão 5 — Janela = `{min, max}` das datas, não semana calendário

### Contexto

"Últimos 7 dias fechados" pode ou não coincidir com segunda-domingo.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — `window_start=min(dates)`, `window_end=max(dates)` (escolhida) | Exatamente os 7 fechados; SP-110 literal | "Semana" pode ter buracos (dias não fechados no meio) |
| B — Semana ISO (seg-dom) | Familiar | Inclui dias abertos ou sem registro — viola INV-8 |

### Decisão tomada

**Opção A.** SP-110 é explícito: "7 `day_logs` com `status='closed'`".

### Consequências

- **Positivas**: INV-8 sempre satisfeito.
- **Negativas**: "semana" pode ser 7 dias não consecutivos. Narrativa LLM precisa lidar (prompt instrui).

---

## Decisão 6 — `_with_disclaimer` duplicado em `weekly_report.py` e `day_close.py`

### Contexto

Mesma função em dois services.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Duplicar (escolhida) | Sem acoplamento entre services | Dois lugares para manter |
| B — Importar de `day_close.py` | DRY | Acoplamento semântico esquisito |
| C — Extrair para `utils/text.py` | DRY e sem acoplamento | Refactor adicional |

### Decisão tomada

**Opção A.** Funções de 5 linhas — custo de manutenção mínimo; acoplamento de services é pior.

### Consequências

- **Positivas**: ambos os services são independentes.
- **Negativas**: se disclaimer mudar, atualizar em 2 lugares. Aceito (basta grep).

---

## Dívida técnica conhecida

| Item | Impacto | Prioridade |
|---|---|---|
| `_with_disclaimer` duplicado (`day_close.py` + `weekly_report.py`) | Baixo | Baixa; extrair para `utils/text.py` no v2 |
| `snapshot_versions` comparação de lista de dicts — frágil se ordem mudar | Médio | Média; usar hash deterministico (SHA-256 do JSON sorted) |
| JSONB sem shape validation — campo novo ausente = None silencioso | Médio | Média; Pydantic no output side já protege |
| `latest()` não usado hoje (rota `GET /weekly` sempre faz `generate`) | Baixo | Baixa |
| Payload LLM sem `per_day` — narrativa pode ficar genérica | Baixo (qualidade) | Baixa; incluir `per_day` compacto se qualidade melhorar |

## Riscos identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| `snapshot_versions` fingerprint falha por ordem não determinística | Baixa (sorted por .bytes) | Médio (LLM chamada toda vez) | Teste de determinismo; migrar para hash SHA-256 |
| Anthropic outage → fallback; usuário vê narrativa genérica | Média | Baixo | Fallback explícito; UX aceitável |
| `per_day` com snapshot faltante → zeros silenciosos | Baixa (anomalia) | Baixo | `_reduce_snapshot(day, None)` defende; log de warning futuro |
| Crescimento de `weekly_reports` (1 por janela por user) | Muito baixa (single-user, poucas janelas) | Baixo | Ignorar no MVP |
| `window_start == window_end` (1 dia fechado) → UNIQUE key válida | Esperado | Zero | Funciona; `days_included=1` |

## Alternativas para pós-MVP

- **Hash SHA-256 de `snapshot_versions`** para fingerprint mais robusto.
- **`per_day` compacto no payload LLM** para narrativa mais detalhada.
- **Cache HTTP `ETag`/`Last-Modified`** na rota `GET /weekly` — client pode condicional `If-None-Match`.
- **Métricas de uso**: quantas vezes foi `reused=True` vs. regenerado por semana.
- **Comparação com semana anterior** no payload LLM — "essa semana vs. semana passada".
- **Exportação CSV/PDF do semanal** — feature B-06 listada em `spec.md §7`.
