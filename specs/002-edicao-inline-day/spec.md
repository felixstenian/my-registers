# Feature Specification — Edição inline de registros na página `/day`

**Feature ID:** 002-edicao-inline-day
**Status:** Proposed (aguardando PR `spec:`)
**Owner:** Felix
**Constituição aplicável:** [`../../.specify/memory/constitution.md`](../../.specify/memory/constitution.md) v1.0.0
**Spec-fonte (MVP):** [`../001-mvp-registro-diario/spec.md`](../001-mvp-registro-diario/spec.md) — estende §3.15 (página `/day`) e supre SP-150 "Fora do escopo: Edição/deleção inline (v2)".
**Plano técnico:** [`plan.md`](plan.md)
**Tarefas:** [`tasks.md`](tasks.md)
**Decisões:** [`research.md`](research.md)

---

## Regras deste documento (spec-kit)

- Este arquivo descreve **o quê** e **por quê**, nunca **como** (implementação vive em `plan.md`).
- Cada requisito tem ID estável `SP-XX` — nunca renumerar; para deprecar, marcar `~~SP-XX~~ DEPRECATED (motivo)`.
- Cada `SP-XX` deve ter pelo menos um teste (unit, integration ou manual) rastreado em `tasks.md`.
- Palavras-chave (RFC 2119): **MUST**, **MUST NOT**, **SHOULD**, **MAY**.
- Critérios no formato Given / When / Then (Dado / Quando / Então).
- Nesta spec, `must` bloqueia a entrega; `should` é importante mas negociável; `may` fica para follow-up.

---

## 1. Contexto e objetivo

**Problema.** Hoje a página `/day` (SP-150..SP-155) é **somente leitura** — toda mutação de registro acontece via chat (correção SP-70..SP-74, remoção SP-80..SP-82). Em produção, ao registrar um alimento por foto de rótulo nutricional (Fase 4.b / SP-30..SP-35), alguns valores per-100g lidos pela LLM vieram incorretos. O usuário percebe o erro ao ver a linha do item na tabela do `/day`, mas precisa voltar ao chat e redigir uma frase de correção — fricção alta e resultado incerto (matching ambíguo, SP-71).

**Por que agora.** A página `/day` já renderiza item-a-item com macros/micros (SP-152). O backend já oferece `PATCH /records/food-items/{id}` (edição de quantidade + recompute determinístico) e `PATCH /nutrient-facts/{id}` (SP-33, edição de per-100g lidos de rótulo). Falta: (a) expor a edição **inline** na UI, (b) estender o PATCH aos demais tipos de registro (água/bebida/atividade — só food tem PATCH REST hoje), (c) **propagar** a edição de um `nutrient_fact` aos `food_items`/`beverage_records` que o referenciam (hoje o cache materializado fica stale — bug emergente).

**Resultado observável.** O usuário expande um item na tabela do `/day`, ajusta quantidade e/ou valores do rótulo diretamente nos campos que aparecem, salva, e vê a tabela + totais atualizados em poucos segundos — sem sair da página e sem escrever no chat.

---

## 2. Personas e escopo

### 2.1 Persona P1 — Felix (usuário único)
Mesma persona do MVP. Acessa `/day` em desktop e mobile; quer validar/corrigir o que foi registrado sem depender do chat.

### 2.2 Cenário-âncora
1. Registra iogurte por foto de rótulo via chat. O rótulo é lido como `kcal=72` per-100g, mas o valor correto é `98`.
2. Abre `/day`, expande a linha do iogurte, vê `kcal` aparente baixo.
3. Edita o campo `kcal` (per-100g) do rótulo no painel de edição expandido → salva.
4. Sistema recalcula o item consumido (180g → 176 kcal em vez de 130), propaga a todos os itens do mesmo rótulo no dia, recomputa o snapshot. Totais do dia atualizam na tela.
5. Cenário b: a quantidade consumida também estava errada (180g era 150g) — ajusta `grams` no mesmo painel → recompute.

---

## 3. Requisitos funcionais

### 3.1 Edição de quantidade do food_item

