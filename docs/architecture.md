# Arquitetura

Este documento é um índice curto — a fonte de verdade é [`../app_plan.md`](../app_plan.md).

- **§3** Arquitetura da solução (diagrama + camadas do backend)
- **§4** Fluxo completo de uma mensagem com foto
- **§6** Modelagem de banco de dados
- **§8** Contrato de integração com Anthropic (schema + prompt v2)
- **§16** Segurança (checklist)

## Fases de implementação

Ver §18 do plano. A Fase 0 (fundação) entrega apenas o esqueleto executável: FastAPI com `/health`, Next.js com página placeholder, Postgres e MinIO subindo via `docker-compose.local.yml`.
