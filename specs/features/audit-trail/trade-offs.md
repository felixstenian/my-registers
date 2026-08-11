# Trade-offs — Trilha de auditoria

## Decisão 1 — Repository em `repositories/food.py` (não arquivo próprio)

### Contexto

`AuditEventRepository` está em `repositories/food.py` por razões históricas (criado junto com `FoodRecordRepository` na Fase 4).

### Consequências

- **Negativas**: nome enganoso — dev novo não acha.
- **Mitigação**: extrair para `repositories/audit.py` é refactor simples; nenhuma regra de negócio muda.
- **Prioridade**: baixa — funciona; nenhum bug.

---

## Decisão 2 — `entity_id` sem FK constraint

### Contexto

Cada `entity_type` aponta para tabela diferente. SQL relacional não suporta FK polimórfica nativa.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Sem FK (escolhida) | Simples; audit sobrevive se entidade for hard-deletada | Sem integridade referencial; orphan possível |
| B — Tabelas separadas por tipo | FK real | Explosão de tabelas; code duplication |
| C — Extension ltree ou herança | Elegante | Complexidade de infra |

### Decisão tomada

**Opção A.** Todas as deleções são soft — orphan é improvável.

### Consequências

- **Positivas**: audit é permanente mesmo se entidade sumir.
- **Negativas**: nenhuma garantia DB de que `entity_id` existe.

---

## Decisão 3 — JSONB para `before`/`after`

### Contexto

Shape varia por `entity_type`. Colunas tipadas exigiriam migration por novo campo.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — JSONB (escolhida) | Flexível; evolução sem migration | Sem validação de schema |
| B — Colunas por tipo | Type-safe | Explosão de colunas |

### Decisão tomada

**Opção A.**

### Consequências

- **Positivas**: adicionar campo em snapshot é mudar uma linha de código no service.
- **Negativas**: bugs de shape passam silenciosos. Mitigação: testes nos callers.

---

## Decisão 4 — `flush()` dentro de `record()`, não `commit()`

### Contexto

Garantir atomicidade com a transação do caller.

### Decisão tomada

`flush()` inclui o INSERT no batch da sessão atual. `commit()` quebraria atomicidade — audit persistiria mesmo se caller fizer rollback.

---

## Decisão 5 — Bug latente: `action='confirm'` fora de `AUDIT_ACTIONS`

### Contexto

`confirmation.py` usa `action="confirm"` mas `AUDIT_ACTIONS = ("create","update","delete","correct")` no model. Se o CHECK constraint em `audit_events` foi criado com essa tupla, INSERT com `action='confirm'` falhará.

### Ação recomendada

1. Verificar migration que cria `audit_events` — o CHECK usa `AUDIT_ACTIONS` da classe ou hard-codes?
2. Se não incluiu `confirm`: criar migration `ALTER TABLE audit_events DROP CONSTRAINT ck_audit_events_action; ALTER TABLE audit_events ADD CONSTRAINT ck_audit_events_action CHECK (action IN ('create','update','delete','correct','confirm','close'))`.
3. Atualizar `AUDIT_ACTIONS` no modelo.

---

## Dívida técnica conhecida

| Item | Impacto | Prioridade |
|---|---|---|
| `AuditEventRepository` em `repositories/food.py` | Baixo (descoberta) | Baixa; extrair para `repositories/audit.py` |
| `action='confirm'` pode estar fora do CHECK | Alto (bug latente se constraint existe) | **Alta — verificar imediatamente** |
| Sem endpoint de leitura de auditoria | Médio (operacional) | Média; admin endpoint futuro |
| `before`/`after` JSONB sem shape validation | Médio (silencia bugs de shape) | Média; Pydantic no momento de escrita |
| `entity_id` sem FK | Baixo (soft delete protege) | Baixa |
| `audit_events` cresce sem purge | Baixo no MVP | Baixa; archive cron futuro |
| Testes gaps nos callers (water, beverage, activity, confirm) | Médio (INV-10 parcialmente não testado) | **Alta — adicionar asserts** |

## Riscos identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| `action='confirm'` falha no Postgres (CHECK) | Média (se constraint existe) | Alto (confirmação quebra) | Verificar migration + adicionar `confirm` ao CHECK |
| Dev novo não encontra `AuditEventRepository` | Média | Baixo | Extrair para `repositories/audit.py` |
| `before`/`after` shape inconsistente entre services | Média | Médio (investigação difícil) | Documentar shapes na tabela de specifications.md |
| Audit cresce indefinidamente | Baixa (single-user) | Baixo | Archive cron para rows > 1 ano |

## Alternativas para pós-MVP

- **Endpoint `GET /admin/audit-events`** com filtros por entity, action, date.
- **Extrair `AuditEventRepository` para `repositories/audit.py`**.
- **Adicionar `action='close'` à constante** (já usado mas pode não estar no CHECK).
- **Schema validation em `before`/`after`** via Pydantic por entity_type.
- **Event sourcing** completo — audit como fonte de verdade para reconstruir estado. Overkill para MVP.
- **Archive job** — mover rows > 1 ano para tabela `audit_events_archive` ou S3.