**SP-160** (`must`) — Editar quantidade inline do food_item.
- **Given** o usuário está em `/day` (ou `/day/[date]` com `status='open'`) e expande um `food_item`.
- **When** altera `grams` (ou `ml`, ou `quantity`+`unit`) no painel de edição expandido e confirma.
- **Then** `PATCH /records/food-items/{id}` é chamado com os campos alterados; o backend recalcula macros via `NutritionCalculator` a partir do `nutrient_fact` referenciado (Const. Art. II §5 — LLM não calcula); grava `audit_events` (`action='correct'`, `actor='user'`); chama `DailyRecomputeService.recompute`; a UI revalida a página e mostra novos valores + totais.
- PATCH idempotente no sentido de que reenviar o mesmo valor → 200 sem recompute extra quando nenhum campo mudou (já implementado no endpoint hoje — manter).
- A UI **MUST** invalidar a rota `/day` (`router.revalidate`) ou refazer o fetch server-side após salvar.

**SP-161** (`must`) — Dia encerrado é imutável (Const. Art. VIII §28, INV-5).
- **Given** o dia do item está `status='closed'`.
- **Then** o painel de edição **MUST NOT** exibir inputs editáveis (renderiza somente leitura + dica "Dia encerrado é imutável; corrija via novo registro no dia atual") e o backend retorna `409 conflict_closed_day` se bypassado.

### 3.2 Edição de valores do rótulo (nutrient_fact) + propagação

**SP-162** (`must`) — Editar per-100g do nutrient_fact inline.
- **Given** o `food_item` expandido referencia um `nutrient_fact` com `source ∈ {label_ocr, manual}` e `verified_by_user` qualquer.
- **When** o usuário edita campos per-100g (`kcal`, `protein_g`, `carbs_g`, `fat_g`, `fiber_g`, micros, `serving_grams`) no mesmo painel de edição e confirma.
- **Then** `PATCH /nutrient-facts/{id}` é chamado (SP-33); o backend marca `verified_by_user=true`, grava `audit_events` (`action='update'`, `actor='user'`).
- Facts com `source ∈ {TBCA_2023, USDA_FDC}` **MUST NOT** ser editáveis inline (422 `not_editable` — já implementado); a UI esconde os inputs nesses casos e mostra "Catálogo canônico — não editável".

**SP-163** (`must`) — Propagação de nutrient_fact editado recomputa registros vivos (novo — núcleo desta feature).
- **Given** um `nutrient_fact` foi atualizado via SP-162.
- **When** o PATCH commita.
- **Then** o backend, na mesma transação:
  1. `SELECT` todos os `food_items` vivos (`deleted_at IS NULL`) com `catalog_ref_id = fact.id` cujo `day_log.status='open'`.
  2. Para cada um: `NutritionCalculator.compute(hit=fact_atualizado, grams=item.grams, ml=item.ml)` → sobrescreve macros materializados; `source='user_corrected'`; grava `audit_events` (`action='correct'`, `actor='user'`, `entity_type='food_item'`, before/after).
  3. Idem para `beverage_records` vivos referenciando o fact.
  4. Para cada `day_log_id` distinto afetado: `DailyRecomputeService.recompute(day_log_id)`.
- Registros em dias `status='closed'` **MUST NOT** ser alterados (INV-5); são listados em `propagation_skipped` no response.
- Resposta do `PATCH /nutrient-facts/{id}` estendida com `{ propagated: [{entity_type, entity_id, day_log_id}], propagation_skipped: [{entity_type, entity_id, reason: "day_closed"}] }`.
- A UI usa `propagated` para revalidar apenas `/day` do dia corrente (se afetado); `skipped` gera um toast informativo.

### 3.3 Edição de água, bebida e atividade

**SP-164** (`must`) — `PATCH /records/water/{id}`.
- Body: `{ volume_ml: int > 0 }`.
- Atualiza `volume_ml`, `source='user_corrected'`, grava audit (`action='correct'`, `actor='user'`), chama recompute do `day_log_id`.
- 404 `not_found` se inexistente ou deletado (soft delete). 409 `conflict_closed_day` (INV-5). `user_id` no filtro (Const. Art. V §21).

