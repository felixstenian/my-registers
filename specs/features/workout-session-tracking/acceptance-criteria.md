# Critérios de Aceitação — Módulo de Treino (Workout Module)

> **Rastreabilidade**: SP-120..SP-127, INV-15/16/17 (núcleo) · SP-170..179 (proposto) · Contratos: [`requirements.md`](./requirements.md), [`specifications.md`](./specifications.md). Status: **`documented-only`** — núcleo `[Implementação não localizada]`; módulo `[Proposta]`. Nenhum critério existe ainda no código.

## AC-001 — Iniciar sessão livre (SP-120, INV-15)

**Dado que** o usuário não tem `workout_sessions.status='active'`,
**Quando** a LLM detecta `intent=workout_start` (ex.: "iniciando treino de push"),
**Então** cria `workout_sessions` com `started_at=now()`, `status='active'`, `workout_type` classificado, `detected_name` livre.

**Dado que** já existe sessão ativa,
**Quando** nova `workout_start` é detectada,
**Então** a anterior é encerrada `end_reason='auto_new_session'`; assistant avisa e mostra resumo curto.

**Notas de validação:**
- INV-15 garante 1 ativa por user. Index parcial `(user_id WHERE status='active')`.

---

## AC-002 — Fluxo guiado "Iniciar treino" (RF-020 → SP-178)

**Dado que** há templates com `active=true`,
**Quando** o usuário toca "Iniciar treino" no chat de treino,
**Então** o backend lista os templates como botões selecionáveis.

**Dado que** o usuário escolhe um template,
**Quando** a sessão inicia com `template_id`,
**Então** o chat lista **todos os exercícios** do template como botões.

**Dado que** o usuário escolhe um exercício,
**Quando** `add_exercise` roda,
**Então** o chat busca a última realização daquele exercício e lista **cargas por série e repetições** realizadas.

**Dado que** o usuário envia a carga/reps de uma série,
**Quando** `log_set` roda,
**Então** a série é registrada; a partir da **primeira** série o chat confirma o registro, recapitula o último treino realizado e exibe botão **"Ir para o próximo exercício"**.

**Dado que** o usuário toca "Ir para o próximo exercício",
**Quando** o fluxo repete,
**Então** o chat lista os exercícios novamente e a sequência é repetida.

**Notas de validação:**
- INV-16: `log_set` sempre no último exercício.

---

## AC-003 — Cadastrar treino por texto (RF-015 → SP-171)

**Dado que** o usuário toca "Cadastrar treino",
**Quando** o processamento inicia,
**Então** o chat envia mensagem amigável com **template de exemplo**: tipo de treino (ex. `Musculação`/`Força`/`LPO`), agrupamento muscular para musculação (ex. `Peito + ombro + triceps`), séries e repetições.

**Dado que** o usuário envia o texto do treino,
**Quando** a LLM detecta `intent=workout_register` com `WorkoutTemplateIn`,
**Então** cria `workout_templates` com `created_at=now()` (data de cadastro), `active=true`, exercícios-alvo (nome + target sets/reps).

**Dado que** o usuário envia uma imagem junto ao texto,
**Quando** a LLM extrai do texto e da imagem,
**Então** preenche título/atividade/intensidade/kcal e cadastra o template.

---

## AC-004 — Ativar/inativar treino (RF-016 → SP-172, INV-19)

**Dado que** há um `workout_templates` cadastrado,
**Quando** o usuário desativa na listagem `/workouts`,
**Então** `active=false`; o treino some da aba *Ativos* e aparece na aba *Inativos*; **não** aparece no seletor do fluxo guiado.

**Dado que** o usuário reativa,
**Quando** `active=true`,
**Então** volta à aba *Ativos* e ao seletor.

**Dado que** há sessões finalizadas de um template que foi inativado,
**Quando** o histórico é consultado,
**Então** as sessões continuam visíveis (INV-19/20 — inativar não apaga histórico).

---

## AC-005 — Histórico paginado (RF-017 → SP-177)

**Dado que** há várias sessões finalizadas,
**Quando** `GET /workouts/history?page=N&page_size=20` roda,
**Então** retorna página com nome da atividade, data, hora (se houver), kcal gastas e, para musculação/variantes com carga, cargas/séries/repetições por exercício.

**Dado que** o usuário navega entre páginas,
**Quando** a paginação é usada,
**Então** não há duplicação nem omissão de itens (ordenação determinística).

---

## AC-006 — Chat de treino dedicado (RF-018/019 → SP-173)

**Dado que** o usuário abre `/workouts/chat`,
**Quando** a tela renderiza,
**Então** segue **exatamente o padrão do chat de alimentação** (composer, upload de mídia, `AssistantContent`, polling) e o **header exibe as atividades realizadas no dia e as calorias gastas**.

