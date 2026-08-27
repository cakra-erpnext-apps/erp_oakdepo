"""Grant the missing ``print`` permission on every Container Depot doctype.

``_PERM_LETTERS`` expanded ``r`` to read+report+export but never to ``print``, and ``print``
is its own flag in Frappe. Because the first Custom DocPerm on a doctype makes Frappe ignore
that doctype's shipped permissions wholesale, a flag the seeder never sets is a flag nobody
has — so the Desk offered no Print action on any depot document: EIR, Bon Bongkar, Bon Muat,
all of them.

Fixing ``_PERM_LETTERS`` alone is not enough: ``_ensure_docperm`` is add-only, so the rows
already written keep their ``print = 0`` for ever. This backfills them.

Scope is deliberately narrow:
  * only doctypes in module Container Depot — Custom DocPerm on another app's doctype is
    not ours to touch (see ``setup_permissions``);
  * only rows that already carry ``read``, so this grants nothing to a role that could not
    already open the document;
  * ``print`` only. ``email`` stays off: printing hands a copy to someone already allowed
    to read the document, emailing hands it to someone who is not.
"""

import frappe


def execute():
	doctypes = frappe.get_all(
		"DocType", filters={"module": "Container Depot", "istable": 0}, pluck="name"
	)
	if not doctypes:
		return
	rows = frappe.get_all(
		"Custom DocPerm",
		filters={"parent": ["in", doctypes], "read": 1, "print": 0},
		pluck="name",
	)
	for name in rows:
		frappe.db.set_value("Custom DocPerm", name, "print", 1, update_modified=False)
	if rows:
		frappe.clear_cache()
