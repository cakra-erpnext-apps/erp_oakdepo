"""Scope an external customer account to its own company's records.

A customer login is an ordinary Frappe user holding the `Customer Desk` role plus a
**User Permission** ``allow=Customer`` naming the company it belongs to — written by
``portal.sync_portal_user_permission`` when a `Customer Portal User` row goes Active.
That single row is the company flag; there is no user group and no second doctype.

Frappe applies it natively to any doctype carrying a Link to Customer
(``db_query.add_user_permissions``), which covers Depot Contract, Container and
Container Activity for free. This module fills the two holes that leaves:

1. **Doctypes with no Customer link at all.** Gate Entry (its ``container_no`` is plain
   Data), Container Movement and Item Price are not touched by User Permissions, so a
   customer would read the whole depot's gate history. They are filtered here, by
   walking one link to the owning record.

2. **Doctypes with SEVERAL Customer links.** ``add_user_permissions`` joins one
   condition per link field with **and**, not or — so on Container Booking
   (customer + principal + surveyor) a booking billed to PT Cakra but shipped for
   another principal would vanish from PT Cakra's own list. The link fields that are not
   the ownership test carry ``ignore_user_permissions`` in their doctype JSON, and the
   or-condition this file returns replaces them.

Both halves run through ``frappe.get_list``, so the same conditions also scope the Desk
list views, the Number Cards and the Dashboard Charts with nothing extra: a number card
whose doctype the customer cannot read is already dropped by Frappe
(``number_card.get_permission_query_conditions``).

Internal staff hold no Customer User Permission, so every function here returns None for
them and nothing changes.
"""

from __future__ import annotations

import frappe

# Modules a customer account may read outside the depot: what the Desk itself is built
# from — files, comments, notes, list settings, dashboards, print formats — and nothing
# else. `Contacts` and `Geo` are deliberately NOT here; Contact and Address are other
# customers' data, and no depot form a customer can open needs to pick one. See
# `foreign_doctype_*` at the bottom of this file for what this list is for.
_DESK_PLUMBING_MODULES = {"Core", "Custom", "Desk", "Printing"}

# Doctypes outside the Container Depot module that the customer role is granted outright
# (install.CUSTOMER_STANDARD_DOCPERMS) — their own rate card.
_ALLOWED_FOREIGN_DOCTYPES = {"Price List", "Item Price"}

# Core doctypes the Desk plumbing would otherwise carry through, kept shut anyway.
#
# `Report` is the load-bearing one, and it is what makes the REPORT LINKS DISAPPEAR from
# the workspace cards and the left sidebar instead of erroring when clicked. Both menus
# ask `boot.get_allowed_reports`, which ends by running `frappe.get_list("Report", ...)`
# and dropping every report that query does not return (`non_permitted_reports`) — so the
# condition below empties the list, and a menu entry nobody may open is never drawn. The
# customer role holds no `report` permission (see the `v` grammar in install.py), so
# without this the link renders and then throws "You don't have permission to get a report
# on: <doctype>" — a menu that exists only to refuse is worse than no menu.
_DENIED_CORE_DOCTYPES = {"Report"}

_SKIP_USERS = {"Administrator", "Guest"}


def get_user_customers(user: str | None = None) -> list[str] | None:
	"""Customers this user is restricted to, or ``None`` when unrestricted.

	Mirrors the convention in ``user_branch.get_user_branches``: no User Permission at
	all means no restriction (that is every internal account), NOT "sees nothing".
	"""
	user = user or frappe.session.user
	if user in _SKIP_USERS:
		return None
	# Frappe's own cached reader, not a fresh query: these functions run on every list
	# load, every dashboard number and every document open.
	permissions = frappe.permissions.get_user_permissions(user) or {}
	customers = [
		p.get("doc") for p in permissions.get("Customer", []) if not p.get("applicable_for")
	]
	return customers or None


def _values(user: str | None) -> str | None:
	"""Escaped, comma-joined customer names for an SQL ``in`` clause."""
	customers = get_user_customers(user)
	if not customers:
		return None
	return ", ".join(frappe.db.escape(c, percent=False) for c in customers)


def _owned_containers(values: str) -> str:
	return f"(select `name` from `tabContainer` where `principal` in ({values}))"


# --- permission_query_conditions (list views, reports, cards, charts) -------


