# Fase 10 — Setup manual antes do primeiro deploy automático

Este roteiro cobre as duas tarefas da Fase 10 que **não podem ser feitas via commit** — só via UI do GitHub e SSH tradicional na VPS. Depois de concluí-las, o próximo merge em `main` dispara o deploy automatizado.

> Referência completa: `docs/deploy.md` §14. Este arquivo é o passo a passo enxuto pra fazer numa sessão só (~15 min).

## Contexto

Os workflows `ci.yml` e `deploy.yml` já estão em `main` a partir do PR #34. O que falta:

- **T-1003** — Branch protection em `main` (bloqueia merge se CI falhar).
- **T-1004** — Chave SSH `deploy-only` na VPS + GitHub Secret/Variables.

## Ordem recomendada

1. Gerar par de chaves no laptop
2. Registrar public key na VPS com `command="…"` restringido
3. Registrar private key + variáveis no GitHub
4. Configurar branch protection em `main`
5. (Opcional) Testar SSH manualmente antes do primeiro release

---

## 1. Gerar par de chaves SSH (~1 min)

No **laptop**, gera par dedicado (nunca reusar chave pessoal):

```bash
ssh-keygen -t ed25519 -f ~/.ssh/deploy_myregisters -N "" -C "deploy-only-my-registers"
```

Isso gera:
- `~/.ssh/deploy_myregisters` — **private key** (vai pro GitHub Secret)
- `~/.ssh/deploy_myregisters.pub` — **public key** (vai pra VPS)

`-N ""` = sem passphrase (obrigatório porque o GitHub Actions não pode digitar).

---

## 2. Registrar public key na VPS (~5 min)

### 2.1 Copiar a public key do laptop

```bash
cat ~/.ssh/deploy_myregisters.pub
# Copia a linha inteira (começa com `ssh-ed25519 AAAA…`)
```

### 2.2 Conectar na VPS via SSH tradicional

```bash
ssh felix@myregister.felix.dev.br
```

### 2.3 Adicionar ao `authorized_keys` com `command="…"` restringido

Dentro da VPS, ainda como `felix`:

```bash
# 1. Define o comando fixo que a chave pode executar. NADA mais.
DEPLOY_CMD='cd ~/my-registers && git pull && ./scripts/bootstrap.sh .env.production && docker compose -f docker-compose.production.yml --env-file .env.production up -d --build api web'

# 2. Cole a public key do laptop na variável PUB_KEY:
PUB_KEY='ssh-ed25519 AAAA…COLE_AQUI…deploy-only-my-registers'

# 3. Prepend a linha ao authorized_keys com todas as restrições:
echo "command=\"$DEPLOY_CMD\",no-port-forwarding,no-x11-forwarding,no-agent-forwarding,no-pty $PUB_KEY" \
  >> ~/.ssh/authorized_keys

# 4. Garante permissões:
chmod 600 ~/.ssh/authorized_keys
chmod 700 ~/.ssh
```

### 2.4 Confirmar que a linha foi adicionada

```bash
tail -1 ~/.ssh/authorized_keys
# Deve imprimir a linha inteira começando com command="cd ~/my-registers && ..."
```

### 2.5 Testar do laptop (opcional mas recomendado)

Fecha o SSH atual, e no laptop:

```bash
ssh -i ~/.ssh/deploy_myregisters felix@myregister.felix.dev.br
```

O que deve acontecer:
- SSH conecta com a chave deploy
- **Executa o comando restringido** (git pull + bootstrap + docker compose up)
- Desconecta

⚠️ **Este teste dispara um deploy real.** Só rode se estiver ok redeployar agora. Se não, pule este passo — o próximo deploy via workflow vai testar o setup.

Se a chave estiver mal configurada, você vê `Permission denied (publickey)` ou o SSH abre um shell interativo em vez de rodar o comando restrito.

---

## 3. Registrar credenciais no GitHub (~3 min)

Repo → **Settings → Secrets and variables → Actions**.

### 3.1 Secret

Aba **Secrets** → **New repository secret**:

| Campo | Valor |
|--|--|
| Name | `DEPLOY_SSH_KEY` |
| Secret | Conteúdo completo de `~/.ssh/deploy_myregisters` (private key) — inclui as linhas `-----BEGIN OPENSSH PRIVATE KEY-----` e `-----END OPENSSH PRIVATE KEY-----`. |

```bash
# No laptop, pra copiar o conteúdo pro clipboard (macOS):
cat ~/.ssh/deploy_myregisters | pbcopy
```

### 3.2 Variables

Aba **Variables** → **New repository variable** (fazer 2 vezes):

| Name | Value |
|--|--|
| `DEPLOY_HOST` | `myregister.felix.dev.br` |
| `DEPLOY_DOMAIN` | `myregister.felix.dev.br` |

