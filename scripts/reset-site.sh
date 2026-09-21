#!/usr/bin/env bash
# Reset satu site Container Depot kembali ke kondisi "baru selesai di-seed".
#
#   ./scripts/reset-site.sh                       # dev, transaksi saja, seed dev
#   MASTERS=1 ./scripts/reset-site.sh             # dev, master ikut dibangun ulang
#   STACK=prod ./scripts/reset-site.sh            # prod, site dibaca dari .env.prod
#
# Backup diambil lebih dulu, SELALU, lalu disalin keluar volume ke ./_backups.
# Yang TIDAK disentuh: site itu sendiri, user, role, dan site_config.json (termasuk
# kunci VAPID). Untuk membuang itu semua juga, pakai `docker compose down -v`.
set -euo pipefail

STACK="${STACK:-dev}"
MASTERS="${MASTERS:-0}"        # 1 = master kurasi ikut dihapus lalu di-seed ulang
# Seeder mengikuti stack-nya, dan itu bukan kenyamanan belaka: `seed_dev` menanam
# Customer contoh DAN satu Depot Contract Active berisi tarif karangan — dan kontrak
# Active menerbitkan Price List yang dibaca booking, cleaning dan M&R sebagai rate
# card. Di produksi itu artinya harga palsu yang terlihat sah. Default yang salah di
# sini lebih berbahaya daripada tidak ada default sama sekali.
# `${SEED-...}` tanpa titik dua, dan itu bukan gaya: dengan `:-` sebuah `SEED=`
# eksplisit (artinya "jangan seed apa pun") diperlakukan sama dengan tidak diset dan
# diam-diam berubah jadi `dev` — operator meminta site kosong dan mendapat data contoh.
SEED="${SEED-$([ "$STACK" = "prod" ] && echo prod || echo dev)}"   # dev | prod | ""
BACKUP_DIR="${BACKUP_DIR:-_backups}"

cd "$(dirname "$0")/.."

case "$STACK" in
  dev)
    COMPOSE=(docker compose -f compose.dev.yaml)
    SVC=frappe
    SITE="${SITE:-oakdepo.localhost}"
    ;;
  prod)
    [ -f .env.prod ] || { echo "compose prod butuh .env.prod di $(pwd) — jalankan dari repo di server prod." >&2; exit 1; }
    COMPOSE=(docker compose --env-file .env.prod -f compose.prod.yaml)
    SVC=backend
    # Nama site diambil dari .env.prod kalau tidak diberikan: satu sumber kebenaran,
    # dan satu kesempatan salah ketik yang hilang.
    if [ -z "${SITE:-}" ]; then
      SITE=$(sed -n 's/^SITE_NAME=//p' .env.prod | tail -1 | tr -d '"' | tr -d "'" | tr -d ' ')
    fi
    [ -n "$SITE" ] || { echo "SITE tidak diberikan dan SITE_NAME tidak ada di .env.prod" >&2; exit 1; }
    if [ "$SEED" = "dev" ]; then
      echo "SEED=dev ditolak untuk STACK=prod: seeder dev menanam kontrak + tarif karangan." >&2
      exit 1
    fi
    ;;
  *)
    echo "STACK harus 'dev' atau 'prod' (dapat: $STACK)" >&2
    exit 1
    ;;
esac

log() { printf '\n== %s ==\n' "$*"; }

# Rencananya dicetak sebelum apa pun terjadi — kegagalan pertama skrip ini di lapangan
# adalah ia diam-diam memilih stack dev, lalu mengeluh "service frappe is not running"
# tanpa pernah menyebut site mana yang sebetulnya dituju.
log "rencana"
printf '  stack   : %s\n  site    : %s\n  seed    : %s\n  masters : %s\n' \
  "$STACK" "$SITE" "${SEED:-tidak}" "$MASTERS"

if ! "${COMPOSE[@]}" ps --status running --services 2>/dev/null | grep -qx "$SVC"; then
  echo "service '$SVC' tidak jalan untuk stack $STACK. Stack-nya belum naik, atau STACK=$STACK salah." >&2
  exit 1
fi

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