**Dado que** não há treino ativo,
**Quando** o header renderiza,
**Então** exibe os botões **"Cadastrar treino"** e **"Iniciar treino"** (no lugar de "Encerrar dia").

**Dado que** um treino foi iniciado,
**Quando** o header renderiza,
**Então** o botão da posição de "Iniciar treino" vira **"Finalizar treino"** (mesmo local).

---

## AC-007 — Registro por imagem (RF-022 → SP-174, INV-21)

**Dado que** o usuário anexa uma imagem de atividade realizada no chat de treino,
**Quando** a mensagem processa,
**Então** a LLM extrai da imagem: **título**, **atividade**, **intensidade** (se houver) e **calorias gastas durante a atividade** (se houver).

**Dado que** a kcal aparece na imagem (ex. esteira/pulso),
**Quando** `kcal_burned_reported` é extraído,
**Então** ela vira a fonte de kcal da sessão (INV-21) e entra no snapshot.

**Dado que** a imagem representa um treino completo reutilizável,
**Quando** a LLM decide,
**Então** cria `workout_templates` em vez de sessão livre.

---

## AC-008 — Edição de peso/séries/kcal (RF-023 → SP-175, INV-17/20)

**Dado que** o usuário corrige por chat,
**Quando** `intent=workout_correct` (ou `workout_correct_set`) roda,
**Então** atualiza `workout_sets` (`weight_kg`/`reps`/`notes`) ou `workout_sessions.kcal_burned_reported`, com `audit_events` (INV-10).

**Dado que** o usuário corrige pelo `/day`,
**Quando** a seção de treinos é editada inline,
**Então** PATCH `/records/workout-sets/{id}` e/ou PATCH `/records/workout-sessions/{id}` atualizam e recomputam o snapshot.

**Dado que** a sessão está encerrada,
**Quando** uma edição ocorre,
**Então** o `activity_record` consolidado é **reconsolidado** (INV-20) — `/day` fica consistente.

**Dado que** o dia está fechado,
**Quando** qualquer edição é tentada,
**Então** 409 `conflict_closed_day` (Const. Art. VIII).

---

## AC-009 — Cronômetro e tempo registrado (RF-021 → SP-179)

**Dado que** o usuário inicia um treino,
**Quando** a sessão fica `active`,
**Então** um cronômetro é exibido na tela.

**Dado que** o usuário finaliza (botão "Finalizar treino" ou texto),
**Quando** `end_session(end_reason='user')` roda,
**Então** o cronômetro **para** e `duration_minutes = ended_at - started_at` é persistido.

**Dado que** o dia é fechado com treino ativo (SP-125),
**Quando** `auto_close_day` roda,
**Então** cronômetro para, sessão encerra e o tempo é registrado.

---

## AC-010 — Adicionar exercício + histórico contextual (SP-121)

**Dado que** há sessão ativa,
**Quando** LLM detecta `intent=workout_add_exercise` com `exercise_name`,
**Então** cria `workout_exercises` com `sequence_index=max+1`, `normalized_name`; `HistoryContext` populado.

**Dado que** usuário nunca fez o exercício,
**Quando** lookup histórico retorna vazio,
**Então** `first_time=True` → "Primeira vez registrando esse exercício."

**Dado que** usuário fez em sessões anteriores,
**Quando** lookup retorna,
**Então** mostra última sessão + PR (peso/reps/data).

---

## AC-011 — Registrar séries (SP-122, INV-16)

**Dado que** a sessão ativa tem ≥1 exercício,
**Quando** LLM detecta `intent=workout_log_set`,
**Então** cria `workout_sets` no **último** exercício com `sequence_index=max+1`.

**Dado que** "3×8 60 kg",
**Quando** payload indica múltiplas séries,
**Então** backend cria 3 sets iguais sem re-invocar LLM.

**Dado que** "só a barra",
**Quando** payload é ambíguo sem default,
**Então** backend assume `DEFAULT_OLYMPIC_BAR_KG=20`.

**Dado que** input ambíguo,
**Quando** LLM emite `clarify`,
**Então** nenhum set é criado.

---

## AC-012 — Encerramento explícito e consolidação (SP-124/126, INV-17)

**Dado que** sessão ativa,
**Quando** `intent=workout_end` ("finalizar treino"),
**Então** `status='ended'`, `ended_at=now()`, `end_reason='user'`; `consolidate_to_activity` roda.

**Dado que** kcal reportada existe,
**Quando** consolidação calcula,
**Então** usa `kcal_burned_reported` (INV-21), `met_value=NULL`, `calc_method='workout_session'`.

**Dado que** sem kcal reportada,
**Quando** consolidação calcula,
**Então** usa MET fixo × `weight_kg` (perfil) × horas; sem peso → `kcal_burned=NULL` + warning.

