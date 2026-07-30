# Critérios de Aceitação — Treino estruturado (Bloco 3)

> **Rastreabilidade**: SP-120..SP-127, INV-11/12/13, ADR-011 · Contratos: [`requirements.md`](./requirements.md), [`specifications.md`](./specifications.md). Status: **`documented-only`** — todos os critérios abaixo serão verificáveis quando o Bloco 3 for implementado; nenhum existe ainda no código.

## AC-001 — Iniciar sessão (SP-120, INV-11)

**Dado que** o usuário não tem `workout_sessions.status='active'`,
**Quando** a LLM detecta `intent=workout_start` (ex.: "iniciando treino de push"),
**Então** cria `workout_sessions` com `started_at=now()`, `status='active'`, `workout_type` classificado em enum canônico, `detected_name` livre.

**Dado que** já existe sessão ativa,
**Quando** nova `workout_start` é detectada,
**Então** a anterior é encerrada `end_reason='auto_new_session'`, `ended_at=now()`; assistant avisa e mostra resumo curto.

**Dado que** após a primeira sessão foi encerrada com `auto_new_session`,
**Quando** `consolidate_to_activity` roda (SP-126) no `day_log` da anterior,
**Então** `activity_record` consolidado entra no snapshot.

**Notas de validação:**
- INV-11 garante 1 ativa por user. Index `(user_id WHERE status='active')`.

---

## AC-002 — Adicionar exercício (SP-121)

**Dado que** há sessão ativa,
**Quando** LLM detecta `intent=workout_add_exercise` com `exercise_name`,
**Então** cria `workout_exercises` com `sequence_index = max+1` da sessão, `normalized_name` para lookup.

**Dado que** usuário nunca fez o exercício,
**Quando** `add_exercise` termina lookup,
**Então** `HistoryContext.first_time = True` e assistant responde "Primeira vez registrando esse exercício."

**Dado que** usuário fez o exercício em sessões anteriores,
**Quando** lookup retorna,
**Então** `HistoryContext.last_session_date`, `last_sets` (linha "peso × reps" por série) e `pr_weight_kg`, `pr_reps_at_pr`, `pr_date` são populados e exibidos na resposta.

**Dado que** a sessão ativa já tem outro exercício em andamento (A),
**Quando** novo exercício B é adicionado,
**Então** A é implicitamente encerrado (sem `ended_at`; só `sequence_index` difere).

---

## AC-003 — Registrar séries (SP-122, INV-12)

**Dado que** a sessão ativa tem ≥1 exercício,
**Quando** LLM detecta `intent=workout_log_set` com `weight_kg` + `reps`,
**Então** cria `workout_sets` no **último** exercício da sessão com `sequence_index = max+1`.

**Dado que** LLM parseia "3×8 60 kg",
**Quando** payload indica múltiples séries,
**Então** backend cria 3 sets iguais sem re-invocar LLM.

**Dado que** "20 kg da barra + 20 kg de cada lado",
**Quando** LLM parser executa,
**Então** `weight_kg = 60` (20 + 2×20) — backend só valida `> 0`.

**Dado que** "só a barra",
**Quando** payload é ambíguo sem default,
**Então** backend assume `DEFAULT_OLYMPIC_BAR_KG = 20`.

**Dado que** input ambíguo (peso/reps não claros),
**Quando** LLM emite `clarify`,
**Então** nenhum set é criado; assistant pede esclarecimento.

**Notas de validação:**
- INV-12 — Set sempre no último exercício; não existe "adicionar ao exercício X que não é último".

---

## AC-004 — Encerramento implícito de exercício (SP-123)

**Dado que** sessão ativa com exercício A (sequence_index=1),
**Quando** usuário adiciona B (sequence_index=2),
**Então** A é marcado implicitamente encerrado (nenhum `ended_at` em `workout_exercises`).

**Dado que** usuário tenta adicionar série a A,
**Quando** `log_set` executa,
**Então** a série é atribuída a B (último exercício da sessão ativa).

---

## AC-005 — Encerramento explícito de sessão (SP-124)

**Dado que** sessão ativa,
**Quando** LLM detecta `intent=workout_end`,
**Então** `workout_sessions.status='ended'`, `ended_at=now()`, `end_reason='user'`.

**Dado que** encerramento dispara SP-126,
**Quando** `consolidate_to_activity` roda,
**Então** `activity_record` é criado com `activity_type='strength'`, `calc_method='workout_session'`, `kcal_burned` calculado, `notes=JSON` com IDs de exercícios/séries.

**Quando** assistant devolve,
**Então** "Treino de push encerrado (58 min). 4 exercícios · 14 séries · ~380 kcal estimados." + tabela markdown por exercício (séries/peso/reps).

---

## AC-006 — Encerramento ao fechar dia (SP-125)

**Dado que** há sessão ativa ao executar `_handle_close_day` (SP-100),
**Quando** o processamento inicia,
**Então** `WorkoutService.end_session(end_reason='auto_close_day')` + `consolidate_to_activity` rodam **antes** do recompute do snapshot.

**Dado que** `activity_record` consolidado foi persistido,
**Quando** recompute executa,
**Então** snapshot inclui o `kcal_out` da sessão naquele dia; sem "reinserção" porque a ordem foi respeitada.

---

## AC-007 — Consolidação em activity_record (SP-126, INV-13)

**Dado que** encerramento dispara SP-126,
**Quando** backend calcula `duration_minutes` e `kcal_burned`,
**Então** `duration = (ended_at - started_at).total_seconds() / 60`; `kcal = MET × weight_kg × (duration_min / 60)` com MET fixo (`push`/`pull`/`upper` = 5.0; `legs`/`lower` = 6.0; `full_body` = 5.5; `cardio` = livre da feature `activity-cardio-logging`).

