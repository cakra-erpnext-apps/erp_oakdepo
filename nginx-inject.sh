#!/usr/bin/env bash
set -euo pipefail
export BACKEND=${BACKEND:-0.0.0.0:8000}
export SOCKETIO=${SOCKETIO:-0.0.0.0:9000}
export UPSTREAM_REAL_IP_ADDRESS=${UPSTREAM_REAL_IP_ADDRESS:-127.0.0.1}
export UPSTREAM_REAL_IP_HEADER=${UPSTREAM_REAL_IP_HEADER:-X-Forwarded-For}
export UPSTREAM_REAL_IP_RECURSIVE=${UPSTREAM_REAL_IP_RECURSIVE:-off}
export FRAPPE_SITE_NAME_HEADER=${FRAPPE_SITE_NAME_HEADER:-\$host}
export PROXY_READ_TIMEOUT=${PROXY_READ_TIMEOUT:-120}
export CLIENT_MAX_BODY_SIZE=${CLIENT_MAX_BODY_SIZE:-50m}

echo "[nginx-inject] Generating frappe.conf from template..."
envsubst '${BACKEND} ${SOCKETIO} ${UPSTREAM_REAL_IP_ADDRESS} ${UPSTREAM_REAL_IP_HEADER} ${UPSTREAM_REAL_IP_RECURSIVE} ${FRAPPE_SITE_NAME_HEADER} ${PROXY_READ_TIMEOUT} ${CLIENT_MAX_BODY_SIZE}' </templates/nginx/frappe.conf.template >/etc/nginx/conf.d/frappe.conf

echo "[nginx-inject] Injecting /depot route..."
if ! grep -q 'location /depot' /etc/nginx/conf.d/frappe.conf; then
  python3 - <<'PYEOF'
from pathlib import Path
p = Path('/etc/nginx/conf.d/frappe.conf')
content = p.read_text()
block = """    location /depot {
        try_files $uri $uri/ /assets/container_depot/frontend/index.html;
    }

"""
content = content.replace('    location /assets {', block + '    location /assets {', 1)
p.write_text(content)
print('[nginx-inject] /depot route injected.')
PYEOF
fi
exec nginx -g 'daemon off;'
