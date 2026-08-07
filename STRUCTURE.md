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

### Moving between the Desk and the PWA

Both directions are shortcuts only; neither grants anything.

| From | To | Where |
|---|---|---|
| Desk | `/depot` | Sidebar item **Depot PWA (Lapangan)** + a Shortcut card on the Container Depot workspace. Both are plain `link_type: URL` rows in the shipped JSON. |
| PWA | `/desk` | **Buka Desk** in the Home hero, and as a button on the empty state. Rendered only when `get_menu` answers `desk_access: true`. |

`desk_access` comes from `ess/context.py::has_desk_access`, which reads `User.user_type`.
Do not "improve" it into a scan of the user's roles for `desk_access = 1`: `frappe.get_roles`
appends the automatic **Desk User** role to every System User, so that scan answers yes for
everyone. `User.set_system_user` already keeps `user_type` in step with the roles.

Note the side effect of the sidebar item: a URL row is always permitted
(`desk_views.py::is_item_allowed`), and a sidebar renders whenever one non-Section-Break
item survives — so the Container Depot sidebar is now visible to every Desk user, including
one with no depot DocPerms at all (they will see only that one entry). Drop the item from
`workspace_sidebar/container_depot.json` if that is not wanted; the workspace Shortcut has
no such effect.

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
