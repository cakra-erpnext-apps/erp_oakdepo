"""Take the landing page off the app's Roles; it lives on the Role Profile now.

``Role.home_page`` is Frappe's built-in way to say "send this person here after login", and
it cannot be scoped to the people you meant. ``website/utils.py::get_home_page`` walks EVERY
role a user holds and returns the first home page it finds, so setting ``/depot`` on Security
also redirected **Administrator** — who holds every role — and any supervisor holding that
role alongside a Desk job. It was set on this site while chasing the "Not Permitted on login"
bug, and it never fixed that bug either: for a Website User, ``auth.py`` resolves the landing
through ``get_default_path()``, which answers before ``get_home_page()`` is ever called.

The replacement is a ``home_page`` custom field on **Role Profile** (see
``install.CUSTOM_FIELDS`` and ``desk_landing.py``): one job, one profile, one landing page,
no collateral.

Scoped to the app's own roles. A role belonging to ERPNext or another app may be using this
field deliberately and is none of our business.
"""

import frappe

from container_depot.install import FIELD_ROLES, OFFICE_ROLES


def execute():
	if not frappe.db.has_column("Role", "home_page"):
		return
	for role in FIELD_ROLES + OFFICE_ROLES:
		if not frappe.db.exists("Role", role):
			continue
		if not frappe.db.get_value("Role", role, "home_page"):
			continue
		# Value-only write: Role.validate routes `disabled` to remove_roles(), which deletes
		# Has Role rows. Nothing here should be able to reach that by accident.
		frappe.db.set_value("Role", role, "home_page", None, update_modified=False)
	frappe.db.commit()
