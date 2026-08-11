# Requisitos — Visão detalhada do dia (Bloco 6)

> **Rastreabilidade**: SP-150..SP-155 em [`specs/001-mvp-registro-diario/spec.md`](../../001-mvp-registro-diario/spec.md#315-visão-detalhada-do-dia) · Implementação: `apps/web/src/app/(app)/day/` + `apps/api/app/services/day_query.py::_load_food` (micros) · Bloco 6 (T-B601..T-B608) — PRs #43, #44 e #46; T-B608 concluído via commit `2681fba`.

## Visão geral

Página server-rendered `/day` (e `/day/[date]`) com visão detalhada do dia: refeições agrupadas por `meal_slot` com macros por item, expansão `<details>` para micros + origem, seções auxiliares (hidratação, bebidas, atividade), totais do dia, narrativa LLM pós-fechamento (quando existir), navegação temporal (prev/next/hoje + date picker). Escopo v1 é **read-only**; mutações de records continuam via chat. Exceção: confirmar item inline e encerrar dia retroativo.

## Requisitos funcionais

| ID | Requisito | SP | Prioridade |
|---|---|---|---|
| RF-001 | Rota `/day` (server component protegido, `force-dynamic`) faz fetch de `GET /days/today` via `INTERNAL_API_URL`. Header exibe data formatada em pt-BR (`domingo, 27 de julho`), badge `status`, botão "Encerrar dia" (só quando `status='open'` && não vazio). Link "Hoje"/"Detalhes" no header do layout protegido. | SP-150 | Should Have |
| RF-002 | Refeições agrupadas por `meal_slot` na ordem `breakfast → lunch → snack → dinner → unspecified`. Slots vazios não renderizam. Cabeçalho da seção tem nome pt-BR + horário do primeiro registro + kcal parcial. Tabela com colunas Item/Quantidade/Calorias/P/C/G/Fib. | SP-151 | Should Have |
| RF-003 | Badge amarelo "confirmar" inline quando `needs_confirmation=true` (botão `ConfirmItemButton` → `POST /records/food-items/{id}/confirm`); badge "sem catálogo" quando `catalog_ref_id=null`. | SP-151 | Should Have |
| RF-004 | Linha de food_item expansível via `<details>` nativo (zero JS); revela micros: Sódio/Cálcio/Ferro/Potássio (mg). Valores zero/nulos renderizam `—`. Mostra `source` em pt-BR + `confidence` da LLM quando `source='llm'`. | SP-152 | Should Have |
| RF-005 | Seção **Hidratação**: lista (horário + volume) + totalizador `Água: N ml`. Sección **Bebidas**: tabela reduzida (item/volume/kcal/P/C/G) com badge "confirmar". Sección **Atividade**: nome + tipo pt-BR + duração + intensidade + kcal gastas + método pt-BR. Cada seção some se sua lista é vazia. | SP-153 | Should Have |
| RF-006 | Rota `/day/[date]` (server component); valida param contra `^\d{4}-\d{2}-\d{2}$` rejeitando path traversal; `GET /days/{date}`. 404 amigável ("Nenhum registro encontrado nesta data") + link "Voltar para hoje". Edição de records continua via chat; `allowClose=true` permite encerrar dia passado aberto. | SP-154 | May Have |
| RF-007 | Data futura (`date > hoje` local): renderiza "Não é possível ver o futuro" + link "Voltar para hoje"; não chama backend. Datas anteriores ao primeiro `day_log` caem no 404 de SP-154. | SP-155 | Should Have |
| RF-008 | Navegação temporal: botão "← Dia anterior" (sempre); "Próximo dia →" (só se `date+1 <= hoje`, escondido no dia atual); "Hoje" (escondido no dia atual); `<input type="date" max={today}>` + botão "Ir" que navega. Coluna "Dia" do `/weekly` vira link pra `/day/[date]`. | SP-155 | Should Have |
| RF-009 | Totais do dia em card: Cal. in (destaque), Cal. out + Saldo (só se `kcal_out>0`), Proteína/Carbo/Gordura/Fibras, Água, Outros líq. (só se `>0`). | [Inferido do código] | Must Have |
| RF-010 | Narrativa LLM (`data.narrative`) exibida em card "Resumo" quando existir (aparece pós-fechamento). | [Inferido do código] | Should Have |
| RF-011 | Aviso legal (Const. Art. VII §26) obrigatório em rodapé da página. | Art. VII §26 | Must Have |
| RF-012 | `RefreshOnFocus`: `router.refresh()` no mount + `visibilitychange` (debounce 2s) — pega staleness do Router Cache do Next após mutações externas (ex.: confirmação pelo chat). | [Inferido do código] | Must Have |

## Requisitos não funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | Server components (zero JS no render das tabelas); `<details>` HTML nativo para expansão — sem biblioteca de accordion. | Performance |
| RNF-002 | `force-dynamic` em ambas rotas — records mudam a cada mensagem no chat; cache HTTP não faz sentido. | Corretude |
| RNF-003 | `INTERNAL_API_URL` para fetch server-side (DNS interno do compose); `NEXT_PUBLIC_API_URL` não usada aqui (só client). Aprendizado do hotfix #25. | Infra/Corretude |
| RNF-004 | Cookie enviado via `headers: { cookie: cookieHeader }` no `fetch` server-side. | Segurança |
| RNF-005 | `credentials` automático no client (botões); o `api-client` cuida. | Segurança |
| RNF-006 | Aritmética de datas UTC interna (`addDaysISO`/`partsToISO`) — evita DST drift; input YYYY-MM-DD sem hora tratado como dia calendário. | Corretude |
| RNF-007 | `Intl.NumberFormat('pt-BR')` para números; `Intl.DateTimeFormat('pt-BR')` para datas/horários. | UX |
| RNF-008 | `/day` and `/day/:path*` em `PROTECTED_PREFIXES` do `proxy.ts` (proteção por cookie). | Segurança |
| RNF-009 | Zero `null` numbers vira `—` (menos ruído visual — SP-152). | UX |

## Restrições e premissas

- **SP-150..154 são `should`/`may`**, já em produção (PRs #43/#44/#46).
- **Escopo v1 read-only**: mutações de registros (correção/exclusão) continuam via chat — pagina `/day` não expõe botões de editar/excluir item. Exceção: confirmar inline (`ConfirmItemButton`) e encerrar dia retroativo (`CloseDayButton` reusado do chat).
- **INV-5 (dia fechado imutável)**: confirm inline e encerrar respeitam backend (dia `closed` não muta).
- **Timezone**: `todayLocalISO`/`fmtTime` usam fuso do browser; na maioria dos casos casa com `user.timezone` do backend. Em fuso divergente do container, backend responde 404 no limite e UI cai no ErrorPanel.
- **Fora do escopo** (por design): edição/deleção inline (v2), filtros/ordenação, exportação CSV/PDF (B-06), gráficos de macros (v2+), comparação com dias anteriores (v2+).

## Dependências

**Depende de:**
- [`daily-snapshot`](../daily-snapshot/requirements.md) — `GET /days/today` e `GET /days/{date}`; `DaySnapshot` shape.
- [`day-close`](../day-close/requirements.md) — `CloseDayModal` reusado; `POST /days/{date}/close` funciona em qualquer data aberta.
- [`record-correction`](../record-correction/requirements.md) — `POST /records/food-items/{id}/confirm` (inline).
- [`weekly-report`](../weekly-report/requirements.md) — coluna "Dia" vira link pra `/day/[date]` (SP-155).
- [`food-logging`](../food-logging/requirements.md) — `food_items` shape com `needs_confirmation`/`has_catalog`/`source`/`confidence`.
- [`assistant-message-rendering`](../assistant-message-rendering/requirements.md) — `DayTotalsBar` reusado por `CloseDayButton`? Não — independente.
- Fase 1 (`authentication-session`) — `proxy.ts` protege `/day`.

**Requerido por:**
- Sem dependentes diretos — é camada de visualização.