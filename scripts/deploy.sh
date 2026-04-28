#!/usr/bin/env bash
# ============================================================================
# deploy.sh  --  One-command deployment for the Deep Agents reference app
# ============================================================================
#
# Deploy a single domain pack, every domain at once, or to Kanopy.
#
# Usage:
#   scripts/deploy.sh <domain>           # deploy one domain (Docker)
#   scripts/deploy.sh --all              # deploy all 5 domains (Docker)
#   scripts/deploy.sh --kanopy           # push + deploy to Kanopy staging
#   scripts/deploy.sh --kanopy <domain>  # seed a single domain on Kanopy
#   scripts/deploy.sh --status           # show running containers / pods
#   scripts/deploy.sh --down             # tear down the Docker stack
#
# Available domains:
#   reference | healthcare | finance | retail | telco | <your-pack>
#
# Environment overrides:
#   COMPOSE            compose CLI (default: "docker compose")
#   DEEP_AGENT_PORT    host port for backend (default: 8010)
#   FRONTEND_PORT      host port for frontend (default: 3000)
#   HEALTH_URL         override health probe URL
#   TIMEOUT            health-wait timeout in seconds (default: 180)
#   MONGODB_DB_PREFIX  DB-name prefix (default: deep_agents)
#   NO_BUILD           set to 1 to skip image rebuild
#   NO_SEED            set to 1 to skip seeding
#   NO_FRONTEND        set to 1 to skip the frontend container
#
set -euo pipefail

# ---------- colour helpers ----------
red()    { printf '\033[0;31m%s\033[0m\n' "$*" >&2; }
green()  { printf '\033[0;32m%s\033[0m\n' "$*" >&2; }
yellow() { printf '\033[0;33m%s\033[0m\n' "$*" >&2; }
bold()   { printf '\033[1m%s\033[0m\n' "$*" >&2; }

# ---------- resolve repo root (works from any cwd) ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# ---------- shared defaults ----------
COMPOSE="${COMPOSE:-docker compose}"
DEEP_AGENT_PORT="${DEEP_AGENT_PORT:-8010}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
HEALTH_URL="${HEALTH_URL:-http://localhost:${DEEP_AGENT_PORT}/health}"
TIMEOUT="${TIMEOUT:-180}"
DB_PREFIX="${MONGODB_DB_PREFIX:-deep_agents}"

# Kanopy release / ingress names (derived from the repo directory name;
# override via env if you forked the repo under a different name).
KANOPY_RELEASE_PREFIX="${KANOPY_RELEASE_PREFIX:-mongodb-langchain-deep-agents}"
KANOPY_API_HOST="${KANOPY_API_HOST:-${KANOPY_RELEASE_PREFIX}-api.maap.staging.corp.mongodb.com}"
KANOPY_UI_HOST="${KANOPY_UI_HOST:-${KANOPY_RELEASE_PREFIX}.maap.staging.corp.mongodb.com}"
KANOPY_BACKEND_RELEASE="${KANOPY_RELEASE_PREFIX}-backend"

