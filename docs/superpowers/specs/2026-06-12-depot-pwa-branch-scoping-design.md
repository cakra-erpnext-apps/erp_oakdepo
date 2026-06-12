# Design: Depot PWA Branch-Scoping + Depot Storage UX

**Date:** 2026-06-12
**Status:** Approved (brainstorming)

## Context / Problem

The Depot OAK PWA currently shows the same data to every authenticated user regardless of which physical branch (e.g. Medan vs Surabaya) they work at. Operators see (and can act on) other branches' isotanks, occupancy, and notifications. The app already has the raw mechanism for branch membership — a `branch` multiselect on User that syncs to `User Permission (allow=Branch)` via `operations/user_branch.py` — but the PWA does not use it, and Frappe's User Permission on Branch does **not** auto-filter `Container` (Container has no branch field; it reaches Branch only via `Container.depot → Depot.branch`).

Separately, the recently shipped Depot Storage page does not scale: its single-depot toggle is awkward when one branch has up to ~5 depots, and the per-zone container list loads everything at once with no search.

## Goals

1. **Branch-scope all PWA data** (lists + notifications) to the user's allowed branch(es).
2. **Block** Gate In / EIR actions on records outside the user's branch.
3. **Redesign Okupansi Zona** as a depot **accordion** that scales to many depots.
4. **Per-zone container list**: server-side search + "load more" (infinite scroll), mobile-first.

## Decisions (from brainstorming)

- Scope **DATA only** — menu tiles stay visible to everyone; only the data inside is filtered.
- **Empty branch = all branches** (HQ/admin view), matching the existing `User.branch` convention.
- Source of truth = **User Permission (allow=Branch)** (what Frappe actually enforces), empty ⇒ all.
- Occupancy layout = **depot accordion** (summary header per depot, expand to zones-by-block).
- Per-zone list = **search + "Muat lebih"** (server-side pagination), not numbered pages.
- Gate/EIR out-of-branch lookups = **blocked** with "di luar branch Anda".

## Architecture

### 1. Branch resolution backbone — `operations/user_branch.py` (extend)
Pure helpers, used by every scoped endpoint:
- `get_user_branches(user=None) -> list[str] | None` — branches from `User Permission` (allow=Branch). Empty ⇒ `None` (= all branches).
- `get_user_depots(user=None) -> list[str] | None` — active depots whose `branch` ∈ allowed (None ⇒ all).
- `assert_in_user_branch(branch=None, depot=None)` — raise `frappe.PermissionError("Di luar branch Anda.")` when out of scope; no-op when all-branches. Resolves depot→branch when only depot is given.

### 2. User context endpoint — `ess/context.py` (new)
- `get_user_context()` → `{user, full_name, roles, branches, all_branches}`. Lets the PWA show the active branch in the Depot Storage header and label "Semua Branch" for HQ users.

### 3. Okupansi Zona — `ess/yard.py` + `DepotStorage.vue`
- `yard_overview(depot=None)`: restrict zones to `get_user_depots()`. Return `depots: [{code, name, branch, occupied, capacity, utilization, full_count, zone_count}]` (per-depot rollup for accordion headers) + the existing flat `zones`.
- `DepotStorage.vue`: replace depot toggle with a **depot accordion** — each header shows depot name + occupancy bar + %; expand reveals that depot's zones grouped by block (reuse existing zone cards). First depot auto-expanded. Page header shows the branch (or "Semua Branch"). If the user has >1 branch, show a branch tag on each depot header.

### 4. Per-zone container list — `ess/yard.py` + `DepotStorage.vue`
- `yard_zone_tanks(zone, search, start, page_length)` already delegates to `get_tank_list` (supports `start`/`page_length`/`total`/`search`). No backend change beyond branch scoping inherited from the zone.
- Zone sheet redesign: full-height bottom sheet with a **sticky debounced search** (container_no) + scrollable list + **"Muat lebih"** button that appends the next page (page_length 50) and shows "X dari Y". Search resets the list to page 0.

### 5. Notifications — `ess/notifications.py`
- `list_notifications(limit)`: for each `Notification Log`, derive its document's branch (Order Bongkar/Muat & Container Booking have `branch`; Inspection/Container via `depot`). Keep only logs whose branch ∈ allowed. All-branches ⇒ no filter. Logs whose branch can't be resolved are **kept** (don't hide system info). Batch-resolve per doctype to avoid N+1.

### 6. Gate In & EIR — block out-of-branch
- `api.gate_lookup(code)`: after resolving the booking, `assert_in_user_branch(branch=booking.branch)`.
- `operations/eir.py` (`prefill` / `open_draft` / `create_eir`): resolve container→depot→branch then `assert_in_user_branch`.

### 7. Other inventory lists — data-only scoping
- `ess/inventory.py` `get_tank_list` + `get_inventory_summary`: intersect filters with `get_user_depots()` (so every inventory list is branch-scoped). EIR History is already per-user.

## Reused building blocks
- `operations/user_branch.py` (extend, don't duplicate), existing `User Permission` sync.
- `ess/inventory.py:get_tank_list` (already paginated + search) for the zone list.
- Existing zone cards / `_zone_view` occupancy shape in `operations/yard.py`.
- `ess/notifications.py` Notification Log reads; `api.gate_lookup`; `operations/eir.py`.

## Testing
- Backend `FrappeTestCase`: two users (branch=Medan, branch=all) + data across two branches. Assert: `get_user_branches/get_user_depots/assert_in_user_branch`; `yard_overview` & `get_tank_list` scoped; `list_notifications` filtered; `gate_lookup` & EIR raise PermissionError out-of-branch; zone list pagination + search.
- Frontend: build + manual check — accordion expand/collapse, branch header, zone search + "Muat lebih".

## Edge cases
- All-branches/Administrator: no filtering anywhere.
- Multi-branch user: accordion lists depots from all their branches; depot headers tagged with branch.
- 100+ tanks in one zone: server-side pagination (50/page) keeps it light.
- Notification with unresolvable branch: shown (conservative).

## Out of scope (v1)
- Hiding menu tiles by role/branch (decided: data-only).
- A branch switcher control (HQ users just see everything; revisit if requested).
