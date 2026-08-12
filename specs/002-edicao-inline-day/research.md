# Research & ADRs — Edição inline de registros na página `/day`

**Feature ID:** 002-edicao-inline-day
**Escopo:** decisões arquiteturais e técnicas com trade-offs. Append-only — nunca reescrever ADR aceito; para rever, criar novo ADR com `supersedes`.

Formato de cada ADR:
```
## ADR-NNN — Título curto
Status: proposed | accepted | superseded by ADR-MMM
Data: yyyy-mm-dd

Contexto: por que a decisão precisou ser tomada.
Decisão: o que fica escolhido.
Consequências: efeitos (bons e ruins).
Alternativas descartadas: com motivo objetivo.
```

---

## ADR-013 — Propagação síncrona na edição de `nutrient_fact`

**Status:** proposed
**Data:** 2026-08-12

**Contexto.** `food_items` e `beverage_records` materializam (cacheiam) macros/micros no momento da criação/correção (Const. Art. III §10 — recompute from-scratch do snapshot lê direto das tabelas cruas, mas o *valor por item* fica congelado). O `PATCH /nutrient-facts/{id}` (SP-33) edita valores per-100g lidos de rótulo (Fase 4.b) mas, hoje, **não propaga** — ao corrigir `kcal=72→98` do rótulo do iogurte, o item já consumido permanece com `kcal` antigo. Em produção isso deixou registros stale após correção do rótulo. Precisávamos escolher *quando* e *como* os caches de item são invalidados.

**Decisão.** Propagação **síncrona na mesma transação** do `PATCH /nutrient-facts/{id}`:
1. `SELECT` registros vivos (`deleted_at IS NULL`) referenciando o fact, em dias `status='open'`.
2. `NutritionCalculator.compute` sobrescreve os caches; `source='user_corrected'`; audit por item.
3. `DailyRecomputeService.recompute` para cada `day_log_id` distinto afetado.
4. Dias `closed` pulam (INV-5) e voltam em `propagation_skipped` no response.

O cliente recebe `propagated`/`propagation_skipped` no 200 e sabe quais dias revalidar.

**Consequências.**
- ✔ Consistência imediata — nenhum item stale sobrevive ao PATCH commitar (INV-14).
- ✔ Reusa `NutritionCalculator` e `DailyRecomputeService` existentes; sem novo mecanismo de invalidação.
- ✔ Audit por item garante trilha completa (Art. III §11).
- ✘ P95 do PATCH nutrient-facts cresce com o nº de itens referenciando o fact. Em MVP de 1 usuário com ~5 refeições/dia, o máximo realista é dezenas de itens na mesma transação — ainda ≤ 300ms (RNF-001). Para escala futura (multi-usuário), migrar para fila assíncrona (ver Alternativa B).
- ✘ Transação mais longa; se falhar no meio, rollback desfaz tudo (aceitável — sem efeito parcial).

**Alternativas descartadas.**
- **A. Não propagar; exigir re-PATCH de cada item.** UI teria que orquestrar N PATCHs após editar o fact. Frágil (usuário esquece um item) e não resolve o staleness emergente. Rejeitado.
- **B. Fila assíncrona (job pós-commit).** Escala melhor, mas adiciona infra de fila ausente no MVP (hoje só `BackgroundTasks` FastAPI em processo) e introduz janela de inconsistência visível — usuário edita rótulo, totais não atualizam imediatamente. Rejeitado para v1; retomar se propagação passar de ~100 itens.
- **C. Eliminar o cache de macros do item e sempre JOIN no fact no recompute do snapshot.** Mais limpo (single source of truth), mas quebra o modelo de `food_items` materializado que `DailyRecomputeService` e o snapshot dependem hoje, exigiria migration de leitura e mudança no `SUM` — fora do escopo desta feature. Rejeitado; poderia ser ADR futuro.
- **D. Recompute on-read (sem snapshot cacheado).** Já descartado no ADR-004 do MVP por piorar `GET /days/today` P95.

---

## ADR-014 — Edição inline via Server Action + montagem lazy do form client

**Status:** proposed
**Data:** 2026-08-12

**Contexto.** `FoodItemRow` hoje é **server component** com `<details>` HTML nativo (zero JS — decisão explícita do SP-152 da spec 001). A edição inline exige interatividade (inputs, diff, submit, loading, erro). Havia três caminhos: (a) converter tudo em client component, (b) manter server e injetar um client component filho só no `<details open>`, (c) fazer a edição via rota API tradicional com fetch client-side. O `app_plan.md` padroniza Server Components que precisam bater na API usando `INTERNAL_API_URL` (DNS interno) — multipart/auth/cookies em fetch client-side exigiria expor o path público e repassar credenciais.

