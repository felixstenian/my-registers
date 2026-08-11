# Histórias de Usuário — Registro de alimentos

## Personas

- **Felix (P1) — usuário único**: fluente em pt-BR, familiar com macros/treino, acessa em desktop e mobile. Uso pessoal diário. Cenário-âncora em [`spec.md §2.2`](../../001-mvp-registro-diario/spec.md).

---

### US-001 — Registrar refeição com quantidades explícitas

**Como** Felix,
**Quero** digitar "150 g de arroz, 90 g de feijão, 180 g de frango" no chat,
**Para que** o sistema resolva macros pelo catálogo TBCA sem eu precisar procurar cada alimento.

**Critérios de aceitação resumidos:**
- [ ] 3 `food_items` criados sob 1 `food_records`.
- [ ] Cada item com `catalog_ref_id` preenchido, `is_estimate=false`.
- [ ] Total do dia atualizado na resposta (SP-118: tabela markdown).
- [ ] Assistente cita disclaimer (Const. §26).

**Notas:**
- Cobertura: SP-20.

---

### US-002 — Registrar com unidade doméstica ("uma concha de feijão")

**Como** Felix,
**Quero** dizer "uma concha de feijão" sem ter que pesar em gramas,
**Para que** consiga registrar refeições no dia a dia sem interromper o fluxo.

**Critérios de aceitação resumidos:**
- [ ] `unit='concha'`, `grams` estimado pela LLM, `is_estimate=true`, `confidence ≤ 0.7`.
- [ ] UI mostra badge visual de estimativa (SP-115 card + SP-116 barra).
- [ ] Cálculo usa `grams` estimado × `CatalogHit.per_100g/100`.

**Notas:**
- Cobertura: SP-21.

---

### US-003 — Registrar refeição inteira por foto

**Como** Felix,
**Quero** tirar uma foto do meu prato e mandar com "meu almoço",
**Para que** o assistente identifique os alimentos por visão e me poupe listar cada um.

**Critérios de aceitação resumidos:**
- [ ] Aceita 1-4 fotos por mensagem (SP-11 + SP-17).
- [ ] Cada alimento visível vira `food_items` com `is_estimate=true`, `confidence ≤ 0.7`.
- [ ] Todos os itens agrupados em 1 `food_records`, não separando por sub-refeição (SP-25 explicitou não fatiar).
- [ ] Resposta lista o que foi entendido e pede confirmação.

**Notas:**
- Cobertura: SP-22, SP-25.

---

### US-004 — Registrar item fora do catálogo sem perder o dado

**Como** Felix,
**Quero** mandar "sushi ninja rolls" mesmo sabendo que não está na TBCA,
**Para que** o item apareça no meu histórico e eu possa completá-lo depois via rótulo ou cadastro manual.

**Critérios de aceitação resumidos:**
- [ ] Item persiste com `catalog_ref_id=null`, `kcal=0`, macros zerados.
- [ ] Warning `no_catalog_hit` no item e no snapshot do dia.
- [ ] Assistente pergunta valores por 100g/marca ou sugere foto do rótulo (link para [manual-catalog-recovery](../manual-catalog-recovery/) via SP-140).
- [ ] Barra de totais (SP-116) e card (SP-115) marcam item com badge "sem catálogo".

**Notas:**
- Cobertura: SP-23.

---

### US-005 — Ver e resolver itens com confiança baixa

**Como** Felix,
**Quero** ser avisado quando o assistente não teve certeza (`confidence < 0.5`),
**Para que** eu possa confirmar/corrigir antes de fechar o dia.

**Critérios de aceitação resumidos:**
- [ ] Item marcado com `needs_confirmation=true`.
- [ ] Aparece com destaque no card SP-115 e contador na barra SP-116.
- [ ] "Confirmo tudo" via chat → intent `confirm_items` scope `all` (SP-24a).
- [ ] "Confirma o feijão" → intent `confirm_items` scope `specific` com target hint `feijão`.
- [ ] Alternativa: modal inline (SP-117) → `PATCH /records/food-items/{id}`.
- [ ] Confirmar não recomputa snapshot (macros não mudam); apenas remove flag e registra `audit_events(action='confirm')`.

**Notas:**
- Cobertura: SP-24, SP-24a, SP-117.

---

### US-006 — Registrar sem informar refeição

**Como** Felix,
**Quero** dizer "comi uma banana" a qualquer hora sem ter que escolher refeição,
**Para que** eu não bloqueie o registro tentando classificar tudo.

**Critérios de aceitação resumidos:**
- [ ] `meal_slot='unspecified'` grava normal.
- [ ] `/day` (feature `daily-detail-view`) renderiza seção `unspecified` só se houver itens ali.
- [ ] SP-118 usa "Total do registro" como fallback quando slot é `unspecified`.

**Notas:**
- Cobertura: SP-26.

---

### US-007 — Confiar no total do dia sem inspeção manual

**Como** Felix,
**Quero** que qualquer mudança na LLM (nova versão, prompt tuning, retry) **não** afete meu total do dia,
**Para que** meu histórico seja confiável ao longo dos meses.

**Critérios de aceitação resumidos:**
- [ ] Trocar `AnthropicClient` por mock que devolve `kcal=99999` no envelope não afeta `daily_snapshots.kcal_in` (INV-1).
- [ ] Deletar/recriar snapshot manualmente reproduz mesmos números (INV-4).
- [ ] `audit_events` tem entrada por criação, permitindo replay do histórico.

**Notas:**
- Cobertura: INV-1, INV-4, INV-10. Este é o requisito estrutural que dita design.
