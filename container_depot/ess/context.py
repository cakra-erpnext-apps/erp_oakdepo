"""ESS PWA user-context endpoints — who the caller is, which branches they see, and
which of the nine PWA menus they may open. Read-only."""
from __future__ import annotations

import frappe

from container_depot.api import _require_authenticated_user
from container_depot.container_depot.user_branch import get_user_branches

# The PWA menu, as (key, route, deciding doctype, ptype).
#
# This is the one hardcoded table in the role redesign, deliberately so: it maps a menu
# to a DOCTYPE, never to a role. Adding a role stays an admin action (tick
# `Role.is_depot_field_role`, grant DocPerms in Permission Manager) with no deploy.
# Adding a *menu* always needs a new Vue page anyway, so a config doctype would buy
# nothing here — unlike notification routing, which is data (Depot Notification Rule).
#
# `surveyPos` and `posFix` share one doctype and split on ptype. The discriminator for
# surveyPos is CREATE, not write, and that is not an accident: Frappe's Document.submit()
# calls save(), which checks the "write" permission, so anyone who may submit necessarily
# also has write. Splitting on write would have handed Team Kalmar the survey-recording
# menu too. Against §8.1 the create flag lands exactly right —
#   Team Survey  rwc  -> create yes, submit no  -> surveyPos only
#   Team Kalmar  rws  -> create no,  submit yes -> posFix only
#   SPV Lapangan rwcs -> both                   -> both menus
_MENU = [
	("gate",         "/gate",            "Order Bongkar",             "create"),
	("eir",          "/eir",             "Inspection",                "write"),
	("cleaning",     "/cleaning",        "Cleaning Order",            "write"),
	("mr",           "/mr",              "Repair Order",              "write"),
	("periodicTest", "/periodic-test",   "Periodic Test Order",       "write"),
	("monitor",      "/monitor",         "Container",                 "read"),
	("surveyPos",    "/survey-position", "Container Position Survey", "create"),
	("posFix",       "/position-fix",    "Container Position Survey", "submit"),
]

MENU_KEYS = [key for key, _route, _dt, _ptype in _MENU]


def _field_roles() -> set:
	"""Every Role with `is_depot_field_role` ticked.

	Uncached on purpose. It is one indexed read against a table with a few dozen rows,
	and caching it means a role ticked in the UI would not take effect until whatever
	invalidates the cache runs — which is precisely the "no deploy needed" promise the
	checkbox exists to make.

	A missing custom field (new code, not yet migrated) yields an empty set, which empties
	the PWA for everyone. That is the fail-safe direction — visibly broken beats silently
	wide open — and one migrate fixes it.
	"""
	try:
		return set(frappe.get_all("Role", filters={"is_depot_field_role": 1}, pluck="name"))
	except Exception:
		frappe.log_error(title="Role.is_depot_field_role unreadable", message=frappe.get_traceback())
		return set()


def has_field_role(user: str = None) -> bool:
	"""True when the user holds at least one Role marked as a depot field role.

	This is what keeps office staff out of the PWA without a separate "Depot PWA" role:
	they may open /depot, they just get an empty menu. Admin Ops is deliberately flagged
	too (``install.PWA_OFFICE_ROLES``) — it keeps its Desk access and gains the PWA.
	"""
	return bool(_field_roles() & set(frappe.get_roles(user or frappe.session.user)))


def has_desk_access(user: str = None) -> bool:
	"""True when this user may open the Desk — i.e. Frappe considers them a System User.

	Reads ``user_type``, which is the same gate the Desk itself applies, rather than
	scanning the user's roles for ``desk_access``. Scanning roles looks more direct but is
	circular: :func:`frappe.get_roles` appends the automatic "Desk User" role (desk_access
	= 1) to every System User, so the scan would answer "yes" for everyone it was asked
	about. ``User.set_system_user`` already derives ``user_type`` from the roles on every
	save, so this stays in step on its own — a depot field role carries desk_access = 0,
	which is exactly what demotes its users to Website User.

	Drives the "Buka Desk" shortcut in the PWA. Cosmetic: offering the link to someone
	without Desk access would only send them to a wall, and withholding it from someone who
	has access costs them a bookmark.
	"""
	user = user or frappe.session.user
	if user == "Guest":
		return False
	return frappe.permissions.is_system_user(user)


def allowed_menu(user: str = None) -> list:
	"""Menu keys this user may open. Empty for anyone without a field role."""
	if not has_field_role(user):
		return []
	return [key for key, _route, dt, ptype in _MENU if frappe.has_permission(dt, ptype, user=user)]


@frappe.whitelist(methods=["GET"])
def get_user_context():
	"""GET /api/v1/ess/user-context — {user, full_name, user_image, roles, branches, all_branches}."""
	_require_authenticated_user()
	user = frappe.session.user
	info = frappe.db.get_value("User", user, ["full_name", "user_image"], as_dict=True) or {}
	branches = get_user_branches(user)
	return {
		"success": True,
		"user": user,
		"full_name": info.get("full_name") or user,
		# The PWA falls back to initials when this is empty — see ess.profile for the writer.
		"user_image": info.get("user_image") or None,
		"roles": frappe.get_roles(user),
		"branches": branches or [],
		"all_branches": branches is None,
	}


@frappe.whitelist(methods=["GET"])
def get_menu():
	"""GET /api/v1/ess/menu — the menu keys the caller may see, plus their Desk access.

	Cosmetic only. This drives which tiles Home.vue renders and which routes the router
	lets through; nothing here stops a caller from hitting an endpoint directly. That is
	what :func:`container_depot.ess.guard.require_menu` is for.

	``desk_access`` rides along rather than getting its own endpoint: the PWA already
	fetches this once per app load, and the one screen that most needs the Desk link is
	the empty state — an office user who followed the app switcher into /depot and has
	nothing here. Making them find their way back by URL is the kind of dead end that
	turns into a support call.
	"""
	_require_authenticated_user()
	return {"success": True, "menu": allowed_menu(), "desk_access": has_desk_access()}
