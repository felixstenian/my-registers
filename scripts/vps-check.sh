#!/usr/bin/env bash
# Radiografia rápida da VPS: capacidade, containers, backups, TLS.
#
# Uso:
#   ./scripts/vps-check.sh
#
# Ou via cron (semanal) mandando por email/Discord/etc:
#   0 9 * * 1 /home/felix/my-registers/scripts/vps-check.sh > /tmp/vps-check.txt 2>&1
#
# Exit codes: 0 = tudo OK · 1 = algum WARN · 2 = algum FAIL.
# Bom pra plugar em healthchecks.io como check secundário.
set -uo pipefail

# Localiza raiz do repo (o script pode ser invocado de qualquer lugar).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_DIR/.env.production}"
COMPOSE_FILE="$REPO_DIR/docker-compose.production.yml"

# --- thresholds (env-overridable) ---
LOAD_WARN="${LOAD_WARN:-2.0}"
LOAD_FAIL="${LOAD_FAIL:-4.0}"
MEM_WARN_PCT="${MEM_WARN_PCT:-85}"
MEM_FAIL_PCT="${MEM_FAIL_PCT:-95}"
DISK_WARN_PCT="${DISK_WARN_PCT:-80}"
DISK_FAIL_PCT="${DISK_FAIL_PCT:-90}"
SWAP_WARN_PCT="${SWAP_WARN_PCT:-25}"
BACKUP_WARN_HOURS="${BACKUP_WARN_HOURS:-30}"     # dump > 30h atrás soa alarme
BACKUP_FAIL_HOURS="${BACKUP_FAIL_HOURS:-48}"
CERT_WARN_DAYS="${CERT_WARN_DAYS:-14}"
CERT_FAIL_DAYS="${CERT_FAIL_DAYS:-5}"

# --- cores (opt-out via NO_COLOR=1) ---
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  GREEN='\033[0;32m'
  YELLOW='\033[0;33m'
  RED='\033[0;31m'
  BOLD='\033[1m'
  DIM='\033[2m'
  NC='\033[0m'
else
  GREEN=''; YELLOW=''; RED=''; BOLD=''; DIM=''; NC=''
fi

# --- estado global ---
WORST=0        # 0=ok, 1=warn, 2=fail
TOTAL_OK=0; TOTAL_WARN=0; TOTAL_FAIL=0

status() {
  local code="$1" label="$2" detail="${3:-}"
  case "$code" in
    ok)
      printf "  ${GREEN}✓${NC} %-32s ${DIM}%s${NC}\n" "$label" "$detail"
      ((TOTAL_OK++)) || true
      ;;
    warn)
      printf "  ${YELLOW}!${NC} %-32s ${YELLOW}%s${NC}\n" "$label" "$detail"
      ((TOTAL_WARN++)) || true
      [[ $WORST -lt 1 ]] && WORST=1
      ;;
    fail)
      printf "  ${RED}✗${NC} %-32s ${RED}%s${NC}\n" "$label" "$detail"
      ((TOTAL_FAIL++)) || true
      WORST=2
      ;;
    info)
      printf "  ${DIM}·${NC} %-32s ${DIM}%s${NC}\n" "$label" "$detail"
      ;;
  esac
}

section() {
  printf "\n${BOLD}%s${NC}\n" "$1"
}

# ---------------------------------------------------------------------------
header() {
  local host uptime_str
  host="$(hostname -f 2>/dev/null || hostname)"
  uptime_str="$(uptime -p 2>/dev/null || uptime)"
  printf "${BOLD}my-registers VPS check${NC} ${DIM}(%s)${NC}\n" "$(date '+%Y-%m-%d %H:%M %z')"
  printf "${DIM}host=%s · uptime=%s${NC}\n" "$host" "$uptime_str"
}

# ---------------------------------------------------------------------------
check_load() {
  section "Capacidade"
  # 1min load average — 3 números em /proc/loadavg
  local load1 load5 load15
  read -r load1 load5 load15 _ < /proc/loadavg
  local cpus; cpus=$(nproc)
  local ratio; ratio=$(awk "BEGIN{printf \"%.2f\", $load1/$cpus}")
  local detail="load1=$load1  load5=$load5  load15=$load15  ratio=$ratio (cpus=$cpus)"
  if awk "BEGIN{exit !($load1 >= $LOAD_FAIL)}"; then
    status fail "CPU load" "$detail"
  elif awk "BEGIN{exit !($load1 >= $LOAD_WARN)}"; then
    status warn "CPU load" "$detail"
  else
    status ok "CPU load" "$detail"
  fi
}

