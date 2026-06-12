# Depot PWA Branch-Scoping + Depot Storage UX — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scope every Depot PWA list + notification to the logged-in user's branch, block Gate/EIR actions on out-of-branch records, and rebuild Depot Storage's occupancy as a scalable depot accordion with a searchable, paginated per-zone container list.

**Architecture:** A small server-side backbone (`operations/user_branch.py`) resolves the user's allowed branches/depots from `User Permission (allow=Branch)` (empty ⇒ all). Existing ESS read endpoints intersect their filters with `get_user_depots()`; Gate/EIR call `assert_in_user_branch()`. The Vue PWA gains a depot-accordion occupancy view and an infinite-scroll zone list, and learns the active branch from a new `get_user_context` endpoint.

**Tech Stack:** Frappe v16 (Python 3.14), Vue 3 + Vite + frappe-ui (PWA under `container_depot/frontend`), dockerized bench (`cakra_erpnext-frappe-1`, site `$SITE_NAME`).

**Conventions:**
- Run tests: `docker exec cakra_erpnext-frappe-1 bash -lc 'cd /home/frappe/frappe-bench && bench --site $SITE_NAME run-tests --module container_depot.tests.<mod>'`
- Migrate: `docker exec cakra_erpnext-frappe-1 bash -lc 'cd /home/frappe/frappe-bench && bench --site $SITE_NAME migrate'`
- Build PWA: `docker exec cakra_erpnext-frappe-1 bash -lc 'cd /home/frappe/frappe-bench/apps/container_depot/frontend && yarn build'`
- `frappe.get_all` ignores User Permissions (admin-level); `frappe.get_list` respects them. Branch scoping here is **explicit** (via `get_user_depots`), so it works regardless of which is used.
- Commits: follow the repo owner's commit policy at execution time; commit steps below are logical checkpoints.

---

## File Structure

**Backend (create):**
- `container_depot/container_depot/ess/context.py` — `get_user_context()` PWA endpoint.
- `container_depot/container_depot/tests/test_branch_scoping.py` — all backend tests for this feature.

**Backend (modify):**
- `container_depot/container_depot/operations/user_branch.py` — add `get_user_branches`, `get_user_depots`, `assert_in_user_branch`.
- `container_depot/container_depot/operations/yard.py` — `zone_occupancy(depots=...)` accepts a depot list; add per-depot rollup helper.
- `container_depot/container_depot/ess/yard.py` — `yard_overview` scopes to user depots + returns depot rollup.
- `container_depot/container_depot/ess/inventory.py` — `get_tank_list` + `get_inventory_summary` intersect with user depots.
- `container_depot/container_depot/ess/notifications.py` — `list_notifications` branch filter.
- `container_depot/container_depot/api.py` — `gate_lookup` blocks out-of-branch.
- `container_depot/container_depot/operations/eir.py` — `prefill`/`open_draft`/`create_eir` block out-of-branch.

**Frontend (modify):**
- `container_depot/frontend/src/data/context.js` — new: fetch `get_user_context` (active branch/roles).
- `container_depot/frontend/src/pages/DepotStorage.vue` — depot accordion + zone list search/"Muat lebih" + branch header.
- `container_depot/frontend/src/utils/labels.js` — new strings.

---

## Task 1: Branch resolution helpers

**Files:**
- Modify: `container_depot/container_depot/operations/user_branch.py`
- Test: `container_depot/container_depot/tests/test_branch_scoping.py`

- [ ] **Step 1: Write the failing test**

Create `container_depot/container_depot/tests/test_branch_scoping.py`:

