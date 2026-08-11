# Critérios de Aceitação — Visão detalhada do dia (Bloco 6)

> **Rastreabilidade**: SP-150..SP-155 · Contratos: [`requirements.md`](./requirements.md), [`specifications.md`](./specifications.md).

## AC-001 — Rota /day renderiza hoje (SP-150)

**Dado que** o usuário autenticado entra em `/day`,
**Quando** o server component monta,
**Então** faz `GET /days/today` via `INTERNAL_API_URL` com cookie; `force-dynamic`; renderiza `<DayView data allowClose />`.

**Dado que** o backend responde erro não-2xx,
**Quando** o fetch retorna,
**Então** exibe ErrorPanel "Erro {status} ao carregar o dia."

**Dado que** o dia está `status='closed'`,
**Quando** renderiza,
**Então** header badge "Dia encerrado" (.green); botão "Encerrar dia" **não** aparece.

**Dado que** o dia está `status='open'` com registros,
**Quando** renderiza,
**Então** header badge "Em aberto" (slate); botão "Encerrar dia" aparece.

**Dado que** o dia está `status='open'` mas vazio (`isEmpty`),
**Quando** renderiza,
**Então** botão "Encerrar dia" **não** aparece (não útil fechar vazio).

**Notas de validação:**
- Implementação: `page.tsx:14`, `DayView.tsx:52`.

---

## AC-002 — Refeições agrupadas por meal_slot (SP-151)

**Dado que** o dia tem 2 refeições `lunch` e 1 `breakfast`,
**Quando** `groupBySlot` agrupa e `DayView` renderiza,
**Então** slots aparecem na ordem `breakfast → lunch`; slots vazios (`snack`/`dinner`/`unspecified`) não renderizam.

**Dado que** uma seção tem registros,
**Quando** `MealSection` renderiza,
**Então** header tem nome pt-BR + horário do primeiro `occurred_at` + kcal parcial (soma de `rec.items[].kcal`). Grid 12-col header: Item(4)/Quantidade(2)/Calorias(2)/P(1)/C(1)/G(1)/Fib(1).

**Dado que** slot é desconhecido (ex.: `'brunch'`),
**Quando** `groupBySlot` bucketiza,
**Então** cai em `unspecified` (label "Outros").

**Notas de validação:**
- Implementação: `DayView.tsx:86` (`groupBySlot`), `MealSection.tsx`.

---

## AC-003 — Badges "confirmar" e "sem catálogo" (SP-151)

**Dado que** um `food_item` tem `needs_confirmation=true`,
**Quando** `FoodItemRow` renderiza,
**Então** nome acompanhado de `<ConfirmItemButton>` (badge amber "confirmar").

**Dado que** o usuário clica no botão,
**Quando** `POST /records/food-items/{id}/confirm` retorna 200,
**Então** botão some (`state='done'`) e `router.refresh()` re-renderiza a página sem o badge.

**Dado que** um item tem `has_catalog=false`,
**Quando** `FoodItemRow` renderiza,
**Então** badge cinza "sem catálogo" com tooltip "Sem catálogo — macros podem estar zerados".

**Notas de validação:**
- Click no botão **não** toggle do `<details>` pai (`e.preventDefault/stopPropagation`).
- Dia fechado bloqueia confirm no backend (INV-5).

---

## AC-004 — Expansão de item com micros + origem (SP-152)

**Dado que** o usuário expande uma linha de item (`<details>` aberto),
**Quando** revela conteúdo,
**Então** mostra Sódio/Cálcio/Ferro/Potássio (mg) + Origem (`SOURCE_LABEL_PT`) + Confiança LLM (se `source==='llm'`).

**Dado que** todos os micros são `null/0`,
**Quando** expande,
**Então** exibe "Sem micronutrientes registrados neste item." (em itálico).

**Dado que** um valor de macro/micro é `0` ou `null`,
**Quando** renderiza,
**Então** mostra `—` (em vez de `0`).

