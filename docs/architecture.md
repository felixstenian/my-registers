# Arquitetura

Este diretório contém apenas notas curtas de navegação. A fonte de verdade é o conjunto **SDD (Spec-Driven Development)** abaixo.

## Fluxo SDD

O projeto segue Spec-Driven Development. A ordem é: **Constituição → Spec → Plan → Tasks → Código**. Alterar código sem passar antes pelos artefatos correspondentes viola o processo.

```
.specify/
  memory/
    constitution.md          # princípios inegociáveis (Art. I-X)

specs/
  001-mvp-registro-diario/
    spec.md                  # O QUÊ (SP-01..SP-113, invariantes)
    plan.md                  # COMO (mapeia SPs, ordem, gates)
    tasks.md                 # tarefas atômicas T-XXX por fase
    research.md              # ADRs (10 decisões arquiteturais)

app_plan.md                  # design técnico canônico (referenciado por plan.md)
```

## Índice rápido

- **Princípios que não posso violar:** [`../.specify/memory/constitution.md`](../.specify/memory/constitution.md).
- **O que o sistema faz (WHAT):** [`../specs/001-mvp-registro-diario/spec.md`](../specs/001-mvp-registro-diario/spec.md).
- **Como implementar (HOW):** [`../specs/001-mvp-registro-diario/plan.md`](../specs/001-mvp-registro-diario/plan.md) + [`../app_plan.md`](../app_plan.md).
- **O que fazer agora:** [`../specs/001-mvp-registro-diario/tasks.md`](../specs/001-mvp-registro-diario/tasks.md).
- **Por que fizemos assim:** [`../specs/001-mvp-registro-diario/research.md`](../specs/001-mvp-registro-diario/research.md).

## Regras de ouro do SDD neste projeto

1. **Nova feature começa pela `spec.md`.** PR isolado, título `spec:`. Nunca implemente sem SP-XX registrado.
2. **`plan.md` só mapeia SPs para arquivos e ordem.** Não invente comportamento aqui — se for novo comportamento, é `spec.md`.
3. **`tasks.md` é executável.** Uma tarefa = 1 PR ≤ 1 dia = commits fechando um ou mais T-XXX.
4. **Emenda constitucional é rara.** Requer PR próprio com prefixo `constitution:`, incremento de versão, cool-off 24h.
5. **ADR novo sempre que trade-off relevante:** append em `research.md`, nunca reescreva ADR aprovado (use `superseded by`).

Detalhes do processo: [`../specs/001-mvp-registro-diario/plan.md`](../specs/001-mvp-registro-diario/plan.md) §6.
