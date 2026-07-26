# Constitution — my-registers

Princípios **inegociáveis** que regem qualquer trabalho neste repositório, humano ou IA. Um PR que viola um artigo desta constituição é rejeitado sem discussão. Alterações requerem PR próprio marcado `constitution-change` justificando cada revisão.

**Versão:** 1.0.0
**Última revisão:** 2026-07-15
**Escopo:** MVP single-user (§6 do plano); relaxamentos multi-user exigem emenda.

---

## Artigo I — Fonte de verdade

**§1.** O **PostgreSQL** é a única fonte de verdade para registros de alimentação, hidratação, atividade, dias e usuários.
**§2.** A LLM **não** armazena estado de negócio. Toda memória de sessão que a LLM aparente ter vem de dados recuperados do Postgres pelo backend a cada request.
**§3.** Imagens vivem em **object storage S3-compatible**. O banco guarda apenas metadados e `storage_key`.

## Artigo II — Papéis: LLM interpreta, backend calcula

**§4.** A LLM é usada **exclusivamente** para: (a) interpretar texto e imagens; (b) classificar intenção; (c) extrair itens estruturados; (d) gerar narrativas amigáveis sobre números **já calculados** pelo backend.
**§5.** Todo cálculo de kcal, macros, micros, agregados diários e semanais é **determinístico** e executado no backend. Um teste automatizado deve substituir o cliente Anthropic por mock devolvendo lixo e ainda assim produzir totais corretos.
**§6.** A LLM **nunca** soma valores nem faz aritmética que apareça na tabela do dia ou do relatório.
**§7.** Toda resposta da LLM chega via `tool_use` com JSON schema definido. Texto livre da LLM é descartado.

## Artigo III — Confiabilidade dos dados

**§8.** Todo item extraído pela LLM carrega `confidence ∈ [0,1]` e `is_estimate: bool`. Ambos persistidos.
**§9.** Item com `confidence < 0.5` ou faltando campo essencial dispara pedido de confirmação; o registro é criado com `needs_confirmation=true` **ou** não é criado, conforme severidade (definida no dispatcher).
**§10.** Correções e deleções sempre passam pelo `NutritionCalculator` novamente. Snapshots são **sempre** recomputados do zero (SELECT sobre tabelas cruas com `deleted_at IS NULL`), nunca incrementados delta-a-delta.
**§11.** Toda mutação em registros de negócio (create/update/delete/correct) grava linha em `audit_events` com `before`, `after`, `actor`, `message_id`.

## Artigo IV — Separação água ↔ outros líquidos

**§12.** `water_records` conta apenas água pura. Contribui só para `water_ml`. Nunca tem kcal, macros ou micros.
**§13.** `beverage_records` conta bebidas com calorias (café, leite, suco, refrigerante, chá adoçado, álcool). Contribui para `other_liquids_ml`, `kcal_in`, macros e micros.
**§14.** O `IntentDispatcher` valida essa separação. Bebida com `kcal>0` classificada como `log_water` é rejeitada ou reclassificada.

## Artigo V — Segurança

**§15.** Senhas com **Argon2id** (`time_cost=3, memory_cost=64MB, parallelism=2`).
**§16.** Sessão com JWT curto (15 min) em cookie `HttpOnly` + refresh opaco rotacionado (14 dias). Cookies **sempre** `HttpOnly; Secure` (prod); `SameSite=Lax` padrão.
**§17.** Reuso de refresh revogado invalida a família inteira.
**§18.** **Nunca** existirá endpoint HTTP público de cadastro ou reset de senha. Criação e reset são exclusivamente CLI (`app.cli create-admin`, `app.cli reset-password`) executados por humano com SSH.
**§19.** Segredos (Anthropic API key, JWT secret, S3 keys) nunca aparecem em: código versionado, migrations, respostas HTTP, logs, `raw_llm_response`, `audit_events`.
**§20.** CORS: allowlist explícita, `allow_credentials=true`, **sem wildcard**.
**§21.** Autorização é verificada em **toda** query de repositório via `user_id`. Não há query que ignore isolamento.
**§22.** Uploads validam MIME server-side com `Pillow` decode probe, ≤ 8 MB, nome gerado pelo backend.

## Artigo VI — Bootstrap e migrations

**§23.** Migrations Alembic descrevem **schema**, nunca dados sensíveis. Senha inicial do admin **nunca** entra em migration.
**§24.** Criação do admin default é feita por comando CLI idempotente (`app.cli bootstrap`) que lê `DEFAULT_ADMIN_EMAIL` e `DEFAULT_ADMIN_PASSWORD` do ambiente, aplica hash e nunca ecoa a senha.
**§25.** Runtime da API **não** executa migrations sozinho. Deploy roda `alembic upgrade head` como passo explícito.

## Artigo VII — Estimativa e conformidade

**§26.** Todo relatório diário ou semanal, no chat ou na UI, inclui o aviso: *"As estimativas nutricionais são aproximações e não substituem acompanhamento médico ou nutricional."*
**§27.** O assistente **nunca** dá conselho médico, prescreve dieta, sugere remédio ou avalia se o consumo é "bom" ou "ruim". Descreve o que foi registrado, no máximo.

## Artigo VIII — Imutabilidade do dia encerrado

**§28.** Dia com `status='closed'` é imutável. Correções, novos registros e exclusões são rejeitados (409). Reabertura não existe no MVP.
**§29.** Encerramento é idempotente. Fechar um dia já fechado retorna o snapshot atual sem regravar `closed_at`.

## Artigo IX — Semana

**§30.** No MVP, "semana" = **últimos 7 dias com `status='closed'`**. Dias abertos são ignorados. Alternativas (seg-dom, janela móvel) exigem emenda.

## Artigo X — Ambiente de desenvolvimento

**§31.** Em macOS, o padrão de dev é **infra em Docker, backend/frontend no host** (o bind mount do Docker Desktop dispara `EDEADLK` no import Python). Ver `scripts/dev-infra.sh` e o README.
**§32.** Nenhum commit inclui `.env`, `uv.lock` de outro sistema operacional divergente, ou artefatos de build (`.next`, `.venv`, `node_modules`).
**§33.** Alembic pinado em `>=1.14,<1.16` para evitar o auto-discovery de `pyproject.toml` que quebra o `alembic.ini` clássico.

---

## Processo de emenda

1. Abrir PR com prefixo `constitution:` alterando este arquivo.
2. Incrementar `Versão` (SemVer: major para remoção/afrouxamento; minor para adição de artigo; patch para redação).
3. Atualizar `Última revisão`.
4. No corpo do PR, para cada mudança: qual regra saiu/entrou, motivo, quais requisitos SP-XX podem violar, plano de migração se aplicável.
5. Auto-aprovação **não** é permitida em PRs de emenda mesmo em regime single-committer — cool-off mínimo de 24h antes de mergear.
