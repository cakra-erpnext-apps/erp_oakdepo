#!/usr/bin/env bash
set -euo pipefail
BENCH=/home/frappe/frappe-bench
cd "$BENCH"
for app in container_depot; do
  if [ -d "apps/$app" ]; then
    env/bin/python -c "import $app" 2>/dev/null || { echo "[ensure-apps] installing $app..."; env/bin/pip install -e "apps/$app" --no-deps -q; }
    # Dependensi pihak ketiga dipasang terpisah, SETIAP boot.
    # `pip install -e --no-deps` di atas sengaja tidak memasangnya (biar resolver pip tidak
    # menaikkan pin frappe), dan barisnya cuma jalan saat app belum bisa di-import — jadi
    # dependensi yang ditambahkan belakangan tidak akan pernah terpasang sendiri. Itu yang
    # membuat py_vapid (dari pywebpush) hilang di produksi dan mematikan notifikasi HP.
    # Versi di requirements.txt sudah dipin supaya aman tanpa --no-deps. Idempotent.
    if [ -f "apps/$app/requirements.txt" ]; then
      env/bin/pip install -q -r "apps/$app/requirements.txt" || echo "[ensure-apps] WARN: gagal memasang requirements $app"
    fi
  fi
done
if [ -f sites/apps.txt ]; then
  for app in container_depot; do
    if [ -d "apps/$app" ] && ! grep -qx "$app" sites/apps.txt; then echo "$app" >> sites/apps.txt; fi
  done
fi
exec "$@"
