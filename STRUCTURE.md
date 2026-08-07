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
   carry Container Depot module permissions only:

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

Each direction is gated by the Role flag that matches it, and by nothing else.

| From | To | Shown when | Surfaces |
|---|---|---|---|
| Desk | `/depot` | **Depot Field Role (PWA)** ticked | Sidebar item, workspace Shortcut card, `/apps` tile |
| PWA | `/desk` | **Desk Access** (`user_type` = System User) | "Buka Desk" in the Home hero + on the empty state |

**Desk → PWA.** All three surfaces point at the Desk Page `depot-pwa`
(`container_depot/page/depot_pwa/`), which does nothing but redirect. The Page exists purely to
own a `roles` table: Frappe filters sidebar entries and shortcuts of type `Page` against it,
whereas a `link_type: URL` row is waved through unconditionally
(`desk_views.py::is_item_allowed` returns True for "url") and would show the shortcut to
every Desk user — including office staff who land on an empty PWA. The `/apps` tile is
gated separately by `www/depot.py::check_app_permission`.

`install.setup_pwa_page_roles()` keeps the Page's roles equal to the roles carrying
`is_depot_field_role`. It is a **full sync**, so unticking the flag removes the shortcut;
roles hand-added to the Page are dropped (it is `standard: Yes` — tick the flag instead).
Ticking a new field role needs one `bench migrate` before the Desk shortcut appears; the
PWA menu itself is still instant, and so is the `/apps` tile.

`/depot` itself stays open to any logged-in user — see handoff §5.5 and the note in
`www/depot.py`. The shortcut is an advertisement, not the gate.

**PWA → Desk.** `desk_access` comes from `ess/context.py::has_desk_access`, which reads
`User.user_type`. Do not "improve" it into a scan of the user's roles for `desk_access = 1`:
`frappe.get_roles` appends the automatic **Desk User** role to every System User, so that
scan answers yes for everyone. `User.set_system_user` already keeps `user_type` in step
with the roles.

Consequence of the split worth knowing: field roles ship with `desk_access = 0` and office
roles without a field role, so **an account sees at most one of the two shortcuts** unless
an admin deliberately grants both.

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
