# Trade-offs — Remoção de registros

## Decisão 1 — Soft delete (`deleted_at`) vs. hard delete

### Contexto

Registros de negócio (food, water, beverage, activity) poderiam ser deletados fisicamente para simplificar queries.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Soft delete `deleted_at=now()` (escolhida) | Histórico para audit; recovery possível via SQL; `messages` não ficam órfãs | Queries precisam de `WHERE deleted_at IS NULL` |
| B — Hard delete | Schema limpo | Sem audit; `messages.food_records` ficam com FK morta |

### Decisão tomada

**Opção A.** Const. Art. III §11 exige auditoria total. Hard delete destruiria `before` state.

### Consequências

- **Positivas**: `audit_events.before` preserva estado.
- **Negativas**: DB cresce com linhas soft-deleted. Aceito — volume é baixo (single-user).

---

## Decisão 2 — Idempotência: 2ª chamada é no-op silencioso (SP-81)

### Contexto

Usuário pode clicar "Remover" duas vezes ou mensagem pode ser reprocessada.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — `already_deleted=True` → 200 sem efeitos (escolhida) | HTTP-correto; UX tolerante | Caller precisa checar campo |
| B — 404 na 2ª chamada | Explícito | Erro em UX tolerante |
| C — 409 conflict | Explícito | Desnecessariamente severo |

### Decisão tomada

**Opção A.** SP-81 codifica "idempotente".

### Consequências

- **Positivas**: double-click nunca quebra.
- **Negativas**: recompute extra evitado — snapshot não é "corrigido" erroneamente.

---

## Decisão 3 — Reutilizar `TargetMatcher` e `_snapshot` de `correction.py`

### Contexto

Deletion e correction precisam das mesmas operações de matching + snapshot de estado.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Importar diretamente de `correction.py` (escolhida) | DRY; um lugar para mudar | Acoplamento entre módulos |
| B — Duplicar código | Isolamento | Drift ao mudar matcher |
| C — Extrair para módulo compartilhado `matching.py` | Clean | Refactor adicional |

### Decisão tomada

**Opção A.** Features são genuinamente gêmeas; acoplamento é intencional.

### Consequências

- **Positivas**: mudança em `TargetMatcher` afeta ambas automaticamente.
- **Negativas**: `deletion.py` importa de `correction.py`; se `correction.py` for renomeado, `deletion.py` quebra. Aceito — são mesma feature-set.

---

## Decisão 4 — 4 endpoints separados vs. 1 genérico

### Contexto

`DELETE /records/{type}/{id}` vs. `DELETE /records/food-items/{id}` + `/water/{id}` etc.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — 4 endpoints separados (escolhida) | OpenAPI explícito; path param fortemente tipado | 4 funções quase idênticas |
| B — 1 endpoint com `{type}` path param | DRY | OpenAPI menos legível; type validation mais fraco |

### Decisão tomada

**Opção A.** `_delete_generic` seca o código; os 4 endpoints são wrappers de 2 linhas.

### Consequências

- **Positivas**: `/docs` mostra 4 rotas claras.
- **Negativas**: adicionar kind novo (ex.: workout_set) requer novo endpoint. Aceito.

---

## Decisão 5 — `actor` inferido de `message_id`

### Contexto

`actor='llm'` vs. `'user'` — como diferenciar chat de REST?

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — `actor = 'llm' if message_id else 'user'` (escolhida) | Sem argumento extra; infere do contexto | Acoplamento semântico sutil |
| B — Argumento explícito `actor: str` | Explícito | API mais verbosa |

### Decisão tomada

**Opção A.** REST passa `message_id=None` por default; chat sempre tem `message_id`.

### Consequências

- **Positivas**: API de `_soft_delete` simples.
- **Negativas**: se surgir caso de REST com `message_id` (impossível hoje), `actor` seria 'llm' erroneamente. Aceito.

---

## Decisão 6 — Sem `DELETE /records/food-records/{id}`

### Contexto

`food_records` é o agrupador de `food_items`. Poderia ser deletável.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Sem endpoint para food_record (escolhida) | Simplifica; user remove item a item | food_record "fantasma" (todos items deleted) permanece |
| B — Delete em cascade em food_record | UX de "remover refeição inteira" | Comportamento de CASCADE confuso; sem precedente na spec |

### Decisão tomada

**Opção A.** Spec SP-80 fala em "registros" individualmente; sem menção a refeição inteira.

### Consequências

- **Positivas**: simplicidade.
- **Negativas**: user precisa remover item por item se quiser limpar refeição. Edge case — aceito.

---

## Dívida técnica conhecida

| Item | Impacto | Prioridade |
|---|---|---|
| `food_records` "fantasmas" acumulam (todos items deleted, record permanece) | Muito baixo | Baixa; cosmético |
| Sem purge de linhas soft-deleted (DB cresce indefinidamente) | Baixo (single-user) | Baixa; cron de archive futuro |
| `deletion.py` importa de `correction.py` — acoplamento | Baixo | Média; extrair `_matching.py` no v2 |
| Sem `DELETE /records/food-records/{id}` | Baixo (UX) | Baixa; adicionar se surgir demanda |
| Sem "undelete" / restore | Baixo (audit permite manual) | Baixa; CLI admin como escape hatch |

## Riscos identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| Double-delete concorrente (2 requests simultâneos ao mesmo item) | Baixa | Baixo (idempotente) | 2ª executa no-op; audit tem 1 entrada |
| Delete de item em dia fechado via race (close + delete concorrente) | Baixa | Alto (INV-5) | `_ensure_day_open` no início; ambas transações veem `status='closed'` |
| `correction.py` renomeado sem atualizar `deletion.py` | Baixa (CI) | Médio (import error) | Teste de import; refator conjunto |
| Volume de linhas soft-deleted impactar queries | Muito baixa (single-user) | Baixo | `deleted_at IS NULL` é indexável; mitigação futura |
