# Pós-deploy — hotfix macros zerados + confirmar item

Passos a rodar na VPS **depois de mergear PR #37 e o deploy subir**. Só o passo 1 é obrigatório; 2 é validação; 3 é opcional (só faz sentido se houver items zerados em prod).

Referência: PR #37 fecha 2 bugs — (a) macros zerados em prod por seed TBCA nunca ter rodado; (b) modal "Confirmar" não desmarcava `needs_confirmation` quando item só tinha `quantity`.

---

## 1. Confirmar que o seed rodou (obrigatório)

O `scripts/bootstrap.sh` do PR #37 passa a chamar `python -m app.cli seed-nutrition` automaticamente. Confirmar:

```bash
docker compose -f docker-compose.production.yml --env-file .env.production \
  exec postgres psql -U registers_app -d registers \
  -c "SELECT COUNT(*), MIN(created_at), MAX(created_at) FROM nutrient_facts;"
```

**Esperado:** `count ≥ ~100` (número de linhas do `seed_tbca.csv`).

**Se voltar 0 ou número pequeno**, o seed não rodou por algum motivo — força manual:

```bash
docker compose -f docker-compose.production.yml --env-file .env.production run --rm api \
  python -m app.cli seed-nutrition
```

O comando é idempotente — pode rodar N vezes sem risco. Ele faz upsert por `canonical_name`.

---

## 2. Smoke test do fluxo (recomendado, ~2 min)

No browser em produção:

### Bug 1 — macros zerados no registro

1. Login → chat.
2. Envie: `100g de arroz`.
3. Aguarde a assistant message (~5-10s).
4. **Esperado:**
   - Assistant message mostra `~130 kcal` (não `0 kcal`).
   - `DayTotalsBar` no topo atualiza com `Cal. in ≈ 130 kcal`.
   - Não aparece badge "item precisa de confirmação".

Se aparecer com 0 kcal, o seed não está populado — volta ao passo 1.

### Bug 2 — modal "Confirmar" não desmarcava flag

Só testável se houver item pendente. Se não tiver, forçar:

1. Envie mensagem que a LLM não consegue estimar grams (ex.: `"comi uma concha de feijão"`).
2. Assistant deve criar o item com `needs_confirmation=true` — aparece badge amarelo no `DayTotalsBar`.
3. Clica no badge → abre `PendingItemsModal`.
4. Clica em **Confirmar** no item.
5. **Esperado:**
   - Modal fecha.
   - Badge some do `DayTotalsBar` (revalidou `/days/today`).
   - Se reabrir o modal, o item não aparece mais como pendente.

Se o badge continuar aparecendo depois do Confirmar, o novo endpoint `POST /records/food-items/{id}/confirm` não está ativo — verificar logs da API:

```bash
docker compose -f docker-compose.production.yml --env-file .env.production logs --tail=50 api
```

---

## 3. Recuperar itens legados com kcal=0 (opcional)

Itens **já criados** em prod antes deste hotfix continuam com `kcal=0` e `catalog_ref_id=NULL` no snapshot — o fix não altera dados retroativos. Se houver muitos, considere um dos caminhos.

### 3.1 Verificar quantos itens estão zerados

```bash
docker compose -f docker-compose.production.yml --env-file .env.production \
  exec postgres psql -U registers_app -d registers -c "
SELECT COUNT(*)
FROM food_items
WHERE deleted_at IS NULL
  AND catalog_ref_id IS NULL
  AND kcal = 0
  AND needs_confirmation = true;"
```

Se **0**, pode pular esta seção.

### 3.2 Opção A — Recuperar via chat (recomendado)

Para cada item zerado, no chat da app:

```
corrija arroz 100g
```

O PATCH melhorado do PR #37 sempre tenta lookup pelo `normalized_name`. Se o catálogo tem entrada compatível, promove `catalog_ref_id`, recomputa macros, desmarca `needs_confirmation` e faz recompute do snapshot do dia.

Vantagens:
- Gera `audit_events` (`action='correct'`, `actor='user'`)
- Snapshot é reagregado automaticamente
- Reversível se der errado

### 3.3 Opção B — Descartar via chat

```
apaga o arroz
```

Soft-delete + recompute. Kcal_in do dia cai (não muda porque já era 0, mas o item some da lista).

### 3.4 Opção C — Bulk via SQL (não recomendado)

Só se houver dezenas de itens e você quiser resolver de uma vez. Antes:

```bash
./scripts/backup-postgres.sh  # snapshot pre-alteração
```

Depois, avaliar item por item — não existe uma query genérica segura porque cada `food_item` tem `normalized_name` diferente. Se quiser, cria uma issue e escrevo um script Python que lê cada item pendente, faz lookup e atualiza (com audit adequado).

**Não recomendo** `UPDATE food_items SET ... WHERE ...` direto porque:
- Bypassa audit
- Não recomputa snapshot (aparece divergência entre item e snapshot)
- Difícil reverter

---

## Se o CD (Fase 10) já estiver ativo

Se você configurou T-1003 + T-1004 (branch protection + chave SSH deploy-only), o deploy foi automático. O `command="..."` do `authorized_keys` já chama `bootstrap.sh`, então **o passo 1 executou sozinho**. Apenas confirme com a query do passo 1 e faça o smoke test do passo 2.

Se `command="..."` foi copiado da doc antiga (antes do PR #37 corrigir o `bootstrap.sh`), a linha já chama `./scripts/bootstrap.sh .env.production` — nada muda. O `bootstrap.sh` novo é lido do repo atualizado após `git fetch origin && git reset --hard origin/main` (ver `docs/deploy.md` §14.2 — `git pull` foi trocado por `reset --hard`).

## Se o CD ainda não estiver ativo

Deploy manual:

```bash
cd ~/my-registers
git fetch origin && git reset --hard origin/main   # traz bootstrap.sh novo + código
./scripts/bootstrap.sh .env.production      # roda seed + admin (idempotente)
docker compose -f docker-compose.production.yml --env-file .env.production \
  up -d --build api web                     # rebuild com fix do endpoint + modal
```

Depois seguir os passos 1 e 2 acima.
