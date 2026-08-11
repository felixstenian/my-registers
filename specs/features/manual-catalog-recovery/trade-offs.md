# Trade-offs — Recuperação manual de itens sem catálogo

## Decisão 1 — Prompt textual com CTAs vs. UI estruturada nativa

### Contexto

O bloco de recovery aparece na assistant message. Poderia ser JSON estruturado (o backend anexa `{ type: "recovery", items: [...] }` e o cliente renderiza componente próprio) ou texto markdown com padrão detectável.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Markdown com CTAs textuais + regex no cliente (escolhida) | Não muda contrato do `messages.content`; degradação graciosa em clientes sem regex; testável só no backend | Acoplamento por regex; formatter e parser precisam concordar |
| B — Campo extra em `messages` (JSONB `structured_content`) | Type-safe | Migration extra; quebra assumptions de outros consumidores; frontend ignora campo se legado |
| C — Endpoint separado `GET /messages/{id}/actions` que devolve CTAs | Separado | 2× requests; latência dobrada |

### Decisão tomada

**Opção A.** Spec §140 já define o formato textual dos CTAs. Frontend estende `AssistantContent.tsx` com regex.

### Consequências

- **Positivas**: mudança backend é 1 função (`compose_meal`); teste unit direto.
- **Negativas**: regressão no formato quebra silenciosamente os botões — teste E2E obrigatório.

---

## Decisão 2 — Transação única, promoção como "partial success"

### Contexto

Cadastro do fact e promoção do item legado são semanticamente distintos. O cliente disparou uma requisição pedindo ambas.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — 1 transação; fact sempre criado; promoção com warning se falhar (escolhida) | User não perde form; erro comunicado sem rollback | Semântica "201 com warning" é peculiar (2xx + falha parcial) |
| B — 2 endpoints separados (POST create + POST promote) | Cada um atomicamente correto | 2 requests, UX pior, timeout duplicado |
| C — 1 transação com rollback total se promoção falhar | Puro all-or-nothing | User re-preencher form é UX ruim; edge cases de "outro user" viram erro |

### Decisão tomada

**Opção A.** Spec §142 é explícita: "endpoint retorna 201 do fact criado + warning `promotion_failed` no body (não falha o cadastro)".

### Consequências

- **Positivas**: um único caminho happy path; user sempre tem o fact.
- **Negativas**: contract sofisticado — cliente precisa checar `promotion.warning`, não só status code.

---

## Decisão 3 — `source='user_manual'` vs. reusar `'manual'`

### Contexto

`CATALOG_SOURCES = ('TBCA_2023','USDA_FDC','manual','label_ocr')` — `manual` já existe. Migration T-B502 adiciona `user_manual`.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Adicionar `user_manual` novo (spec-driven) (escolhida) | Semântica clara: "criado por user via form"; distingue de seed manual legado | Migration extra; 5 valores no enum ao invés de 4 |
| B — Reusar `manual` | Sem migration | Ambiguidade: linha `manual` pode ter vindo de seed OU de user form; auditabilidade ruim |
| C — Novo enum tipo `origin` separado de `source` | Rigor máximo | Overkill; 2 colunas para 1 conceito |

### Decisão tomada

**Opção A.** Consistente com spec §141: "Persiste com `source='user_manual'`".

### Consequências

- **Positivas**: audit trail claro; queries "quantos facts o Felix cadastrou?" simples.
- **Negativas**: se release for antes da migration → CHECK constraint falha em `INSERT`. Deploy runbook precisa deixar isso claro (`docs/deploy.md`).

---

## Decisão 4 — `aliases` como ARRAY do Postgres

### Contexto

`pão_de_queijo_congelado` precisa casar com "pão de queijo" também.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — `ARRAY(Text)` na tabela `nutrient_facts` (escolhida) | Sem JOIN; GIN index disponível se precisar | Nativo do Postgres; menos portável |
| B — Tabela `nutrient_fact_aliases (fact_id, alias)` | Portável; row per alias | Overhead de JOIN em toda busca |
| C — Aliases dentro de `canonical_name` separados por vírgula | Simplicíssimo | Zero estrutura; regex bug prone |

### Decisão tomada

**Opção A.** Já existe no modelo (`aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), ...)`); reusa.

### Consequências

- **Positivas**: lookup pode ser `WHERE 'pao de queijo' = ANY(aliases)`.
- **Negativas**: sem constraint de unicidade entre aliases de facts diferentes do mesmo user; precedência resolve.

---

## Decisão 5 — Sem sugestão automática pela LLM

### Contexto