```python
"""Branch-scoping backbone + scoped ESS endpoints (Depot PWA branch filter)."""
from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.operations.user_branch import (
	get_user_branches,
	get_user_depots,
	assert_in_user_branch,
)

BR_MEDAN = "Oak Depot Medan"
BR_SBY = "Oak Depot Surabaya"
USER_MEDAN = "branchtest_medan@oak.local"
USER_ALL = "branchtest_all@oak.local"


def _ensure_branch(name):
	if not frappe.db.exists("Branch", name):
		frappe.get_doc({"doctype": "Branch", "branch": name}).insert(ignore_permissions=True)


def _ensure_depot(code, name, branch):
	if not frappe.db.exists("Depot", code):
		frappe.get_doc({
			"doctype": "Depot", "depot_code": code, "depot_name": name,
			"branch": branch, "is_active": 1,
		}).insert(ignore_permissions=True)
	else:
		frappe.db.set_value("Depot", code, "branch", branch)


def _ensure_user(email, branches):
	if not frappe.db.exists("User", email):
		frappe.get_doc({
			"doctype": "User", "email": email, "first_name": email.split("@")[0],
			"send_welcome_email": 0, "roles": [{"role": "System Manager"}],
		}).insert(ignore_permissions=True)
	frappe.db.delete("User Permission", {"user": email, "allow": "Branch"})
	for b in branches:
		frappe.get_doc({
			"doctype": "User Permission", "user": email, "allow": "Branch",
			"for_value": b, "apply_to_all_doctypes": 1,
		}).insert(ignore_permissions=True)


def _build_scoping_fixtures():
	_ensure_branch(BR_MEDAN)
	_ensure_branch(BR_SBY)
	_ensure_depot("BST_MD1", "Branch Test Medan 1", BR_MEDAN)
	_ensure_depot("BST_SB1", "Branch Test Surabaya 1", BR_SBY)
	_ensure_user(USER_MEDAN, [BR_MEDAN])
	_ensure_user(USER_ALL, [])  # no branch UP = all branches
	frappe.db.commit()


def _teardown_scoping_fixtures():
	for u in (USER_MEDAN, USER_ALL):
		frappe.db.delete("User Permission", {"user": u})
		if frappe.db.exists("User", u):
			frappe.delete_doc("User", u, force=True, ignore_permissions=True)
	for d in ("BST_MD1", "BST_SB1"):
		if frappe.db.exists("Depot", d):
			frappe.db.delete("Depot", {"name": d})
	frappe.db.commit()


class TestBranchHelpers(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		_teardown_scoping_fixtures()
		_build_scoping_fixtures()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		_teardown_scoping_fixtures()
		super().tearDownClass()

	def test_branches_for_scoped_user(self):
		self.assertEqual(get_user_branches(USER_MEDAN), [BR_MEDAN])

	def test_branches_none_for_unscoped_user(self):
		self.assertIsNone(get_user_branches(USER_ALL))

	def test_depots_for_scoped_user(self):
		depots = get_user_depots(USER_MEDAN)
		self.assertIn("BST_MD1", depots)
		self.assertNotIn("BST_SB1", depots)

	def test_depots_none_for_unscoped_user(self):
		self.assertIsNone(get_user_depots(USER_ALL))

	def test_assert_in_branch_passes_for_own_depot(self):
		frappe.set_user(USER_MEDAN)
		try:
			assert_in_user_branch(depot="BST_MD1")  # no raise
		finally:
			frappe.set_user("Administrator")

	def test_assert_in_branch_blocks_other_depot(self):
		frappe.set_user(USER_MEDAN)
		try:
			with self.assertRaises(frappe.PermissionError):
				assert_in_user_branch(depot="BST_SB1")
		finally:
			frappe.set_user("Administrator")

	def test_assert_in_branch_noop_for_all_user(self):
		frappe.set_user(USER_ALL)
		try:
			assert_in_user_branch(depot="BST_SB1")  # no raise (all branches)
		finally:
			frappe.set_user("Administrator")
```

- [ ] **Step 2: Run it, verify it fails**

Run: `docker exec cakra_erpnext-frappe-1 bash -lc 'cd /home/frappe/frappe-bench && bench --site $SITE_NAME run-tests --module container_depot.tests.test_branch_scoping'`
Expected: ImportError / AttributeError — `get_user_branches` not defined in `user_branch.py`.

- [ ] **Step 3: Implement the helpers**

Append to `container_depot/container_depot/operations/user_branch.py`:

```python
from frappe import _

_ALL_BRANCHES = None  # sentinel meaning "no restriction"


def get_user_branches(user=None):
	"""Branches the user is restricted to (User Permission allow=Branch).

	Returns a list of Branch names, or ``None`` when the user has no Branch
	permission at all — the established convention that an empty selection means
	'all branches' (HQ/admin view). Administrator/Guest are always unrestricted.
	"""
	user = user or frappe.session.user
	if user in ("Administrator", "Guest"):
		return _ALL_BRANCHES
	branches = frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": "Branch"},
		pluck="for_value",
	)
	return branches or _ALL_BRANCHES


def get_user_depots(user=None):
	"""Active depots whose branch is in the user's allowed branches.

	Returns ``None`` (no restriction) when the user is unrestricted, else a list
	of Depot names (may be empty if the branch has no depots).
	"""
	branches = get_user_branches(user)
	if branches is _ALL_BRANCHES:
		return None
	return frappe.get_all(
		"Depot", filters={"branch": ["in", branches], "is_active": 1}, pluck="name"
	)


def assert_in_user_branch(branch=None, depot=None, user=None):
	"""Raise PermissionError if the given branch/depot is outside the user's scope.

	No-op for unrestricted users. When only ``depot`` is given, its branch is
	resolved first. A blank branch/depot is treated as in-scope (nothing to block).
	"""
	allowed = get_user_branches(user)
	if allowed is _ALL_BRANCHES:
		return
	if not branch and depot:
		branch = frappe.db.get_value("Depot", depot, "branch")
	if branch and branch not in allowed:
		frappe.throw(_("Di luar branch Anda."), frappe.PermissionError)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `docker exec cakra_erpnext-frappe-1 bash -lc 'cd /home/frappe/frappe-bench && bench --site $SITE_NAME run-tests --module container_depot.tests.test_branch_scoping'`
Expected: 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add container_depot/container_depot/operations/user_branch.py container_depot/container_depot/tests/test_branch_scoping.py
git commit -m "feat(pwa): branch resolution helpers (get_user_branches/depots, assert_in_user_branch)"
```

---

## Task 2: `get_user_context` endpoint

**Files:**
- Create: `container_depot/container_depot/ess/context.py`
- Test: add to `container_depot/container_depot/tests/test_branch_scoping.py`

- [ ] **Step 1: Write the failing test** (append a class)

```python
from container_depot.ess.context import get_user_context


class TestUserContext(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		_teardown_scoping_fixtures()
		_build_scoping_fixtures()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		_teardown_scoping_fixtures()
		super().tearDownClass()

	def test_context_scoped_user(self):
		frappe.set_user(USER_MEDAN)
		try:
			ctx = get_user_context()
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(ctx["user"], USER_MEDAN)
		self.assertEqual(ctx["branches"], [BR_MEDAN])
		self.assertFalse(ctx["all_branches"])

	def test_context_all_user(self):
		frappe.set_user(USER_ALL)
		try:
			ctx = get_user_context()
		finally:
			frappe.set_user("Administrator")
		self.assertTrue(ctx["all_branches"])
		self.assertEqual(ctx["branches"], [])

	def test_context_rejects_guest(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				get_user_context()
		finally:
			frappe.set_user("Administrator")
```