Note que `DEPLOY_HOST` e `DEPLOY_DOMAIN` acabam iguais neste projeto — mas o workflow os usa para propósitos diferentes (SSH target vs URL do smoke test), então melhor manter separados.

Não colocar o `ANTHROPIC_API_KEY`, `POSTGRES_PASSWORD`, etc. aqui — esses continuam só na VPS.

---

## 4. Branch protection em `main` (~3 min)

Repo → **Settings → Branches → Add branch ruleset** (ou **Add rule** em UIs mais antigas).

Configuração:

- **Branch name pattern:** `main`
- **Restrict deletions**: ✓
- **Require a pull request before merging**: ✓
  - Required approving reviews: `0` (você é solo dev)
- **Require status checks to pass before merging**: ✓
  - Search e adicione: `api (ruff + pytest)`
  - Search e adicione: `web (typecheck + build)`
  - **Require branches to be up to date before merging**: ✓
- **Block force pushes**: ✓
- **Do not allow bypassing the above settings**: ✓ (aplica pra você também)

Save.

> ⚠️ Se `api (ruff + pytest)` ou `web (typecheck + build)` não aparecem na busca, é porque o CI ainda não rodou nenhuma vez em `main`. Solução: crie uma PR triviais pra `main` (`dev → main`) e deixe o CI rodar; depois volte aqui e adiciona os checks.

---

## 5. Primeiro release automatizado

Depois dos 4 passos acima:

```bash
# No laptop:
gh pr create --base main --head dev --title "release: primeiro deploy automatizado (CI/CD ativo)"
```

Ao mergear:

1. `ci.yml` roda em `main` (paralelamente api + web)
2. Se verde, `deploy.yml` dispara via `workflow_run`
3. SSH pra VPS → dispara o command restrito → git pull + bootstrap + docker compose up -d --build
4. Smoke test bate em `https://myregister.felix.dev.br/api/health` (até 60s)
5. Verde ✓

Você pode acompanhar em tempo real:

```bash
gh run watch --workflow=deploy.yml
```

Ou pela UI: repo → aba **Actions** → workflow **deploy**.

---

## 6. Rotação de chave (semestral, opcional)

A cada 6 meses ou se suspeitar de comprometimento:

```bash
# 1. Gera par novo
ssh-keygen -t ed25519 -f ~/.ssh/deploy_myregisters_v2 -N "" -C "deploy-only-v2"

# 2. Adiciona a nova public key no authorized_keys da VPS (deixa a velha por enquanto)
# ... via SSH tradicional, seguindo passo 2 acima

# 3. Atualiza `DEPLOY_SSH_KEY` no GitHub com a nova private key

# 4. Testa: faz um merge trivial em main, confirma que deploy passa

# 5. Remove a linha da chave antiga do authorized_keys da VPS

# 6. Apaga o par antigo do laptop
rm ~/.ssh/deploy_myregisters ~/.ssh/deploy_myregisters.pub
mv ~/.ssh/deploy_myregisters_v2 ~/.ssh/deploy_myregisters
mv ~/.ssh/deploy_myregisters_v2.pub ~/.ssh/deploy_myregisters.pub
```

---

## Troubleshooting

### `Permission denied (publickey)` no primeiro deploy

- Confere se o `DEPLOY_SSH_KEY` no GitHub tem as linhas `-----BEGIN/END OPENSSH PRIVATE KEY-----` inclusas.
- Verifica se a public key foi mesmo adicionada ao `authorized_keys` da VPS: `cat ~/.ssh/authorized_keys` como `felix`.
- Confere o dono/permissões: `ls -la ~/.ssh/authorized_keys` (deve ser `-rw------- felix felix`).

### Deploy SSH conecta mas não roda `git pull`

- O `command="…"` provavelmente foi mal escapado no `authorized_keys`. Confere com `tail -1 ~/.ssh/authorized_keys` — as aspas duplas devem ficar preservadas ao redor do comando.

### `git pull` roda mas `docker compose` falha

- A conta `felix` precisa estar no grupo `docker` na VPS: `groups felix | grep docker`. Se não estiver: `sudo usermod -aG docker felix` + logout.

### Smoke test do workflow falha com HTTP 502/503

- Container `api` demorou pra ficar healthy. Aumente o loop de smoke test em `deploy.yml` (hoje 12 × 5s = 60s) — a fase 4b (leitura de rótulo) pode segurar startup até 30s no cold start com prompt cache miss.

### Branch protection bloqueia meu próprio merge

- Se você marcou "Do not allow bypassing", nem admin passa. Isso é intencional. Pra emergência, desabilite temporariamente o ruleset na UI, mergeie, e reabilite.
