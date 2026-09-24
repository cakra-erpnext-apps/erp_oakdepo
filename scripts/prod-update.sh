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

# Hitung mundur di semua layar Desk + PWA supaya user sempat Save (container_depot/maintenance.py),
# lalu tunggu selama itu sebelum halaman maintenance naik. MAINT_WARN_SECONDS=0 = lewati.
WARN="${MAINT_WARN_SECONDS:-30}"
if [ "$WARN" -gt 0 ]; then
  log "announce maintenance ($WARN s)"
  docker exec erp_oakdepo_prod-backend-1 bash -lc "cd /home/frappe/frappe-bench && bench --site '$SITE' execute container_depot.maintenance.announce --kwargs '{\"seconds\": $WARN}'" \
    || echo "announce gagal — lanjut tanpa hitung mundur"
  sleep "$WARN"
fi

# Halaman maintenance selama update, bukan 502 (nginx/conf.d/default.conf). Berkasnya
# terlihat nginx lewat bind mount; trap menghapusnya juga saat script gagal di tengah jalan.
MAINT="$ROOT/nginx/conf.d/maintenance.on"
trap 'rm -f "$MAINT"' EXIT
log "maintenance on"
# Dibaca halaman maintenance: jam mulai + perkiraan selesai. MAINT_MINUTES=30 kalau lama.
printf 'start=%s\nminutes=%s\n' "$(date +%s)" "${MAINT_MINUTES:-15}" > "$MAINT"
# Reload, bukan restart: memuat default.conf hasil git pull tanpa memutus koneksi.
docker exec erp_oakdepo_prod-frontend-1 sh -c 'nginx -t -q && nginx -s reload'

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


log "patch CRM assign_to compatibility"
docker cp scripts/patch-crm-assign-to.py erp_oakdepo_prod-backend-1:/tmp/patch-crm-assign-to.py
docker exec erp_oakdepo_prod-backend-1 bash -lc "python3 /tmp/patch-crm-assign-to.py"
log "backup site"
docker exec erp_oakdepo_prod-backend-1 bash -lc "cd /home/frappe/frappe-bench && bench --site '$SITE' backup"

log "migrate"
docker exec erp_oakdepo_prod-backend-1 bash -lc "cd /home/frappe/frappe-bench && bench --site '$SITE' migrate"

# Langkah "materialize assets for nginx" di bawah mengubah sites/assets/<app> jadi direktori
# nyata milik root. Run berikutnya, `bench build` tidak bisa rmtree direktori itu untuk
# memasang ulang symlink-nya, sehingga apps/frappe/frappe/public/node_modules tidak pernah
# dibuat dan desk.bundle.scss gagal di import highlight.js. Buang salinannya dulu.
log "unmaterialize assets"
docker exec -u root erp_oakdepo_prod-backend-1 bash -lc '
  cd /home/frappe/frappe-bench/sites/assets || exit 0
  for app in frappe erpnext container_depot hrms telephony helpdesk raven gameplan crm; do
    [ -L "$app" ] || rm -rf "$app"
  done
  # salinan itu dibuat oleh root (job create-site), termasuk direktori assets-nya sendiri,
  # jadi user frappe tidak bisa memasang symlink baru di sini sampai kepemilikannya balik.
  chown -R frappe:frappe /home/frappe/frappe-bench/sites/assets
'

log "build bench assets"
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

log "build container_depot PWA frontend on host"
if [ -f frontend/package.json ]; then
  docker run --rm \
    -u "$(id -u):$(id -g)" \
    -v "$ROOT:/workspace" \
    -w /workspace/frontend \
    node:20-bullseye bash -lc '
      set -euo pipefail
      export COREPACK_HOME=/tmp/corepack
      corepack yarn install --frozen-lockfile || corepack yarn install
      corepack yarn build
    '
else
  echo "skip container_depot PWA frontend: package.json not found"
fi
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
  erp_oakdepo_prod-backend-1 \
  erp_oakdepo_prod-websocket-1 \
  erp_oakdepo_prod-queue-short-1 \
  erp_oakdepo_prod-queue-long-1 \
  erp_oakdepo_prod-scheduler-1 >/dev/null

# Reload setelah restart: nginx me-resolve nama `backend` hanya saat start/reload, dan
# container yang di-recreate bisa dapat IP baru. Restart frontend (cara lama) memutus
# nginx itu sendiri, dan proxy di depannya membalas 502 — persis yang mau dihindari.
docker exec erp_oakdepo_prod-frontend-1 sh -c 'nginx -t -q && nginx -s reload'

log "wait for backend"
for _ in $(seq 1 60); do
  docker exec erp_oakdepo_prod-frontend-1 wget -q -O /dev/null --header "Host: $SITE" http://backend:8000/api/method/ping && break
  sleep 2
done

log "maintenance off"
rm -f "$MAINT"

log "verify"
sleep 5
curl -k -sS -o /dev/null -w 'HTTP %{http_code} %{time_total}s https://app.oakdepo.com\n' --max-time 20 https://app.oakdepo.com
docker exec erp_oakdepo_prod-backend-1 bash -lc "cd /home/frappe/frappe-bench && bench --site '$SITE' list-apps"

echo "DONE oakdepo update"
