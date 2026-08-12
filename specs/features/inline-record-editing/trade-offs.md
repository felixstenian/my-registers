# Trade-offs — Edição inline de registros na página `/day`

> **Rastreabilidade**: SP-160..SP-169, INV-14 · ADRs em [`specs/002-edicao-inline-day/research.md`](../../002-edicao-inline-day/research.md): ADR-013 (propagação), ADR-014 (Server Action + lazy mount), ADR-015 (`correction_ops` compartilhado).
> Estende [`daily-detail-view/trade-offs.md`](../daily-detail-view/trade-offs.md) — decisão 9 ("read-only v1") é suplantada por esta feature.

## Decisão 1 — Propagação síncrona na mesma transação

### Contexto
`food_items`/`beverage_records` materializam (cacheiam) macros no momento da criação/correção. O `PATCH /nutrient-facts/{id}` (SP-33) edita valores per-100g do rótulo mas, hoje, **não propaga** — ao corrigir `kcal=72→98` do rótulo, o item já consumido fica stale. Motivador direto da feature.

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A — Síncrona na mesma transação** (escolhida, ADR-013) | Consistência imediata (INV-14); sem janela inconsistente; reusa `NutritionCalculator`/`DailyRecomputeService` | PATCH nutrient-facts mais lento com N itens (≤ 300ms no MVP — RNF-001) |
| B — Fila assíncrona (BackgroundTasks) | Escala melhor; PATCH rápido | Janela de inconsistencies visível; UX confusa (totais não atualizam imediatamente); MVP não tem fila robusta |
| C — Não propagar; exigir re-PATCH de cada item | Simples backend; sem work extra | Frágil; usuário esquece item; não resolve staleness |
| D — Eliminar cache do item e JOIN no fact no recompute | Single source of truth | Quebra modelo `food_items` materializado; migration de leitura; fora de escopo |

### Decisão Tomada
**Opção A** — `propagate(session, fact, user)` roda na mesma transação do `PATCH /nutrient-facts/{id}`; recompute de cada `day_log_id` afetado; `propagation_skipped` para itens em dia `closed`.

### Consequências
- Positivas: INV-14 garantido; zero janela inconsistente; audit por item.
- Negativas / dívida técnica: PATCH mais lento em escala (centenas de itens) — mitigado por janela aceitável no MVP; para multi-tenant futura, migrar para fila (alternativa B) ou redesign (alternativa D).

---

## Decisão 2 — Server Action + lazy mount do form client

### Contexto
`FoodItemRow` hoje é server component com `<details>` HTML nativo (zero JS — decisão explícita do SP-152). Edição inline exige interatividade (inputs, diff, submit, loading, erro). Avaliação de hibridação.

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A — Shell server + client island lazy mount** (escolhida, ADR-014) | Preserva benefício SP-152 quando recolhido; só paga hidratação no item expandido; coerente com padrão Server Islands | Indireção extra (toggle state); server action serialização严格要求 |
| B — Converter `FoodItemRow` inteiro em client | Estado centralizado; fácil animação | Hidrata 20+ itens/dia (bundle + CPU); perde FCP rápido |
| C — Fetch client-side direto p/ `NEXT_PUBLIC_API_URL` | Sem server actions | Expõe mutação ao browser; handle 401/refresh no client; diverge do padrão |
| D — Modal/drawer fora da expansão | Mais espaço para campos | Quebra contexto visual; decisão rejeitada na pergunta de escopo |

### Decisão Tomada
**Opção A** — `FoodItemRow` server mantém; `<details onToggle>` injeta `{open && <EditFoodItemForm/>}`. Server Actions em `actions.ts` fazem o PATCH via `INTERNAL_API_URL` + cookie + `revalidatePath`.

### Consequências
- Positivas: payload JS preserva baixo; auth/cookies no servidor; revalidação declarativa.
- Negativas: `onToggle` precisa de wrapper client minúsculo; serialização do retorno server action deve ser plana (`{ok, error?}` — sem funções/Dates).

---

## Decisão 3 — `correction_ops.py` compartilhado chat + REST