- [ ] **Step 2: Run, verify fail** — ImportError on `ess.context`.

- [ ] **Step 3: Implement** — create `container_depot/container_depot/ess/context.py`:

```python
"""ESS PWA user-context endpoint — tells the frontend the active user's branch
scope so it can label the Depot Storage header and adapt the UI. Read-only."""
from __future__ import annotations

import frappe

from container_depot.api import _require_authenticated_user
from container_depot.operations.user_branch import get_user_branches


@frappe.whitelist(methods=["GET"])
def get_user_context():
	"""GET /api/v1/ess/user-context — {user, full_name, roles, branches, all_branches}."""
	_require_authenticated_user()
	user = frappe.session.user
	branches = get_user_branches(user)
	return {
		"success": True,
		"user": user,
		"full_name": frappe.db.get_value("User", user, "full_name") or user,
		"roles": frappe.get_roles(user),
		"branches": branches or [],
		"all_branches": branches is None,
	}
```

- [ ] **Step 4: Run tests, verify pass** (3 new tests PASS).

- [ ] **Step 5: Commit**

```bash
git add container_depot/container_depot/ess/context.py container_depot/container_depot/tests/test_branch_scoping.py
git commit -m "feat(pwa): get_user_context endpoint exposing user branch scope"
```

---

## Task 3: Branch-scope inventory lists

**Files:**
- Modify: `container_depot/container_depot/ess/inventory.py` (`get_tank_list` ~line 184, `get_inventory_summary` ~line 145)
- Test: append to `test_branch_scoping.py`

- [ ] **Step 1: Write failing test** (append a class; reuse fixtures, add containers)

```python
from container_depot.ess.inventory import get_tank_list, get_inventory_summary


class TestInventoryScoping(FrappeTestCase):
	TANKS = {"BSTU0000001": "BST_MD1", "BSTU0000002": "BST_SB1"}

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		_teardown_scoping_fixtures()
		_build_scoping_fixtures()
		for no, depot in cls.TANKS.items():
			if not frappe.db.exists("Container", no):
				frappe.get_doc({
					"doctype": "Container", "container_no": no, "container_type": "ISO Tank",
					"status": "Available", "depot": depot,
				}).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.db.delete("Container Movement", {"container": ["in", list(cls.TANKS)]})
		frappe.db.delete("Container", {"name": ["in", list(cls.TANKS)]})
		_teardown_scoping_fixtures()
		super().tearDownClass()

	def test_tank_list_scoped_to_branch(self):
		frappe.set_user(USER_MEDAN)
		try:
			res = get_tank_list()
		finally:
			frappe.set_user("Administrator")
		nos = {i["container_no"] for i in res["items"]}
		self.assertIn("BSTU0000001", nos)
		self.assertNotIn("BSTU0000002", nos)

	def test_tank_list_blocks_out_of_branch_depot_param(self):
		frappe.set_user(USER_MEDAN)
		try:
			res = get_tank_list(depot="BST_SB1")  # explicitly asking other branch
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(res["items"], [])

	def test_tank_list_unscoped_sees_all(self):
		frappe.set_user(USER_ALL)
		try:
			res = get_tank_list()
		finally:
			frappe.set_user("Administrator")
		nos = {i["container_no"] for i in res["items"]}
		self.assertTrue({"BSTU0000001", "BSTU0000002"} <= nos)
```

- [ ] **Step 2: Run, verify fail** — `test_tank_list_scoped_to_branch` fails (sees both tanks).

- [ ] **Step 3: Implement.** In `ess/inventory.py`, add import at top:

```python
from container_depot.operations.user_branch import get_user_depots
```

Add a shared helper near the top of the module:

```python
def _apply_user_depot_scope(filters, depot):
	"""Intersect a Container query's depot filter with the user's allowed depots.

	Returns the (possibly updated) filters dict, or None to signal 'no results'
	(the requested depot is outside the user's branch scope)."""
	allowed = get_user_depots()
	if allowed is None:
		if depot:
			filters["depot"] = depot
		return filters
	if depot:
		if depot not in allowed:
			return None
		filters["depot"] = depot
	else:
		filters["depot"] = ["in", allowed]
	return filters
```

In `get_tank_list`, replace the `if depot: filters["depot"] = depot` block with:

```python
	scoped = _apply_user_depot_scope(filters, depot)
	if scoped is None:
		return {"success": True, "total": 0, "start": start, "page_length": page_length, "items": []}
	filters = scoped
```

In `get_inventory_summary`, replace `if depot: filters["depot"] = depot` with:

```python
	scoped = _apply_user_depot_scope(filters, depot)
	if scoped is None:
		return {"success": True, "counts": {b: 0 for b in BUCKETS}, "periodic_test_due": 0, "total": 0}
	filters = scoped
```

- [ ] **Step 4: Run tests, verify pass.**

- [ ] **Step 5: Commit**

```bash
git add container_depot/container_depot/ess/inventory.py container_depot/container_depot/tests/test_branch_scoping.py
git commit -m "feat(pwa): branch-scope tank list + inventory summary by user depots"
```

---

## Task 4: Branch-scoped occupancy + per-depot rollup

**Files:**
- Modify: `container_depot/container_depot/operations/yard.py` (`zone_occupancy` ~line 136)
- Modify: `container_depot/container_depot/ess/yard.py` (`yard_overview`)
- Test: append to `test_branch_scoping.py`