**Dado que** usuário sem `weight_kg` no perfil,
**Quando** `consolidate_to_activity` roda,
**Então** `activity_record.kcal_burned = NULL`, warning `weight_kg_required_for_kcal` no snapshot; sessão e séries persistem.

**Dado que** delete em `activity_record` com `calc_method='workout_session'` é chamado,
**Quando** operação executa,
**Então** `workout_sessions/exercises/sets` associados **não** são afetados (INV-13).

**Dado que** delete em `workout_sets`,
**Quando** executa,
**Então** `activity_record` já consolidado **não** muda (INV-13 — consistência via recompute manual, fora MVP).

---

## AC-008 — Histórico via chat (SP-127)

**Dado que** LLM detecta `intent=workout_history` com `exercise_name`,
**Quando** backend executa `WorkoutService.history`,
**Então** responde últimas 3 sessões (data + estrutura "peso × reps") + PR (mesmo formato do SP-121).

**Dado que** `exercise_name` ausente,
**Quando** intent processa,
**Então** LLM emite `clarify` pedindo qual exercício.

**Dado que** usuário nunca fez o exercício,
**Quando** lookup é vazio,
**Então** resposta neutra "Você ainda não registrou esse exercício."

---

## AC-009 — Tool schema + prompt regra 19 (T-B302)

**Dado que** prompt `system_v2.md` é atualizado,
**Quando** regra 19 está presente,
**Então** LLM passa a classificar `intent` em 5 novos valores (`workout_start`, `workout_add_exercise`, `workout_log_set`, `workout_end`, `workout_history`) e gerar payloads `_LenientBase` adequados.

**Dado que** `record_intent` tool schema é estendido,
**Quando** LLM manda output,
**Então** backend acepta via validação Pydantic; `text` livre é descartado (INV-1 / Art. II).

---

## AC-010 — Formatter markdown (T-B305)

**Dado que** handler `_handle_workout_*` processou com sucesso,
**Quando** `compose_workout_*` monta a resposta,
**Então** aparece em pt-BR com tabelas markdown 2-cols (consistência SP-118) + cabeçalho curto + adicionais (histórico/PR/resumo).

**Notas:**
- Aderência ao dialeto conhecido do `AssistantContent` (feature `assistant-message-rendering`).

---

## AC-011 — Frontend (T-B308, opcional)

**Dado que** `AssistantContent` renderiza mensagens `workout_*`,
**Quando** há peso PR,
**Então** exibe визу destacado em amber; série atual em verde.

**Dado que** usuário pede histórico no chat,
**Quando** formatter responde tabular,
**Então** `WorkoutHistoryCard` mostra sessões/PR de forma visual.

**Notas:**
- Backend em markdown já é usável; frontend visual é optional.

---

## Cenários de Borda

| Cenário | Comportamento Esperado |
|---|---|
| Tentar `add_exercise` sem sessão ativa | LLM emite `clarify` ("Inicie um treino primeiro"); nenhum exercício criado. |
| `log_set` sem exercício na sessão | Erro sem `clarify` — backend rejeita (`409` ou similar) com mensagem clara. |
| 2 sessões `start` simultâneas (race) | Index parcial `(user_id WHERE status='active')` garante 1 — segundo `start` auto-encerra a primeira. |
| `weight_kg`/`reps` zero (parser falhou) | Validação backend rejeita (`CHECK > 0`); nenhuma série criada; warning. |
| Sessão órfã (usuário nunca encerra, nunca fecha dia) | Aceito: `status` permanece `active`; lookup por `active` ainda acha. |
| Dia `closed` com sessão `active` | INV-5: dia fechado imutável. Sessão não pode ser encerrada ou consolidada (fora de SP-125 que já teria rodado no fechamento); aceito. |
| Delete de `workout_session` em cascade | `ON DELETE CASCADE` em `workout_exercises`/`sets`; mas `activity_records.workout_session_id` é FK sem cascade → referência dangling. MVP aceito (INV-13 — unlink). |
| Múltiplas séries "3x8 60kg" com notas divergentes | Backend cria N sets com mesma nota; notas divergentes requerem mensagens separadas. |
| Histórico fuzzy match sem match | `first_time = True` ou mensagem neutra. |
| `workout_type` ausente no payload | LLM `clarify` ("Qual tipo? push/pull/legs/...") |
| Hora inválida (`started_at > ended_at`) | Validation rejeita; sistema nunca grava inverted. |

## Critérios de Não-Funcionalidade

| Critério | Threshold |
|---|---|
| INV-11 — sessões ativas | ≤1 por usuário |
| INV-12 — atribuição de set | 100% no último exercício da sessão ativa |
| INV-13 — unlink bidirectional (`workout_*` ↔ `activity_record`) | Mutação em um não afeta o outro |
| INV-10 — audit coverage | 100% das mutações em `workout_*` gravam `audit_events` |
| `user_id` isolation | Zero queries sem `user_id` (Const. V §21) |
| Testes backend | Coverage ≥ 80% em `app/services/workout.py` |
| Latência `end_session` (consolidação) | < 200ms típico |
| Estado conversacional | 100% no DB; zero memória em LLM |
| Parsing pt-BR pela LLM (`weight_kg`/`reps`) | Backend só valida `>0` |
| MET fixo por `workout_type` (`push`/`pull`/`upper` = 5.0; `legs`/`lower` = 6.0; `full_body` = 5.5) | Hardcoded |