**Decisão.** Hibrido:
- **Server Actions** (`apps/web/src/app/(app)/day/actions.ts`) fazem o PATCH via `INTERNAL_API_URL` no servidor, repassando cookies, e chamam `revalidatePath('/day')` + `revalidatePath('/day/[date]')` ao fim.
- O `FoodItemRow` permanece server component; no `<details onToggle>`, monta (`{ open && <EditFoodItemForm/> }`) um **client component** filho que chama a Server Action via `useActionState`. O form só hidrata quando o usuário expande a linha — evita carregar JS de N forms para uma página com 20 itens.
- Mesmo padrão para `EditWaterForm`/`EditBeverageForm`/`EditActivityForm`.

**Consequências.**
- ✔ Server Action resolve auth/cookies internalmente sem expor `NEXT_PUBLIC_API_URL` para mutação; coerente com o proxy.ts do repo.
- ✔ Revalidação declarativa (`revalidatePath`) — totais e snapshot saem do cache Next.js consistentes.
- ✔ Lazy mount mantém o payload de JS baixo (somente item expandido paga o custo do form).
- ✘ Server Actions no Next 16 App Router requerem cuidado com `use client` boundary e serialização do retorno (sem funções/Dates inválidas); mitigado retornando tipos planos `{ok, error?}`.
- ✘ `onToggle` precisa de um pequeno client wrapper para detectar `open` — aceitável (1 minúsculo component de toggle).

**Alternativas descartadas.**
- **A. Converter `FoodItemRow` inteiro em client component.** Hidrata todas as linhas (20+ itens/dia) —_payload de JS desnecessário; perde o beneficio do SP-152. Rejeitado.
- **C. Fetch client-side direto p/ `NEXT_PUBLIC_API_URL`.** Passa mutação pelo path público/browser, exigindo handle de 401/refresh no client (lógica hoje só está no server). Diverge do padrão do repo (Server Components usam `INTERNAL_API_URL`). Rejeitado.
- **D. Modal/drawer fora da expansão.** Quebra o contexto visual (usuário perde de vista a linha que está corrigindo); decidido como não-desejado na pergunta de escopo. Rejeitado.

---

## ADR-015 — `correction_ops` como camada compartilhada chat + REST

**Status:** proposed
**Data:** 2026-08-12

**Contexto.** A lógica de correção (recalcular macros/kcal após mudar quantidade, gravar audit, warnings) já existe em `services/correction.py` no fluxo de chat (SP-70..SP-74), acoplada ao `LLMEnvelope`. Os novos PATCH REST (SP-164/165/166) precisam da mesma essência com payloads Pydantic tipados. Duplicação é risco de divergência (chat calcula de um jeito, REST de outro — violaria Const. Art. II §5 indiretamente).

**Decisão.** Extrair funções puras por tipo em `app/services/correction_ops.py`:
- `apply_water_change(record, *, volume_ml) -> {changed, warnings}`
- `apply_beverage_change(record, *, volume_ml, session) -> {changed, warnings}` (session para lookup de fact)
- `apply_activity_change(record, *, duration_minutes?, intensity?, kcal_burned?, user) -> {changed, warnings}`

`CorrectionService` (chat) converte `LLMEnvelope.correction.changes` → kwargs dessas funções; os handlers REST passam o payload Pydantic direto. Ambos chamam `DailyRecomputeService` e `AuditEventRepository` (a grave permanece no caller — `correction_ops` só muta a entidade e reporta `changed`/`warnings`).

**Consequências.**
- ✔ Single source of truth para a matemática de correção; chat e REST não divergem.
- ✔ `correction_ops` funções puras → fáceis de testar unitariamente (90% alvo).
- ✘ Indireção extra na chamada do chat; mitigada mantendo a assinatura próxima da atual.
- ✘ Auditing/`source='user_corrected'`/recompute ficam no caller (2 callers), não no `correction_ops` — leve boilerplate por handler. Aceitável dado que issuer do audit (`actor='llm'` vs `actor='user'`, `message_id`) já diverge entre chat e REST.

**Alternativas descartadas.**
- **A. Duplicar a lógica em cada handler REST.** Risco alto de divergência do cálculo (Const. Art. II). Rejeitado.
- **B. Fazer o chat chamar os handlers REST internamente.** Inversão de camadas (service → route); acoplamento estranho. Rejeitado.