**SP-165** (`must`) — `PATCH /records/beverage/{id}`.
- Body: `{ volume_ml?: int > 0 }` (adiar edição de per-100g via chat — fora do escopo v1 desta feature; ver §7).
- Quando `volume_ml` muda: recalcula macros via `NutritionCalculator` a partir do `nutrient_fact` referenciado, `source='user_corrected'`, audit, recompute. Mesmas garantias de 404/409/`user_id` de SP-164.

**SP-166** (`must`) — `PATCH /records/activity/{id}`.
- Body: `{ duration_minutes?: number > 0, intensity?: 'light'|'moderate'|'vigorous'|'unknown', kcal_burned?: number ≥ 0 }`.
- Se `kcal_burned` informado explicitamente → `calc_method='user_manual'`, `met_value=NULL` (respeitando precedence do chat em SP-64).
- Se `kcal_burned` omitido mas `duration_minutes`/`intensity` mudou → recalcula via `ActivityCalculator.compute` ( requer `user.weight_kg` — sem peso → warning `weight_kg_required_for_kcal`, mantém `kcal_burned` anterior). Const. Art. II §5.
- `source`/audit/recompute/404/409/`user_id` iguais a SP-164. `detected_name` **não** é editável aqui (continua via chat para evitar desalinhamento com `normalized_name`).

### 3.4 UI inline na expansão do item

**SP-167** (`must`) — Painel de edição na expansão do `FoodItemRow`.
- O elemento `<details>` existente (SP-152) ganha, na seção expandida, um painel "Editar" com inputs para `grams`/`ml` (ou `quantity`+`unit`) e — quando `has_catalog && source ∈ {label_ocr, manual}` — inputs para per-100g do fact.
- Inputs renderizados como um `<form>` nativo, submetido via `useActionState`/Server Action (Next.js) ou fetch client-side para o PATCH. Estado inicial = valores atuais.
- Botão "Salvar" desabilitado enquanto nada mudou (diff raso contra estado inicial). Botão "Cancelar" reverte.
- Feedback de loading (spinner), erro (mensagem inline com código estável) e sucesso (colapsa o painel + revalida).
- Acessibilidade: labels associadas, foco no primeiro input ao abrir o painel, `aria-live` para erros.

**SP-168** (`should`) — Edição inline nas seções auxiliares (water/beverage/activity).
- `AuxiliarySections.tsx` (SP-153) ganha o mesmo padrão de painel-editável-na-expansão para: `WaterRecord` (`volume_ml`), `BeverageRecord` (`volume_ml`), `ActivityRecord` (`duration_minutes`, `intensity`, `kcal_burned`).
- Mesmas garantias de SP-161 (dia fechado desabilita inputs), SP-167 (loading/erro/sucesso, a11y).

**SP-169** (`should`) — Revalidação seletiva pós-edição.
- Após salvar via Server Action, `revalidatePath('/day')` e `revalidatePath('/day/[date]')` (ou equivalente) garante que totais e tabela reflitam o novo snapshot sem refresh manual.
- Se o dia corrente não está entre os afetados (raro, mas possível em propagação cross-day), a UI exibe toast "Itens de outros dias também foram atualizados" e links para o primeiro `day_log` afetado.

---

## 4. Requisitos não-funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | Latência P95 do PATCH (any kind) ≤ 300ms incl. recompute | Performance |
| RNF-002 | Toda mutação grava `audit_events` antes de commit (INV-10) | Auditoria |
| RNF-003 | `user_id` no `WHERE` de toda query de mutação (Const. Art. V §21) | Segurança |
| RNF-004 | Dia `closed` retorna 409 (INV-5) — validado antes de mutar | Segurança |
| RNF-005 | Aviso legal (Const. Art. VII §26) permanece visível no `/day` após edição | Conformidade |
| RNF-006 | Sem soma nutricional via LLM — só `NutritionCalculator`/`ActivityCalculator` (Const. Art. II) | Determinismo |

---

