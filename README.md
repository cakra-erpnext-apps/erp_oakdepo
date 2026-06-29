# ERPOakDepo

Production stack/bundle repository for OakDepo ERPNext/Frappe deployment.

This repo follows same stack structure as `cakra-erpnext-apps/erp_cakra`, while keeping OakDepo app identity as `container_depot`.

## Components

- `container_depot/` — custom Frappe app for Container and ISO Tank Depot Management System.
- `frontend/` — OakDepo SPA source, if used.
- `compose.prod.yaml` — production Docker stack.
- `ensure-apps.sh` — runtime app install/self-heal for bind-mounted custom app.
- `nginx-inject.sh` — nginx template customization for SPA route.
- `STRUCTURE.md` — repository coding and structure rules.

## Features

- Container asset tracking
- Voucher/Gate management (Bon Bongkar QR system)
- Inspection system with photo evidence
- Maintenance & Repair workflow
- Cleaning queue management
- Split-billing support

## Local app install inside existing bench

```bash
cd /home/frappe/frappe-bench
bench get-app container_depot <path_to_this_repo>
bench --site <site> install-app container_depot
bench --site <site> migrate
```

## Production stack deploy

```bash
cp .env.prod.example .env.prod
# edit .env.prod with real values; do not commit it

docker compose --env-file .env.prod -f compose.prod.yaml config
docker compose --env-file .env.prod -f compose.prod.yaml up -d
```

Before production changes:

```bash
docker compose --env-file .env.prod -f compose.prod.yaml exec backend bench --site "$SITE_NAME" backup
```

## Rules

See `STRUCTURE.md`.
