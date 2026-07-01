#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/apps/erp_oakdepo/erp_oakdepo"
SITE="${SITE:-app.oakdepo.com}"
IMAGE="${IMAGE:-oakdepo-erpnext:prod}"
APPS_TXT=$'frappe\nerpnext\ncontainer_depot\nhrms\ntelephony\nhelpdesk\nraven\ngameplan\ncrm\n'
BUILD_IMAGE="${BUILD_IMAGE:-0}"
SKIP_GIT_PULL="${SKIP_GIT_PULL:-0}"

cd "$ROOT"

log() { printf '\n== %s ==\n' "$*"; }

dc() {
  docker compose --env-file .env.prod -f compose.prod.yaml "$@"
}

log "git remote"
git remote -v

if [ "$SKIP_GIT_PULL" != "1" ]; then
  log "git pull"
  git fetch origin
  branch="$(git branch --show-current)"
  git pull --ff-only origin "$branch"
fi

if [ "$BUILD_IMAGE" = "1" ]; then
  log "build image $IMAGE"
  docker build -t "$IMAGE" .
fi

log "recreate app containers"
dc up -d --no-deps --force-recreate backend websocket queue-short queue-long scheduler

log "ensure bench app list + editable install"
docker exec erp_oakdepo_prod-backend-1 bash -lc "
  set -euo pipefail
  cd /home/frappe/frappe-bench
  printf %s \"$APPS_TXT\" > sites/apps.txt
  env/bin/pip install -e apps/container_depot --no-deps -q
"

log "backup site"
docker exec erp_oakdepo_prod-backend-1 bash -lc "cd /home/frappe/frappe-bench && bench --site '$SITE' backup"

log "migrate"
docker exec erp_oakdepo_prod-backend-1 bash -lc "cd /home/frappe/frappe-bench && bench --site '$SITE' migrate"

log "build assets"
docker exec erp_oakdepo_prod-backend-1 bash -lc "
  set -euo pipefail
  cd /home/frappe/frappe-bench
  bench build --apps frappe,erpnext
  bench build --apps container_depot
  bench build --apps hrms,raven
  bench build --apps helpdesk
  bench build --apps gameplan
  bench build --apps crm
"

log "materialize assets for nginx"
docker exec erp_oakdepo_prod-backend-1 bash -lc "
  set -euo pipefail
  cd /home/frappe/frappe-bench
  for app in frappe erpnext container_depot hrms telephony helpdesk raven gameplan crm; do
    src=\"apps/\$app/\$app/public\"
    [ -d \"\$src\" ] || src=\"apps/\$app/public\"
    if [ -d \"\$src\" ]; then
      echo \"materialize \$app <- \$src\"
      rm -rf \"sites/assets/\$app\"
      mkdir -p \"sites/assets/\$app\"
      cp -a \"\$src/.\" \"sites/assets/\$app/\"
    else
      echo \"skip \$app no public dir\"
    fi
  done
"

log "clear cache"
docker exec erp_oakdepo_prod-backend-1 bash -lc "
  cd /home/frappe/frappe-bench
  bench --site '$SITE' clear-cache
  bench --site '$SITE' clear-website-cache
"

log "restart oakdepo services"
docker restart \
  erp_oakdepo_prod-frontend-1 \
  erp_oakdepo_prod-backend-1 \
  erp_oakdepo_prod-websocket-1 \
  erp_oakdepo_prod-queue-short-1 \
  erp_oakdepo_prod-queue-long-1 \
  erp_oakdepo_prod-scheduler-1 >/dev/null

log "verify"
sleep 5
curl -k -sS -o /dev/null -w 'HTTP %{http_code} %{time_total}s https://app.oakdepo.com\n' --max-time 20 https://app.oakdepo.com
docker exec erp_oakdepo_prod-backend-1 bash -lc "cd /home/frappe/frappe-bench && bench --site '$SITE' list-apps"

echo "DONE oakdepo update"