check_mem() {
  # `free -m` → linhas Mem: e Swap:. Colunas: total used free shared buff/cache available
  local mem_total mem_used mem_avail pct swap_total swap_used swap_pct
  read -r _ mem_total mem_used _ _ _ mem_avail < <(free -m | awk '/^Mem:/ {print}')
  read -r _ swap_total swap_used _ < <(free -m | awk '/^Swap:/ {print}')
  pct=$(( 100 - (mem_avail * 100 / mem_total) ))
  local detail="usado=${pct}%  avail=${mem_avail}MB de ${mem_total}MB"
  if [[ $pct -ge $MEM_FAIL_PCT ]]; then
    status fail "Memória RAM" "$detail"
  elif [[ $pct -ge $MEM_WARN_PCT ]]; then
    status warn "Memória RAM" "$detail"
  else
    status ok "Memória RAM" "$detail"
  fi

  if [[ ${swap_total:-0} -gt 0 ]]; then
    swap_pct=$(( swap_used * 100 / swap_total ))
    local sdet="usado=${swap_pct}%  (${swap_used}MB de ${swap_total}MB)"
    if [[ $swap_pct -ge $SWAP_WARN_PCT ]]; then
      status warn "Swap ativo" "$sdet — indício de RAM insuficiente"
    else
      status ok "Swap" "$sdet"
    fi
  fi
}

check_disk() {
  # `df -PB1` → mesmo output em qualquer locale
  local used_pct avail
  used_pct=$(df -P / | awk 'NR==2 {gsub("%",""); print $5}')
  avail=$(df -Ph / | awk 'NR==2 {print $4}')
  local detail="usado=${used_pct}%  livre=${avail}"
  if [[ $used_pct -ge $DISK_FAIL_PCT ]]; then
    status fail "Disco raiz" "$detail"
  elif [[ $used_pct -ge $DISK_WARN_PCT ]]; then
    status warn "Disco raiz" "$detail"
  else
    status ok "Disco raiz" "$detail"
  fi

  # Docker overlay pode consumir muito (imagens antigas, layers órfãos)
  if command -v docker >/dev/null 2>&1; then
    local docker_size
    docker_size=$(docker system df --format '{{.Size}}' 2>/dev/null | head -1)
    status info "Docker footprint" "${docker_size:-desconhecido}"
  fi
}

