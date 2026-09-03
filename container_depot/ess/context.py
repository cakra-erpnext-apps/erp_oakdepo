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
# `surveyPos` and `posFix` share one doctype and split on ptype, and since the workflow was
# reversed (lowering first, survey second — see ``tank_survey``) the split runs the other way
# round from how it used to.
#
# `posFix` is the LOWERING queue and keys on WRITE, because marking a tank lowered is a save.
# `surveyPos` is the surveyor's calendar and keys on SUBMIT, because closing the last tank on a
# day submits its Survey Order (``survey_order.refresh_progress``).
#
# Frappe's Document.submit() calls save(), so anyone holding submit necessarily holds write —
# which means the submit key is strictly the narrower of the two and the overlap falls exactly
# where it should. Against the §8.1 matrix —
#   Team Kalmar  rw   -> write yes, submit no  -> posFix only
#   Team Survey  rws  -> both                  -> both menus
#   SPV Lapangan rwcs -> both                  -> both menus
#
# Team Survey holding BOTH is the deliberate part: a surveyor already standing at a tank that
# is plainly on the ground marks it down themselves rather than waiting for an operator to open
# their phone. Only the closing is theirs alone.
#
# `tankPos` is a THIRD menu over a different doctype entirely, and it is open to every field
# team on purpose — see ``ess/container_position.py``. Where a tank stands is not the survey's
# private business: it is the one fact every crew in the yard needs and every crew can correct.
#
# `schedule` is the one entry whose doctype slot holds a TUPLE, and it is an ANY-OF: the
# universal Jadwal calendar opens for anyone who can read at least one kind of planned work,
# and then shows only the kinds they can actually read (container_depot.schedule._visible_sources).
# Written as a tuple rather than as four menu keys because it is one screen — four keys would
# mean four tiles racing to render the same calendar.
SCHEDULE_DOCTYPES = ("Survey Order", "Cleaning Order", "Repair Order", "Container Booking")

_MENU = [
	("gate",         "/gate",            "Order Bongkar",      "create"),
	("eir",          "/eir",             "Inspection",         "write"),
	("cleaning",     "/cleaning",        "Cleaning Order",     "write"),
	("mr",           "/mr",              "Repair Order",       "write"),
	("monitor",      "/monitor",         "Container",          "read"),
	("schedule",     "/schedule",        SCHEDULE_DOCTYPES,    "read"),
	("surveyList",   "/survey-orders",   "Survey Order",       "read"),
	("surveyPos",    "/survey-orders",   "Survey Order",       "submit"),
	("posFix",       "/position-fix",    "Survey Order",       "write"),
	("tankPos",      "/tank-position",   "Container Position", "create"),
]

MENU_KEYS = [key for key, _route, _dt, _ptype in _MENU]


def _may(dt, ptype, user=None) -> bool:
	"""Permission for one menu entry, where the doctype slot may be one name or several.

	Several means ANY of them is enough — the only entry that uses it is the universal
	calendar, and "you may see the schedule" there means "you may see at least one thing on
	it". Filtering WHAT you see is a separate job done per source, one layer down.
	"""
	names = dt if isinstance(dt, (tuple, list)) else (dt,)
	return any(frappe.has_permission(name, ptype, user=user) for name in names)


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
	return [key for key, _route, dt, ptype in _MENU if _may(dt, ptype, user=user)]


def depot_roles(user: str = None) -> list:
	"""The user's roles that are depot roles, sorted, e.g. ["SPV Lapangan", "Team EIR"].

	The PWA names the account by what it does ("Team Cleaning") rather than by its menu
	list. `frappe.get_roles` also returns All / Guest / Desk User and whatever ERPNext
	roles the account carries alongside, none of which say anything about depot work —
	so the answer is intersected with the same `is_depot_field_role` set that decides
	whether the PWA opens at all. An account with none (office staff) gets [], which is
	the same signal as the empty menu.
	"""
	return sorted(_field_roles() & set(frappe.get_roles(user or frappe.session.user)))


@frappe.whitelist(methods=["GET"])
def get_user_context():
	"""GET /api/v1/ess/user-context — {user, full_name, user_image, roles, depot_roles,
	branches, all_branches}."""
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
		"depot_roles": depot_roles(user),
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