def gate_entry_query(user=None, doctype=None) -> str:
	"""Gate Entry has no Customer link — join through its tank's principal.

	``Container.container_no`` is the doctype's autoname, so ``container_no`` on the gate
	row IS the Container's primary key.
	"""
	values = _values(user)
	if not values:
		return ""
	return f"`tabGate Entry`.`container_no` in {_owned_containers(values)}"


def container_movement_query(user=None, doctype=None) -> str:
	values = _values(user)
	if not values:
		return ""
	return f"`tabContainer Movement`.`container` in {_owned_containers(values)}"


def container_booking_query(user=None, doctype=None) -> str:
	"""Billed-to OR tank owner. See the module docstring on and-vs-or."""
	values = _values(user)
	if not values:
		return ""
	return (
		f"(`tabContainer Booking`.`customer` in ({values})"
		f" or `tabContainer Booking`.`principal` in ({values}))"
	)


def price_list_query(user=None, doctype=None) -> str:
	"""Only the customer's OWN rate card.

	Strict on purpose, with no "or the field is empty" arm: a Price List with no customer
	is a shared/standard OAK rate card (`Standard Selling`), and those are not an external
	party's business. That is the opposite of Frappe's own default for User Permissions,
	which does let an empty link through.
	"""
	values = _values(user)
	if not values:
		return ""
	return f"`tabPrice List`.`customer` in ({values})"


def item_price_query(user=None, doctype=None) -> str:
	"""Item Price carries no customer — it is owned by the Price List above it."""
	values = _values(user)
	if not values:
		return ""
	return (
		"`tabItem Price`.`price_list` in"
		f" (select `name` from `tabPrice List` where `customer` in ({values}))"
	)


# --- has_permission (opening one document directly) ------------------------
# A query condition only guards the list. Frappe routes a single-document read through
# has_permission, so every doctype filtered above needs the same test again here.
#
# A controller hook can only DENY (frappe.permissions.has_controller_permissions treats a
# falsy return — None included — as a refusal), so each of these returns True explicitly.


def _allowed(value: str | None, user: str | None) -> bool:
	customers = get_user_customers(user)
	return not customers or value in customers


def _principal_of(container: str | None) -> str | None:
	return frappe.db.get_value("Container", container, "principal") if container else None


def gate_entry_permission(doc, ptype=None, user=None, **kwargs) -> bool:
	return _allowed(_principal_of(doc.get("container_no")), user)


def container_movement_permission(doc, ptype=None, user=None, **kwargs) -> bool:
	return _allowed(_principal_of(doc.get("container")), user)


def container_booking_permission(doc, ptype=None, user=None, **kwargs) -> bool:
	customers = get_user_customers(user)
	if not customers:
		return True
	return doc.get("customer") in customers or doc.get("principal") in customers


def price_list_permission(doc, ptype=None, user=None, **kwargs) -> bool:
	return _allowed(doc.get("customer"), user)


def item_price_permission(doc, ptype=None, user=None, **kwargs) -> bool:
	customers = get_user_customers(user)
	if not customers:
		return True
	return frappe.db.get_value("Price List", doc.get("price_list"), "customer") in customers


# --- the rest of the site --------------------------------------------------
# A customer account is a System User, and a System User inherits every doctype the stock
# `All` / `Desk User` roles can read — which on this site includes another app's support
# tickets (HD Ticket), staff leave ledgers, Quality records and a pile of integration
# settings. Blocking the modules (portal._restrict_modules) takes those off the sidebar; it
# does not stop someone typing /app/hd-ticket. These two close the doctype itself.
#
# An allowlist, not a list of the offenders: the next app installed adds its own doctypes
# to that inheritance, and a deny-list would not know about them.


def _is_foreign(doctype: str | None) -> bool:
	if not doctype or doctype in _ALLOWED_FOREIGN_DOCTYPES:
		return False
	if doctype in _DENIED_CORE_DOCTYPES:
		return True
	module = frappe.get_cached_value("DocType", doctype, "module")
	if module == "Container Depot":
		return False  # its own DocPerm decides — the customer role holds six of them
	return module not in _DESK_PLUMBING_MODULES


def foreign_doctype_query(user=None, doctype=None) -> str:
	"""Empty every list outside the depot for a customer account (hooks `*`)."""
	if not get_user_customers(user) or not _is_foreign(doctype):
		return ""
	return "1=0"


def foreign_doctype_permission(doc, ptype=None, user=None, **kwargs) -> bool:
	if not get_user_customers(user):
		return True
	return not _is_foreign(doc.get("doctype"))
