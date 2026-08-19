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
| Security | Gate · Monitor |
| Team EIR | EIR · Monitor |
| Team Kalmar | Position Fix · Monitor |
| Team Cleaning | Cleaning · Monitor |
| Team Repair | M&R · Uji Periodik · Monitor |
| Team Survey | Survey Posisi · Monitor |
| SPV Lapangan | all of them |

Monitor is the read-only yard browser and follows Container read, which every field role
holds because every worklist shows container data.

**Office roles** — `desk_access = 1`, no PWA menu: Cashier, Finance, Commercial,
Warehouse, Management (read-only everywhere).

**Admin Ops** is both (`install.py::PWA_OFFICE_ROLES`): `desk_access = 1` *and*
`is_depot_field_role = 1`, so it works the Desk and the PWA. It sees **every** tile,
because the menu is derived from DocPerm and Admin Ops holds perms on every depot
doctype — narrowing that would mean cutting its Desk access too.

### Why the role picker is short

Nine apps are installed and each contributes roles to the same flat checkbox list on the
User form — 71 entries, six of them ever assigned. `install.PARKED_ROLES` tags 48 of them
with the **`Unused`** domain, which is never activated; `get_all_roles` drops any role whose
`restrict_to_domain` is not an active domain, so the picker shows **23**.

**Never use `Role.disabled` for this.** `Role.validate` routes it to `remove_roles()`, which
`db.delete`s every `Has Role` row for that role — ticking the box unassigns everyone holding
it, and unticking does not bring them back. The domain tag has the same on-screen effect and
touches no assignment.

To bring one back: clear its **Restrict To Domain** and save, or
`bench --site <site> execute container_depot.install.unpark_roles` for all of them.

Two things that will bite:

- **Never activate the `Unused` domain** — all 48 reappear at once. A test guards it.
- The five roles in `FIXTURE_OWNED_ROLES` (Gameplan ×3, TP ×2) are shipped as their app's
  fixtures, and `sync_fixtures()` runs *after* the patch queue. They are re-parked in
  `after_migrate`, so un-parking one by hand will not survive a migrate — remove it from
  that list instead.

### Assigning a user

1. Create the User as **System User**.
2. Set **Role Profile** to the one job that person does. One pick — the profile carries the
   depot role and, for office roles, the standard ERPNext companion role that goes with it:

   | Role Profile | Grants |
   |---|---|
   | Security / Team EIR / Team Kalmar / Team Cleaning / Team Repair / Team Survey / SPV Lapangan | the field role itself |
   | Admin Ops · Management | the office role itself |
   | Cashier | `Cashier` + `Accounts User` |
   | Finance | `Finance` + `Accounts Manager` |
   | Commercial | `Commercial` + `Sales Manager`, `Item Manager` |
   | Warehouse | `Warehouse` + `Stock User`, `Purchase User` |

   The companion roles are not optional extras and they are not seeded as DocPerms: the
   custom roles carry Container Depot module permissions **only**. The first Custom DocPerm
   written on a doctype makes Frappe ignore that doctype's shipped permissions entirely, so
   granting perms on Sales Invoice or Purchase Order here would silently disable ERPNext's
   own accounting and stock roles. Bundling them in the profile is how they stop being
   forgotten.

3. Optionally scope the user to a Branch (User → Branch). Empty = all branches.

Nobody holds a role until an admin assigns one, so a new account opens `/depot` and sees
an empty state until step 2 is done.

#### What a Role Profile does to a user

A profile is **authoritative, not additive**. `User.populate_role_profile_roles` sets the
user's roles to the union of their assigned profiles and drops everything else — so a role
that is in no profile the user holds disappears on their next save. Two rules follow:

