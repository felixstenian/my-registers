# Próximos passos — my-registers

Snapshot da fila de trabalho pós-release v1.2 (2026-07-27). Organizado por retorno
esperado. Fonte de verdade das tarefas continua em
`specs/001-mvp-registro-diario/tasks.md`; este arquivo é o resumo executivo.

## Nível 1 — Fechar cauda funcional do MVP

Backend pronto e testado, falta interface. Sem essas telas o usuário paga VPS +
Anthropic pra usar uma app que não fecha o dia nem mostra o semanal.

- **T-704** — Botão "Encerrar dia" na barra do chat + tela de resumo pós-fechamento. (M, 4-6h)
- **T-804** — Página `/weekly` com tabela cronológica dos 7 dias fechados. (M, 4-6h)
- **T-408 + T-409 + T-410** — `GET /days/today` + página `/days` renderizando totals + testes. Backend existe; tarefa é só de UI. (M+M+M)

Prioridade dentro do nível: começar por **T-704**. Sem encerramento, não há
snapshot final e o relatório diário não é acionado. É o loop crítico.

## Nível 2 — Ícone real do PWA

- **T-B402 (retrabalho)** — Trocar placeholder `mr` por asset final em
  `apps/web/public/icons/*.png`. Não muda código. (XS)
- Destrava **T-B408 (splash iOS)** que estava adiado esperando asset.

## Nível 3 — Automação de deploy (Fase 10 / CI/CD)

Especificada no PR #22. Sete tarefas, elimina deploy manual e bloqueia PRs que
quebram testes.

- **T-1001 + T-1002** — `ci.yml` com pytest+ruff (Python) e typecheck (web) em cada PR. (S+S)
- **T-1003** — Branch protection em `main` (require CI green). (S)
- **T-1004** — Chave SSH `deploy-only` na VPS com `command="..."` restrito. (S)
- **T-1005** — `deploy.yml` disparando SSH após CI passar. (M)
- **T-1006 + T-1007** — Docs + smoke test pós-deploy. (S+S)

Quando faz sentido: hoje o loop manual funciona porque é solo, mas o hotfix #24
(Next 16 build failure) mostrou que é fácil esquecer teste local.

## Nível 4 — Registro estruturado de treino (Bloco 3)

Especificada no PR #21. Oito tarefas, requer migração (`workout_sessions`,
`workout_exercises`, `workout_sets`). Bloqueado por T-704 (SP-125 exige
integração com `_handle_close_day`).

## Nível 5 — Dívidas técnicas descobertas nos deploys

- **D-01** — `infra/certbot/README.md` documentar `--entrypoint certbot` na primeira emissão (entrypoint em daemon-mode ignora o comando).
- **D-02** — Trocar `sed` manual em `app.conf` por envsubst nativo do nginx (config template em `/etc/nginx/templates/`).
- **D-03** — Atualizar `CLAUDE.md` (menciona Fase 0 como próxima; app está em prod).
- **D-04** — Adicionar seção "Se ícones/manifest não atualizam após deploy" em `docs/pwa.md` — cache do SW pode servir versão antiga se update prompt for ignorado.

## Nível 6 — Backlog (`may`, do `tasks.md`)

Ordenado por afinidade com uso solo/pessoal:

| Id | O quê | Motivador |
|--|--|--|
| **B-05** | Notificações push sobre encerramento pendente | Esquece de fechar dia? |
| **B-06** | Exportação CSV/PDF diário e semanal | Nutricionista pediu os dados |
| **B-01** | Persistir açúcares e gorduras específicas | Tracking mais fino |
| **B-08** | PWA offline completo (fila IndexedDB) | Uso fora de wifi |
| **B-02** | Leitura de código de barras | UX melhor que foto de rótulo |
| **B-03** | Integração Apple Health / Google Fit | Auto-importa treino/passos |
| **B-04** | Reabertura de dia encerrado | Corrigir depois do fechamento |
| **B-07** | Multi-usuário público | Só se abrir pra família (emenda constitucional) |
| **B-09** | Migrar fila pra RQ/Dramatiq | Só com >1 usuário concorrente |

## Ordem sugerida de execução

1. **T-704 + T-804** — fecha cauda funcional (1 dia)
2. **D-01 + D-03 + D-04** — 30 min de doc que evita repetir erros
3. **T-B402 real** — asset de design
4. **Fase 10 CI/CD** (T-1001..T-1007) — 1-2 dias; a partir daí deploy vira `merge → automagia`
5. **Bloco 3 workout** ou **B-05 notificações** — o que for mais útil no uso real