### Contexto
Lógica de correção (recalcular macros/kcal após mudar quantidade, audit, warnings) já existe em `services/correction.py` no fluxo de chat, acoplada ao `LLMEnvelope`. Os novos PATCH REST (SP-164/165/166) precisam da mesma essência. Duplicação é risco de divergência (chat calcula X, REST calcula Y — viola Const. Art. II §5 indiretamente).

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A — Extrair `correction_ops.py`** (escolhida, ADR-015) | Single source of truth; teste unit fáceis; cobre 90% | Indireção no chat; boilerplate leve por caller (audit `actor` difere) |
| B — Duplicar em cada handler REST | Isolamento | Risco alto de divergência no cálculo |
| C — Chat chama handlers REST internamente | Reuso total | Inversão de camadas (service → route); acoplamento estranho |

### Decisão Tomada
**Opção A** — funções puras `apply_water_change`/`apply_beverage_change`/`apply_activity_change` em `services/correction_ops.py`. `CorrectionService` (chat) converte `LLMEnvelope` → kwargs; handlers REST passam payload Pydantic. Auditing/`source='user_corrected'`/recompute ficam no caller (2 callers — `actor` já diverge `'llm'` vs `'user'`).

### Consequências
- Positivas: teste unit 90% direto; sem divergência; chat unchanged.
- Negativas: leve boilerplate por handler (recompute + audit explícitos); aceitável dado que auditoria já diverge por caller.

---

## Decisão 4 — Dia closed validado no início do handler

### Contexto
SP-161/INV-5 exige 409 antes de qualquer mutação. Avaliação de ordem: validar primeiro vs validar depois do SELECT.

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A — Validar `day_log.status='open'` antes de mutar** (escolhida) | Sem efeito colateral; sem audit órfão; rápido fail | Segundo SELECT (depois do item) |
| B — Mutar + rollback se dia closed | Sem segundo SELECT | Audit_gravado mesmo em fail; complexidade de rollback |
| C — Validar somente no commit | Simples | Race conditions; violação INV-5 potencial |

### Decisão Tomada
**Opção A** — handler começa com `_ensure_day_open` (reuso de `correction.py::_ensure_day_open`); 409 antes de qualquer mutação.

### Consequências
- Positivas: claro e seguro; mesmo padrão do chat.
- Negativas: item + day_log fetched separadamente; aceitável (filtro `user_id` no SELECT do item já é obrigatório).

---

## Decisão 5 — `propagated`/`propagation_skipped` no response com default `[]`

### Contexto
O `PATCH /nutrient-facts/{id}` passa a retornar arrays. Clientes antigos (testes, scripts) não esperavam esses campos.

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A — Default `[]` em Pydantic** (escolhida) | Backwards compatible; RFC 2119 SHOULD | Schema mais verboso |
| B — Novo endpoint `/nutrient-facts/{id}/propagate` | Separação | Quebra atomicidade; client precisa 2 chamadas |
| C — Versionar endpoint | Strict | Overhead de versionamento para 1 campo |

### Decisão Tomada
**Opção A** — `NutrientFactOut` estendido com `propagated: list[PropagatedItem] = []` e `propagation_skipped: list[SkippedItem] = []`. Clientes que não leem esses campos continuam funcionando.

### Consequências
- Positivas: zero breaking change; UI pode ignorar quando vazios.
- Negativas: schema um pouco maior; mitigado por `default=[]`.

---

## Decisão 6 — `detected_name` não editável via REST

### Contexto
`food_items.detected_name`/`normalized_name` podem estar errados (LLM interpretou). Avaliação se expor inline.

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A — Continua via chat (SP-72)** (escolhida) | Matching por `normalized_name` + `meal_slot` é complexo; `normalized_name` afeta lookup histórico | UX salta pro chat |
| B — Editar `detected_name` mas não `normalized_name` | Mais simples | Inconsistência nome exibido ≠ nome de lookup |
| C — Editar ambos com renormalização | Completo | Validação/renormalização complexa; fora do escopo |

### Decisão Tomada
**Opção A** — `detected_name` e `normalized_name` não aceitos no PATCH food-items/activity. Mensagens do chat continuam fazendo matching (SP-72).

### Consequências
- Positivas: escopo controlado; sem desalinhamento.
- Negativas / dívida técnica: UX futura pode pedir edição; presumir v2.

---

## Decisão 7 — Edição de per-100g da bebida fora do escopo v1