# ---------- usage ----------
usage() {
  cat >&2 <<EOF
$(bold "Deep Agents Deploy Script")

Usage:
  $(basename "$0") <domain>           Deploy a single domain (Docker)
  $(basename "$0") --all              Deploy all domains (Docker)
  $(basename "$0") --kanopy           Build + deploy to Kanopy staging
  $(basename "$0") --kanopy <domain>  Seed a single domain on Kanopy
  $(basename "$0") --status           Show running services
  $(basename "$0") --down             Tear down the Docker stack

Available domains:
EOF
  for d in domains/*/; do
    [[ -d "$d" ]] && echo "  - $(basename "$d")" >&2
  done
  cat >&2 <<EOF

Environment overrides:
  DEEP_AGENT_PORT=$DEEP_AGENT_PORT  FRONTEND_PORT=$FRONTEND_PORT  TIMEOUT=$TIMEOUT
  MONGODB_DB_PREFIX=$DB_PREFIX  NO_BUILD=0  NO_SEED=0  NO_FRONTEND=0
EOF
  exit 2
}

# ---------- preflight checks ----------
preflight() {
  local ok=1

  # .env file
  if [[ ! -f ".env" ]]; then
    red "ERROR: .env file not found."
    echo "  Copy the example and fill in your credentials:"
    echo "    cp .env.example .env && \$EDITOR .env"
    ok=0
  else
    # Check for required keys (must have a non-placeholder value)
    for key in MONGODB_URI VOYAGE_API_KEY; do
      val=$(grep -E "^${key}=" .env 2>/dev/null | head -1 | cut -d= -f2-)
      if [[ -z "$val" || "$val" == *"..."* || "$val" == *"USER:PASS"* ]]; then
        red "ERROR: $key in .env is missing or still has a placeholder value."
        ok=0
      fi
    done
    # Warn if VFS_BACKEND=s3 but no bucket set (deploy still proceeds with
    # the Settings-level validator catching it, but flag early).
    vfs=$(grep -E '^VFS_BACKEND=' .env 2>/dev/null | head -1 | cut -d= -f2- || true)
    if [[ "$vfs" == "s3" ]]; then
      bucket=$(grep -E '^VFS_S3_BUCKET=' .env 2>/dev/null | head -1 | cut -d= -f2- || true)
      if [[ -z "$bucket" ]]; then
        red "ERROR: VFS_BACKEND=s3 in .env but VFS_S3_BUCKET is empty."
        ok=0
      fi
    fi
  fi

  # Docker / compose
  if ! command -v docker &>/dev/null; then
    red "ERROR: docker is not installed or not in PATH."
    ok=0
  elif ! $COMPOSE version &>/dev/null 2>&1; then
    red "ERROR: '$COMPOSE' is not available."
    echo "  Install Docker Compose v2 or set COMPOSE to your compose binary."
    ok=0
  fi

  # curl (for health checks)
  if ! command -v curl &>/dev/null; then
    red "ERROR: curl is not installed (needed for health checks)."
    ok=0
  fi

  [[ "$ok" -eq 1 ]] || { echo; red "Preflight checks failed. Fix the above and re-run."; exit 1; }
}

# ---------- validate domain name ----------
validate_domain() {
  local domain="$1"
  if [[ "$domain" == *"/"* || "$domain" == *"\\"* || "$domain" == *".."* ]]; then
    red "ERROR: domain '$domain' must be a simple identifier (no path separators)"
    exit 2
  fi
  if [[ ! -d "domains/$domain" ]]; then
    red "ERROR: domain '$domain' not found under ./domains/"
    usage
  fi
}

# ---------- list all available domains ----------
list_domains() {
  local domains=()
  for d in domains/*/; do
    [[ -d "$d" ]] && domains+=("$(basename "$d")")
  done
  echo "${domains[@]}"
}

# ---------- build images ----------
build_images() {
  if [[ "${NO_BUILD:-0}" == "1" ]]; then
    yellow "==> skipping image build (NO_BUILD=1)"
    return 0
  fi
  bold "==> building Docker images"
  $COMPOSE build
}

# ---------- wait for health ----------
wait_for_health() {
  local url="$1" timeout_s="$2"
  bold "==> waiting for $url (up to ${timeout_s}s)"
  local deadline=$(( $(date +%s) + timeout_s ))
  while (( $(date +%s) < deadline )); do
    if curl --silent --fail --max-time 3 "$url" >/dev/null 2>&1; then
      echo
      green "==> health check passed"
      return 0
    fi
    printf "."
    sleep 2
  done
  echo

  red "ERROR: service did not become healthy within ${timeout_s}s"
  echo
  yellow "--- Last 30 lines of backend logs ---"
  $COMPOSE logs --tail=30 deep_agent 2>&1 || true
  echo
  yellow "--- Health endpoint response ---"
  curl --silent --max-time 5 "$url" 2>&1 || echo "(no response)"
  echo
  yellow "--- Troubleshooting ---"
  echo "  1. Check .env has valid MONGODB_URI (can the container reach Atlas?)"
  echo "  2. Check Docker network: docker network inspect $(basename "$REPO_ROOT")_default"
  echo "  3. Check container status: $COMPOSE ps"
  echo "  4. Full logs: $COMPOSE logs deep_agent"
  return 1
}

# ---------- seed a single domain ----------
seed_domain() {
  local domain="$1"
  local db_name="${DB_PREFIX}_${domain}"
  if [[ "${NO_SEED:-0}" == "1" ]]; then
    yellow "==> skipping seed (NO_SEED=1)"
    return 0
  fi
  bold "==> seeding domain '$domain' into database '$db_name'"
  if ! $COMPOSE exec -T \
    -e DOMAIN="$domain" \
    -e MONGODB_DB="$db_name" \
    deep_agent deep-agent --domain "$domain" seed 2>&1; then
    red "ERROR: seeding failed for domain '$domain'"
    yellow "  Check logs: $COMPOSE logs --tail=50 deep_agent"
    return 1
  fi
  green "==> seeded $domain"
}

