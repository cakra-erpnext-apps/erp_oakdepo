"""Depot Service Menu — a dynamic, group-based filter over the Item catalog.

Items already carry an **Item Group**; a *menu* (Booking / Cleaning / Maintenance /
…) is just a named collection of Item Groups (plus optional individual extra items).
"Items in menu X" = items whose Item Group (or a descendant of it) is listed in the
menu, OR that are pinned in the menu's ``extra_items``. This keeps setup near-zero
(map the handful of groups once) while staying dynamic — new menus are added in Desk.

Deliberately free of ``@frappe.whitelist`` (mirrors operations/mr.py): the endpoint
layer (ess/ and the Depot Contract controller) adds auth + whitelisting.

Reads the menu via ``get_cached_doc`` (no permission enforcement) so the PWA M&R
picker can filter by menu under the caller's session without extra DocPerms.
"""

from __future__ import annotations

import frappe
from frappe.utils.nestedset import get_descendants_of

# --- the default menus --------------------------------------------------------
# One menu per flow whose item picker is scoped by a price list: Booking (lift), Cleaning,
# Maintenance (M&R), Survey and Periodic Test. A flow missing from here has its filter buried
# in code, where no operator can see or change it — which is how Survey Order and Periodic
# Test Order ended up offering the whole catalogue.
#
# The menus ship with NO Item Groups on purpose. Production has no Item Prices registered
# yet, so any mapping guessed here would be fiction — and the old seeder proved the failure
# mode: it named the placeholder groups from patches.v0_11.seed_item_groups, those groups
# were later replaced by the customer's real rate-card groups, and every fresh install
# silently got a Cleaning and a Maintenance menu pointing at nothing.
#
# An empty menu does not filter (``is_real_menu`` -> False), so each picker stays open until
# an operator maps the groups in Desk. Dev sites get a realistic mapping from
# ``seed_dev.MENUS`` instead of a migration.
DEFAULT_MENUS = ("Booking", "Cleaning", "Maintenance", "Survey", "Periodic Test")

DEFAULT_SEQUENCE = {"Booking": 1, "Cleaning": 2, "Maintenance": 3, "Survey": 4, "Periodic Test": 5}


def seed_default_menus() -> int:
	"""Ensure the default menus exist (empty, active). Returns the number created.

	Creates only what is missing and never touches an existing menu — not its groups, not its
	sequence, not its active flag. Mapping groups is the operator's job (or the dev seeder's);
	a migration that re-asserted them would undo the pruning an operator had just done.
	"""
	created = 0
	for menu_name in DEFAULT_MENUS:
		if frappe.db.exists("Depot Service Menu", menu_name):
			continue
		doc = frappe.new_doc("Depot Service Menu")
		doc.menu_name = menu_name
		doc.is_active = 1
		doc.sequence = DEFAULT_SEQUENCE.get(menu_name, 0)
		doc.insert(ignore_permissions=True)
		created += 1
	if created:
		frappe.db.commit()
	return created


def _active_menu(menu_name):
	"""Return the active Depot Service Menu doc, or None when missing / inactive."""
	if not menu_name or not frappe.db.exists("Depot Service Menu", menu_name):
		return None
	doc = frappe.get_cached_doc("Depot Service Menu", menu_name)
	return doc if doc.is_active else None


def _menu_groups(menu_name) -> list:
	"""Every Item Group in the menu, expanded to include descendant groups (Item
	Group is a tree, so a parent group implies its children)."""
	doc = _active_menu(menu_name)
	if not doc:
		return []
	groups: set = set()
	for row in doc.get("item_groups") or []:
		if not row.item_group:
			continue
		groups.add(row.item_group)
		# Include descendants so a parent group covers its children.
		try:
			groups.update(get_descendants_of("Item Group", row.item_group))
		except Exception:
			pass
	return list(groups)


def _menu_extra_items(menu_name) -> list:
	doc = _active_menu(menu_name)
	if not doc:
		return []
	return [row.item for row in (doc.get("extra_items") or []) if row.item]


def is_real_menu(menu_name) -> bool:
	"""True when the menu exists, is active, and actually constrains anything
	(has at least one group or extra item). Empty / missing menus don't filter."""
	if not _active_menu(menu_name):
		return False
	return bool(_menu_groups(menu_name) or _menu_extra_items(menu_name))


def filter_items_by_menu(item_codes, menu_name) -> list:
	"""Narrow ``item_codes`` to those belonging to ``menu_name``.

	An item belongs when its Item Group is in the menu's groups (incl. descendants)
	or it is pinned in ``extra_items``. When the menu is missing / inactive / empty,
	returns ``item_codes`` unchanged (safe fallback — never hides everything)."""
	codes = [c for c in (item_codes or []) if c]
	if not codes or not is_real_menu(menu_name):
		return codes

	extras = set(_menu_extra_items(menu_name))
	groups = _menu_groups(menu_name)
	in_group: set = set()
	if groups:
		in_group = set(
			frappe.get_all(
				"Item",
				filters={"name": ["in", codes], "item_group": ["in", groups]},
				pluck="name",
			)
		)
	return [c for c in codes if c in in_group or c in extras]


def items_in_menu(menu_name, txt=None, base_price_list=None, limit=500) -> list:
	"""Items belonging to ``menu_name`` (group-derived + extra_items), optionally
	restricted to those with a selling Item Price in ``base_price_list`` and matched
	against ``txt``. Returns dicts ``{item_code, item_name, item_group}``."""
	groups = _menu_groups(menu_name)
	extras = _menu_extra_items(menu_name)
	if not groups and not extras:
		return []

	# Candidate set = items priced in the base list (when given), else all items.
	if base_price_list:
		candidate = frappe.get_all(
			"Item Price",
			filters={"price_list": base_price_list, "selling": 1},
			pluck="item_code",
			distinct=True,
		)
	else:
		candidate = frappe.get_all("Item", filters={"disabled": 0}, pluck="name")
	if not candidate:
		return []

	# Resolve which candidates fall in the menu (group-derived ∪ pinned extras).
	codes = set(filter_items_by_menu(candidate, menu_name))
	codes |= {e for e in extras if e in set(candidate)}
	if not codes:
		return []

	filters = {"name": ["in", list(codes)], "disabled": 0}
	or_filters = None
	txt = (txt or "").strip()
	if txt and txt.lower() != "undefined":
		or_filters = {"item_code": ["like", f"%{txt}%"], "item_name": ["like", f"%{txt}%"]}
	return frappe.get_all(
		"Item",
		filters=filters,
		or_filters=or_filters,
		fields=["name as item_code", "item_name", "item_group"],
		order_by="item_name asc",
		limit_page_length=limit,
	)


def menus_for_item(item_code) -> list:
	"""Reverse lookup — the names of active menus this item belongs to (for display)."""
	if not item_code:
		return []
	item_group = frappe.db.get_value("Item", item_code, "item_group")
	out = []
	for menu_name in active_menus_names():
		if item_code in _menu_extra_items(menu_name):
			out.append(menu_name)
		elif item_group and item_group in _menu_groups(menu_name):
			out.append(menu_name)
	return out


def active_menus_names() -> list:
	return frappe.get_all(
		"Depot Service Menu",
		filters={"is_active": 1},
		pluck="name",
		order_by="sequence asc, menu_name asc",
	)


def active_menus() -> list:
	"""Active menus as ``{name, menu_name, description}`` dicts for selectors."""
	return frappe.get_all(
		"Depot Service Menu",
		filters={"is_active": 1},
		fields=["name", "menu_name", "description"],
		order_by="sequence asc, menu_name asc",
	)
