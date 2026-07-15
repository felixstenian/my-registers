# Implementation Plan — MVP: Registro Diário por Chat com IA

**Feature ID:** 001-mvp-registro-diario
**Owner:** Felix
**Depende de:** [`spec.md`](spec.md) v1.0, [`../../.specify/memory/constitution.md`](../../.specify/memory/constitution.md) v1.0.0
**Referencia:** [`../../app_plan.md`](../../app_plan.md) (fonte canônica de arquitetura, DB, endpoints)

---

## Regras deste documento

- Este `plan.md` descreve **como** implementar o que está em `spec.md`, sem duplicar decisões.
- A fonte canônica de arquitetura é `app_plan.md` (20 seções). Aqui apenas: (a) mapeio SP-XX → seção do plano; (b) adiciono decisões SDD-específicas (gates, ADRs, ordem de execução); (c) registro divergências do plano quando houver.
- Alterações neste arquivo requerem PR próprio; alterações que atinjam artigos da Constituição exigem emenda constitucional.

---

## 1. Mapa SP-XX → seções do plano

| SP | Área | Plano | Arquivos-chave |
|----|------|-------|----------------|
| SP-01 a SP-06 | Autenticação | §7, §10 | `app/api/routes/auth.py`, `app/services/auth.py`, `app/core/security.py` |
| SP-10 a SP-14 | Chat | §4, §6 (messages), §10 | `app/api/routes/chat.py`, `app/services/chat.py`, `app/integrations/anthropic/` |
| SP-20 a SP-26 | Registro de alimentos | §6, §8, §9 | `app/api/routes/records.py`, `app/services/meal.py`, `app/services/nutrition_calculator.py` |
| SP-30 a SP-35 | Rótulo nutricional | §8.2 (extensão), §6 (nutrient_facts) | `app/services/label_catalog.py`, `app/integrations/nutrition/` |
| SP-40 a SP-42 | Água | §6, §10 | `app/services/hydration.py` |
| SP-50 a SP-52 | Outros líquidos | §6, §10 | `app/services/beverage.py` |
| SP-60 a SP-64 | Atividades | §6, §10 | `app/services/activity.py`, `app/services/activity_calculator.py` (METs) |
| SP-70 a SP-74 | Correções | §6 (audit_events), §10 | `app/services/correction.py` |
| SP-80 a SP-82 | Remoções | §6, §10 | `app/services/*` (soft delete + recompute) |
| SP-90 a SP-92 | Consulta do dia | §10 | `app/api/routes/days.py`, `app/services/daily_report.py` |
| SP-100 a SP-104 | Encerramento | §6, §10 | `app/services/daily_report.py` (close) |
| SP-110 a SP-113 | Relatório semanal | §6 (weekly_reports), §10 | `app/services/weekly_report.py` |

---

## 2. Ordem de execução (Fases)

Idêntica à §18 do plano, com sub-fase 4.b já incorporada.

| Fase | Nome | Estim. | Entrega os SPs |
|------|------|--------|----------------|
| 0 ✅ | Fundação | 2-3d | (esqueleto executável, sem SPs; base para as demais) |
| 1 | Autenticação + bootstrap admin | 1-2d | SP-01, SP-02, SP-03, SP-04, SP-05, SP-06 |
| 2 | Mensagens e upload de mídia | 2d | SP-10, SP-11, SP-12 (parcial), fluxo base para §3.3-§3.7 |
| 3 | Integração Anthropic | 3d | SP-13, SP-14, contrato JSON validado |
| 4 | Registro de alimentos | 3d | SP-20 a SP-26, INV-1 |
| 4.b | Leitura de tabela nutricional | 1-2d | SP-30 a SP-35 |
| 5 | Hidratação + atividades | 2d | SP-40 a SP-42, SP-50 a SP-52, SP-60 a SP-64, INV-2, INV-3 |
| 6 | Correções e remoções | 2d | SP-70 a SP-74, SP-80 a SP-82, INV-4, INV-10 |
| 7 | Encerramento + relatório diário | 1d | SP-90 a SP-92, SP-100 a SP-104, INV-5 |
| 8 | Relatório semanal | 1d | SP-110 a SP-113, INV-8 |
| 9 | Hardening + deploy | 2d | (segurança, backup, HTTPS; cross-cutting) |

Total: ~20-21 dias úteis focados.

---

## 3. Gates de fase

Cada fase só é considerada **entregue** quando:

1. **Todos os SPs `must` da fase têm teste automatizado verde** (unit ou integration).
2. **Nenhum artigo da Constituição é violado** — checklist manual (§4 abaixo).
3. **Nenhuma alteração de spec** foi feita sem PR próprio.
4. **`git log` do PR referencia SPs** cobertos: exemplo `feat(fase-4): SP-20 SP-21 SP-23 - registro por texto`.
5. **`app_plan.md` atualizado** se decisões arquiteturais mudaram.

