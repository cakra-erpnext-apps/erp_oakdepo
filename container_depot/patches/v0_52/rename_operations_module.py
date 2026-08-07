"""Rename the app's module ``Operations`` -> ``Container Depot`` (2026-08-07).

The app has always shipped a single module, but it was named ``Operations`` while
everything the user actually sees — the app, the Workspace, the left rail, the
Desk home icon — says "Container Depot". The mismatch bites in exactly one place
that matters: User -> Allow Modules lists the module name, so an admin looking to
grant or revoke depot access has to know that the box labelled "Operations" is the
depot. Renaming removes the translation step.

Runs pre_model_sync so the Module Def is in place before ``sync_all()`` imports the
81 fixtures that now carry ``"module": "Container Depot"``.

``frappe.rename_doc`` cascades to every *Link* field pointing at Module Def, which
moves ``tabDocType.module``, ``tabReport.module``, ``tabWorkspace.module``,
``tabPrint Format.module`` and ``tabPage.module``.

It does NOT move the one that governs access control. ``Block Module.module`` — the
child table behind User -> Allow Modules — is a plain **Data** field, not a Link, so
the cascade cannot see it and the row is left dangling on a Module Def that no longer
exists. Observed consequence on the dev site: the dangling row was dropped outright,
silently un-blocking the module for every user who had it blocked. ``_move_block_modules``
rewrites those rows explicitly, before the rename removes the old name.
"""

import frappe

OLD = "Operations"
NEW = "Container Depot"


def execute():
	if frappe.db.exists("Module Def", NEW):
		# Already renamed, or a fresh site that built the Module Def from modules.txt.
		_move_block_modules()
		_drop_stale_old()
		return

	if not frappe.db.exists("Module Def", OLD):
		# Nothing to rename (fresh install); sync_all() creates NEW from modules.txt.
		return

	_move_block_modules()

	# The real implementation, not frappe.rename_doc — the top-level wrapper drops
	# ignore_permissions, and a patch runs with no user context to check against.
	from frappe.model.rename_doc import rename_doc

	# ModuleDef.before_rename refuses anything that isn't a Custom module. That guard
	# exists to stop a rename from orphaning the on-disk folder, which is precisely what
	# this patch has already handled (the folder moved with the commit), so flip the flag
	# for the duration and restore it after.
	frappe.db.set_value("Module Def", OLD, "custom", 1, update_modified=False)
	frappe.clear_document_cache("Module Def", OLD)
	try:
		rename_doc("Module Def", OLD, NEW, force=True, ignore_permissions=True)
	finally:
		target = NEW if frappe.db.exists("Module Def", NEW) else OLD
		frappe.db.set_value(
			"Module Def",
			target,
			{"custom": 0, "module_name": target, "app_name": "container_depot"},
			update_modified=False,
		)
	frappe.clear_cache()


def _move_block_modules() -> None:
	"""Repoint User -> Allow Modules rows at the new module name.

	Idempotent, and safe to run on a site where the rename already happened: rows
	already reading NEW are untouched, and a user who somehow has both ends up with a
	duplicate that Frappe collapses on the next save (same effect either way — blocked).
	"""
	frappe.db.sql(
		"update `tabBlock Module` set module = %s where module = %s and parenttype = 'User'",
		(NEW, OLD),
	)
	frappe.db.sql(
		"update `tabBlock Module` set module = %s where module = %s and parenttype = 'Module Profile'",
		(NEW, OLD),
	)
	frappe.clear_cache()


def _drop_stale_old() -> None:
	"""Both names present: the rename already ran and modules.txt no longer lists OLD."""
	if not frappe.db.exists("Module Def", OLD):
		return
	if frappe.db.count("DocType", {"module": OLD}):
		# Something still lives there — leave it alone rather than orphan its doctypes.
		return
	frappe.delete_doc("Module Def", OLD, force=True, ignore_permissions=True)