# ---------- seed all domains ----------
#
# The deep-agent CLI does not ship a `seed --all` subcommand yet, so iterate
# every pack and shell the seed loader per pack. Each call sets DOMAIN +
# MONGODB_DB so seeds land in the right per-domain DB (`<prefix>_<pack>`).
seed_all() {
  if [[ "${NO_SEED:-0}" == "1" ]]; then
    yellow "==> skipping seed (NO_SEED=1)"
    return 0
  fi
  local domains
  read -ra domains <<< "$(list_domains)"
  bold "==> seeding all domains (${#domains[@]} packs)"
  local d
  local failed=()
  for d in "${domains[@]}"; do
    yellow "  - seeding $d -> ${DB_PREFIX}_${d}"
    if ! $COMPOSE exec -T \
      -e DOMAIN="$d" \
      -e MONGODB_DB="${DB_PREFIX}_${d}" \
      deep_agent deep-agent --domain "$d" seed 2>&1 >/dev/null; then
      failed+=("$d")
      red "    FAILED: $d"
    fi
  done
  if [[ "${#failed[@]}" -gt 0 ]]; then
    red "ERROR: seed --all failed for: ${failed[*]}"
    yellow "  Re-run a single pack: scripts/deploy.sh ${failed[0]} (after fixing)."
    return 1
  fi
  green "==> all domains seeded"
}

# ---------- print summary ----------
print_summary() {
  local mode="$1"
  shift
  local domains=("$@")
  echo
  bold "============================================"
  green "  Deployment complete ($mode)"
  bold "============================================"
  echo
  echo "  Backend:    http://localhost:${DEEP_AGENT_PORT}"
  echo "  Frontend:   http://localhost:${FRONTEND_PORT}"
  echo "  Health:     ${HEALTH_URL}"
  echo "  Chat API:   http://localhost:${DEEP_AGENT_PORT}/chat"
  echo "  Domains:    http://localhost:${DEEP_AGENT_PORT}/domains"
  echo "  Plans:      http://localhost:${DEEP_AGENT_PORT}/plans?user_id=demo-user&thread_id=<thread>"
  echo
  echo "  Deployed domains:"
  for d in "${domains[@]}"; do
    echo "    - $d  (db: ${DB_PREFIX}_${d})"
  done
  echo
  echo "  Quick test:"
  echo "    curl -N -X POST http://localhost:${DEEP_AGENT_PORT}/chat \\"
  echo "      -H 'Content-Type: application/json' \\"
  echo "      -H 'X-Domain: ${domains[0]}' \\"
  echo "      -d '{\"user_id\":\"demo\",\"message\":\"hello\"}'"
  echo
  if [[ "${#domains[@]}" -gt 1 ]]; then
    echo "  Open the web UI at http://localhost:${FRONTEND_PORT}"
    echo "  Use the sidebar to switch between domains."
  fi
  echo
}

# ---------- cleanup on failure ----------
_deploy_ok=0
cleanup() {
  if [[ "$_deploy_ok" -ne 1 ]]; then
    echo
    red "==> deployment failed; tearing down compose stack"
    $COMPOSE down >/dev/null 2>&1 || true
  fi
}

# ==========================================================================
#  DOCKER: deploy a single domain
# ==========================================================================
deploy_single() {
  local domain="$1"
  validate_domain "$domain"

  export DOMAIN="$domain"
  export MONGODB_DB="${DB_PREFIX}_${domain}"

  trap cleanup EXIT
  preflight
  build_images

  bold "==> starting compose stack (DOMAIN=$DOMAIN, MONGODB_DB=$MONGODB_DB)"
  if [[ "${NO_FRONTEND:-0}" == "1" ]]; then
    $COMPOSE up -d deep_agent
  else
    $COMPOSE up -d
  fi

  wait_for_health "$HEALTH_URL" "$TIMEOUT" || exit 1
  seed_domain "$domain" || exit 1

  _deploy_ok=1
  print_summary "single-domain" "$domain"
}

# ==========================================================================
#  DOCKER: deploy all domains
# ==========================================================================
deploy_all() {
  local domains
  read -ra domains <<< "$(list_domains)"

  # Multi-domain: backend handles X-Domain routing; DOMAIN is the fallback.
  export DOMAIN="${domains[0]}"
  export MONGODB_DB="${DB_PREFIX}"

  trap cleanup EXIT
  preflight
  build_images

  bold "==> starting compose stack (multi-domain: ${domains[*]})"
  $COMPOSE up -d

  wait_for_health "$HEALTH_URL" "$TIMEOUT" || exit 1
  seed_all || exit 1

  _deploy_ok=1
  print_summary "all-domains" "${domains[@]}"
}