- [ ] **Step 1: Write failing test**

```python
from container_depot.ess.yard import yard_overview


class TestYardOverviewScoping(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		_teardown_scoping_fixtures()
		_build_scoping_fixtures()
		for code, depot in (("BSTZ-MD", "BST_MD1"), ("BSTZ-SB", "BST_SB1")):
			if not frappe.db.exists("Yard Zone", code):
				frappe.get_doc({
					"doctype": "Yard Zone", "zone_code": code, "zone_name": code,
					"depot": depot, "category": "Ready", "capacity": 10,
					"max_rows": 5, "max_rows_full": 6, "max_tiers": 5, "is_active": 1,
				}).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.db.delete("Yard Zone", {"name": ["in", ["BSTZ-MD", "BSTZ-SB"]]})
		_teardown_scoping_fixtures()
		super().tearDownClass()

	def test_overview_scoped_to_branch_depots(self):
		frappe.set_user(USER_MEDAN)
		try:
			res = yard_overview()
		finally:
			frappe.set_user("Administrator")
		zone_codes = {z["zone_code"] for z in res["zones"]}
		self.assertIn("BSTZ-MD", zone_codes)
		self.assertNotIn("BSTZ-SB", zone_codes)
		depot_codes = {d["code"] for d in res["depots"]}
		self.assertIn("BST_MD1", depot_codes)
		self.assertNotIn("BST_SB1", depot_codes)

	def test_overview_depot_rollup_fields(self):
		frappe.set_user(USER_MEDAN)
		try:
			res = yard_overview()
		finally:
			frappe.set_user("Administrator")
		md = next(d for d in res["depots"] if d["code"] == "BST_MD1")
		for key in ("name", "branch", "occupied", "capacity", "utilization", "full_count", "zone_count"):
			self.assertIn(key, md)
		self.assertEqual(md["zone_count"], 1)
		self.assertEqual(md["capacity"], 10)
```

- [ ] **Step 2: Run, verify fail** — overview returns both zones / depots lack rollup fields.

- [ ] **Step 3: Implement.** In `operations/yard.py`, change `zone_occupancy` to accept a depot list:

```python
def zone_occupancy(depot=None, depots=None):
	"""Occupancy per active Yard Zone, optionally restricted to one depot (``depot``)
	or a set of depots (``depots``). ``depots=[]`` yields no rows (empty scope)."""
	filters = {"is_active": 1}
	if depot:
		filters["depot"] = depot
	elif depots is not None:
		if not depots:
			return []
		filters["depot"] = ["in", depots]
	zones = frappe.get_all(
		"Yard Zone",
		filters=filters,
		fields=[
			"name", "zone_name", "depot", "block", "category",
			"capacity", "max_rows", "max_rows_full", "max_tiers",
		],
		order_by="depot asc, block asc, name asc",
	)
	occupancy = _occupancy_map([z.name for z in zones])
	return [_zone_view(z, occupancy.get(z.name, 0)) for z in zones]
```

Add a rollup helper in `operations/yard.py`:

```python
def depot_rollup(zone_views):
	"""Aggregate zone occupancy into per-depot summaries for the accordion headers."""
	by_depot = {}
	for z in zone_views:
		d = by_depot.setdefault(z["depot"], {"occupied": 0, "capacity": 0, "full_count": 0, "zone_count": 0})
		d["occupied"] += z["occupied"]
		d["capacity"] += z["capacity"] or 0
		d["full_count"] += 1 if z["is_full"] else 0
		d["zone_count"] += 1
	out = {}
	for code, d in by_depot.items():
		util = round((d["occupied"] / d["capacity"]) * 100, 1) if d["capacity"] else None
		out[code] = {**d, "utilization": util}
	return out
```

In `ess/yard.py`, import and rewrite `yard_overview`:

```python
from container_depot.operations.user_branch import get_user_depots
```

```python
@frappe.whitelist(methods=["GET"])
def yard_overview(depot=None):
	"""GET /api/v1/ess/yard-overview — branch-scoped zones + per-depot rollup."""
	_require_authenticated_user()
	allowed = get_user_depots()
	if depot and allowed is not None and depot not in allowed:
		return {"success": True, "zones": [], "depots": []}
	zones = yard.zone_occupancy(depot=depot, depots=None if depot else allowed)

	rollup = yard.depot_rollup(zones)
	codes = list(dict.fromkeys(z["depot"] for z in zones if z["depot"]))
	meta = {
		d.name: d
		for d in frappe.get_all(
			"Depot", filters={"name": ["in", codes]}, fields=["name", "depot_name", "branch"]
		)
	} if codes else {}
	depots = [
		{
			"code": c,
			"name": meta.get(c, frappe._dict()).depot_name or c,
			"branch": meta.get(c, frappe._dict()).branch,
			**rollup.get(c, {"occupied": 0, "capacity": 0, "utilization": None, "full_count": 0, "zone_count": 0}),
		}
		for c in codes
	]
	return {"success": True, "zones": zones, "depots": depots}
```

- [ ] **Step 4: Run tests, verify pass.** Also re-run existing yard tests (must stay green):

`docker exec cakra_erpnext-frappe-1 bash -lc 'cd /home/frappe/frappe-bench && bench --site $SITE_NAME run-tests --module container_depot.tests.test_yard'`

- [ ] **Step 5: Commit**

