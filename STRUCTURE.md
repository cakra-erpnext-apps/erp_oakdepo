# ERPOakDepo Structure Rules

This repository is OakDepo stack/bundle repository. It follows same production pattern as `cakra-erpnext-apps/erp_cakra`.

## Repository contract

- Repository name: `erp_oakdepo`
- Docker compose project: `erp_oakdepo_prod`
- Frappe app package: `container_depot`
- Production site: configured by `SITE_NAME` in `.env.prod`

Repo name and Frappe app name may differ. Do not rename `container_depot` package without planned migration.

## Top-level layout

```text
.
├── compose.prod.yaml
├── .env.prod.example
├── Caddyfile
├── ensure-apps.sh
├── nginx-inject.sh
├── container_depot/
├── frontend/
├── docs/
├── README.md
└── STRUCTURE.md
```

## Code rules

1. Keep Frappe/ERPNext/CRM core untouched.
2. All custom backend code lives under `container_depot/`.
3. DocTypes live under `container_depot/<module>/doctype/<doctype>/`.
4. Hooks register in `container_depot/hooks.py`.
5. Data changes use fixtures, patches, or install hooks. No manual DB-only source of truth.
6. Production migrations must be repeatable and idempotent.
7. Tests go under `container_depot/tests/`.
8. Root scripts are stack-level only; app logic stays in Python app code.
9. Secrets stay in `.env.prod` or server secret store; never commit secrets.
10. Deploy through git then stack update. No live container edits as permanent fix.

## Role model

Rebuilt 2026-08-06, replacing the Phase-6 model purged on 2026-08-05. Seeded by
`container_depot/install.py::ensure_roles_exist` on every migrate (idempotent).

**Field roles** — `desk_access = 0`, `is_depot_field_role = 1`. Their users work the yard
through the `/depot` PWA and are bounced out of `/app` on purpose.

| Role | PWA menus |
|---|---|
| Security | Gate · Siap Keluar · Monitor |
| Team EIR | EIR · Monitor |
| Team Kalmar | Siap Keluar · Position Fix · Monitor |
| Team Cleaning | Cleaning · Monitor |
| Team Repair | M&R · Uji Periodik · Monitor |
| Team Survey | Survey Posisi · Monitor |
| SPV Lapangan | all nine |

Monitor is the read-only yard browser and follows Container read, which every field role
holds because every worklist shows container data.

**Office roles** — `desk_access = 1`, no PWA menu: Admin Ops, Cashier, Finance,
Commercial, Warehouse, Management (read-only everywhere).

### Assigning a user

1. Create the User as **System User**.
2. Add exactly one field role, or one office role.
3. For office roles, ALSO add the standard ERPNext companion role — the custom roles
   carry Operations-module permissions only:

   | Office role | Add alongside |
   |---|---|
   | Cashier | `Accounts User` |
   | Finance | `Accounts Manager` |
   | Commercial | `Sales Manager`, `Item Manager` |
   | Warehouse | `Stock User`, `Purchase User` |

   This is deliberate. The first Custom DocPerm written on a doctype makes Frappe ignore
   that doctype's shipped permissions entirely, so seeding perms on Sales Invoice or
   Purchase Order would silently disable ERPNext's own accounting and stock roles.

4. Optionally scope the user to a Branch (User → Branch). Empty = all branches.

Nobody holds a role until an admin assigns one, so a new account opens `/depot` and sees
an empty state until step 2 is done.

### Adding a NEW field role — no deploy needed

Create the Role in Desk, tick **Depot Field Role (PWA)**, set `desk_access = 0`, then grant
its DocPerms in Permission Manager. The menu follows from the permissions
(`container_depot/ess/context.py::_MENU` maps menu → doctype + ptype, never menu → role).

### Where access is actually enforced

`container_depot/ess/guard.py::require_menu` on every ESS endpoint. The Home.vue tile
filter and the router guard are cosmetic — a caller with curl sees neither.

## Notifications

Routing is DATA, not code: one `Depot Notification Rule` per event (19 seeded), editable
in Desk with no deploy. `Depot Notification Settings` holds the master switch and the
fallback roles used when an event has no rule — never "everyone".

A recipient must clear both filters: branch scope AND one of the event's roles.

This is deliberately the opposite call from the PWA menu, which stays hardcoded — a new
menu always needs a new Vue page, so a config doctype would save nothing there. Do not
"make them consistent".

## Split-stack rule

OakDepo runs in its own stack, separate from Cakra/Oakglobal stack.

- OakDepo repo/stack: `erp_oakdepo`
- Cakra/Oakglobal repo/stack: `erp_cakra`
- Do not share MariaDB volumes between stacks unless intentionally designed and documented.
- Do not install OakDepo app into Cakra/Oakglobal sites.