# ==========================================================================
#  KANOPY: build + deploy via git push (Drone picks it up)
# ==========================================================================
deploy_kanopy() {
  local domain="${1:-}"
  bold "==> Kanopy deployment"

  # Verify we're on main and up to date
  local branch
  branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
  if [[ "$branch" != "main" ]]; then
    yellow "WARNING: current branch is '$branch', not 'main'."
    echo "  Drone only triggers on main. Switch with: git checkout main"
    read -rp "  Continue anyway? [y/N] " ans
    [[ "$ans" =~ ^[Yy]$ ]] || exit 0
  fi

  # Check for uncommitted changes
  if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
    red "ERROR: uncommitted changes detected."
    echo "  Commit or stash your changes before deploying to Kanopy."
    echo "  git status:"
    git status --short
    exit 1
  fi

  local sha
  sha="$(git rev-parse --short HEAD)"
  bold "==> deploying commit $sha to Kanopy staging"
  echo "  Drone pipeline will:"
  echo "    1. Build backend image  -> ECR maap/\${DRONE_REPO_NAME}/backend:git-$sha"
  echo "    2. Build frontend image -> ECR maap/\${DRONE_REPO_NAME}/frontend:git-$sha"
  echo "    3. Helm upgrade backend  -> ${KANOPY_API_HOST}"
  echo "    4. Helm upgrade frontend -> ${KANOPY_UI_HOST}"

  # Push (Drone triggers on push to main)
  if git push origin main 2>&1; then
    green "==> pushed to origin/main -- Drone pipeline triggered"
  else
    red "ERROR: git push failed"
    exit 1
  fi

  # If a specific domain was requested, seed it via kubectl exec.
  # This is best-effort: the Drone build must finish + pods must be Ready,
  # which can take a few minutes. The user can always seed later via:
  #   kubectl exec -n maap deploy/<release>-web-app -- deep-agent --domain <d> seed
  if [[ -n "$domain" ]]; then
    validate_domain "$domain"
    bold "==> seeding domain '$domain' on Kanopy (best-effort)"
    echo "  (requires kubectl access to the staging cluster)"
    if kubectl exec -n maap "deploy/${KANOPY_BACKEND_RELEASE}-web-app" -- \
      env DOMAIN="$domain" MONGODB_DB="${DB_PREFIX}_${domain}" \
      deep-agent --domain "$domain" seed 2>&1; then
      green "==> seeded $domain on Kanopy"
    else
      yellow "WARNING: kubectl seed failed (VPN or token may be required; pods may not be ready yet)"
      echo "  Manual seed once pods are ready:"
      echo "    kubectl exec -n maap deploy/${KANOPY_BACKEND_RELEASE}-web-app -- \\"
      echo "      env DOMAIN=$domain MONGODB_DB=${DB_PREFIX}_${domain} deep-agent --domain $domain seed"
    fi
  fi

  echo
  bold "============================================"
  green "  Kanopy deployment initiated"
  bold "============================================"
  echo
  echo "  Drone pipeline:  https://drone.corp.mongodb.com"
  echo "  Backend:         https://${KANOPY_API_HOST}"
  echo "  Frontend:        https://${KANOPY_UI_HOST}"
  echo "  Health:          https://${KANOPY_API_HOST}/health"
  echo
  echo "  Seed a domain (from any machine with kubectl access):"
  echo "    for d in $(list_domains); do"
  echo "      kubectl exec -n maap deploy/${KANOPY_BACKEND_RELEASE}-web-app -- \\"
  echo "        env DOMAIN=\$d MONGODB_DB=${DB_PREFIX}_\$d deep-agent --domain \$d seed"
  echo "    done"
  echo
}

# ==========================================================================
#  STATUS: show running services
# ==========================================================================
show_status() {
  bold "==> Docker Compose status"
  $COMPOSE ps 2>/dev/null || yellow "(no compose stack running)"
  echo

  bold "==> Kanopy pods (if kubectl is configured)"
  kubectl get pods -n maap -l "app.kubernetes.io/instance=${KANOPY_RELEASE_PREFIX}-backend" 2>/dev/null || true
  kubectl get pods -n maap -l "app.kubernetes.io/instance=${KANOPY_RELEASE_PREFIX}-frontend" 2>/dev/null || true
}

# ==========================================================================
#  TEARDOWN
# ==========================================================================
teardown() {
  bold "==> tearing down compose stack"
  $COMPOSE down --remove-orphans
  green "==> stack removed"
}

# ==========================================================================
#  MAIN: parse arguments and dispatch
# ==========================================================================
[[ $# -ge 1 ]] || usage

case "$1" in
  --all|-a)
    deploy_all
    ;;
  --kanopy|-k)
    deploy_kanopy "${2:-}"
    ;;
  --status|-s)
    show_status
    ;;
  --down|-d)
    teardown
    ;;
  --help|-h)
    usage
    ;;
  --*)
    red "ERROR: unknown flag '$1'"
    usage
    ;;
  *)
    deploy_single "$1"
    ;;
esac