**Dado que** `source='user_corrected'`,
**Quando** expande,
**Então** "Confiança da LLM" **não** aparece (só relevante para `source='llm'`).

**Notas de validação:**
- `<details>` HTML nativo (zero JS).

---

## AC-005 — Seções auxiliares (SP-153)

**Dado que** o dia tem registros de água,
**Quando** `<HydrationSection>` renderiza,
**Então** header tem "Hidratação" + `Água: N ml`; lista com horário (HH:mm) + volume.

**Dado que** o dia tem bebidas calóricas,
**Quando** `<BeverageSection>` renderiza,
**Então** header tem "Bebidas" + `{ml} ml · {kcal}`; grid com item/volume/kcal/P/C/G; badge "confirmar" se `needs_confirmation`.

**Dado que** o dia tem atividade,
**Quando** `<ActivitySection>` renderiza,
**Então** header "Atividade" + `Calorias gastas: N kcal`; grid com nome+tipo pt-BR+duração+intensidade+kcal+method pt-BR.

**Dado que** uma seção tem 0 registros,
**Quando** renderiza,
**Então** retorna `null` (some).

**Notas de validação:**
- Mapas: `ACTIVITY_TYPE_LABEL_PT`, `CALC_METHOD_LABEL_PT`, `SOURCE_LABEL_PT` em `types.ts`.

---

## AC-006 — Rota /day/[date] (SP-154)

**Dado que** o usuário acessa `/day/2026-07-29`,
**Quando** o server component valida `DATE_PATTERN` (`^\d{4}-\d{2}-\d{2}$`),
**Então** se inválido → ErrorPanel "Data inválida" (não chama backend).

**Dado que** a data é válida e existe `day_log`,
**Quando** `GET /days/{date}` retorna 200,
**Então** renderiza `<DayView data allowClose />`.

**Dado que** `day_log` não existe para `date`,
**Quando** backend responde 404,
**Então** ErrorPanel "Nenhum registro encontrado nesta data." + link "Voltar para hoje".

**Dado que** a data é válida mas está `status='open'` (usuário esqueceu),
**Quando** renderiza,
**Então** botão "Encerrar dia" aparece (permite encerramento retroativo).

**Dado que** a data é `status='closed'`,
**Quando** renderiza,
**Então** botão "Encerrar dia" não aparece (INV-5 — já fechado).

**Notas de validação:**
- `allowClose=true` para `/day/[date]`; `DayView` checa internamente `status==='open'`.
- Edição de records continua só via chat (não há botões mutar item nesta página, com exceção do `ConfirmItemButton` e `CloseDayButton`).

---

## AC-007 — Data futura bloqueada (SP-155)

**Dado que** o usuário acessa `/day/2026-12-31` (futuro) e hoje é `2026-07-30`,
**Quando** o server component calcula `compareISO(date, todayLocalISO()) > 0`,
**Então** retorna "Não é possível ver o futuro" + link "Voltar para hoje" — **sem** chamar backend.

**Dado que** o usuário usa o date picker com futura data,
**Quando** tenta "Ir",
**Então** `goToPicked` bloqueia client-side (sanity); não navega.

---

## AC-008 — Navegação temporal (SP-155)

**Dado que** `DayNavigator` monta com `date` igual a hoje,
**Quando** renderiza,
**Então** mostra "← Dia anterior" e o date picker; **esconde** "Hoje" e "Próximo dia →".

**Dado que** `date` é um dia passado,
**Quando** renderiza,
**Então** mostra "← Dia anterior" + "Hoje" (link `/day`) + "Próximo dia →" só se `nextDate <= today`; date picker `max=today`.

**Dado que** o usuário preenche o date picker e clica "Ir",
**Quando** `picked === today`,
**Então** `router.push('/day')`.

**Dado que** `picked` é passado e diferente de `date`,
**Quando** clica "Ir",
**Então** `router.push('/day/${picked}')`.

**Dado que** `picked === date` (sem mudança),
**Quando** clica "Ir",
**Então** botão `disabled` (não navega).

