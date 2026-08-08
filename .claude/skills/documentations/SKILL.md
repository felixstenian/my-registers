# Skill: Feature Documentation Generator

## Objetivo

Analisar a documentação existente no projeto (READMEs, CHANGELOGs, arquivos de release, wikis, comentários de código) e as implementações reais, construir um **índice de features** e, para cada feature, gerar um conjunto completo de artefatos de especificação dentro de `specs/<feature-slug>/`.

---

## Localização

```
<project-root>/
└── .claude/
    └── skills/
        └── documentations/
            └── SKILL.md   ← este arquivo
```

---

## Artefatos gerados por feature

Para cada feature identificada, a skill cria a pasta `specs/<feature-slug>/` com os seguintes arquivos:

| Arquivo | Conteúdo |
|---|---|
| `requirements.md` | Requisitos funcionais e não funcionais |
| `specifications.md` | Especificações técnicas detalhadas |
| `user-stories.md` | Histórias de usuário (formato padrão) |
| `acceptance-criteria.md` | Critérios de aceitação (Given/When/Then) |
| `test-cases.md` | Casos de teste (unitários, integração, E2E) |
| `architecture.md` | Design de arquitetura e diagramas em Mermaid |
| `trade-offs.md` | Trade-offs, decisões de design e alternativas |

Adicionalmente, na raiz de `specs/` é gerado o arquivo de índice:

| Arquivo | Conteúdo |
|---|---|
| `specs/INDEX.md` | Índice geral de todas as features com links |

---

## Protocolo de Execução

### Fase 1 — Descoberta de documentação

Varrer o projeto em busca de fontes de conhecimento na seguinte ordem de prioridade:

1. **Arquivos de release/changelog**
   - `CHANGELOG.md`, `CHANGELOG.rst`, `CHANGELOG.txt`
   - `RELEASES.md`, `RELEASE_NOTES.md`
   - `HISTORY.md`, `NEWS.md`
   - Tags e releases do repositório Git (`git tag -l`, `git log --oneline --decorate`)

2. **Documentação geral**
   - `README.md` (e variantes: `README.rst`, `README.txt`)
   - `docs/` — percorrer recursivamente todos os `.md`, `.rst`, `.txt`, `.html`
   - `wiki/` se existir
   - `ADR/` (Architecture Decision Records) se existir

3. **Comentários e anotações no código**
   - Docstrings em funções/classes públicas
   - Comentários `TODO`, `FIXME`, `NOTE`, `FEATURE` no código-fonte
   - Anotações JSDoc / TSDoc / Swagger / OpenAPI

4. **Configurações e manifests**
   - `package.json` → campo `description`, `scripts`, dependências
   - `pyproject.toml`, `setup.py`, `Cargo.toml`, `go.mod`
   - `openapi.yaml`, `swagger.json`
   - `.env.example` — variáveis de ambiente revelam capacidades

### Fase 2 — Descoberta de implementações

Mapear o código-fonte para identificar módulos, serviços e funcionalidades reais:

1. Listar a estrutura de diretórios de nível superior (`src/`, `lib/`, `app/`, `packages/`, `services/`, `modules/`, `features/`)
2. Identificar rotas de API (Express, FastAPI, Rails, etc.)
3. Identificar componentes de UI principais (React, Vue, Angular, etc.)
4. Identificar entidades/modelos de dados (schemas, migrations, ORM models)
5. Identificar workers, jobs, cron tasks
6. Identificar integrações externas (SDKs, webhooks, third-party APIs)

### Fase 3 — Construção do Índice de Features

Cruzar a documentação encontrada com as implementações reais para:

1. **Nomear cada feature** de forma clara e no vocabulário do domínio
2. **Classificar** cada feature por categoria (ex: Auth, Billing, Notifications, Core, Integrations, Admin, etc.)
3. **Determinar status** de cada feature:
   - `stable` — documentada e implementada
   - `partial` — implementada mas sem documentação completa
   - `documented-only` — documentada mas sem implementação clara
   - `deprecated` — marcada como descontinuada
4. **Priorizar** features para documentação (começar pelas `stable` e `partial`)

Gerar `specs/INDEX.md` com o índice completo antes de gerar os artefatos individuais.