Tentador: LLM emite `intent=log_food` + `no_catalog_hit` → LLM sugere valores em `nutrient_fact_hint`.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — LLM não preenche form (escolhida) | Const. §5 (LLM não calcula); UX honesta ("adivinhar" não é confiança) | Um passo extra pra user |
| B — LLM sugere valores no bloco, user confirma no form | Menos digitação | Viola Const.; valores errados persistidos sem revisão |

### Decisão tomada

**Opção A.** Constituição Art. II §5 é literal.

### Consequências

- **Positivas**: valores no catálogo do user são 100% humanos-verificados.
- **Negativas**: user precisa digitar mais. Aceito.

---

## Decisão 6 — Sem endpoint DELETE de fact manual

### Contexto

User cadastra "pão de queijo" com kcal errado. Como corrigir?

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Sem DELETE; corrigir via `PATCH /nutrient-facts/{id}` (existente) (escolhida) | Reusa infra da SP-33 (label OCR) | Sem "unpromote" — item legado fica com fact deletado (mas fact persiste, então OK) |
| B — DELETE que soft-deleta fact | Simétrico | Precisa lidar com items apontando pro fact deletado |
| C — DELETE hard | Simplíssimo | Perde histórico; audit fica meia-boca |

### Decisão tomada

**Opção A.** PATCH da SP-33 aceita `label_ocr` **e** `manual` como editáveis. Estender pra `user_manual` é trivial.

### Consequências

- **Positivas**: código existente já cobre; audit funciona.
- **Negativas**: user "cria" fact "errado" ficando forever no DB. Aceito — auditoria preserva; espaço é irrisório.

---

## Dívida técnica conhecida

| Item | Impacto | Prioridade |
|---|---|---|
| Regex no `AssistantContent.tsx` acopla-se ao markdown do formatter | Médio (regressão silenciosa) | Média; adicionar teste E2E que valida botões |
| ADR pendente sobre 200 vs 201 em merge de `canonical_name` | Baixo (só definição) | Alta antes do merge |
| Dia fechado + promoção — comportamento exato (200/201 com warning vs 409) não fechado | Baixo (uma decisão) | Média; T-B505 pin |
| `created_by` sem foreign key CASCADE clarificado | Baixo | Baixa; NULL vira orphan se user for deletado |
| Migration 0008 precisa rodar em produção antes do release do endpoint | Alto (release quebra sem migration) | Alta; deploy runbook |
| Sem métrica de "quantos manual creates por semana" | Baixo (produto) | Baixa; futuro |

## Riscos identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| Migration 0008 esquecida no deploy | Média (Fase 10 automatiza `alembic upgrade head`, mas se falhar) | Alto (500 no POST) | CI/CD chama `alembic upgrade head` (docs/deploy.md §14); healthcheck pós-deploy |
| Cliente frontend não passa `promote_food_item_id` corretamente | Média (bug UX) | Médio (fact criado, item continua zerado) | Teste E2E fim-a-fim; UI mostra "item vinculado: X" antes do submit |
| Race: item deletado entre GET (form aberto) e POST (submit) | Baixa | Baixo (warning promotion_failed cobre) | Aceito; UI mostra warning |
| Precedência do catálogo confunde (`user_manual` empata com TBCA?) | Média (lógica sutil) | Médio (usuário vê valores errados) | Teste explícito de precedência em `LocalTBCACatalog` |
| Regex do bloco de recovery quebra em português com acentos ("São") | Baixa | Baixo | Regex tolerante; teste com nomes acentuados |
| Duas requests POST simultâneas mesmo canonical_name do mesmo user | Baixa | Baixo (2 linhas duplicadas se ADR não fechar merge) | Constraint UNIQUE `(created_by, canonical_name)` — considerar |

## Alternativas para pós-MVP

- **DELETE de fact** com re-mapeamento de items para catalog_ref_id=NULL + recompute em cascata.
- **Sugestão contextual pela LLM** com flag explícita "sugestão — revise valores" antes do submit (viola Const. §5, mas UX melhor).
- **Compartilhamento de facts entre users** (opcional, opt-in): fact "público" que outros users podem usar. Precisa ADR (§21 vs. praticidade).
- **Barcode scanner** (`nutrient_facts.barcode` já existe, spec §7 mantém "campo pré-preparado"). Feature futura.
- **Auto-cadastro por marca**: se user já cadastrou "Forno de Minas: pão de queijo congelado", oferecer preencher form com valores do mesmo brand para outro produto similar.
- **Métricas de qualidade do catálogo**: quantos `no_catalog_hit` viram cadastro? Sinal pra investir em seed TBCA.
