#!/usr/bin/env bash
set -euo pipefail
BENCH=/home/frappe/frappe-bench
cd "$BENCH"
for app in container_depot; do
  if [ -d "apps/$app" ]; then
    env/bin/python -c "import $app" 2>/dev/null || { echo "[ensure-apps] installing $app..."; env/bin/pip install -e "apps/$app" --no-deps -q; }
  fi
done
if [ -f sites/apps.txt ]; then
  for app in container_depot; do
    if [ -d "apps/$app" ] && ! grep -qx "$app" sites/apps.txt; then echo "$app" >> sites/apps.txt; fi
  done
fi
exec "$@"
