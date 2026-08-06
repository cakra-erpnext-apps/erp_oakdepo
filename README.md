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

## Deploying the role model (2026-08-06 release)

This release seeds 13 roles, rewrites the permission matrix, and **deletes five
Notification records** that duplicated the app's own events. Back up first — the step
above is not optional here.

```bash
# 1. Pull + rebuild the PWA bundle (menu gating lives in the built assets)
git pull
docker compose --env-file .env.prod -f compose.prod.yaml exec backend \
  bash -lc 'cd apps/container_depot/frontend && yarn build'

# 2. Migrate. Seeds the roles, the permission matrix, and 19 notification rules;
#    patch v0_51 removes the duplicate Notifications. Idempotent — safe to re-run.
docker compose --env-file .env.prod -f compose.prod.yaml exec backend \
  bench --site "$SITE_NAME" migrate

# 3. Verify
docker compose --env-file .env.prod -f compose.prod.yaml exec backend \
  bench --site "$SITE_NAME" execute frappe.client.get_list \
  --kwargs "{'doctype':'Role','filters':{'is_depot_field_role':1},'fields':['name','desk_access']}"
```

**Then assign roles — nothing happens until you do.** No existing user holds any of the
new roles, so every non-System-Manager account opens `/depot` to an empty state until an
admin assigns one. Procedure (which role, which companion ERPNext role, branch scoping) is
in `STRUCTURE.md § Role model → Assigning a user`.

Post-deploy admin screens live under **Container Depot → Notifikasi & Akses**:

| Screen | Use |
|---|---|
| Depot Notification Rule | Change who receives an event. Takes effect immediately, no deploy. |
| Depot Notification Settings | Master switch (turn all depot notifications off during maintenance) + fallback roles. |
| Role | Tick *Depot Field Role (PWA)* to let a new role into `/depot`. |

## Rules

See `STRUCTURE.md`.
