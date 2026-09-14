"""Give every depot role the Email action — the flag on the document AND the role to send with.

Two halves, because the failure had two causes and fixing either alone changes nothing:

1. ``_PERM_LETTERS`` expanded ``r`` to read+report+export+print but never to ``email``, and
   ``email`` is its own Frappe flag. The first Custom DocPerm on a doctype makes Frappe
   ignore that doctype's shipped permissions wholesale, so a flag the seeder never sets is
   a flag nobody has — no Email entry in the form Menu on any Container Depot document.
   ``_ensure_docperm`` is add-only, so fixing the grammar leaves the existing rows at
   ``email = 0`` for ever. This backfills them, exactly as v0_83 did for ``print``.

2. Even with the flag, composing died on *"User X does not have doctype access via role
   permission for document Email Account"*: the compose dialog reads ``Email Account`` for
   the sender's signature, and that read belongs to Frappe's standard ``Inbox User`` role —
   which this app had PARKED (restrict_to_domain = Unused) as desk power-user tooling. So
   un-park it and put it on the six office Role Profiles via COMPANION_ROLES, then push the
   profiles onto the accounts already holding them instead of waiting for a background job.

Scope of half 1 is deliberately narrow, same as v0_83:
  * only doctypes in module Container Depot — a Custom DocPerm on another app's doctype is
    not ours to write (see ``setup_permissions``);
  * only rows that already carry ``read``, so nothing is granted to a role that could not
    already open the document.
"""

import frappe

from container_depot.install import (
	OFFICE_ROLES,
	push_role_profiles_to_users,
	setup_role_profiles,
	unpark_roles,
)

EMAIL_ROLE = "Inbox User"


def execute():
	_grant_email_flag()
	# A role named in COMPANION_ROLES has to stay in the User form's picker.
	unpark_roles([EMAIL_ROLE])
	# Writes EMAIL_ROLE into the office profiles (add-only, see setup_role_profiles).
	setup_role_profiles()
	push_role_profiles_to_users(OFFICE_ROLES)


def _grant_email_flag():
	doctypes = frappe.get_all(
		"DocType", filters={"module": "Container Depot", "istable": 0}, pluck="name"
	)
	if not doctypes:
		return
	rows = frappe.get_all(
		"Custom DocPerm",
		filters={"parent": ["in", doctypes], "read": 1, "email": 0},
		pluck="name",
	)
	for name in rows:
		frappe.db.set_value("Custom DocPerm", name, "email", 1, update_modified=False)
	if rows:
		frappe.clear_cache()


