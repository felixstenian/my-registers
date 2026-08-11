# Histórias de Usuário — Leitura de rótulo nutricional (Fase 4.b)

> **Rastreabilidade**: SP-30..SP-35 · Persona principal: Felix.

## Personas

- **Felix (usuário)**: compra produtos que não estão no catálogo TBCA. Quer fotografar o rótulo para cadastrá-lo e usar depois.
- **Felix consumindo produto novo**: comprou um iogurte artesanal, quer cadastrar **e** registrar que comeu na mesma mensagem.

---

### US-001 — Cadastrar produto só pela foto do rótulo
**Como** Felix,
**Quero** enviar foto do rótulo sem dizer que consumi,
**Para que** o produto fique no catálogo para uso futuro.

**Critérios de Aceitação resumidos:**
- [ ] `nutrient_facts` com `source='label_ocr'`, `label_media_id`, `verified_by_user=false`.
- [ ] **Nenhum** `food_records` criado.
- [ ] Assistente exibe valores por 100g/100ml.
- [ ] Resposta inclui `nutrient_fact_id` no `dispatch`.

**Notas:**
- Fonte: SP-30.

---

### US-002 — Cadastrar e registrar consumo na mesma mensagem
**Como** Felix consumindo produto novo,
**Quero** enviar foto do rótulo + "comi um pote (170g)",
**Para que** o produto seja cadastrado e meu registro do dia inclua o item.

**Critérios de Aceitação resumidos:**
- [ ] `nutrient_facts` criado.
- [ ] `food_records` + `food_items` com `catalog_ref_id` apontando para o fato.
- [ ] `kcal`/macros calculados via `NutritionCalculator` (INV-1).
- [ ] Snapshot do dia recomputado.

**Notas:**
- Fonte: SP-31. `also_consumed` no envelope.

---

### US-003 — Ser avisado quando rótulo tem per_serving sem tamanho
**Como** Felix,
**Quero** que o sistema peça o tamanho da porção se o rótulo trouxer `per_serving` sem `serving_size`,
**Para que** os valores sejam normalizados corretamente.

**Critérios de Aceitação resumidos:**
- [ ] `basis='per_serving'` + sem `serving_size_g/ml` → rejeitado pelo validator.
- [ ] Nenhum `nutrient_facts` persistido.
- [ ] Assistente pergunta tamanho da porção.

**Notas:**
- Fonte: SP-32. `NutritionLabelIn._serving_needs_size`.

---

### US-004 — Confirmar valores do rótulo
**Como** Felix,
**Quero** ajustar valores lidos errado pelo OCR e marcar como verificado,
**Para que** o catálogo tenha dados confiáveis.

**Critérios de Aceitação resumidos:**
- [ ] `PATCH /nutrient-facts/{id}` atualiza campos.
- [ ] `verified_by_user=true` setado.
- [ ] Facts `TBCA_2023`/`USDA_FDC` não são editáveis (`not_editable`).
- [ ] Audit gravado com `actor='user'`.

**Notas:**
- Fonte: SP-33.

---

### US-005 — Saber que micros estão faltando
**Como** Felix,
**Quero** ver um aviso de que cálcio/ferro/potássio estão ausentes no rótulo,
**Para que** eu saiba que esses valores não estão sendo contabilizados.

**Critérios de Aceitação resumidos:**
- [ ] Se `calcium_mg`, `iron_mg` ou `potassium_mg` é `null` → warning `micros_missing_for_product`.
- [ ] Warning lista quais micros faltam.

**Notas:**
- Fonte: SP-34. Rótulos BR geralmente omitem (RDC 429/2020).

---

### US-006 — Refotografar rótulo atualiza sem duplicar
**Como** Felix,
**Quero** enviar foto do mesmo produto novamente e o sistema atualizar em vez de duplicar,
**Para que** meu catálogo não fique cheio de repetidos.

**Critérios de Aceitação resumidos:**
- [ ] Mesmo `barcode` → atualiza fato existente.
- [ ] Sem barcode, mesmo `(canonical_name, brand)` → atualiza.
- [ ] `verified_by_user=true` não é rebaixado para `false` no reupload.

**Notas:**
- [Inferido do código] `_find_existing_label_fact`.

---

### US-007 — Produto de rótulo tem prioridade no lookup
**Como** Felix,
**Quero** que produto cadastrado por rótulo apareça quando registro o mesmo item depois,
**Para que** eu não precise refotografar toda vez.

**Critérios de Aceitação resumidos:**
- [ ] `LocalTBCACatalog.lookup` inclui facts `label_ocr`.
- [ ] Precedência: marca casada > `TBCA_2023` > `label_ocr` > `manual`; `verified_by_user=true` > `false`.
- [ ] Item registrado com `catalog_ref_id` apontando para o fato.

**Notas:**
- Fonte: SP-35. Implementado em `food-logging` (`LocalTBCACatalog`).
