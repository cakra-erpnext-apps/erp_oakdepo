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


log "patch CRM assign_to compatibility"
docker cp scripts/patch-crm-assign-to.py erp_oakdepo_prod-backend-1:/tmp/patch-crm-assign-to.py
docker exec erp_oakdepo_prod-backend-1 bash -lc "python3 /tmp/patch-crm-assign-to.py"
log "backup site"
docker exec erp_oakdepo_prod-backend-1 bash -lc "cd /home/frappe/frappe-bench && bench --site '$SITE' backup"

log "migrate"
docker exec erp_oakdepo_prod-backend-1 bash -lc "cd /home/frappe/frappe-bench && bench --site '$SITE' migrate"

# `bench build` memulai tiap jalannya dengan make_asset_dirs(): sites/assets/<app> dihapus dan
# diganti symlink ke public/ milik app-nya (frappe/build.py, link_assets_dir). Jadi build SELALU
# menulis ke pohon sumber, dan untuk container_depot pohon itu adalah bind mount host — karena itu
# direktori keluarannya disiapkan di atas. Konsekuensi keduanya: build harus SELALU mendahului
# langkah materialize di bawah, sebab ia meninggalkan sites/assets/container_depot sebagai symlink
# yang tidak bisa diikuti nginx dari container-nya sendiri.
# esbuild menulis berkas ber-hash ke container_depot/public/dist, dan direktori itu ada di bind
# mount milik user host sementara bench jalan sebagai uid frappe di dalam container — mkdir-nya
# mati dengan EACCES. Dua uid memang menulis ke pohon ini (build PWA di bawah jalan sebagai user
# host, bench build sebagai frappe), jadi yang dilonggarkan hanya direktori keluarannya, bukan
# seluruh public/.
# ponytail: chmod di satu direktori; samakan uid host dengan uid frappe kalau suatu saat mau rapi
log "prepare container_depot asset output dir"
mkdir -p container_depot/public/dist
# Rekursif di dist: jalan yang gagal sebelumnya bisa meninggalkan dist/js atau dist/css milik uid
# lain, dan esbuild menulis ke dalamnya, bukan cuma ke dist sendiri.
chmod a+rwX container_depot/public
chmod -R a+rwX container_depot/public/dist

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
      # --no-preserve=ownership: sumbernya bind mount milik user host, dan \`cp -a\` menyalin
      # kepemilikan itu ke salinannya — termasuk ke direktori puncaknya. Hasilnya frappe tidak
      # bisa membuat apa pun di dalamnya lagi, dan build berikutnya mati dengan EACCES mkdir.
      cp -a --no-preserve=ownership \"\$src/.\" \"sites/assets/\$app/\"
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