- A user who needs something outside the model (chat's `Raven User`, a second depot role)
  needs it **added to a profile**, or must hold no profile at all and be assigned roles by
  hand. Adding roles to a profile is supported: `install.setup_role_profiles` is **add-only**
  and never prunes a profile back to the shipped list, so the addition survives every migrate.
- Editing a profile re-saves every user holding it, in a background job.

`setup_role_profiles` also deletes the six generic bundles ERPNext and HRMS ship
(`Accounts`, `HR`, `Inventory`, `Manufacturing`, `Purchase`, `Sales`) — they hand out
standard roles that map to no depot job, and a picker offering both "Sales" and
"Commercial" is the same wrong-box problem the parked-roles list exists to solve. Both apps
create them from `after_install` only, so they stay deleted. **A bundle a user still holds
is kept and reported instead** — deleting it would strip that user's roles with nothing left
on the account to reconstruct them from.

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
| Desk | `/depot` | **Depot Field Role (PWA)** ticked | `/desk` home tile, `/apps` tile |
| PWA | `/desk` | **Desk Access** (`user_type` = System User) | "Buka Desk" in the Home hero + on the empty state |

**Desk → PWA.** The `/desk` **home tile** — labelled **Depot OAK (Mobile)** so it is not
mistaken for the Container Depot workspace — is the primary door, and the one that does not
go through the Page:
it is a Desktop Icon of `icon_type: App` (`desktop_icon/depot_oak_(mobile).json`) pointing
straight at `/depot`. That type is deliberate — `DesktopIcon.is_permitted` honours the user's **Allow
Modules** list only for `Link` icons, so a Link tile would vanish for an operator whose Allow
Modules omits Container Depot, even though the PWA has nothing to do with Desk module access.
App icons dispatch to `www/depot.py::check_app_permission` instead, the same gate as `/apps`.
Leave its `roles` table empty: filling it shadows the hook with a static list.

The fixture's **filename must stay `frappe.scrub(label)`**, parentheses included. Every
migrate `model.sync.remove_orphan_entities` deletes any standard Desktop Icon whose scrubbed
file is missing, so relabelling without renaming the file makes the tile vanish on deploy.

**Removed 2026-08-11: the sidebar row and the workspace Shortcut card.** The Container Depot
sidebar and workspace no longer mention the PWA at all. The home tile already lands the
operator one click from `/depot` — the same place Raven's tile sits — so three doors to one
app was two too many. `test_container_depot_menus_do_not_advertise_the_pwa` pins their
absence.

If either is ever restored, restore it as a `link_type: Page` row pointing at `depot-pwa`,
never a `link_type: URL`. Frappe's `desk_views.py::is_item_allowed` returns True for "url"
unconditionally, so a URL row shows to every Desk user — including office staff who land on
an empty PWA. A `Page` carries a `roles` table and IS filtered. That is the whole reason the
Desk Page `depot-pwa` (`container_depot/page/depot_pwa/`) exists; it does nothing but
redirect.

With no menu leading there, the Page's `roles` table now guards the page itself — its
`/app/depot-pwa` URL and its awesomebar entry — which is what an old bookmark hits.
`install.setup_pwa_page_roles()` keeps those roles equal to the roles carrying
`is_depot_field_role`. It is a **full sync**, so unticking the flag closes the page; roles
hand-added to the Page are dropped (it is `standard: Yes` — tick the flag instead). Ticking a
new field role needs one `bench migrate` before the page opens; the PWA menu itself is still
instant, and so is the `/apps` tile (gated separately by
`www/depot.py::check_app_permission`).

`/depot` itself stays open to any logged-in user — see handoff §5.5 and the note in
`www/depot.py`. The shortcut is an advertisement, not the gate.

### Where a field account lands at login — `desk_landing.py`

A field role carries `desk_access = 0`, so `User.set_system_user` makes the account a
**Website User**, and `frappe/www/desk.py` answers every Website User with **Not Permitted**.
Operators were meeting that as their first screen. Two independent mechanisms put them there,
and **`Role.home_page` fixes neither** — do not reach for it:

| Route in | What decides | Why `Role.home_page` misses |
|---|---|---|
| Login response | `auth.py` → `get_default_path()` | It answers first; `get_home_page()` — the only reader of `Role.home_page` — is never called |
| The browser | `login.js` prefers `localStorage.last_visited` | Purely client-side. No server setting is consulted at all |

Worse, `Role.home_page` **leaks**: `get_home_page()` walks *every* role the user holds and
takes the first home page it finds, so setting it on Security also redirects Administrator —
who holds every role — and any supervisor holding that role beside a Desk job. Patch `v0_56`
clears it off the app's roles, and `test_the_app_roles_carry_no_home_page` keeps it clear.

#### The setting: a default on the profile, the value on the user

Two custom fields (`install.CUSTOM_FIELDS`), and the split is the whole design:

| Field | Means | Change it to… |
|---|---|---|
| `Role Profile.home_page` | the default for the **job** | move everyone still inheriting |
| `User.home_page` | the value in force for this **person** | move one person only |

`desk_landing.home_page_for()` reads the user's, then falls back to the profile's.
`remember_landing_app` copies the profile's value onto the user on save — **only when the
user's is blank**, never overwriting. So:

- re-pointing a **profile** moves everyone who has no value of their own, and only them;
- re-assigning a **person** to a different job does *not* move their landing page — theirs is
  already set. **Clear `User.home_page` to make them inherit again.**

`setup_role_profiles` seeds `/depot` on the seven field profiles and leaves the office ones
blank (blank = the Desk). **Admin Ops is deliberately blank** even though it carries the
field-role flag: it is the ops backstop, keeps `desk_access`, and works both surfaces. Only a
blank value is ever filled, so a repointed profile survives every migrate.

**Known limit — login lands on an app root.** `get_default_path` steers on `User.default_app`,
an app *name*, which it resolves to that app's *root* route; Frappe offers no lever for an
arbitrary path. `/depot` is honoured everywhere. A deeper value like `/depot/monitor` governs
the Desk redirect (which writes its own `Location`) but **login still lands on `/depot`**.
`test_login_can_only_land_on_an_app_root` pins it. Closing it would mean the PWA reading a
start route of its own.

Two guards read the resolved value:

1. **`remember_landing_app`** (User `on_update`) stamps `User.default_app`, which
   `get_default_path` checks *before* its app-count guesswork — the login landing stops being
   a function of how many apps happen to be visible. It translates the profile's *path* into
   an *app name* via `add_to_apps_screen`, which is the only currency `get_default_path`
   accepts; a path belonging to no app simply has no `default_app` to express it.
   `install.backfill_landing_app()` catches accounts that predate the hook.
2. **`redirect_field_users_off_the_desk`** (`before_request`) turns any `/desk` or `/app` hit
   by a field-role Website User into a **302** to the profile's home page. This is the only
   guard that covers `last_visited`, bookmarks, and a shared handset.

Both fall back to `/depot` for a yard account holding no profile — roles may still be assigned
by hand.

Two things that will bite:

- It must be a **`before_request`** hook. `PathResolver.resolve` short-circuits `/desk` to a
  hardcoded `TemplatePage` *before* `website_redirects` and the `page_renderer` hook, so
  neither can see the request.
- The redirect is forced to **302**. `werkzeug`'s `RequestRedirect` defaults to 308, which
  browsers cache permanently — an operator later granted Desk access would keep being bounced
  into the PWA by their own machine, with nothing left on the server to fix.

The `user_type` check is load-bearing, not a shortcut: **Admin Ops holds the field-role flag
*and* `desk_access = 1`. A guard keyed on the flag alone throws the ops backstop out of the
Desk.** `test_admin_ops_keeps_the_desk` pins it.

**PWA → Desk.** `desk_access` comes from `ess/context.py::has_desk_access`, which reads
`User.user_type`. Do not "improve" it into a scan of the user's roles for `desk_access = 1`:
`frappe.get_roles` appends the automatic **Desk User** role to every System User, so that
scan answers yes for everyone. `User.set_system_user` already keeps `user_type` in step
with the roles.

Consequence of the split worth knowing: field roles ship with `desk_access = 0` and the
office roles carry no field role, so **most accounts see at most one of the two shortcuts**.
Admin Ops is the shipped exception (see above) and sees both.

## The gate log (Gate Entry / "Riwayat Gate")

**One Gate Entry per depot visit, not one per gate event.** The record carries both
`gate_in_timestamp` and `gate_out_timestamp`; a tank that arrives and later leaves owns one
row, not two. `gate.open_gate_entry_for()` is the invariant in code: at most one record per
tank whose `status` is neither `Gate_Out_Completed` nor `Cancelled`.

| Event | Writer | Effect |
|---|---|---|
| Arrival (Tank In bon submitted) | `Order Bongkar._record_gate_in` | Opens the record — `Gate_In_Completed` |
| Arrival (SST / Hermes terminal) | `api.register_gate_entry` | Inserts **and submits** its own |
| Departure (clean EIR-Out submitted) | `Inspection.on_submit` → `gate.mark_gate_out` | Stamps the open record — `Gate_Out_Completed` + `eir_reference` |
| Bon cancelled | `Order Bongkar._release_gate_in` | Marks it `Cancelled`; never deletes |

**Fixed 2026-08-11: the arrival half was never written.** Until then `mark_gate_out` was the
only writer on the depot flow (`register_gate_entry` is reachable only by the terminals), so
every row in Riwayat Gate read as a departure and the reuse branch in
`_resolve_or_create_gate_entry` had never once fired. The arrival *was* recorded — on the bon
and on the Container Movement — just not where the gate log looks.

Records written on the depot flow stay **drafts** on purpose. `GateEntry.on_submit` forces the
container to `In_Depot` and refuses a tank already present, and both writers set the container
first — submitting would throw every time. `gate_entry_list.js` therefore sets
`has_indicator_for_draft` and reads `status`, because `frappe.get_indicator` labels any
docstatus-0 submittable doc "Draft" before it ever looks at the document's own status.

**Nobody may create one by hand.** `install.NO_MANUAL_CREATE` (Gate Entry + the audit
ledgers) strips create / submit / cancel / amend / delete from every role, including the
System Manager blanket grant; `v0_55.lock_gate_audit_doctypes` clears the flags on sites that
already had the rows. `write` deliberately survives — a mistyped truck plate on an audit row
has to stay correctable by the people at the gate. Administrator bypasses permissions entirely, so
the three list scripts also clear the list view's primary action.

In the Desk this makes Gate Entry an audit surface, and it is filed as one: **Riwayat Gate**
lives under **Audit** beside Container Movement and Container Activity. The doing-things
screen it used to sit with — **Gate Out Plan** — moved to **Bookings**, and the
"Gate & Movement" section no longer exists (sidebar and workspace both).

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

## Loading states (PWA)

Every screen that waits on the network says so, and says it in the shape of what is coming.
`.oak-skeleton` (`main.css`) is the primitive; `components/SkeletonList.vue` and
`components/SkeletonDetail.vue` are the two shared placeholders. Screens with a distinctive
layout (Home, Monitor, the worklists in Eir.vue, HistoryPage) keep their own inline skeletons
— a placeholder is only useful if it matches its content, so a generic box would be a
downgrade there.

**The rule that matters is which nothing you are replacing.**

A placeholder that REPLACES a screen shows immediately (`SkeletonDetail`, default `delay: 0`).
The detail views render behind `v-if="order"`, so before this a tap left the worklist sitting
there unchanged — read as a dead button, and on a slow handset that means tapping again.
Delaying there would only trade that for a blank page.

A placeholder that appears BELOW content still on screen holds back ~180 ms
(`utils/deferredShow.js`): `SkeletonList`, and `SkeletonDetail` at the gate lookup, which
passes `:delay="180"` explicitly. Under ~100 ms a response reads as instant, and a skeleton
painting and vanishing inside that window makes a fast app look like it is struggling.

**Detail fetches track `detailPending` / `detailFailed` explicitly**, not
`route.query.o && !order`. The derived form flickers: completing an order nulls `order` while
the query is still set, so the screen would flash a placeholder on its way back to the
worklist. A failed detail with no cached copy shows an in-page card with Kembali / Coba lagi
rather than a toast — a toast disappears and leaves the operator staring at a worklist
wondering why their tap did nothing.

**Boot splash** lives inline in `frontend/index.html`, styled with an inline `<style>` and no
Tailwind on purpose: it has to paint on the frame the HTML lands, and Tailwind arrives as a
stylesheet the browser must still fetch. It covers a real gap — Vue does not mount until
`router.isReady()`, and the first menu-gated route also awaits `fetchMenu()`. Vue clears
`#app` when it mounts over it, so there is no teardown code to keep in step. Keep the markup
free of `{{ }}`: the built file is copied to `www/depot.html` and rendered by Jinja.

## Notification click-through

Every notification leads somewhere, on all three surfaces — PWA bell, Desk bell, Web Push
banner — and one resolver answers for all of them
(`container_depot/ess/notification_routes.py`). Three tables would drift, and the drift would
only surface when an operator landed on the wrong screen.

**The event decides the destination, not the doctype.** `Order Muat` is the subject of
several events belonging to different screens: a bon was generated (Gate), a survey was
requested (Survey Posisi), a tank is held after its EIR-Out (EIR). So `notify()`
stamps the event onto the Notification Log (`depot_event`, a Custom Field) and the resolver
keys off it. Rows written before that field existed fall back to a doctype map, which is
right often enough to be useful and never claims more than it knows.

The trap this module is prone to, and the reason
`tests/test_notification_routes.py::test_no_resolver_reads_a_doctype_it_was_not_given` exists:
a resolver that looks up a *different* doctype than the notification carries finds nothing,
every time, and returns None — a dead notification that reads as perfectly good code. That
test watches which doctype each resolver actually queries, so it needs no fixtures and cannot
be satisfied by a plausible-looking route.

**Two verdicts, computed separately.** The PWA needs the menu gate — a notification must
never be a side door into a menu the operator's role does not carry, and `can_open_menu` uses
the same `_MENU` table as the tile filter and the router guard. The Desk does not: an office
account with no field role has every right to open the document on the Desk, so running it
through the PWA menu check would block a link that has always worked. Hence `allowed` /
`reason` for the PWA and `desk_allowed` / `desk_message` for the Desk. A refused document
returns no `desk_route` either — no "you may not open this, here is where it lives".

Finished work routes to Riwayat (`?open=`), open work to its form (`?o=`): a worklist only
lists open work, so sending someone to `/cleaning?o=X` for an order completed yesterday lands
them on a form that refuses to save.

The list endpoint tags rows with `openable` using a **role-level** check only — the bell polls
every minute and twenty document reads per poll is not a trade worth making for a chevron. The
authoritative check, which does load the document, runs once on the tap (`open_target`).

**Desk** is a click interceptor (`public/js/notification_click.js`, `app_include_js`) that
asks before following the link, so a recipient who cannot read the document gets a plain
reason instead of Frappe's "Insufficient Permission" page. It hangs off core markup
(`a.notification-item[data-name]`) and therefore **fails open**: if the selector stops matching
or the call fails, the click proceeds into Frappe's own permission handling exactly as before.
It is a courtesy on top of a server-side check, never the check itself.

Adding a notification event means: a row in `_BY_EVENT`, and a row in `EVENT_DOCTYPES` in the
test — which is held against `notify.py` by source scan, so an unrouted event fails the suite.

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
