# Critérios de Aceitação — Correção de registros

## AC-001 — Correção não ambígua atualiza + recomputa (SP-70)

**Dado que** dia aberto com único `food_item` "arroz" (`grams=150, kcal=195`)
**Quando** LLM devolve `intent=correct_record, target_hint="arroz", changes={grams:200}`
**Então**:
- `food_items.grams=200`
- `kcal` recomputado (200×130/100 = 260)
- `source='user_corrected'`
- Snapshot version+1

**Notas**: `test_correction_updates_grams_and_recomputes_macros`, `test_snapshot_recomputes_after_correction`.

---

## AC-002 — Correção ambígua não muta (SP-71)

**Dado que** 2 items "frango" no dia (lunch e dinner) sem qualificador
**Quando** LLM devolve `target_hint="frango", changes={grams:220}`
**Então**:
- `AmbiguousTarget` levanta com winners=2
- **Nenhum** item alterado
- Nenhum audit_event criado
- Assistant devolve clarify

**Notas**: `test_correction_ambiguous_does_not_persist`, `test_ambiguous_correction_via_chat_returns_clarify`.

---

## AC-003 — Correção qualificada por meal_slot (SP-72)

**Dado que** 2 items "frango" (lunch + dinner)
**Quando** `target_hint="frango almoço", changes={grams:220}`
**Então**:
- `_detect_meal_slot(["almoco"])` → "lunch"
- Item lunch: `score = tokens∩ + 5` (bônus meal_slot)
- Item dinner: `score = tokens∩` (sem bônus)
- Winner = item lunch; corrigido

**Notas**: `test_matcher_qualified_by_meal_slot`.

---

## AC-004 — Dia fechado bloqueia via chat (SP-73, INV-5)

**Dado que** dia `status='closed'`
**Quando** `CorrectionService.apply_from_llm` roda
**Então** `_ensure_day_open` levanta `DayClosedError`
**E** processor devolve mensagem informativa
**E** nada em DB muda.

**Notas**: `test_correction_on_closed_day_blocks`.

---

## AC-005 — Dia fechado bloqueia via REST

**Dado que** dia `status='closed'`
**Quando** `PATCH /records/food-items/{id}` com body válido
**Então** 409 `code=conflict_closed_day`
**E** DB inalterado.

---

## AC-006 — Item não é do user → 404 sem vazamento

**Dado que** food_item pertence a other_user
**Quando** current_user faz PATCH
**Então** 404 `not_found` (não distingue "não existe" vs. "não é seu").

---

## AC-007 — Item deletado (soft) → 404

**Dado que** food_item com `deleted_at != NULL`
**Quando** PATCH
**Então** 404 `not_found`.

**Motivação**: soft delete deve ser transparente para consumidores; PATCH em item "morto" seria zombie.

---

## AC-008 — Audit before/after gravado (SP-74, INV-10)

**Dado que** correção com sucesso
**Então** exatamente 1 nova linha em `audit_events`:
- `entity_type='food_item'` (ou water/beverage/activity conforme kind)
- `action='correct'`
- `actor='llm'` (chat) ou `'user'` (REST)
- `before` shape adequado ao kind (`_snapshot` function)
- `after` shape mesmo
- `message_id` presente se chat

**Notas**: `test_correction_grava_audit_event`.

---

## AC-009 — Score do matcher e regras de tie

**Dado que** dia com "arroz branco" (item A) e "arroz integral cozido" (item B)
**Quando** `target_hint="arroz"`
**Então**:
- A: tokens `{arroz, branco}` ∩ `{arroz}` = 1
- B: tokens `{arroz, integral, cozido}` ∩ `{arroz}` = 1
- Empate → `AmbiguousTarget`

**Cenário 2**: `target_hint="arroz branco"` → A wins com 2, B com 1.

**Notas**: `test_matcher_unambiguous_food_hit`, `test_matcher_ambiguous_raises`.

---

## AC-010 — `NoTargetFound` quando nada bate

**Dado que** hint = "quinoa" e não há item com "quinoa" no dia
**Então** `TargetMatcher.resolve` levanta `NoTargetFound(hint)`
**E** assistant devolve "não achei X no seu dia".

**Notas**: `test_matcher_no_target_raises`.

---

