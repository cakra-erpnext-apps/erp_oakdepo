"""Delete the app's custom role model — run MANUALLY, never from patches.txt.

The 13 roles below were seeded by ``install.ensure_roles_exist`` and carried the whole
Phase-6 permission matrix. They are being retired on 2026-08-05 so the role model can be
redesigned from scratch; until the new one lands, access falls back to Frappe's own
System Manager (and Administrator, which bypasses permissions entirely).

What this removes, per role: the ``Role`` record, its ``Custom DocPerm`` rows, and every
``Has Role`` assignment (users AND role-restricted Reports / Pages).

This is deliberately NOT registered in ``patches.txt``. A patch would fire on the next
production migrate and silently strip permissions off live users; retiring a role model is
a decision per site, not a code deployment. Run it where you mean it:

    bench --site <site> execute container_depot.purge_roles.run

Add ``--kwargs "{'dry_run': True}"`` to print the blast radius without deleting anything.
Idempotent: a second run finds nothing and reports zeroes.
"""

from __future__ import annotations

import frappe

# Every role created by the app's own seeder. Verified against Frappe/ERPNext before
# deletion: none of these ship with the framework, so nothing standard is lost. ("Cashier"
# appears in ERPNext only as a POS field label, never as a Role.)
CUSTOM_ROLES = [
	"Container Depot",                 # legacy blanket-grant role
	"Container Depot SST Service",     # SST API service account role
	"Depot PWA",                       # /depot page access
	"Depot Driver (SST)",
	"Admin Ops",
	"Ops Supervisor",
	"Commercial",
	"Management",
	"Surveyor",
	"Operator Kalmar",
	"Security",
	"Cashier",
	"IT Support",
]


def run(dry_run: bool = False) -> dict:
	"""Delete every role in :data:`CUSTOM_ROLES`. Returns what was (or would be) removed."""
	report = {"roles": [], "custom_docperms": 0, "has_role": 0, "missing": []}
	for role in CUSTOM_ROLES:
		if not frappe.db.exists("Role", role):
			report["missing"].append(role)
			continue
		perms = frappe.db.count("Custom DocPerm", {"role": role})
		holders = frappe.get_all(
			"Has Role", filters={"role": role}, fields=["parenttype", "parent"]
		)
		report["roles"].append({
			"role": role,
			"custom_docperms": perms,
			"assigned_to": [f"{h.parenttype}: {h.parent}" for h in holders],
		})
		report["custom_docperms"] += perms
		report["has_role"] += len(holders)
		if dry_run:
			continue
		# Order matters: the Role cannot be deleted while rows still link to it.
		frappe.db.delete("Custom DocPerm", {"role": role})
		frappe.db.delete("Has Role", {"role": role})
		frappe.delete_doc("Role", role, force=True, ignore_permissions=True)
		print(f"[container_depot] deleted Role {role} ({perms} DocPerms, {len(holders)} assignments)")

	if not dry_run:
		frappe.db.commit()
		# The blanket System Manager grant is what keeps the Container Depot doctypes reachable
		# once the custom roles are gone — most of them ship with an empty "permissions"
		# array, so without this nobody but Administrator could open them.
		from container_depot.install import setup_permissions

		setup_permissions()
		frappe.clear_cache()
	print(
		f"[container_depot] {'would delete' if dry_run else 'deleted'} "
		f"{len(report['roles'])} roles, {report['custom_docperms']} Custom DocPerms, "
		f"{report['has_role']} assignments; {len(report['missing'])} already absent."
	)
	return report
