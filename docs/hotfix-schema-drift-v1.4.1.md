# Hotfix v1.4.1 — Schema drift por deploy sem migrations

Resumo simplificado do que foi feito na branch `hotfix/deploy-schema-drift-hardening`
(PR [#58](https://github.com/felixstenian/my-registers/pull/58)) e por quê.

## O que aconteceu (o problema)

Em **2026-08-13**, todos os registros de **comida e bebida** no app de
produção pararam de funcionar: o chat respondia "Não consegui interpretar
sua mensagem agora. Pode reformular?". Só **água** continuava funcionando.

A causa não era a IA (LLM) — era **schema drift**: o banco da VPS estava
diferente do código.

- O Bloco 5 (feature "recuperação de itens sem catálogo") adicionou uma
  coluna `created_by` na tabela `nutrient_facts`, com uma migration
  (`0008`) que cria essa coluna.
- Essa migration **nunca foi aplicada no banco de produção** (o deploy
  manual fez `git pull && docker compose up -d` sem rodar o `bootstrap.sh`,
  que é quem aplica as migrations).
- O código novo faz `SELECT ... created_by` para registrar comida/bebida →
  coluna não existe → erro → cai no fallback genérico ("Não consegui
  interpretar").
- Água funcionava porque o registro de água **não consulta** essa tabela.

## O que foi feito (o fix)

**Passo 1 — Fix operacional (na VPS, não faz parte da branch):**
rodar `./scripts/bootstrap.sh .env.production`, que aplica as migrations
pendentes (0008, 0009, 0010) e re-popula o catálogo de alimentos.

**Passo 2 — Hardening (esta branch/PR):** garantir que isso nunca volte a
acontecer silenciosamente.

## Arquivos alterados nesta branch

| Arquivo | O que mudou | Por quê |
|--|--|--|
| `scripts/bootstrap.sh` | Passa a logar `alembic current` (revisão atual do schema) depois do `upgrade head` | Confirmar visualmente que o banco está no schema esperado a cada deploy |
| `docs/deploy.md` (§10.1) | Deixa explícito que migrations são obrigatórias em **todo** deploy, manual ou automático + documenta o failure mode de 13/08 | Deploy sem migrations quebra comida/bebida de forma silenciosa |
| `docs/deploy.md` (§10.2) | Checagem pós-deploy: `alembic current` + grep de `UndefinedColumnError` + "canário" (mandar mensagem de comida no chat) | Detectar schema drift logo após o deploy |
| `docs/deploy.md` (§14) | Nota de que todo deploy passa por `bootstrap.sh`; corrige referência a um doc que não existe (`docs/fase-10-setup.md`) | Evitar confusão e dar o caminho certo de deploy |
| `AGENTS.md` | Estado atual atualizado para v1.4.1 + incidente documentado | Registro histórico para quem for mexer no código depois (`docs/AGENTS.md` serve de memória do projeto) |
| `CHANGELOG.md` | Entrada do hotfix v1.4.1 | Registro da release |

## Como saber se voltou a acontecer

- **Canário rápido:** mandar "água" funciona e "comida/bebida" falha com
  "Não consegui interpretar" = **schema drift**, não problema de LLM.
- **No deploy:** conferir `alembic current` → deve sair `0010_propagate_action`.
- Grep nos logs da API por `UndefinedColumnError`.

## O que NÃO foi feito nesta branch

- Nenhum código de produto (Python/TS) — é só script de deploy + documentação.
- Os problemas separados já investigados (imagem 404 no chat e item ≈0 kcal)
  continuam como itens à parte.