### Fase 4 — Geração dos Artefatos por Feature

Para cada feature do índice, criar `specs/<feature-slug>/` e gerar os 7 arquivos abaixo:

---

#### `requirements.md` — Requisitos

```markdown
# Requisitos — <Nome da Feature>

## Visão Geral
<Descrição concisa da feature em 2–3 frases>

## Requisitos Funcionais
| ID | Requisito | Prioridade |
|---|---|---|
| RF-001 | ... | Must Have |
| RF-002 | ... | Should Have |
| RF-003 | ... | Could Have |

## Requisitos Não Funcionais
| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | ... | Performance |
| RNF-002 | ... | Segurança |
| RNF-003 | ... | Escalabilidade |

## Restrições e Premissas
- ...

## Dependências
- Depende de: <outras features ou sistemas>
- Requerido por: <features que dependem desta>
```

---

#### `specifications.md` — Especificações Técnicas

```markdown
# Especificações Técnicas — <Nome da Feature>

## Escopo Técnico
<Descrição dos limites técnicos da feature>

## Endpoints / Interface
<Documentar cada endpoint, método, parâmetros, request/response — usar blocos de código>

## Modelo de Dados
<Esquema das entidades envolvidas — tabelas, campos, tipos, relações>

## Fluxo de Dados
<Descrever como os dados fluem entre componentes>

## Regras de Negócio
1. ...
2. ...

## Configurações e Variáveis de Ambiente
| Variável | Descrição | Padrão | Obrigatória |
|---|---|---|---|
| ... | ... | ... | Sim/Não |

## Referências de Implementação
- Arquivos principais: `src/...`
- Módulos relacionados: `...`
```

---

#### `user-stories.md` — Histórias de Usuário

```markdown
# Histórias de Usuário — <Nome da Feature>

## Personas
- **<Persona 1>**: <descrição breve do perfil>
- **<Persona 2>**: <descrição breve do perfil>

---

### US-001 — <Título da História>
**Como** <persona>,  
**Quero** <ação ou capacidade>,  
**Para que** <benefício ou objetivo>.

**Critérios de Aceitação resumidos:**
- [ ] ...

**Notas:**
- ...

---

### US-002 — <Título da História>
...
```

---

#### `acceptance-criteria.md` — Critérios de Aceitação

```markdown
# Critérios de Aceitação — <Nome da Feature>

## AC-001 — <Título do Critério>
**Dado que** <contexto/pré-condição>,  
**Quando** <ação executada>,  
**Então** <resultado esperado>.

**Notas de validação:**
- ...

---

## AC-002 — <Título do Critério>
...

---

## Cenários de Borda
| Cenário | Comportamento Esperado |
|---|---|
| ... | ... |

## Critérios de Não-Funcionalidade
| Critério | Threshold |
|---|---|
| Tempo de resposta | < 200ms |
| ... | ... |
```

---

#### `test-cases.md` — Casos de Teste

```markdown
# Casos de Teste — <Nome da Feature>

## Cobertura Alvo
- Unitários: <módulos/funções críticas>
- Integração: <fluxos entre serviços>
- E2E: <jornadas de usuário>

---

## Testes Unitários

### TC-U-001 — <Descrição>
- **Módulo**: `src/...`
- **Função/Método**: `...`
- **Entrada**: `...`
- **Saída esperada**: `...`
- **Tipo**: Happy path / Edge case / Error case

---

## Testes de Integração

### TC-I-001 — <Descrição>
- **Fluxo**: <serviço A> → <serviço B>
- **Pré-condições**: ...
- **Passos**: ...
- **Resultado esperado**: ...

---

## Testes E2E

### TC-E-001 — <Descrição>
- **Persona**: <persona que executa>
- **Jornada**: ...
- **Passos**: ...
- **Resultado esperado**: ...

---

## Testes de Regressão
<Listar casos críticos que devem ser mantidos a cada release>
```

---

#### `architecture.md` — Design de Arquitetura

```markdown
# Arquitetura — <Nome da Feature>

## Visão Geral
<Descrição de alto nível da solução arquitetural>

## Componentes Envolvidos
| Componente | Responsabilidade | Tecnologia |
|---|---|---|
| ... | ... | ... |

## Diagrama de Contexto
```mermaid
graph TD
    A[Usuário] --> B[Frontend]
    B --> C[API]
    C --> D[Banco de Dados]
