#!/usr/bin/env bash
# Reset satu site Container Depot kembali ke kondisi "baru selesai di-seed".
#
#   ./scripts/reset-site.sh                       # dev, transaksi saja, seed dev
#   MASTERS=1 ./scripts/reset-site.sh             # dev, master ikut dibangun ulang
#   STACK=prod SITE=app.oakdepo.com ./scripts/reset-site.sh
#
# Backup diambil lebih dulu, SELALU, lalu disalin keluar volume ke ./_backups.
# Yang TIDAK disentuh: site itu sendiri, user, role, dan site_config.json (termasuk
# kunci VAPID). Untuk membuang itu semua juga, pakai `docker compose down -v`.
set -euo pipefail

STACK="${STACK:-dev}"
MASTERS="${MASTERS:-0}"        # 1 = master kurasi ikut dihapus lalu di-seed ulang
SEED="${SEED:-dev}"            # dev | prod | "" (tanpa seed)
BACKUP_DIR="${BACKUP_DIR:-_backups}"

cd "$(dirname "$0")/.."

case "$STACK" in
  dev)
    COMPOSE=(docker compose -f compose.dev.yaml)
    SVC=frappe
    SITE="${SITE:-oakdepo.localhost}"
    ;;
  prod)
    COMPOSE=(docker compose --env-file .env.prod -f compose.prod.yaml)
    SVC=backend
    SITE="${SITE:?SITE wajib diisi untuk STACK=prod}"
    ;;
  *)
    echo "STACK harus 'dev' atau 'prod' (dapat: $STACK)" >&2
    exit 1
    ;;
esac

log() { printf '\n== %s ==\n' "$*"; }

# Prod tidak pernah jalan tanpa diketik ulang nama site-nya.
if [ "$STACK" = "prod" ] && [ "${FORCE:-0}" != "1" ]; then
  printf 'Ini akan MENGHAPUS semua transaksi di %s. Ketik nama site untuk lanjut: ' "$SITE"
  read -r typed
  [ "$typed" = "$SITE" ] || { echo "Dibatalkan."; exit 1; }
fi

log "backup $SITE"
"${COMPOSE[@]}" exec -T "$SVC" bash -lc "cd ~/frappe-bench && bench --site '$SITE' backup --with-files"

mkdir -p "$BACKUP_DIR"
cid="$("${COMPOSE[@]}" ps -q "$SVC")"
docker cp "$cid:/home/frappe/frappe-bench/sites/$SITE/private/backups/." "$BACKUP_DIR/"
echo "backup tersalin ke $BACKUP_DIR/"

log "reset data"
"${COMPOSE[@]}" exec -T "$SVC" bash -lc "cd ~/frappe-bench && bench --site '$SITE' execute container_depot.reset_data.run --kwargs \"{'confirm': '$SITE', 'masters': $MASTERS, 'seed': '$SEED'}\""

log "clear cache"
"${COMPOSE[@]}" exec -T "$SVC" bash -lc "cd ~/frappe-bench && bench --site '$SITE' clear-cache"

log "selesai"
