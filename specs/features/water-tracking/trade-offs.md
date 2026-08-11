# Trade-offs — Registro de água pura

## Decisão 1 — Tabela dedicada `water_records` vs. tabela unificada de líquidos

### Contexto
SP-40..42 exigem registrar água pura; SP-50..52 bebidas calóricas. A Constituição Art. IV §12-14 fixa que água nunca tem kcal e bebida nunca conta como `water_ml` (INV-2/INV-3). Era necessário escolher entre uma tabela `liquid_records` com discriminator ou duas tabelas separadas.

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A. Tabelas separadas** `water_records` + `beverage_records` (escolhida) | INV-2 enforced por **ausência de coluna** — impossível registrar kcal em água por engano. Queries de `SUM(water_ml)` são triviais. Isolamento físico reflete a separação semântica. | Dois schemas para manter. Migração que adiciona coluna em `water_records` quebraria INV-2 se não revisada. |
| B. `liquid_records` com `kind IN ('water','beverage')` | Um schema só. | Risco de dupla contagem: nada impede `kind=water` com `kcal>0`. INV-2 viraria validação runtime (frágil). Recomputo precisaria filtrar por `kind`. |
| C. `water_records` com colunas kcal nullable | Reutiliza estrutura. | Mesmo problema que B — coluna existe, pode ser preenchida por bug. |

### Decisão Tomada
**Opção A** — tabelas separadas. INV-2 é inegociável (Const. Art. IV §12); a melhor forma de garantir é **não ter a coluna**. O custo de manter dois schemas é menor que o risco de dupla contagem.

### Consequências
- **Positivas**: `assert not hasattr(record, "kcal")` fecha a questão em teste. `DailyRecomputeService._aggregate_water` é um `SELECT SUM(volume_ml)` sem `WHERE kind=...`.
- **Negativas / dívida técnica**: correção/deleção genérica precisa de `TargetKind.WATER` vs `TargetKind.BEVERAGE` em `correction.py`/`deletion.py` — switches adicionais.

---

## Decisão 2 — Validação semântica via `_NON_WATER_HINTS` vs. confiar só no schema/prompt

### Contexto
O schema já bloqueia kcal em água (INV-2). Mas se a LLM classificar "café expresso" como `log_water`, o volume (50ml) ainda seria persistido em `water_records` e somado a `water_ml` — inflando hidratação sem violar INV-2 (não há kcal). SP-41 / Art. IV §14 exigem anti-dupla-contagem.

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A. Hints no `user_text_summary`** (escolhida) | Último gate antes do INSERT. Não depende da LLM cooperar. Custo O(n) barato. | Lista manual pode não cobrir tudo ("chalé", "agua com acucar"). Falsos positivos teóricos ("água com cheiro de café"). |
| B. Só confiar no prompt (`system_v2.md`) | Sem código extra. | LLM é não-determinística; prompt já diz para não fazer isso, mas falha. |
| C. Validar kcal no envelope water | Garantia absoluta. | `WaterIn` não tem campo kcal (por design) — não há o que validar. |

### Decisão Tomada
**Opção A** — hints no resumo. Defensivo, barato, e o `user_text_summary` é texto da própria LLM (já filtrado). `_strip_accents` torna o casamento robusto a acentos.

### Consequências
- **Positivas**: `test_sp41_rejects_water_intent_when_summary_hints_beverage` garante o fluxo. Adicionar bebida nova = adicionar string na lista.
- **Negativas**: lista `_NON_WATER_HINTS` é hardcoded — não cobre tudo. Se a LLM não mencionar a bebida no `user_text_summary`, o hint não casa. Risco residual baixo (a LLM geralmente resume o que interpretou).

---

## Decisão 3 — `is_estimate` hardcoded `False` vs. ler do envelope

### Contexto
SP-42 pede `is_estimate=true` para volumes estimados ("um copo" → 250ml). O `WaterIn` schema só tem `volume_ml` + `confidence` — não há campo `is_estimate`.

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A. `is_estimate=False` hardcoded** (escolhida hoje) | Simples. Sem campo extra no schema. | SP-42 não é totalmente atendido — o flag nunca fica `true` no banco. |
| B. Adicionar `is_estimate` ao `WaterIn` | SP-42 atendido; UI pode destacar estimativas. | LLM precisa emitir o campo; mais um ponto de falha. |

### Decisão Tomada
**Opção A** (estado atual). A estimativa de volume acontece **dentro da LLM** (ela converte "um copo" em `volume_ml=250`); o flag `is_estimate` não é propagado. SP-42 fica parcialmente atendido.

### Consequências
- **Positivas**: menos acoplamento com a LLM.
- **Negativas / dívida técnica**: SP-42 marcado como `should` — não bloqueia MVP, mas a UI não consegue distinguir "500ml explícitos" de "uma garrafinha estimada". Ver `<!-- TODO -->` em `acceptance-criteria.md` AC-004 e `architecture.md` decisão 4.

---

## Decisão 4 — Sem endpoint HTTP próprio para criar água

### Contexto
Toda criação de registro de negócio passa pelo chat (Const. Art. II). Mas correção e deleção têm endpoints REST (`PATCH /records/...`, `DELETE /records/...`).

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A. Só via chat** (escolhida) | Alinha com Art. II (LLM interpreta). Um caminho de criação. | Não há como criar água por API sem LLM (ex.: import de smartwatch). |
| B. Endpoint `POST /records/water` adicional | Permite integração programática. | Duplica lógica; viola Art. II se aceitar texto livre. |

### Decisão Tomada
**Opção A** — só via chat. MVP é single-user e não tem integrações externas de hidratação.

### Consequências
- **Positivas**: um pipeline só. `HydrationService` é chamado exclusivamente por `IntentDispatcher`.
- **Negativas**: se surgir integração com smart bottle / app de hidratação, será necessário adicionar endpoint — mas isso é pós-MVP.

---

## Dívida Técnica Conhecida

| Item | Impacto | Prioridade |
|---|---|---|
| `is_estimate` nunca persistido como `true` | SP-42 parcial; UI não destaca estimativas | Média |
| `_NON_WATER_HINTS` é lista hardcoded | Pode não cobrir todas as bebidas calóricas | Baixa |
| Sem métricas de taxa de `water_intent_rejected` | Difícil calibrar prompt | Baixa |

## Riscos Identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| LLM classifica bebida como `log_water` sem hint no summary | Média | Médio (hidratação inflada) | `_NON_WATER_HINTS` cobre casos comuns; monitorar via audit |
| Falso positivo de hint (ex.: "água com cheiro de café") | Baixa | Baixo | Fluxo `clarify` permite corrigir |
| Migração adiciona coluna kcal em `water_records` por engano | Baixa | Alto (quebra INV-2) | Code review + `assert not hasattr(record, "kcal")` no teste |
