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

## Booking attribution

Which Container Booking did this work belong to? Answered by `container_booking` on
Inspection, Cleaning Order, Repair Order and Periodic Test Order — derived in
`container_depot/booking_link.py`, surfaced on the booking's **Connections** tab
(`container_booking_dashboard.py`).

The chain: `Container Booking → Order Bongkar (.booking) → Inspection (.referred_voucher)
→ Cleaning Order / Repair Order (.inspection)`. The EIR resolves it once and the orders
below copy it, so a bon re-pointed after a cancel carries its orders with it.

**One rule, and it is the whole design: only an EIR reference confers parentage.** An order
raised on its own — walk-in cleaning, ad-hoc repair, scheduled periodic test — stays blank.
There is deliberately **no** fall-back to the container's most recent booking: a single tank
appears on as many as 52 bookings, so a guess files real work under a visit that never
happened. Blank means "raised outside a booking", which is true and searchable.

The field is editable so an operator can attribute what the automation could not, but a
hand-set booking must actually list the container (`assert_booking_covers_container`) — a
booking that never carried this tank is a typo, not an intention. A value already present
is never re-derived; clearing it lets the EIR fill it again.

`patches/v0_53/backfill_container_booking.py` recovers pre-existing rows by walking the same
chain, and leaves unresolvable ones blank rather than guessing.

### Where it shows up

| Surface | Shape |
|---|---|
| Container Booking → **Pekerjaan per Container** section | One block per container ROW, its work in one timeline (EIR → cleaning → repair), plus a count of that tank's unattributed orders |
| Container Booking → **Connections** tab | The same records as four flat per-doctype lists |

The section is the one to reach for on a multi-container booking: Connections cannot say
which EIR belongs to which tank. Served by `container_booking.orders_by_container`, rendered
by `_render_work_per_container` in `container_booking.js`.

Containers with no work still get a block ("nothing has happened yet" is an answer), and
unattributed orders are **counted, never listed as members** — surfacing them as candidates
is useful, folding them in would be the guess the rule above refuses to make.

Note when adding a doctype to `_WORK_SOURCES`: the date fields are not all one type
(Inspection dates a Date, the work orders a Datetime), so the timeline sort coerces through
`get_datetime` — comparing them raw raises TypeError and takes the whole panel down.

## Offline (PWA)

The yard has dead spots. Three separate problems, three mechanisms — do not merge them:

| Problem | Mechanism | Lifetime |
|---|---|---|
| The tab died / battery went flat | `data/drafts.js` — form state to IndexedDB on every keystroke | disposable, pruned at 14 days |
| There is no signal (writing) | `data/outbox.js` — the finished submission, queued | never dropped by a timer |
| There is no signal (reading) | `data/cache.js` — the last good answer to each GET | convenience, pruned at 7 days / 300 entries |

The read cache is not an optimisation, it is the other half of the feature. Every screen
starts with a worklist fetched from the server; with no cached answer the operator sees an
empty list, never reaches the form, and so never reaches the queue. Without it the queue only
ever helps someone whose signal died *while a form was already open*.

Two rules `cachedResource` will not bend. **Only a request that got no answer is served from
cache** — a server that replied "you may not do that" is a real answer and must reach the
operator (`looksOffline` tests for a missing `.response`, plus 5xx). And **entries are scoped
to the logged-in user** and dropped on a change of login, because depot handsets get passed
between shifts and one operator's branch-scoped worklist is not the next one's.

`data/menu.js` caches by hand for the same reason: an empty menu means no tiles and a router
guard that refuses every route. Safe because the menu is presentation only — `ess/guard.py`
re-checks every endpoint, so a stale entry can show a tile that refuses on tap but can never
grant anything.

**Photos are not uploaded when picked.** They are shrunk (`utils/photo.js`, 1600 px / q0.82,
roughly 15x) and parked in IndexedDB, and the form carries a `local:<uuid>` reference that
behaves like a file_url. Render one with `photoSrc()`; never bind a raw ref to `:src`. The
outbox uploads the blob, substitutes the real URL into the payload, and only then saves the
document — one atomic row, so uploads can never succeed while the save never does.

IndexedDB, not localStorage, and this is not a preference: localStorage caps at ~5 MB,
holds strings only (base64, +33%) and is synchronous. One 12 MP photo exceeds the whole
budget.

**Every queued write carries a `request_id`** (`ess/idempotency.py`). This is the load-bearing
part. The dangerous case is not being offline — nothing happened — it is LAG: the request
lands, the work is done, the response is lost coming back, and a naive retry raises a second
EIR, issues the same parts from stock twice, or advances a test due-date by a second interval.
Any new endpoint the outbox may replay must be wrapped in `guarded(request_id, ...)` **and
added to `REPLAYED_ENDPOINTS` in `tests/test_idempotency.py`** — that list is held to both
rules (takes the kwarg, and actually honours it), so a signature that accepts `request_id`
without wrapping the call fails there rather than in the yard.

Server autosave still runs when there is a link, so the Desk sees live progress, but
`local:` references are stripped from it — writing one into an Inspection Photo row would be
a broken image for ever. They travel with the final queued submit instead.

### What each menu does offline

| Menu | Offline |
|---|---|
| EIR In / Out | full — worklist, form, photos, Mulai, submit |
| Cleaning | full — worklist, form, QC photos, signature, Mulai, Selesaikan |
| M&R · Uji Periodik | full — worklist, detail, Mulai, Selesaikan |
| Survey Posisi · Position Fix | full — worklist, detail, photos, save / approve |
| Siap Keluar | full — queue readable, ACC queued |
| Monitor · Riwayat | readable from cache |
| Sortir Foto | readable from cache, assignment queued |
| **Gate** | **no** — see below |

**Gate is deliberately online-only.** Issuing a bon needs a live read of the booking's payment
and block status, and a bon issued against a stale "Paid" is a financial error. So the screen
says so up front (`labels.gateNeedsOnline`) instead of letting the operator scan and fail. It
still carries a `request_id`, minted when the vehicle form opens rather than per click — on a
slow link the operator presses Generate, sees nothing, and presses again, and that second
press must be recognised as the same bon.

**A queued action leaves its worklist immediately.** `enqueue({ref})` names the document and
`outbox.refs` exposes the set; each worklist filters on `isQueued`. Without it the server's
answer — which has not heard about the queued work — puts the finished job straight back in
front of the operator, and it gets done twice. `ref` goes on terminal actions only: a queued
"Mulai" must leave the order in the list.

**Gate-out is queued, and that is a real trade.** The server's guards (open work holding the
tank, branch scope) only run when the queue drains, so an invalid release surfaces as a failed
row in the queue panel rather than as a refusal at the barrier. Accepted deliberately: holding
a truck at the gate because a handset cannot reach the server jams every truck behind it, and
the discrepancy is at least visible.

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