## AC-011 — Recompute automático via NutritionCalculator (RF-007)

**Dado que** food com hit no catálogo, `grams=100 → 150`
**Quando** correção aplica
**Então** `NutritionCalculator.compute(hit, grams=150, ml=None)` roda
**E** kcal/protein_g/etc. atualizados
**E** warnings de `reasons` (ex.: `missing_grams`) coletados.

---

## AC-012 — Activity com kcal reportado sobrescreve

**Dado que** activity `duration_minutes=40`, `kcal_burned=300`
**Quando** LLM `changes={kcal_burned:380}`
**Então**:
- `record.kcal_burned=380`
- `record.calc_method='user_manual'`
- Nenhuma recomputação MET

---

## AC-013 — Activity sem weight_kg emite warning

**Dado que** `user.weight_kg=NULL`
**Quando** activity duration muda (sem reported kcal)
**Então** warning `missing_weight_kg` em `warnings`
**E** `kcal_burned` inalterado (não recompute).

---

## AC-014 — Beverage recompute via NutritionCalculator

**Dado que** beverage com `volume_ml=200, kcal=50, catalog_ref_id=X`
**Quando** correção `volume_ml=400`
**Então** `NutritionCalculator.compute(hit, grams=None, ml=400)` roda
**E** `kcal=100` (dobrou), `volume_ml=400`, `source='user_corrected'`.

---

## AC-015 — Correção sem efeito falha (chat)

**Dado que** food.grams=150 e `changes={grams:150}` (mesmo valor)
**Quando** correção
**Então** `changed={}` → `ValidationAppError code=correction_no_effect`
**E** nada em DB muda.

---

## AC-016 — PATCH sem mudança real retorna 200 sem audit

**Dado que** PATCH `{grams:150}` mas item já tem `grams=150`
**Quando** endpoint
**Então**:
- 200 com RecordSummary corrente
- Sem audit_events gravado
- `changed=False` interno

---

## AC-017 — SP-24 revalidação: needs_confirmation off pós correção

**Dado que** food com `needs_confirmation=True, catalog_ref_id=X`
**Quando** correção aplica changes válidas
**Então** `needs_confirmation=False`
**E** audit registra a mudança de `needs_confirmation` também.

---

## AC-018 — PATCH promoção retroativa de catalog_ref_id

**Dado que** food_item com `catalog_ref_id=NULL, normalized_name='arroz_branco_cozido'`
**E** seed TBCA foi enriquecido depois (agora tem match)
**Quando** PATCH `{grams:200}`
**Então**:
- `catalog_ref_id` = novo hit UUID
- Macros recomputados via catalog
- `needs_confirmation=False`

**Motivação**: bug histórico (`scripts/bootstrap.sh`) — items criados antes do seed rodar ficavam órfãos. Fix documentado em `docs/pos-deploy-macros-fix.md`.

---

## Cenários de borda

| Cenário | Comportamento esperado |
|---|---|
| `changes` vazio | `correction_no_effect` |
| `unit='g'` mas `quantity=None` | Backend descarta unit sem quantity |
| Water com `target_hint="água"` mas sem records de água no dia | `NoTargetFound` |
| Activity com `changes.intensity="pesada"` | LLM já normaliza via `_normalize_intensity` para "vigorous" antes do envelope |
| Corrigir food com PATCH sem grams/ml (só unit) | `changed=True` para unit, mas sem recompute (só grams/ml dispara) |
| Score empatado no top mas kinds diferentes | Ex.: hint "água" pega WATER; se score empata com FOOD "agua-de-coco", ainda `AmbiguousTarget` (matcher não desempata por kind) |
| Multi-mensagem de correção rápida | Cada uma processa isolada; recompute idempotente |

## Critérios de não-funcionalidade

| Critério | Threshold | Fonte |
|---|---|---|
| Latência correção via chat (com LLM) P95 | ≤ 6s | RNF-003 |
| Latência PATCH REST P95 | ≤ 200ms | RNF-003 |
| Cobertura `CorrectionService` | ≥ 90% | RNF-004 |
| Cobertura `TargetMatcher` | ≥ 90% | RNF-004 |
| Isolamento por user | 100% | RNF-002 |
| INV-5 enforce | 100% via `_ensure_day_open` (chat) + check status (REST) | RF-004 |