## 5. Interfaces observáveis

### 5.1 Endpoints REST (esta feature)

| Método | Path | Body | Response | SP |
|---|---|---|---|---|
| PATCH | `/records/food-items/{id}` | `{grams?, ml?, quantity?, unit?}` | `RecordSummary` | SP-160 (já existe) |
| PATCH | `/records/water/{id}` | `{volume_ml}` | `RecordSummary` | SP-164 (novo) |
| PATCH | `/records/beverage/{id}` | `{volume_ml?}` | `RecordSummary` | SP-165 (novo) |
| PATCH | `/records/activity/{id}` | `{duration_minutes?, intensity?, kcal_burned?}` | `RecordSummary` | SP-166 (novo) |
| PATCH | `/nutrient-facts/{id}` | `(SP-33) + extensão response` | `NutrientFactOut + {propagated, propagation_skipped}` | SP-162, SP-163 |

### 5.2 Códigos de erro estáveis (extensão)

- `conflict_closed_day` (já existe — reusado).
- `not_editable` (já existe — fact canônico).
- `propagation_skipped` (novo, informativo — não é erro; vem no body 200).
- `weight_kg_required_for_kcal` (já existe no chat — reusado como warning no response do PATCH activity).

### 5.3 Modelos observáveis (extensão)

- **FoodItem** (sem mudança de shape — SP-160 só altera valores).
- **NutrientFact** — `PATCH` response ganha `propagated` e `propagation_skipped` (arrays; omitidos se vazios para não quebrar clientes antigos — `default=[]` no Pydantic).

---

## 6. Invariantes

Esta feature introduz um novo invariante obrigatório (teste de integração com Postgres real):

- **INV-14** — Edição de `per-100g` de um `nutrient_fact` recalcula **todos** os `food_items` e `beverage_records` vivos (`deleted_at IS NULL`) em dias abertos que o referenciam, e recomputa os snapshots correspondentes. Nenhum cache materializado de registro permanece stale após o PATCH commitar.

Invariantes existentes reafirmados (não novos, mas cobertos por testes novos): INV-1, INV-4, INV-5, INV-10.

---

## 7. Fora do escopo

- Editar `detected_name`/`normalized_name` inline (continua via chat — SP-70..72 faz matching por nome).
- Editar per-100g de bebidas inline (a UI só edita `volume_ml`; o fact da bebida segue editável via `PATCH /nutrient-facts/{id}` chamado fora da tela `/day` — deixe para follow-up se houver demanda).
- Edição em lote (multi-item de uma vez) — cada item é editado individualmente.
- Edição inline de `workout_sets`/`workout_exercises` (Bloco 3 não implementado).
- Undo/redesigna de uma edição (além do que o `audit_events` já permite por inspeção direta).
- Conversão de `food_item` de grams ↔ ml quando o fact é `per_100ml` (o `NutritionCalculator` já decide; não há toggle manual).
- Histórico de versões navegável na UI (audit fica apenas como trilha — ver ADR-014 em `research.md`).

---

## 8. Glossário (extensão)

- **Per-100g / Per-100ml** — `nutrient_fact.basis`; base do cálculo determinístico.
- **Propagação** — recalculo de registros vivos referenciando um `nutrient_fact` recém-editado (SP-163).
- **Cache materializado** — macros/micros persistidos em `food_items`/`beverage_records` (não.View on the fly); vulnerável a staleness quando o fact muda — SP-163 resolve.

---

## Histórico de alterações

- **2026-08-12** — v1.0. Spec inicial. Adicionados SP-160..SP-169 (`must`/`should`) e INV-14. Estende §3.15 da spec 001 (página `/day`) que deixava "edição inline" fora do escopo v1. Motivador: valores per-100g lidos de rótulo via foto vieram incorretos em prod e a correção via chat é incerta (matching ambíguo SP-71). Backend já tem PATCH food-items e PATCH nutrient-facts; faltam PATCH water/beverage/activity, a propagação do PATCH nutrient-facts, e a UI inline. ADR-013 (propagação) e ADR-014 (audit como histórico) em `research.md`.