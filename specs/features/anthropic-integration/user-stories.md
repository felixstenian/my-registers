# Histórias de Usuário — Integração Anthropic

## Personas

- **Felix (P1)** — usuário final que envia texto/foto e espera resposta relevante.
- **Backend developer** — usuário indireto: escreve/testa services que dependem da LLM.
- **Sistema (não-persona)** — governança arquitetural (INV-1, INV-9, custo).

---

### US-001 — Registrar por linguagem natural

**Como** Felix,
**Quero** enviar "150 g arroz, 90 g feijão" e receber o registro pronto,
**Para que** eu não preencha formulário.

**Critérios de aceitação resumidos:**
- [ ] LLM classifica `intent=log_food` e extrai `food_items`.
- [ ] Backend calcula kcal via catálogo, não usa kcal da LLM.
- [ ] Assistant message em pt-BR com tabela SP-118.
- [ ] Disclaimer no final (Const. §26).

**Cobertura**: RF-001, RF-002, INV-1.

---

### US-002 — Registrar por foto de prato

**Como** Felix,
**Quero** mandar foto do meu prato + "meu almoço" e ver os alimentos listados,
**Para que** eu não escreva a lista completa.

**Critérios de aceitação resumidos:**
- [ ] Foto é comprimida (1024px + JPEG q=75) antes de mandar pra Anthropic.
- [ ] Modelo Sonnet usado (visão).
- [ ] Payload chega em base64, nunca URL (Const. §26).

**Cobertura**: RF-004 (roteamento), RF-008 (compressão), RNF-005.

---

### US-003 — Receber narrativa curta ao encerrar o dia

**Como** Felix,
**Quero** ver ~150 palavras em pt-BR sobre o dia ao clicar "Encerrar",
**Para que** eu tenha resumo emocional sem inspecionar tabela.

**Critérios de aceitação resumidos:**
- [ ] `call_narrative` roda com totais já calculados.
- [ ] Prompt `narrative_v1.md`, Sonnet, temperature=0.3.
- [ ] Disclaimer concatenado pelo `DayCloseService` (não pela LLM).

**Cobertura**: RF-012, SP-103, SP-104.

---

### US-004 — Ficar seguro contra "alucinação de macros"

**Como** Felix (implícito),
**Quero** que a LLM nunca decida meu kcal_in por conta própria,
**Para que** meu histórico seja confiável ao longo dos meses.

**Critérios de aceitação resumidos:**
- [ ] Se testes substituírem Anthropic por mock que devolve `FoodItemIn(kcal=99999)`, snapshot final continua correto.
- [ ] `test_log_food_flow.py::test_llm_kcal_lies_ignored_backend_calculates` cobre.

**Cobertura**: INV-1, RF-002, RNF-002.

---

### US-005 — Ser avisado quando a LLM falha

**Como** Felix,
**Quero** ver "Não consegui interpretar; pode reformular?" em vez de silêncio,
**Para que** eu saiba que reenviar é a ação.

**Critérios de aceitação resumidos:**
- [ ] Timeout > 60s → SP-14.
- [ ] `no_tool_use` → SP-14.
- [ ] `validation_exhausted` → SP-14.
- [ ] Nenhum registro criado nesses casos.

**Cobertura**: SP-14, RF-006, RF-007.

---

### US-006 — Rodar backend em dev sem custo

**Como** Backend developer,
**Quero** rodar API local sem `ANTHROPIC_API_KEY`,
**Para que** eu teste rotas de auth/day-view/etc. sem pagar chamada.

**Critérios de aceitação resumidos:**
- [ ] Sem API key → `is_configured=False`.
- [ ] `call_record_intent` devolve `error='anthropic_not_configured'` sem bater na rede.
- [ ] Teste `test_login_alone_does_not_touch_anthropic` verifica.

**Cobertura**: RF-005.

---

### US-007 — Trocar modelo sem quebrar histórico

**Como** operador do app,
**Quero** trocar `ANTHROPIC_MODEL=claude-sonnet-4-6` para `claude-sonnet-4-7` no `.env`,
**Para que** eu ganhe recursos novos sem migração.

**Critérios de aceitação resumidos:**
- [ ] Cliente reinicia com novo modelo.
- [ ] Histórico de items não muda (materialização em `food_items` protege).
- [ ] `PROMPT_VERSION` continua `system_v2` (audit rastreável se prompt não mudou).

**Cobertura**: RF-014, RF-015.

---

### US-008 — Medir hit rate do cache

**Como** operador,
**Quero** log estruturado com `cache_creation_input_tokens` e `cache_read_input_tokens`,
**Para que** eu confirme que o cache ephemeral está ativo.

**Critérios de aceitação resumidos:**
- [ ] Cada chamada loga `event=anthropic_usage` com essas métricas.
- [ ] Primeira mensagem do dia: `cache_creation > 0`, `cache_read = 0`.
- [ ] Segunda mensagem próxima: `cache_read > 0`.

**Cobertura**: RF-010.

---

### US-009 — Retry semântico transparente

**Como** Felix (implícito),
**Quero** que quando a LLM retorne JSON mal-formado, o sistema tente uma vez antes de desistir,
**Para que** um erro pontual não cause "não consegui interpretar".

**Critérios de aceitação resumidos:**
- [ ] Após ValidationError, envia `tool_result is_error=True` + resumo dos erros.
- [ ] Payload de retry limpa metadata do SDK (Haiku 4.5 rejeita `caller`).
- [ ] Se segunda tentativa também falha → `validation_exhausted`, texto SP-14.

**Cobertura**: RF-011.
