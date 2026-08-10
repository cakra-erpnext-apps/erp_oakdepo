"""One-time: hide the ~48 roles this depot will never assign from the User form picker.

Everything — the reasoning, the list, and why this is a domain tag rather than
``Role.disabled`` — lives in ``container_depot.install`` next to the role model it belongs
to. This patch only kicks it off for sites that already exist.

Deliberately one-time and NOT re-asserted on every migrate: un-parking a role is a
legitimate admin decision and must stick. The five fixture-owned roles are the exception
and are handled by ``install.reassert_parked_fixture_roles`` in ``after_migrate``.
"""

import frappe

from container_depot.install import park_roles


def execute():
	parked = park_roles()
	frappe.db.commit()
	print(f"Parked {len(parked)} unused roles under the 'Unused' domain")
