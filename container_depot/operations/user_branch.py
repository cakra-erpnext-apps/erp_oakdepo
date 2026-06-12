"""Sync a User's selected depot Branches into Frappe User Permissions.

The User doctype carries a `branch` Table MultiSelect (child: "Allowed Branch").
We mirror those picks into native **User Permission** rows on "Branch" so data is
scoped per branch with zero per-doctype code:

- empty selection  -> no Branch User Permissions -> user sees every branch
- one / many picks -> one User Permission per branch (apply_to_all_doctypes) ->
  the user only sees rows whose Branch is in the set (Frappe's native filtering),
  i.e. Container Booking, Order Bongkar/Muat, Sales Invoice, etc.

Wired from hooks `doc_events["User"]["on_update"]`, so it re-syncs on every save.
"""

import frappe

# These accounts must never be branch-restricted (avoids locking admins out).
_SKIP_USERS = {"Administrator", "Guest"}


def sync_user_branch_permissions(doc, method=None):
	"""Reconcile (user, allow=Branch) User Permission rows to match the User's
	`branch` multiselect. Idempotent: only inserts the missing ones and deletes
	the de-selected ones."""
	user = doc.name
	if user in _SKIP_USERS:
		return

	desired = {row.branch for row in (doc.get("branch") or []) if row.get("branch")}

	existing = {
		p.for_value: p.name
		for p in frappe.get_all(
			"User Permission",
			filters={"user": user, "allow": "Branch"},
			fields=["name", "for_value"],
		)
	}

	for branch in desired - set(existing):
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": user,
				"allow": "Branch",
				"for_value": branch,
				"apply_to_all_doctypes": 1,
			}
		).insert(ignore_permissions=True)

	for branch, name in existing.items():
		if branch not in desired:
			frappe.delete_doc("User Permission", name, ignore_permissions=True, force=True)


# --- branch-scoping helpers (Depot PWA) ------------------------------------
# Resolve the logged-in user's allowed branches/depots from their Branch User
# Permissions, following the same "empty selection = all branches" convention as
# the sync above. Used by every branch-scoped ESS endpoint + the Gate/EIR guards.
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