```

## Diagrama de Sequência
```mermaid
sequenceDiagram
    actor User
    User->>+API: request
    API->>+DB: query
    DB-->>-API: result
    API-->>-User: response
```

## Decisões de Design
1. **<Decisão>**: <Justificativa>
2. ...

## Padrões Utilizados
- Design Pattern: ...
- Convenções: ...

## Segurança e Autenticação
<Descrever mecanismos de segurança aplicados à feature>

## Observabilidade
- Logs: ...
- Métricas: ...
- Traces: ...
```

---

#### `trade-offs.md` — Trade-offs e Decisões

```markdown
# Trade-offs — <Nome da Feature>

## Decisão 1 — <Título>

### Contexto
<Qual problema estava sendo resolvido e por quê uma decisão era necessária>

### Opções Consideradas
| Opção | Prós | Contras |
|---|---|---|
| Opção A (escolhida) | ... | ... |
| Opção B | ... | ... |
| Opção C | ... | ... |

### Decisão Tomada
**Opção A** — <Justificativa da escolha>

### Consequências
- Positivas: ...
- Negativas / dívida técnica: ...

---

## Decisão 2 — <Título>
...

---

## Dívida Técnica Conhecida
| Item | Impacto | Prioridade |
|---|---|---|
| ... | ... | Alta/Média/Baixa |

## Riscos Identificados
| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| ... | Alta/Média/Baixa | Alto/Médio/Baixo | ... |
```

---

### Fase 5 — Geração do INDEX.md

Gerar `specs/INDEX.md` com estrutura:

```markdown
# Índice de Features — <Nome do Projeto>

> Gerado em: <data>  
> Total de features: <N>

## Categorias

### <Categoria 1>
| Feature | Status | Pasta |
|---|---|---|
| [<Nome>](.<slug>/requirements.md) | stable | `specs/<slug>/` |

### <Categoria 2>
...

## Features por Status

### ✅ Stable
- [<Nome>](./<slug>/requirements.md)

### 🔶 Partial (implementadas, documentação incompleta)
- ...

### 📄 Documented Only (sem implementação clara)
- ...

### ❌ Deprecated
- ...
```

---

## Regras e Boas Práticas

### Sobre o conteúdo

- **Baseie-se somente em evidências**: nunca invente comportamentos. Se a documentação for incompleta, marque com `<!-- TODO: verificar implementação em src/... -->`.
- **Prefira vocabulário do domínio**: use os termos que aparecem no código e na documentação, não traduções livres.
- **Mantenha rastreabilidade**: sempre referencie o arquivo de origem (`docs/release-v1.2.md`, `src/auth/login.ts`) nos artefatos.
- **Evite duplicação**: se duas features compartilham lógica, documente na mais abrangente e faça referência cruzada.

### Sobre os slugs de pasta

- Use `kebab-case` minúsculo: `user-authentication`, `billing-subscriptions`, `email-notifications`
- Sem espaços, acentos ou caracteres especiais
- Máximo 40 caracteres

### Sobre Mermaid

- Use sempre blocos de código com linguagem `mermaid` para diagramas
- Prefira `graph TD` para fluxos e `sequenceDiagram` para interações
- Mantenha os diagramas simples: máximo 10–12 nós por diagrama

### Sobre completude

- Se a implementação existe mas a documentação é ausente, inferir comportamento a partir do código e marcar com `[Inferido do código]`
- Se a documentação existe mas a implementação não foi localizada, marcar com `[Implementação não localizada]`
- Nunca deixar uma seção completamente vazia — ao menos escreva `> Não documentado. Investigação necessária.`

---

## Exemplo de Estrutura Final

```
specs/
├── INDEX.md
├── user-authentication/
│   ├── requirements.md
│   ├── specifications.md
│   ├── user-stories.md
│   ├── acceptance-criteria.md
│   ├── test-cases.md
│   ├── architecture.md
│   └── trade-offs.md
├── billing-subscriptions/
│   └── ...
└── email-notifications/
    └── ...
```
