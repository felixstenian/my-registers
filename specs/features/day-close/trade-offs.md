# Trade-offs — Encerramento de dia

## Decisão 1 — Recompute forçado antes do close (SP-102, INV-4)

### Contexto

Fechamento poderia confiar no snapshot atual (assumindo que último recompute foi correto). Ou recomputar defensivamente.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Sempre recomputar antes de congelar (escolhida) | Snapshot final = fatos vivos; sem race latente | Custo extra ~10ms |
| B — Confiar no snapshot atual | Rápido | Se recompute anterior falhou, dia fecha com valores errados |
| C — Verificar `snapshot.computed_at` vs. `records.updated_at` | Otimização condicional | Complexidade sem valor claro |

### Decisão tomada

**Opção A.** SP-102 codifica. Cost de 10ms é irrelevante frente à latência total (~2-3s LLM).

### Consequências

- **Positivas**: histórico "à prova de bug". Fechar sempre consolida.
- **Negativas**: 10ms extras. Aceito.

---

## Decisão 2 — Idempotência estrita: 2ª chamada não recomputa nem chama LLM

### Contexto

Se dia já é `closed`, o que fazer numa 2ª chamada? Poderia: (a) ignorar completamente, (b) refazer tudo.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Retornar estado atual sem side effect (escolhida) | Const. §29; UX tolerante; sem custo API extra | Se algum bug corrompeu snapshot pós-close, 2ª chamada não corrige |
| B — Recomputar mesmo em closed | "Auto-heal" | Viola INV-5; chamadas Anthropic desnecessárias |
| C — Erro 409 | Explícito | UX ruim (duplo clique) |

### Decisão tomada

**Opção A.** Retornar `was_already_closed=True`; cliente pode reagir mostrando "já fechado" se quiser.

### Consequências

- **Positivas**: UX tolerante; sem custo LLM extra; audit único.
- **Negativas**: raro cenário de "dia fechado com dados errados" precisa manutenção externa. Aceito.

---

## Decisão 3 — Fallback textual quando LLM falha

### Contexto

Se `call_narrative` retorna `error` (timeout, sem API key), o que gravar em `snapshot.narrative`?

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Texto fallback fixo + disclaimer (escolhida) | Nunca deixa `narrative=None`; compliance mantida | Menos personalizado |
| B — `narrative=None` e cliente exibe genérico | Simples | Compliance quebra se cliente esquecer disclaimer |
| C — Retry até LLM voltar | Robusto | Bloqueia UX; dia fica "abrindo" |

### Decisão tomada

**Opção A.** `_FALLBACK_NARRATIVE = "Dia encerrado com os totais registrados no chat..."` — curto, útil, sem alucinação.

### Consequências

- **Positivas**: SP-104 (disclaimer) sempre cumprida; UX previsível.
- **Negativas**: user vê texto genérico em vez de resumo emocional. Aceito.

---

## Decisão 4 — `_with_disclaimer` evita duplicação por substring exata

### Contexto

LLM às vezes inclui texto exato do disclaimer no output. Se concatenarmos, duplicará.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Check `if _DISCLAIMER in stripped` (escolhida) | Simples; funciona | Depende de LLM copiar texto EXATO (fragil se der versão parafraseada) |
| B — Regex fuzzy | Robusto contra parafraseamento | Complexidade; falso-positivo pode remover disclaimer legítimo |
| C — Nunca duplicar; usar sentinel | Explícito | Precisa injetar sentinel em prompt |

### Decisão tomada

**Opção A.** Prompt `narrative_v1.md` orienta LLM a NÃO incluir disclaimer; se incluir, mesmo texto exato.

### Consequências

- **Positivas**: código minimal.
- **Negativas**: se LLM parafrasear (ex.: "As estimativas são aproximadas..."), teste `test_disclaimer_not_duplicated_if_llm_returns_it` falha; forçamos LLM a copiar EXATO ou não incluir.

---

## Decisão 5 — `get_or_create` de day_log em close

### Contexto

User pode querer fechar dia sem registros. Sem `get_or_create`, close falharia com 404.

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — `get_or_create` sempre (escolhida) | UX permissiva; "fechar Zero" é válido | Cria linha "vazia" |
| B — 404 se sem day_log | Explícito | UX ruim (user teria que "abrir" o dia primeiro) |
| C — Só permitir close se houve pelo menos 1 record | Purista | Muito restritivo; edge case comum "sem input" |

### Decisão tomada

