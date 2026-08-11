# Trade-offs — Registro de atividade física (cardio)

## Decisão 1 — Tabela MET em memória vs. tabela no Postgres

### Contexto
SP-60 exige `kcal = MET × weight_kg × (duration/60)`. É necessário uma fonte de valores MET por `activity_type` × `intensity`.

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A. `_MET_TABLE` em memória** (dict Python) (escolhida) | Lookup O(1) sem I/O. Testes triviais. Mudança = commit de código. | Mudar MET requer deploy (não é dado de usuário). |
| B. Tabela `met_values` no Postgres | Editável sem deploy. | Lookup com I/O. Migração para cada ajuste. Overhead para 28 entradas. |

### Decisão Tomada
**Opção A** — dict em memória. 28 entradas (7 tipos × 4 intensidades) não justificam tabela no Postgres. Mudança de MET é rara e requer revisão de qualquer forma.

### Consequências
- **Positivas**: `ActivityCalculator.compute` é pure function — determinismo absoluto, cobertura 90% fácil.
- **Negativas**: adicionar novo tipo de atividade = commit de código + teste.

---

## Decisão 2 — `kcal_burned_reported` autoritativo vs. sempre calcular MET

### Contexto
Felix às vezes envia print de smartwatch com kcal já calculado. Esse valor é mais preciso que a estimativa MET genérica.

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A. `reported` é fonte de verdade** (`calc_method='user_manual'`) (escolhida) | Respeita dispositivo. Não requer peso. Const. Art. III §10 (materializado, sem recompute). | Se a LLM extrair errado do print, kcal errado persiste. |
| B. Ignorar `reported`, sempre MET | Consistência. | Perde precisão do dispositivo. Peso obrigatório sempre. |
| C. Validar `reported` contra MET (tolerância) | Híbrido. | Complexo; qual tolerância? Dispositivos variam. |

### Decisão Tomada
**Opção A** — `reported` autoritativo. `Field(ge=0, le=10000)` no schema limita absurdos. `met_value` ainda gravado para contexto.

### Consequências
- **Positivas**: UX melhor para usuários de smartwatch. Peso não bloqueia.
- **Negativas / dívida técnica**: se LLM extrair kcal errado da foto, não há gate. Confiamos no prompt + `le=10000`.

---

## Decisão 3 — Canonicalização de `activity_type` no backend vs. só no prompt

### Contexto
A LLM às vezes devolve "corrida" (pt-BR) mesmo com prompt em inglês. O `_MET_TABLE` usa chaves canônicas (`cardio_run`).

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A. `_ACTIVITY_TYPE_ALIASES` + `_canonicalize_activity_type`** (escolhida) | Robusto a pt-BR/EN. NFKD remove acentos. | Lista manual pode não cobrir tudo. |
| B. Só prompt | Sem código extra. | LLM é não-determinística; quebra `_MET_TABLE` lookup. |
| C. Aceitar qualquer string e fazer fuzzy match | Flexível. | Complexo; falsos positivos. |

### Decisão Tomada
**Opção A** — aliases em código. 49 mapeamentos cobrem casos comuns. Se não bater, retorna o valor original (lookup direto pode ainda funcionar).

### Consequências
- **Positivas**: `test_canonicalize` fecha casos comuns. Adicionar alias = 1 linha.
- **Negativas**: atividade muito fora do padrão ("parkour") não canonicaliza — cai em `unknown_activity_or_intensity` com `kcal=0`.

---

## Decisão 4 — `WeightRequired` como exceção própria vs. `ValidationAppError`

### Contexto
SP-61: se `users.weight_kg is None` e sem `kcal_burned_reported`, nada persiste. É uma condição de negócio (perfil incompleto), não erro de validação de envelope.

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A. `WeightRequired(Exception)` própria** (escolhida) | Categoria clara. `MessageProcessor` trata diferentemente (clarify pede peso). | Mais uma classe de exceção. |
| B. `ValidationAppError(code="weight_required")` | Menos classes. | Mistura validação de envelope com condição de perfil. |

### Decisão Tomada
**Opção A** — exceção própria. Semântica diferente: validação de envelope é erro de parsing; peso faltante é dado de perfil.

### Consequências
- **Positivas**: `MessageProcessor` pode ter handler específico.
- **Negativas**: `WeightRequired` não herda de `AppError` — não é serializada pelo handler global. Tratada só no pipeline de chat.

---

## Decisão 5 — SP-62: `strength` + `unknown` → `moderate` no cálculo, `unknown` no registro

### Contexto
Musculação sem intensidade é comum. SP-62 pede default `moderate` (met=5.0).

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A. Default `moderate` no cálculo, preservar `unknown` no registro** (escolhida) | Auditoria honesta (usuário não informou). Cálculo razoável. | `record.intensity != intensity_for_calc` — pode confundir. |
| B. Sobrescrever `intensity='moderate'` no registro | Consistência. | Perde informação — não sabemos se usuário informou ou foi default. |
| C. Bloquear até informar intensidade | Precisão. | Fricção. |

### Decisão Tomada
**Opção A** — dual: cálculo usa `moderate`, registro guarda `unknown`. `test_sp62` valida ambos.

### Consequências
- **Positivas**: auditoria mostra quando intensidade foi inferida.
- **Negativas**: se alguém ler `record.intensity` para recompute, precisa saber que `unknown` implica `moderate` para strength — lógica em `correction.py` replica.

---

## Decisão 6 — SP-63: estimar duração por velocidade média vs. pedir duração

### Contexto
"Caminhei 4 km" sem cronômetro é comum. SP-63 pede estimativa.

### Opções Consideradas

| Opção | Prós | Contras |
|---|---|---|
| **A. `_SPEED_KMH` por tipo** (escolhida) | Resolve caso comum. | Estimativa grosseira (5 km/h para caminhada é média, não individual). |
| B. Pedir duração sempre | Precisão. | Fricção. |
| C. Estimativa por histórico do usuário | Personalizada. | Complexo; MVP é single-user sem histórico suficiente. |

### Decisão Tomada
**Opção A** — velocidades médias fixas. Simples, resolve o caso comum.

### Consequências
- **Positivas**: "caminhei 4 km" → 48 min automaticamente.
- **Negativas**: velocidade individual varia; estimativa pode ser 20-30% off. `kcal_burned` segue a imprecisão.

---

## Dívida Técnica Conhecida

| Item | Impacto | Prioridade |
|---|---|---|
| `_MET_TABLE` não cobre todas as atividades (ex.: surf, escalada técnica) | `kcal=0` + warning para atividades não mapeadas | Média |
| `_SPEED_KMH` é fixo, não personalizado | Estimativa de duração grosseira | Baixa |
| Sem `needs_confirmation` para activity | kcal errado não é destacado para revisão | Baixa |
| `WeightRequired` não herda de `AppError` | Não serializada por handler global; só funciona no pipeline de chat | Baixa |

## Riscos Identificados

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| LLM extrai `kcal_burned_reported` errado da foto | Média | Médio (kcal errado persiste) | `Field(le=10000)` + prompt orienta |
| Atividade não mapeada em `_MET_TABLE` | Média | Baixo (`kcal=0` + warning, não bloqueia) | Adicionar tipos conforme demanda |
| `weight_kg` desatualizado no perfil | Média | Médio (kcal MET errado) | UI de perfil; usuário pode atualizar |
| Mudança de `_MET_TABLE` sem teste | Baixa | Médio | Code review + `test_canonicalize` |