# ---------------------------------------------------------------------------
check_containers() {
  section "Containers"
  if ! command -v docker >/dev/null 2>&1; then
    status fail "Docker" "não instalado"
    return
  fi
  if ! docker info >/dev/null 2>&1; then
    status fail "Docker daemon" "não responde"
    return
  fi
  if [[ ! -f "$COMPOSE_FILE" ]]; then
    status warn "docker-compose.production.yml" "não encontrado em $COMPOSE_FILE"
    return
  fi

  local ps_json
  if ! ps_json=$(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" ps --format json 2>/dev/null); then
    status fail "docker compose ps" "falhou (env-file ausente?)"
    return
  fi

  # `docker compose ps --format json` emite 1 objeto JSON por linha.
  local services=("nginx" "api" "web" "postgres" "minio" "certbot")
  for svc in "${services[@]}"; do
    local line state health
    line=$(echo "$ps_json" | grep -E "\"Service\":\"$svc\"" || true)
    if [[ -z "$line" ]]; then
      status fail "$svc" "não está no compose"
      continue
    fi
    state=$(echo "$line" | grep -oE '"State":"[^"]+"' | cut -d'"' -f4)
    health=$(echo "$line" | grep -oE '"Health":"[^"]*"' | cut -d'"' -f4)
    if [[ "$state" == "running" ]]; then
      if [[ -z "$health" || "$health" == "healthy" || "$health" == "none" ]]; then
        status ok "$svc" "state=$state${health:+  health=$health}"
      elif [[ "$health" == "starting" ]]; then
        status warn "$svc" "state=$state  health=$health"
      else
        status fail "$svc" "state=$state  health=$health"
      fi
    elif [[ "$state" == "exited" && "$svc" == "certbot" ]]; then
      # certbot pode ficar Exited(0) entre renovações
      status info "$svc" "state=$state (esperado entre renovações)"
    else
      status fail "$svc" "state=${state:-desconhecido}"
    fi
  done
}

# ---------------------------------------------------------------------------
check_health_endpoint() {
  section "Endpoints"
  # Bate no /api/health via localhost (evita DNS externo)
  local rc body
  body=$(curl -fsS -m 5 -o /dev/null -w "%{http_code}" http://127.0.0.1/api/health 2>/dev/null || echo "000")
  if [[ "$body" == "200" ]]; then
    status ok "GET /api/health (localhost)" "200"
  else
    status fail "GET /api/health (localhost)" "http=$body"
  fi

  # Se DOMAIN estiver no .env, tenta o externo também
  if [[ -f "$ENV_FILE" ]]; then
    local domain
    domain=$(grep -E '^DOMAIN=' "$ENV_FILE" | cut -d= -f2- | tr -d '"')
    if [[ -n "$domain" ]]; then
      body=$(curl -fsS -m 8 -o /dev/null -w "%{http_code}" "https://$domain/api/health" 2>/dev/null || echo "000")
      if [[ "$body" == "200" ]]; then
        status ok "GET /api/health (público)" "https://$domain → 200"
      else
        status fail "GET /api/health (público)" "https://$domain → http=$body"
      fi
    fi
  fi
}

# ---------------------------------------------------------------------------
check_backups() {
  section "Backups"
  local pg_dir="/var/backups/pg" minio_dir="/var/backups/minio"

  # Backup mais recente do Postgres
  if [[ -d "$pg_dir" ]]; then
    local latest_pg age_hours size
    latest_pg=$(find "$pg_dir" -maxdepth 1 -name 'registers-*.dump' -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | awk '{print $2}')
    if [[ -n "$latest_pg" ]]; then
      age_hours=$(( ($(date +%s) - $(stat -c %Y "$latest_pg")) / 3600 ))
      size=$(du -h "$latest_pg" | cut -f1)
      local detail="há ${age_hours}h  ($(basename "$latest_pg"), $size)"
      if [[ $age_hours -ge $BACKUP_FAIL_HOURS ]]; then
        status fail "Backup Postgres" "$detail — cron parado?"
      elif [[ $age_hours -ge $BACKUP_WARN_HOURS ]]; then
        status warn "Backup Postgres" "$detail"
      else
        status ok "Backup Postgres" "$detail"
      fi
    else
      status warn "Backup Postgres" "diretório existe mas sem dumps"
    fi
  else
    status warn "Backup Postgres" "$pg_dir não existe — cron nunca rodou?"
  fi

  # Backup mais recente do MinIO
  if [[ -d "$minio_dir" ]]; then
    local latest_minio age_hours size
    latest_minio=$(find "$minio_dir" -maxdepth 1 -mindepth 1 -type d -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | awk '{print $2}')
    if [[ -n "$latest_minio" ]]; then
      age_hours=$(( ($(date +%s) - $(stat -c %Y "$latest_minio")) / 3600 ))
      size=$(du -sh "$latest_minio" 2>/dev/null | cut -f1)
      local detail="há ${age_hours}h  ($(basename "$latest_minio"), $size)"
      if [[ $age_hours -ge $BACKUP_FAIL_HOURS ]]; then
        status fail "Backup MinIO" "$detail"
      elif [[ $age_hours -ge $BACKUP_WARN_HOURS ]]; then
        status warn "Backup MinIO" "$detail"
      else
        status ok "Backup MinIO" "$detail"
      fi
    else
      status warn "Backup MinIO" "diretório existe mas sem espelhos"
    fi
  else
    status warn "Backup MinIO" "$minio_dir não existe — cron nunca rodou?"
  fi

  # Retenção — quantos dumps guardados
  if [[ -d "$pg_dir" ]]; then
    local n
    n=$(find "$pg_dir" -maxdepth 1 -name 'registers-*.dump' 2>/dev/null | wc -l | tr -d ' ')
    status info "Dumps guardados" "$n arquivos em $pg_dir"
  fi
}

# ---------------------------------------------------------------------------
check_cert() {
  section "TLS"
  if [[ ! -f "$ENV_FILE" ]]; then
    status info "Certificado" "sem .env.production — pulei check externo"
    return
  fi
  local domain
  domain=$(grep -E '^DOMAIN=' "$ENV_FILE" | cut -d= -f2- | tr -d '"')
  if [[ -z "$domain" ]]; then
    status info "Certificado" "DOMAIN não setado no .env"
    return
  fi
  # Consulta o próprio Nginx via TLS (sem depender do letsencrypt/ montado)
  local expiry_str
  expiry_str=$(echo | openssl s_client -servername "$domain" -connect "127.0.0.1:443" 2>/dev/null \
    | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
  if [[ -z "$expiry_str" ]]; then
    status fail "Certificado TLS" "não consegui ler expiry de $domain"
    return
  fi
  local expiry_epoch now_epoch days
  expiry_epoch=$(date -d "$expiry_str" +%s 2>/dev/null || echo 0)
  now_epoch=$(date +%s)
  days=$(( (expiry_epoch - now_epoch) / 86400 ))
  local detail="expira em ${days}d  ($expiry_str)"
  if [[ $days -le $CERT_FAIL_DAYS ]]; then
    status fail "Certificado TLS" "$detail — renovação urgente"
  elif [[ $days -le $CERT_WARN_DAYS ]]; then
    status warn "Certificado TLS" "$detail"
  else
    status ok "Certificado TLS" "$detail"
  fi
}

# ---------------------------------------------------------------------------
check_llm_errors() {
  section "LLM (últimas 24h)"
  if [[ ! -f "$ENV_FILE" ]]; then
    status info "LLM errors" "sem .env — pulei"
    return
  fi
  if ! docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" ps postgres --format json 2>/dev/null | grep -q '"State":"running"'; then
    status info "LLM errors" "postgres não está de pé"
    return
  fi
  local pg_user pg_db count
  pg_user=$(grep -E '^POSTGRES_USER=' "$ENV_FILE" | cut -d= -f2-)
  pg_db=$(grep -E '^POSTGRES_DB=' "$ENV_FILE" | cut -d= -f2-)
  count=$(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T postgres \
    psql -U "$pg_user" -d "$pg_db" -tAc "
      SELECT count(*) FROM messages
      WHERE role='assistant'
        AND content = 'Não consegui interpretar sua mensagem agora. Pode reformular?'
        AND created_at > now() - interval '24 hours';
    " 2>/dev/null | tr -d ' ')
  if [[ -z "$count" || ! "$count" =~ ^[0-9]+$ ]]; then
    status info "Fallbacks 24h" "não consegui contar (query falhou)"
    return
  fi
  local detail="$count fallbacks em 24h"
  if [[ $count -ge 20 ]]; then
    status fail "Fallbacks LLM" "$detail — algo quebrado no pipeline"
  elif [[ $count -ge 5 ]]; then
    status warn "Fallbacks LLM" "$detail — verificar logs"
  else
    status ok "Fallbacks LLM" "$detail"
  fi
}

# ---------------------------------------------------------------------------
summary() {
  printf "\n${BOLD}Resumo${NC}  "
  printf "${GREEN}%d OK${NC}  ${YELLOW}%d warn${NC}  ${RED}%d fail${NC}\n" \
    "$TOTAL_OK" "$TOTAL_WARN" "$TOTAL_FAIL"
  case $WORST in
    0) printf "${GREEN}Tudo saudável.${NC}\n" ;;
    1) printf "${YELLOW}Atenção em alguns pontos. Não urgente, mas monitorar.${NC}\n" ;;
    2) printf "${RED}Algo está quebrado ou perto de quebrar. Agir agora.${NC}\n" ;;
  esac
}

# --- run ---
header
check_load
check_mem
check_disk
check_containers
check_health_endpoint
check_backups
check_cert
check_llm_errors
summary
exit "$WORST"