Sem estes gates cumpridos, o merge é bloqueado.

---

## 4. Checklist de conformidade constitucional

Aplicado em **todo PR** que toca código de negócio (services, models, routes):

- [ ] Nenhuma soma nutricional passou pela LLM (Art. II §5).
- [ ] Snapshot recomputa from-scratch, não delta (Art. III §10).
- [ ] `audit_events` gravado em toda mutação (Art. III §11).
- [ ] Água e outros líquidos separados (Art. IV §12-14).
- [ ] `user_id` no filtro de toda query (Art. V §21).
- [ ] Nenhum segredo em código/logs/response (Art. V §19).
- [ ] Aviso legal presente em respostas de dia/semana (Art. VII §26).
- [ ] Nenhum endpoint HTTP de cadastro ou reset (Art. V §18).
- [ ] Dia fechado é imutável no path testado (Art. VIII §28).

---

## 5. Decisões técnicas SDD-específicas

### 5.1 Estrutura de branches

- `dev` — trunk. PRs entram por squash-merge.
- `feat/fase-N-<slug>` — por fase (ou sub-fase). Ex: `feat/fase-1-auth-bootstrap`.
- Merge para `dev` requer: (a) gates §3; (b) checklist §4.
- Push direto em `dev` é permitido só para hotfix da Fase 0 (ambiente).

### 5.2 Convenção de commits

Formato Conventional Commits + referência a SP-XX no primeiro parágrafo:

```
feat(fase-4): registrar alimentos por texto e foto

Cobre SP-20, SP-21, SP-23. Adiciona MealService.create_from_llm,
NutritionCalculator.compute, e recompute do snapshot ao criar itens.

Refs: spec §3.3, constitution Art. II
```

### 5.3 Testes obrigatórios por camada

- **INV-N** → teste de integração com Postgres real (via testcontainers ou banco de teste). Nunca mock.
- **SP-XX must** → teste unit de service + teste de integração ponta-a-ponta (route → service → repo → DB).
- **LLM** → mock do cliente Anthropic. Fixtures em `tests/fixtures/anthropic/*.json`.

Cobertura mínima aceitável no MVP: **80%** em `app/services/` e **90%** em `app/services/nutrition_calculator.py` + `app/services/activity_calculator.py`.

### 5.4 Formato das ADRs

Novas decisões que alteram trade-offs vivem em `research.md` como blocos:

```markdown
## ADR-NNN: título curto
**Data:** yyyy-mm-dd
**Status:** proposed | accepted | superseded by ADR-MMM
**Contexto:** ...
**Decisão:** ...
**Consequências:** ...
**Alternativas descartadas:** ...
```

### 5.5 Divergências vs. `app_plan.md`

Se durante uma fase a implementação divergir do plano, atualize esta seção antes de mergear:

| Fase | Divergência | Motivo |
|------|-------------|--------|
| 0 | Alembic pinado `>=1.14,<1.16` | Auto-discovery de `pyproject.toml` no 1.16+ quebra o `alembic.ini` (ADR-003 em research.md). |
| 0 | Backend rodado no host em macOS via `pnpm dev:api` | `EDEADLK` no bind mount do Docker Desktop (ADR-008). |

---

## 6. Fluxo SDD por feature

Ordem canônica quando uma nova feature entrar (pós-MVP ou dentro de fase):

1. **Escrever o SP-XX na `spec.md`** (What/Why + Given/When/Then). PR isolado, título `spec:`.
2. **Atualizar `plan.md`** com mapeamento SP-XX → arquivos e ordem, se necessário. PR isolado, título `plan:`.
3. **Adicionar tarefas em `tasks.md`** com IDs T-XXX. PR isolado, título `tasks:`.
4. **Implementar** com PR `feat:` cobrindo os T-XXX, marcando os SP-XX no commit body.
5. **Fechar** o SP no changelog do spec (histórico de alterações).

Pular a etapa 1-3 e ir direto pra `feat:` **não é permitido** neste projeto. Emergências (bugs de produção) usam `fix:` + issue vinculada; ainda assim, se afetar comportamento observável, retroativamente descrever em `spec.md`.

---

## 7. Onde vive o quê

```
.specify/
  memory/
    constitution.md          # princípios inegociáveis (Art. I-X)
specs/
  001-mvp-registro-diario/
    spec.md                  # WHAT + porquê
    plan.md                  # HOW (este arquivo)
    tasks.md                 # tarefas atômicas
    research.md              # ADRs
app_plan.md                  # design técnico canônico (referenciado por plan.md)
docs/
  architecture.md            # índice curto para navegação
```

Nada de conteúdo em `spec.md` deve descrever HOW. Nada em `plan.md` deve descrever WHAT novo (só mapeia SPs existentes).

---

## Histórico

- **2026-07-15** — v1.0. Plano inicial. Fase 0 marcada concluída.