**Notas de validação:**
- `<nav aria-label="Navegar entre dias">` acessível.

---

## AC-009 — Link do /weekly para /day/[date] (SP-155)

**Dado que** o usuário está em `/weekly` e a tabela `per_day` mostra linhas com `date`,
**Quando** renderiza,
**Então** coluna "Dia" de cada linha é `<Link href={`/day/${row.date}`}>`.

---

## AC-010 — Totais e narrativa (SP-150 + T-704 refluido)

**Dado que** o dia tem registros,
**Quando** `<TotalsCard>` renderiza,
**Então** mostra Cal. in (destaque), Cal. out + Saldo (só se `kcal_out>0`), Proteína/Carbo/Gordura/Fibras, Água, Outros líq. (só se `>0`).

**Dado que** o dia foi encerrado e `data.narrative` é não-null,
**Quando** `DayView` renderiza,
**Então** mostra `<NarrativeCard text={data.narrative} />` em card "Resumo".

**Dado que** o dia está aberto (ainda não encerrado),
**Quando** renderiza,
**Então** narrativa **não** aparece (gerada no fechamento).

---

## AC-011 — Estados vazios e empty (vazio)

**Dado que** o dia tem 0 registros em todas as listas,
**Quando** `DayView` renderiza,
**Então** `<EmptyState>` mostra:
- `open`: "Ainda não há nada registrado hoje. Comece pelo chat."
- `closed`: "Este dia foi encerrado sem registros."

---

## AC-012 — RefreshOnFocus combate staleness (não-funcional)

**Dado que** o usuário confirmou um item pelo chat em outro dispositivo e volta pra aba `/day`,
**Quando** `visibilitychange` dispara `visible`,
**Então** `router.refresh()` re-fetch (debounce 2s).

**Dado que** o usuário navega client-side para `/day` dentro da app,
**Quando** o componente monta,
**Então** `router.refresh()` no mount (Router Cache pode ter versão pré-mutação).

**Notas de validação:**
- [Inferido do código] — sem custo no caso single-user; rever em multi-user lata.

---

## Cenários de Borda

| Cenário | Comportamento Esperado |
|---|---|
| Data picker vazio (`picked=''`) | Botão "Ir" `disabled` (`!picked`). |
| Path traversal `/day/../../etc/passwd` | `DATE_PATTERN` rejeita; ErrorPanel "Data inválida". |
| Fuso divergente browser vs container | `todayLocalISO` browser-side vs server-side pode divergir; backend responde 404 no limite; ErrorPanel cobre. |
| Slot desconhecido (`'brunch'`) | Cai em `unspecified` ("Outros"). |
| Item com `grams=0` e `ml=0` + `quantity=2 unit='concha'` | `fmtAmount` mostra `2 concha`. |
| `<details>` aberto com zero micros | Mostra "Sem micronutrientes registrados neste item." |
| Narrativa muito longa | `<p className="whitespace-pre-wrap">` respeita quebras; sem truncation (aceito como trade-off). |
| Invalidar Runtime do Next cache | `force-dynamic` em ambas rotas server; sem cache HTTP. |
| Confirmar item offline | POST falha; botão volta a `idle` (sem toast). |
| `RefreshOnFocus` dispara muitas vezes | Debounce 2s evita spam. |

## Critérios de Não-Funcionalidade

| Critério | Threshold |
|---|---|
| `/day` sempre dinâmico | `force-dynamic`; sem cache HTTP |
| Render de tabelas sem JS extra | `<details>` nativo; MealSection/FoodItemRow server components |
| Aritmética de datas | UTC interno; zero DST drift |
|.pt-BR format | `Intl.NumberFormat`/`DateTimeFormat` 'pt-BR' |
| Valores zero/null | Renderiza `—` |
| Futuro bloqueado | Sem backend hit |
| Path traversal | Regex `YYYY-MM-DD` rejeita antes do fetch |
| Debounce de refresh | 2000ms |
| Cookie server-side | `headers: { cookie: cookieHeader }` em toda fetch server |