**Opção A.**

### Consequências

- **Positivas**: user pode fechar dia sem input.
- **Negativas**: linhas "vazias" em `day_logs` — inócuas.

---

## Decisão 6 — INV-5 enforçado em outros services

### Contexto

Ao fechar, `day_log.status='closed'`. Quem verifica isso ao tentar corrigir/deletar?

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Cada service (Correction/Deletion/etc.) checa (escolhida) | Separação de responsabilidades | Duplicação de check |
| B — Middleware / trigger global | DRY | Acoplamento alto; difícil de testar |
| C — DB trigger que bloqueia UPDATE | Enforçado no schema | Erro obscuro pra cliente; complexidade migration |

### Decisão tomada

**Opção A.** `CorrectionService`, `DeletionService`, `ConfirmationService` cada um checa antes de mutar.

### Consequências

- **Positivas**: local reasoning.
- **Negativas**: se dev novo esqueça check em service novo, INV-5 vaza. Teste E2E cobre.

---

## Decisão 7 — Encerramento retroativo permitido

### Contexto

User esqueceu de encerrar ontem. Deveria poder fechar hoje?

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Permitir close de qualquer data com day_log aberto (escolhida) | UX pragmática; SP-155 v1.11 | Fecha "ontem" com timestamp de hoje (aceito) |
| B — Só permitir close de "hoje" | Puro | UX ruim; força reabertura |
| C — Warning "não é hoje; confirma?" | Compromisso | Complexidade UI |

### Decisão tomada

**Opção A.** Backend não valida data.

### Consequências

- **Positivas**: dia "aberto órfão" tem caminho de resolução.
- **Negativas**: `closed_at != log_date` — cliente precisa lidar.

---

## Decisão 8 — Sem endpoint de "reabrir" (Const. §28)

### Contexto

E se user quiser corrigir dia fechado depois?

### Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A — Sem reabertura (escolhida) | História imutável; Const. §28 | User precisa "criar novo registro hoje" pra compensar |
| B — Endpoint admin de reabertura | Escape hatch | Viola Const.; complexidade |

### Decisão tomada

**Opção A.**

### Consequências

- **Positivas**: história é história.
- **Negativas**: usuário precisa aceitar "erro do passado". Aceito.

---

## Dívida técnica conhecida

| Item | Impacto | Prioridade |
|---|---|---|
| `_require_snapshot` faz recompute em dia closed (situação anômala) — viola INV-5 tecnicamente | Baixo (só em anomalia) | Baixa; comentário documenta |
| `_with_disclaimer` só detecta texto EXATO; parafraseamento passa | Baixo (prompt controla) | Baixa; monitorar via teste |
| Não há timeout / limite max de retentativas na `call_narrative` (usa timeout do cliente global) | Baixo | Baixa |
| INV-5 duplicado em vários services | Médio (DRY) | Média; helper `raise_if_day_closed` |
| Sem métrica de "narrativas fallback / mês" — sinal de LLM instável | Baixo | Baixa |

## Riscos identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| LLM começa a parafrasear disclaimer | Média | Médio (duplicação visível) | Prompt reforça "não repita disclaimer"; teste detecta |
| Anthropic outage durante close | Média | Baixo (fallback textual) | Aceito |
| Dev novo cria service que muta records sem checar INV-5 | Média | Alto (dia "fechado" corrompido) | Teste E2E; code review |
| Race: user clica "encerrar" 2× muito rápido | Alta (UX) | Baixo (idempotente) | Cobre |
| Snapshot corrompido em anomalia + close ignora | Baixa | Alto (dia fecha com números errados) | Runbook manual; recompute via CLI |
| Fuso mudou entre `open` e `close` | Muito baixa | Baixo | `local_today(user.timezone)` no momento |

## Alternativas para pós-MVP

- **Reabrir dia com auditoria explícita** — se surgir demanda; hoje é `may_not`.
- **Narrativa multilíngue** (i18n).
- **Comparação com dia anterior** ("kcal_in 200 acima da média dos últimos 7 dias").
- **Sugestões automáticas** ("Você está com déficit de fibra"). Cuidado — não pode virar aconselhamento médico.
- **Notificação push ao encerrar** ("Dia fechado com sucesso").
- **Draft mode**: user vê narrativa antes de confirmar close. Trade-off: quebra idempotência atômica.
- **Endpoint de "regenerar narrativa"** para user que ficou insatisfeito com a gerada. Trade-off: viola imutabilidade.
