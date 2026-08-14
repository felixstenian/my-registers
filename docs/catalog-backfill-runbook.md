# Backfill de itens zerados + reseed do catálogo TBCA

Runbook de correção one-off para itens **já criados** com `kcal=0` e
`catalog_ref_id=NULL`. Resolve retrospectivamente o mesmo sintoma que o
PR #37 tratou daqui pra frente, sem precisar re-registrar item por item.

## Contexto (investigação 2026-08-14)

- O banco foi seedado de uma **versão antiga** do `seed_tbca.csv`: o
  `nutrient_facts` tem 35 fatos; o CSV atual tem 65.
- Consequência: no momento do registro, o lookup (`LocalTBCACatalog`) não
  achava o fato (ex.: `pepino`, `cuscuz`, `granola`, `pão ceda`,
  `chocolate ao leite` → itens com `kcal=0`, `catalog_ref_id=NULL`).
- **Não há drift de `canonical_name`.** `seed.py` normaliza nomes no ingest
  (`normalize_name`), então `brocolis_cozido` vira `brocoll_cozido` no banco
  — e o lookup também normaliza a query. Renomear esses nomes quebraria o
  matching (busca `brocoll_cozido`, não acharia `brocolis_cozido`).

O fix tem duas partes, entregues como serviços/testes (PR a definir):

1. `python -m app.cli reseed-catalog` — re-roda `seed_from_csv` (upsert
   idempotente) e insere os fatos TBCA faltantes.
2. `python -m app.cli backfill-zeroed [--include-closed]` — varre
   `food_items` vivos com `kcal=0`, religa ao catálogo, recomputa macros,
   grava `audit_events` (`action='correct'`) e recomputa o snapshot por dia.

Código: `apps/api/app/services/catalog_backfill.py` — `CatalogBackfillService`
(`reseed_catalog()` e `backfill_zeroed_items(include_closed=False)`).

---

## 1. Snapshot antes (obrigatório)

```bash
./scripts/backup-postgres.sh
```

## 2. Inserir fatos TBCA faltantes (obrigatório)

```bash
docker compose -f docker-compose.production.yml --env-file .env.production run --rm api \
  python -m app.cli reseed-catalog
```

**Esperado:** `inserted=30` (ou próximo), `updated≈35`. Idempotente — pode
rodar N vezes.

Validação:

```bash
docker compose -f docker-compose.production.yml --env-file .env.production \
  exec postgres psql -U registers_app -d registers \
  -c "SELECT COUNT(*) FROM nutrient_facts;"
```

Esperado: `≥ 65`.

> Nota: `scripts/bootstrap.sh` do deploy roda `seed-nutrition` sozinho, então
> o passo 2 entra automaticamente no próximo deploy verde em `main`. Rodar
> manualmente agora apenas antecipa o estado desejado.

## 3. Backfill dos itens zerados (obrigatório)

Dias **abertos** são corrigidos primeiro; dias **fechados** são pulados
(INV-5 — Art. VIII §28), reportados como `skipped (dia fechado)`.

```bash
docker compose -f docker-compose.production.yml --env-file .env.production run --rm api \
  python -m app.cli backfill-zeroed
```

**Esperado:**

- `scanned=N`, `fixed=M`, `recomputed_days=K`.
- Linhas `unresolved (sem hit no catálogo): <nome>` para itens que o
  catálogo não resolve (ex.: `aveia`, `queijo prato`, `sonho`, `nutella`,
  `sushi`, `cereal de chocolate`).
- Linhas `skipped (dia fechado): <nome>` para itens em dias fechados.

## 4. Revisar itens `unresolved`

Para cada `unresolved`, decidir entre:

- **Opção A (recomendado)** — via chat: `corrija <nome> <quantidade>`.
  Promove `catalog_ref_id` no PATCH, recomputa macros e snapshot (fluxo
  formalizado no Bloco 5 / PR #38).
- **Opção B** — criar fato manual novo (rota de catálogo `POST /nutrient-facts`
  com `source='manual'`) e repetir o backfill.
- **Opção C** — descartar via chat: `apaga o <nome>` (soft-delete + recompute).

Não usar `UPDATE ... WHERE` direto em SQL: bypassa audit e não recomputa o
snapshot (divergência item vs. dia).

## 5. Decidir sobre dias fechados (opcional, com responsabilidade)

Dias fechados são imutáveis (INV-5). Se você quiser corrigir o histórico de
qualquer forma (ex.: o dia não foi fechado de propósito e o item zerado
polui o relatório semanal):

```bash
docker compose -f docker-compose.production.yml --env-file .env.production run --rm api \
  python -m app.cli backfill-zeroed --include-closed
```

Nota: itens em dias fechados **não** estavam sendo contabilizados como zerados
no snapshot? Verificar antes: eles já contam `kcal=0` no snapshot fechado. Este
comando corrige o `food_item` e **regrava** o `closed_at` do snapshot (não faz
reabertura; ver `app/services/day_close.py`).

## 6. Validar

1. `/api/days/today` e `/api/days?from=&to=` mostram kcal corretas no relatório.
2. Query de conferência:

```bash
docker compose -f docker-compose.production.yml --env-file .env.production \
  exec postgres psql -U registers_app -d registers -c "
SELECT COUNT(*) AS zeroed_open
FROM food_items fi
JOIN food_records fr ON fr.id = fi.food_record_id
JOIN day_logs dl ON dl.id = fr.day_log_id
WHERE fi.deleted_at IS NULL
  AND fi.kcal = 0
  AND dl.status = 'open';"
```

Esperado: `0` após o backfill (itens restantes zerados são só `unresolved` ou
em dias fechados).