### Contexto
Bebidas também referenciam `nutrient_fact` (Fase 4.b). Avaliação se a UI inline para beverage edita também per-100g.

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A — UI só edita `volume_ml` da beverage** (escolhida) | Escopo focado na motivação (alimento + rótulo) | Se rótulo de bebida errado, usuário precisa ir no fluxo food |
| B — UI edita `volume_ml` + per-100g da beverage | Completo | Aumenta escopo; fact compartilhado entre food e beverage — edição já funciona via food_item |
| C — Form dedicado para beverage com fields per-100g | Especialização | Duplicação; mesmo fato já editável por outro caminho |

### Decisão Tomada
**Opção A** — `EditBeverageForm` só edita `volume_ml`. Se o rótulo da bebida está errado, o usuário edita o rótulo via `EditFoodItemForm` de outro item que referencia o mesmo fact (SP-163 propaga automaticamente para a beverage).

### Consequências
- Positivas: escopo enxuto; SP-163 propaga automaticamente para beverage se fact compartilhado.
- Negativas / dívida técnica: se beverage é o único registro do fact, edição per-100g indireta; mitigado por future follow-up (atalho direto).

---

## Decisão 8 — Dois PATCHs em sequência para editar quantidade + per-100g no mesmo save

### Contexto
`EditFoodItemForm` pode ter ambos inputs (quantidade + per-100g do fact). Um Save dispara mutação dupla.

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A — Dois PATCHs em sequência** (escolhida) | Simples; cada handler mantém responsabilidades isoladas; reusabilidade | 2 round-trips; latência dupla |
| B — Endpoint composto `PATCH /records/food-items/{id}` com extras per-100g | 1 round-trip | Combina entidades (item + fact); quebra separação |
| C — UI bloqueia edição simultânea (um ou outro) | Simples | UX pior; usuário pode querer corrigir ambos |

### Decisão Tomada
**Opção A** — Server Action `editFoodItem` + `editNutrientFact` em sequência (se ambos dirty). Ordem: fact primeiro (para que propagação calcule com quantity já atualizada) — ou quantity primeiro (para que propagação calcule com quantity nova); decisão de implementação em `tasks.md`.

### Consequências
- Positivas: código isolado; handlers respeitam single responsibility.
- Negativas: 2 round-trips; latência ~2× (aceitável em MVP single-user).

---

## Dívida técnica conhecida

| Item | Impacto | Prioridade |
|---|---|---|
| Sem Vitest/Playwright em `apps/web` — testes UI só especificados | Regressão visual pega por smoke manual | Média |
| Sem métrica de latência específica para PATCH nutrient-facts com propagação | Difícil prever degradação em escala | Média |
| Edição de per-100g da bebida indireta ( requer food item referenciando o mesmo fact) | UX indireta se só há beverage | Baixa |
| Edição de `detected_name` ainda no chat | UX fragmentada | Média (futuro follow-up) |
| `correction_ops` extraído sem mover o teste do chat | Cobertura do módulo novo medir separadamente | Baixa |
| Server Action serialization restritiva (sem Date class) | Manter types planos no contrato | Baixa |
| Sem undo inline (deletar inline) | UX gap — usuário precisa chat para excluir | Média (backlog futuro) |

## Riscos identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| PATCH nutrient-facts escalona (50+ itens propagados) | Baixa (single-user) | Médio | RNF-001 monitorar; migrar para fila assíncrona se exceder |
| Transação longa causa lock em dias concorrentes | Baixa (single-user) | Médio | MVP sem concorrência; futuro multi-user rever |
| Server Action falha 401 (cookie expirado) | Média | Baixo | Error mapping `unauthorized` -> "Sessão expirada, recarregue" |
| Refatoração `correction_ops` quebra chat flow | Média | Alto | TC-I-012 — rodar `tests/test_correction.py` 100% verde |
| `<details>` re-render perde estado do form durante revalidate | Alta | Baixo | Estado do form self-contained; usuário re-expande (aceitável) |
| Propagação chama recompute em dias que o usuário não está vendo | Média | Baixo | Custo baixo; toast informa se cross-day |
| `propagated[]` cresce em response — payload grande | Baixa | Baixo | Limitado a itens vivos do fact; default `[]` |
| Race condition entre edição inline e chat concorrente | Baixa (single-user) | Médio | Fila futura; até então last-write-wins aceitável |
| Usuário tenta editar em dia que fecha entre render e click | Baixa | Baixo | 409 backend; toast "Dia encerrado é imutável" |