```bash
git add container_depot/container_depot/operations/yard.py container_depot/container_depot/ess/yard.py container_depot/container_depot/tests/test_branch_scoping.py
git commit -m "feat(pwa): branch-scope yard_overview + per-depot occupancy rollup"
```

---

## Task 5: Block Gate lookup out-of-branch

**Files:**
- Modify: `container_depot/container_depot/api.py` (`gate_lookup` ~line 1011, `_booking_gate_detail` ~line 954)
- Test: append to `test_branch_scoping.py`

- [ ] **Step 1: Write failing test.** (Create a booking in BR_SBY; a Medan user lookup must be blocked. Reuse the repo's booking helper.)

```python
from container_depot.api import gate_lookup
from container_depot.tests._booking_helpers import make_booking_code


class TestGateBranchBlock(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		_teardown_scoping_fixtures()
		_build_scoping_fixtures()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		_teardown_scoping_fixtures()
		super().tearDownClass()

	def test_gate_lookup_blocks_other_branch(self):
		# A booking whose branch is Surabaya; a Medan-scoped user must be rejected.
		code = make_booking_code(container_no="BSTU0000050", direction="Tank In")
		frappe.db.set_value("Container Booking", code.parent_booking, "branch", BR_SBY) \
			if hasattr(code, "parent_booking") else None
		frappe.db.commit()
		frappe.set_user(USER_MEDAN)
		try:
			res = gate_lookup(code=code.code if hasattr(code, "code") else code.name)
		finally:
			frappe.set_user("Administrator")
		# Out-of-branch lookups return an error payload (valid is False / error set).
		self.assertFalse(res.get("valid", False))
```

> NOTE for implementer: inspect `make_booking_code` (in `tests/_booking_helpers.py`) and `_resolve_booking_from_code` to wire the booking's `branch` field exactly. The assertion only requires that a Medan user gets a non-valid result for a Surabaya booking. Adjust fixture plumbing to match the helper's real return shape.

- [ ] **Step 2: Run, verify fail** — lookup currently succeeds across branches.

- [ ] **Step 3: Implement.** In `api.py`, import:

```python
from container_depot.operations.user_branch import assert_in_user_branch
```

In `_booking_gate_detail(booking)`, after the booking branch is known (it reads `branch` into the detail), guard early:

```python
	branch = frappe.db.get_value("Container Booking", booking, "branch")
	try:
		assert_in_user_branch(branch=branch)
	except frappe.PermissionError:
		return {"valid": False, "error": frappe._("Booking ini di luar branch Anda.")}
```

(Place this at the start of `_booking_gate_detail`, before building the panel, so out-of-branch bookings never expose container/payment data.)

- [ ] **Step 4: Run tests, verify pass.** Re-run `test_api`-adjacent gate tests if any: `... run-tests --module container_depot.tests.test_phase4`.

- [ ] **Step 5: Commit**

```bash
git add container_depot/container_depot/api.py container_depot/container_depot/tests/test_branch_scoping.py
git commit -m "feat(pwa): block gate lookup for out-of-branch bookings"
```

---

## Task 6: Block EIR out-of-branch

**Files:**
- Modify: `container_depot/container_depot/operations/eir.py` (`prefill`, `open_draft`, `create_eir`)
- Test: append to `test_branch_scoping.py`

- [ ] **Step 1: Write failing test**

```python
from container_depot.operations.eir import prefill


class TestEirBranchBlock(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		_teardown_scoping_fixtures()
		_build_scoping_fixtures()
		if not frappe.db.exists("Container", "BSTU0000060"):
			frappe.get_doc({
				"doctype": "Container", "container_no": "BSTU0000060", "container_type": "ISO Tank",
				"status": "Available", "depot": "BST_SB1",  # Surabaya
			}).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.db.delete("Container Movement", {"container": "BSTU0000060"})
		frappe.db.delete("Container", {"name": "BSTU0000060"})
		_teardown_scoping_fixtures()
		super().tearDownClass()

	def test_eir_prefill_blocks_other_branch(self):
		frappe.set_user(USER_MEDAN)
		try:
			with self.assertRaises(frappe.PermissionError):
				prefill(container_no="BSTU0000060")
		finally:
			frappe.set_user("Administrator")
```

- [ ] **Step 2: Run, verify fail** — prefill returns data instead of raising.

- [ ] **Step 3: Implement.** In `operations/eir.py`, import:

```python
from container_depot.operations.user_branch import assert_in_user_branch
```

Add a tiny guard helper and call it once the container is resolved in `prefill`, `open_draft`, and `create_eir` (each resolves a Container/container_no early):

```python
def _guard_container_branch(container_name):
	depot = frappe.db.get_value("Container", container_name, "depot")
	assert_in_user_branch(depot=depot)
```

Call `_guard_container_branch(<resolved container name>)` immediately after each function resolves its container (before building/creating). For `create_eir`, place it after the container is resolved and before insert.

> NOTE for implementer: read each function to find the exact variable holding the resolved Container `name` and insert the guard there. Do not change return shapes.

- [ ] **Step 4: Run tests, verify pass.** Re-run EIR suite: `... run-tests --module container_depot.tests.test_eir`.

- [ ] **Step 5: Commit**

```bash
git add container_depot/container_depot/operations/eir.py container_depot/container_depot/tests/test_branch_scoping.py
git commit -m "feat(pwa): block EIR actions on out-of-branch containers"
```

---

## Task 7: Branch-filter notifications

**Files:**
- Modify: `container_depot/container_depot/ess/notifications.py` (`list_notifications`)
- Test: append to `test_branch_scoping.py`

- [ ] **Step 1: Write failing test.** (Create two Notification Logs for USER_MEDAN, one referencing a Surabaya Order Bongkar, one a Medan one; only Medan's should survive.)

```python
from container_depot.ess.notifications import list_notifications


class TestNotificationScoping(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		_teardown_scoping_fixtures()
		_build_scoping_fixtures()
		# Minimal Order Bongkar rows carrying a branch (no submit needed for branch read).
		cls.ob = {}
		for key, branch in (("md", BR_MEDAN), ("sb", BR_SBY)):
			ob = frappe.get_doc({"doctype": "Order Bongkar", "branch": branch}).insert(ignore_permissions=True)
			cls.ob[key] = ob.name
			frappe.get_doc({
				"doctype": "Notification Log", "for_user": USER_MEDAN, "subject": f"OB {key}",
				"document_type": "Order Bongkar", "document_name": ob.name, "type": "Alert",
			}).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.db.delete("Notification Log", {"for_user": USER_MEDAN})
		for name in cls.ob.values():
			frappe.delete_doc("Order Bongkar", name, force=True, ignore_permissions=True)
		_teardown_scoping_fixtures()
		super().tearDownClass()

	def test_notifications_scoped_to_branch(self):
		frappe.set_user(USER_MEDAN)
		try:
			res = list_notifications()
		finally:
			frappe.set_user("Administrator")
		subjects = {i["subject"] for i in res["items"]}
		self.assertIn("OB md", subjects)
		self.assertNotIn("OB sb", subjects)
```

> NOTE for implementer: confirm `Order Bongkar` can be inserted as a bare draft with only `branch` (it may require other mandatory fields). If so, set the minimal mandatory fields, or branch-stamp an existing test booking instead. The assertion is the contract: a Surabaya-document notification is filtered out for a Medan user.

- [ ] **Step 2: Run, verify fail** — both notifications returned.

- [ ] **Step 3: Implement.** In `ess/notifications.py`, import:

```python
from container_depot.operations.user_branch import get_user_branches
```

Add a branch resolver + filter. Map each notifiable doctype to how its branch is found:

```python
# doctype -> ("field", <branch fieldname>) or ("depot", <depot fieldname>)
_BRANCH_SOURCE = {
	"Order Bongkar": ("field", "branch"),
	"Order Muat": ("field", "branch"),
	"Container Booking": ("field", "branch"),
	"Inspection": ("depot", "depot"),
	"Container": ("depot", "depot"),
}


def _doc_branch(doctype, name):
	"""Best-effort branch for a notification's source document; None if unknown."""
	src = _BRANCH_SOURCE.get(doctype)
	if not src or not name:
		return None
	kind, field = src
	val = frappe.db.get_value(doctype, name, field)
	if not val:
		return None
	return val if kind == "field" else frappe.db.get_value("Depot", val, "branch")


def _filter_by_branch(items):
	allowed = get_user_branches()
	if allowed is None:
		return items
	allowed = set(allowed)
	kept = []
	for it in items:
		b = _doc_branch(it.get("document_type"), it.get("document_name"))
		if b is None or b in allowed:  # unknown branch -> keep (conservative)
			kept.append(it)
	return kept
```

In `list_notifications`, wrap the items before returning:

```python
	items = _filter_by_branch(items)
	# recompute unread off the filtered set if unread is derived from items;
	# otherwise leave the per-user unread count as-is.
```

> NOTE for implementer: read `list_notifications` to see how `items`/`unread` are built and apply `_filter_by_branch(items)` to the returned list (and adjust the `unread` count to count only filtered-unread if that's the current contract).

- [ ] **Step 4: Run tests, verify pass.**

- [ ] **Step 5: Commit**

```bash
git add container_depot/container_depot/ess/notifications.py container_depot/container_depot/tests/test_branch_scoping.py
git commit -m "feat(pwa): branch-filter PWA notifications by source document branch"
```

---

## Task 8: Frontend — user-context data + branch header

**Files:**
- Create: `container_depot/frontend/src/data/context.js`
- Modify: `container_depot/frontend/src/utils/labels.js`
- Modify: `container_depot/frontend/src/pages/DepotStorage.vue` (header)

- [ ] **Step 1: Create the context resource** — `container_depot/frontend/src/data/context.js`:

```javascript
import { createResource } from "frappe-ui"

// Active user's branch scope (for headers / labels). Cached for the session.
export const userContext = createResource({
	url: "container_depot.ess.context.get_user_context",
	cache: "user_context",
	auto: false,
})

export function branchLabel() {
	const d = userContext.data
	if (!d) return ""
	if (d.all_branches) return "Semua Branch"
	return (d.branches || []).join(", ") || "Semua Branch"
}
```

- [ ] **Step 2: Add labels** — in `container_depot/frontend/src/utils/labels.js`, inside the storage block:

```javascript
	storageBranch: "Branch", // branch label in the storage header
	storageLoadMore: "Muat lebih", // load more
	storageSearchTank: "Cari nomor container…", // search containers in a zone
	storageShowing: "menampilkan", // "X dari Y menampilkan"
	storageOf: "dari", // X dari Y
```

- [ ] **Step 3: Show branch in the Depot Storage header.** In `DepotStorage.vue` `<script setup>` add:

```javascript
import { userContext, branchLabel } from "@/data/context"
import { onMounted } from "vue"
onMounted(() => { if (!userContext.data) userContext.reload() })
const branch = computed(() => branchLabel())
```

In the header template (next to the title), add:

```html
<span v-if="branch" class="oak-chip bg-gray-100 text-gray-600">{{ labels.storageBranch }}: {{ branch }}</span>
```

- [ ] **Step 4: Build, verify no errors**

Run: `docker exec cakra_erpnext-frappe-1 bash -lc 'cd /home/frappe/frappe-bench/apps/container_depot/frontend && yarn build'`
Expected: build succeeds; `DepotStorage` chunk emitted.

- [ ] **Step 5: Commit**

```bash
git add container_depot/frontend/src/data/context.js container_depot/frontend/src/utils/labels.js container_depot/frontend/src/pages/DepotStorage.vue
git commit -m "feat(pwa): user-context resource + branch header on Depot Storage"
```

---

## Task 9: Frontend — depot accordion + zone list search/pagination

**Files:**
- Modify: `container_depot/frontend/src/pages/DepotStorage.vue`

- [ ] **Step 1: Replace the occupancy section with a depot accordion.** Swap the depot-toggle + single-depot grid for an accordion driven by `overviewRes.data.depots` (rollup) + `zones` grouped per depot then block. Script additions:

```javascript
const expandedDepot = ref(null) // which depot accordion is open
const overviewDepots = computed(() => overviewRes.data?.depots || [])

// zones grouped: depot -> [{ block, zones }]
function blocksForDepot(code) {
	const zones = (overviewRes.data?.zones || []).filter((z) => z.depot === code)
	const byBlock = new Map()
	for (const z of zones) {
		const k = z.block || ""
		if (!byBlock.has(k)) byBlock.set(k, [])
		byBlock.get(k).push(z)
	}
	return [...byBlock.keys()]
		.sort((a, b) => {
			const ia = BLOCK_ORDER.indexOf(a), ib = BLOCK_ORDER.indexOf(b)
			return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib)
		})
		.map((block) => ({ block, zones: byBlock.get(block) }))
}

function depotBar(d) {
	if (!d.capacity) return d.occupied ? "100%" : "0%"
	return Math.min(100, Math.round((d.occupied / d.capacity) * 100)) + "%"
}
function depotBarClass(d) {
	const u = d.utilization
	if (u == null) return "bg-gray-300"
	if (u >= 90) return "bg-red-500"
	if (u >= 70) return "bg-amber-500"
	return "bg-leaf-500"
}
```

In `overviewRes.onSuccess`, auto-expand the first depot:

```javascript
	onSuccess(data) {
		if (!expandedDepot.value && data?.depots?.length) expandedDepot.value = data.depots[0].code
	},
```

Template (replaces the toggle + grouped grid):

```html
<section class="space-y-2">
	<p class="oak-section-title">{{ labels.storageOccupancy }}</p>
	<p v-if="overviewRes.loading" class="oak-card p-6 text-center text-sm text-gray-400">{{ labels.loading }}</p>
	<p v-else-if="!overviewDepots.length" class="oak-card p-6 text-center text-sm text-gray-400">{{ labels.storageNoZones }}</p>
	<div v-else class="space-y-2">
		<div v-for="d in overviewDepots" :key="d.code" class="oak-card overflow-hidden">
			<button class="flex w-full items-center gap-3 px-4 py-3 text-left" @click="expandedDepot = expandedDepot === d.code ? null : d.code">
				<Icon :name="expandedDepot === d.code ? 'chevron-down' : 'chevron-right'" :size="18" class="shrink-0 text-gray-400" />
				<div class="min-w-0 flex-1">
					<div class="flex items-center justify-between gap-2">
						<p class="truncate text-sm font-bold text-gray-900">{{ d.name }}</p>
						<span class="shrink-0 text-xs font-medium" :class="d.full_count ? 'text-red-600' : 'text-gray-500'">
							{{ d.occupied }}/{{ d.capacity || "∞" }}<span v-if="d.utilization != null"> · {{ d.utilization }}%</span>
						</span>
					</div>
					<div class="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-gray-100">
						<div class="h-full rounded-full" :class="depotBarClass(d)" :style="{ width: depotBar(d) }"></div>
					</div>
				</div>
			</button>
			<div v-if="expandedDepot === d.code" class="space-y-2 border-t border-gray-100 px-3 py-3">
				<div v-for="g in blocksForDepot(d.code)" :key="g.block || 'none'" class="space-y-2">
					<p v-if="g.block" class="px-1 text-xs font-semibold uppercase tracking-wide text-gray-400">{{ g.block }}</p>
					<div class="grid gap-2 sm:grid-cols-2">
						<button v-for="z in g.zones" :key="z.zone_code" class="oak-card oak-press space-y-2 p-3 text-left" @click="openZone(z)">
							<div class="flex items-start justify-between gap-2">
								<p class="text-sm font-bold text-gray-900">{{ z.zone_name }}</p>
								<span class="oak-chip shrink-0 bg-gray-100 text-gray-600">{{ categoryLabel(z.category) }}</span>
							</div>
							<div class="h-2 w-full overflow-hidden rounded-full bg-gray-100">
								<div class="h-full rounded-full" :class="barClass(z)" :style="{ width: barWidth(z) }"></div>
							</div>
							<p class="text-xs font-medium" :class="z.is_full ? 'text-red-600' : 'text-gray-500'">
								{{ z.occupied }}/{{ z.capacity || "∞" }}<span v-if="z.utilization != null"> · {{ z.utilization }}%</span>
							</p>
						</button>
					</div>
				</div>
			</div>
		</div>
	</div>
</section>
```

Remove the now-unused `depots`/`activeDepot`/`groupedZones` toggle code.

- [ ] **Step 2: Add search + "Muat lebih" to the zone tank sheet.** Script — replace single-shot load with accumulating pagination:

```javascript
const zoneSearch = ref("")
const zoneItems = ref([])
const zoneTotal = ref(0)
const zoneStart = ref(0)
const ZONE_PAGE = 50
let zoneSearchTimer = null

function loadZonePage(reset) {
	if (reset) { zoneStart.value = 0; zoneItems.value = [] }
	zoneTanksRes.submit({
		zone: zoneModal.value.zone_code,
		search: zoneSearch.value || undefined,
		start: zoneStart.value,
		page_length: ZONE_PAGE,
	}).then((data) => {
		zoneItems.value = reset ? data.items : zoneItems.value.concat(data.items)
		zoneTotal.value = data.total
		zoneStart.value += data.items.length
	})
}

function openZone(z) {
	zoneModal.value = z
	zoneSearch.value = ""
	loadZonePage(true)
}

function onZoneSearch() {
	clearTimeout(zoneSearchTimer)
	zoneSearchTimer = setTimeout(() => loadZonePage(true), 300)
}

const zoneHasMore = computed(() => zoneItems.value.length < zoneTotal.value)
```

Template — in the zone sheet body, add a sticky search and replace the static list with `zoneItems` + a "Muat lebih" button:

```html
<div class="border-b border-gray-100 p-3">
	<input v-model="zoneSearch" type="text" :placeholder="labels.storageSearchTank" class="oak-input" @input="onZoneSearch" />
</div>
<div class="flex-1 overflow-y-auto px-4 py-3">
	<p v-if="zoneTanksRes.loading && !zoneItems.length" class="py-6 text-center text-sm text-gray-400">{{ labels.loading }}</p>
	<p v-else-if="!zoneItems.length" class="py-6 text-center text-sm text-gray-400">{{ labels.storageNoTanks }}</p>
	<template v-else>
		<ul class="divide-y divide-gray-100">
			<li v-for="t in zoneItems" :key="t.name" class="flex items-center gap-3 py-2.5">
				<span class="oak-icon-tile h-8 w-8 shrink-0 bg-gray-100 text-gray-400"><Icon name="package" :size="16" /></span>
				<div class="min-w-0 flex-1">
					<p class="truncate font-semibold text-gray-900">{{ t.container_no }}</p>
					<p v-if="t.principal" class="truncate text-xs text-gray-500">{{ t.principal }}</p>
				</div>
				<span class="oak-chip shrink-0" :class="statusColors[t.status]">{{ statusLabel(t.status) }}</span>
			</li>
		</ul>
		<button v-if="zoneHasMore" class="oak-btn oak-btn-secondary mt-3 w-full" :disabled="zoneTanksRes.loading" @click="loadZonePage(false)">
			{{ zoneTanksRes.loading ? "…" : labels.storageLoadMore }}
		</button>
		<p class="mt-2 text-center text-xs text-gray-400">{{ zoneItems.length }} {{ labels.storageOf }} {{ zoneTotal }}</p>
	</template>
</div>
```

Update the sheet header count to use `zoneTotal`. Remove the old `zoneTanks` computed.

- [ ] **Step 3: Build, verify no errors**

Run: `docker exec cakra_erpnext-frappe-1 bash -lc 'cd /home/frappe/frappe-bench/apps/container_depot/frontend && yarn build'`
Expected: build succeeds.

- [ ] **Step 4: Manual smoke (record result).** Load `/depot` → Depot Storage. Verify: branch chip in header; depot accordion expands/collapses with summary bars; tap a zone → search filters, "Muat lebih" appends, "X dari Y" updates.

- [ ] **Step 5: Commit**

```bash
git add container_depot/frontend/src/pages/DepotStorage.vue
git commit -m "feat(pwa): depot-accordion occupancy + searchable paginated zone list"
```

---

## Task 10: Full regression + verification

- [ ] **Step 1: Run the whole backend suite**

Run: `docker exec cakra_erpnext-frappe-1 bash -lc 'cd /home/frappe/frappe-bench && bench --site $SITE_NAME run-tests --app container_depot'`
Expected: all green (existing + new `test_branch_scoping`).

- [ ] **Step 2: Migrate (no schema changes expected, sanity only) + build**

Run migrate + `yarn build`; both succeed.

- [ ] **Step 3: Live spot-check with a scoped user.** Create/confirm a User with branch=one branch + a User Permission; via `bench console`, `frappe.set_user(...)` and call `container_depot.ess.yard.yard_overview()` and `container_depot.ess.context.get_user_context()` — confirm only that branch's depots appear.

- [ ] **Step 4: Final commit (if any residual)**

```bash
git add -A && git commit -m "test(pwa): branch-scoping regression green"
```

---

## Self-Review Notes
- **Spec coverage:** §1 backbone→T1; §2 context→T2; §3 occupancy→T4+T9; §4 list→T9; §5 notifications→T7; §6 gate/EIR→T5+T6; §7 other lists→T3. All covered.
- **Type consistency:** `get_user_branches`→`None`|list; `get_user_depots`→`None`|list; `assert_in_user_branch(branch=,depot=)`; `yard_overview` returns `{zones, depots:[{code,name,branch,occupied,capacity,utilization,full_count,zone_count}]}`; frontend reads those exact keys. Consistent.
- **Implementer NOTEs** flag the three spots that need reading the real function bodies (booking helper shape, EIR container-resolution variable, notification items/unread contract) rather than guessing — intentional, not placeholders.
