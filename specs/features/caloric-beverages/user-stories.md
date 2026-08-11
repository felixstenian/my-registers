# Histórias de Usuário — Registro de bebidas calóricas

> **Rastreabilidade**: SP-50..SP-52 · Persona principal: Felix.

## Personas

- **Felix (usuário)**: registra alimentação, hidratação e atividade por chat. Quer que café, suco, refrigerante etc. somem kcal corretamente sem inflar `water_ml`.
- **Sistema (assistentes)**: LLM que interpreta a mensagem e backend que calcula macros via catálogo.

---

### US-001 — Registrar café com calorias do catálogo
**Como** Felix,
**Quero** enviar "200ml de café" e ver as calorias somadas ao total do dia,
**Para que** meu saldo calórico reflita o que bebi.

**Critérios de Aceitação resumidos:**
- [ ] Mensagem "200ml de café" → `beverage_records` com `volume_ml=200`, `kcal` do catálogo.
- [ ] `kcal_in` do snapshot inclui kcal da bebida.
- [ ] `other_liquids_ml` inclui 200ml; `water_ml` **não** inclui (INV-3).
- [ ] Resposta do assistente mostra tabela com kcal, macros e volume.

**Notas:**
- Fonte: SP-50. `NutritionCalculator.compute(hit, ml=200)` usa basis `per_100ml`.

---

### US-002 — Bebida sem catálogo fica pendente
**Como** Felix,
**Quero** que uma bebida desconhecida (ex.: "kombucha artesanal") seja registrada com macros zerados e destaque,
**Para que** eu não perca o registro mas saiba que preciso confirmar os valores.

**Critérios de Aceitação resumidos:**
- [ ] `catalog_ref_id=null`, `kcal=0`, `needs_confirmation=true`.
- [ ] `warnings:[{code:"no_catalog_hit"}]` no resultado.
- [ ] Assistente pergunta valores por 100g/marca.
- [ ] Registro aparece destacado até ser confirmado.

**Notas:**
- Fonte: SP-52. Mesmo fluxo de SP-23 (alimentos sem catálogo).

---

### US-003 — Confiança baixa marca como pendente
**Como** Felix,
**Quero** que bebidas com baixa confiança da LLM fiquem marcadas para confirmação,
**Para que** eu revise antes que somem errado no total.

**Critérios de Aceitação resumidos:**
- [ ] `confidence < 0.5` → `needs_confirmation=true`.
- [ ] `warnings` inclui `{code:"low_confidence_item"}`.
- [ ] UI destaca visualmente (mesmo SP-24 de alimentos).

**Notas:**
- Fonte: SP-52. `LOW_CONFIDENCE_THRESHOLD = Decimal("0.5")`.

---

### US-004 — Bebida não infla hidratação
**Como** Felix,
**Quero** que "500ml de refrigerante" **não** conte como água,
**Para que** meu total de hidratação (`water_ml`) reflita só água pura.

**Critérios de Aceitação resumidos:**
- [ ] Refrigerante vai para `beverage_records`, não `water_records`.
- [ ] `water_ml` permanece inalterado.
- [ ] `other_liquids_ml` soma 500ml.

**Notas:**
- Fonte: SP-51, INV-3. Garantido por tabelas separadas — `DailyRecomputeService._aggregate_water` não lê `beverage_records`.

---

### US-005 — Mix de bebida e água no mesmo dia
**Como** Felix,
**Quero** registrar água e café no mesmo dia e ver ambos separados no snapshot,
**Para que** eu saiba quanto de água pura vs. outros líquidos bebi.

**Critérios de Aceitação resumidos:**
- [ ] `water_ml` soma só `water_records`.
- [ ] `other_liquids_ml` soma só `beverage_records`.
- [ ] `kcal_in` soma food + beverage (não water).
- [ ] Snapshot combina tudo em uma resposta.

**Notas:**
- Fonte: teste `test_snapshot_mixes_food_beverage_activity_water` (linha 217) — valida mix de 4 registros.
