"""Leak Check became submittable (2026-10-02): Submit finishes it, from the Desk like every
other order and from the PWA.

* Every check already ``Completed`` (photos saved under the old rule) is marked submitted, so
  it stays final and keeps counting at the gate.
* Its Custom DocPerm rows are rebuilt from the matrix. The seeder is add-only
  (``install.setup_permissions``) and wrote them while the doctype had no submit at all, so
  nobody — Admin Ops included — would otherwise hold the Submit button. Same forced rebuild
  as Survey Order got in v0_90.
"""

import frappe


def execute():
	done = frappe.get_all("Leak Check", filters={"status": "Completed", "docstatus": 0}, pluck="name")
	if done:
		frappe.db.sql("UPDATE `tabLeak Check` SET docstatus = 1 WHERE name IN %(n)s", {"n": tuple(done)})
		frappe.db.sql(
			"UPDATE `tabLeak Check Photo` SET docstatus = 1 WHERE parenttype = 'Leak Check' AND parent IN %(n)s",
			{"n": tuple(done)},
		)

	frappe.db.delete("Custom DocPerm", {"parent": "Leak Check"})
	from container_depot.install import setup_permissions

	setup_permissions()
	frappe.clear_cache(doctype="Leak Check")