**Dado que** delete em `activity_record` com `calc_method='workout_session'`,
**Quando** operação executa,
**Então** `workout_*` associados não são afetados (INV-17).

---

## AC-013 — Encerramento ao fechar dia (SP-125)

**Dado que** há sessão ativa ao executar `_handle_close_day`,
**Quando** o processamento inicia,
**Então** `end_session(end_reason='auto_close_day')` + `consolidate_to_activity` rodam **antes** do recompute; snapshot inclui o `kcal_out`.

---

## AC-014 — Histórico via chat (SP-127)

**Dado que** LLM detecta `intent=workout_history` com `exercise_name`,
**Quando** backend executa `history`,
**Então** responde últimas 3 sessões + PR (sem criar registro).

**Dado que** `exercise_name` ausente,
**Quando** intent processa,
**Então** LLM emite `clarify`.

---

## AC-015 — Tool schema + prompt (T-B302 + módulo)

**Dado que** prompt `system_v2.md` é atualizado,
**Quando** regra 19 (núcleo) + regras de template/imagem (módulo) estão presentes,
**Então** LLM classifica intents de treino e gera payloads `_LenientBase` corretos; texto livre é descartado (INV-1/Art. II).

---

## AC-016 — Seção de treinos no `/day` (RF-024 → SP-176)

**Dado que** há treinos realizados no dia,
**Quando** `/day` renderiza,
**Então** exibe nova seção "Treinos" com nome, duração e kcal gastas (reportadas ou consolidadas); para força, exercícios com cargas/séries/reps.

**Dado que** não há treinos no dia,
**Quando** `/day` renderiza,
**Então** a seção não aparece (padrão `MealSection`/`ActivitySection`).

---

## Cenários de Borda

| Cenário | Comportamento Esperado |
|---|---|
| Tentar `add_exercise` sem sessão ativa | LLM emite `clarify` ("Inicie um treino primeiro"); nada criado. |
| `log_set` sem exercício na sessão | Backend rejeita com mensagem clara; 409/erro; nenhum set criado. |
| 2 `start` simultâneos (race) | Index parcial `(user_id WHERE status='active')` garante 1; segundo auto-encerra. |
| `weight_kg`/`reps` zero | Validação `CHECK > 0` rejeita; warning. |
| Sessão órfã (usuário nunca encerra, dia nunca fecha) | `status='active'` persiste; lookup por `active` ainda acha. |
| Dia `closed` com sessão `active` | INV-5: imutável; sessão não pode mutar (SP-125 já teria rodado). |
| Delete de `workout_session` em cascade | `CASCADE` em exercises/sets; `activity_records.workout_session_id` sem cascade → dangling (MVP aceito, INV-17). |
| Múltiplas séries "3x8 60kg" com notas divergentes | N sets com mesma nota; notas divergentes requerem mensagens separadas. |
| Histórico fuzzy sem match | `first_time=True`. |
| Template sem exercícios-alvo | `list_exercises` retorna vazio; chat orienta cadastrar exercícios. |
| Template `active=false` tentado no fluxo guiado | Backend exclui da lista (INV-19); nunca inicia. |
| Imagem sem kcal visível | `kcal_burned_reported=None` → MET/sem kcal; warning se perfil sem peso. |
| Imagem corrompida/oversize | `POST /media` valida (Pillow probe, ≤8 MB); erro amigável. |
| Edição de set numa sessão encerrada sem template | Reconsolidação normal (INV-20) sem referência de template. |
| Histórico de template inativado | Sessões permanecem (INV-19/20). |
| Hora inválida (`started_at > ended_at`) | Validação rejeita; nunca grava invertido. |

## Critérios de Não-Funcionalidade

| Critério | Threshold |
|---|---|
| INV-15 — sessões ativas | ≤1 por usuário |
| INV-16 — atribuição de set | 100% no último exercício da sessão ativa |
| INV-17 — unlink bidirectional | Mutação em um não afeta o outro |
| INV-18/19/20 — templates | Queries com `user_id`; `active=false` fora do fluxo; template inativo não apaga histórico; edição reconsolida sessão encerrada |
| INV-21 — kcal | `kcal_burned_reported` (usuário/texto/imagem) é fonte; senão MET backend |
| INV-10 — audit coverage | 100% das mutações de `workout_*` e `workout_templates` |
| `user_id` isolation | Zero queries sem `user_id` (Const. V §21) |
| Testes backend | Coverage ≥ 80% em `app/services/workout.py` |
| Latência `end_session` (consolidação) | < 200ms típico |
| Estado conversacional | 100% no DB; zero memória em LLM |
| Parsing pt-BR (`weight_kg`/`reps`) | Backend só valida `>0` |
| Paginação determinística | Sem duplicar/omitir entre páginas |
| Cronômetro | Para apenas quando `status='ended'` (botão ou `auto_close_day`/`auto_new_session`)