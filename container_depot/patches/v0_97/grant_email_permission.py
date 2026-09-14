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

from container_depot.install import OFFICE_ROLES, PARKED_DOMAIN, setup_role_profiles

EMAIL_ROLE = "Inbox User"


def execute():
	_grant_email_flag()
	_unpark_email_role()
	# Writes EMAIL_ROLE into the office profiles (add-only, see setup_role_profiles).
	setup_role_profiles()
	_push_profiles_to_users()


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


def _unpark_email_role():
	"""A role named in COMPANION_ROLES has to stay in the User form's picker."""
	if not frappe.db.exists("Role", EMAIL_ROLE):
		return
	if frappe.db.get_value("Role", EMAIL_ROLE, "restrict_to_domain") == PARKED_DOMAIN:
		# db.set_value, not doc.save(): Role.validate() is where the Has Role wipe lives.
		frappe.db.set_value("Role", EMAIL_ROLE, "restrict_to_domain", None, update_modified=False)
		frappe.clear_cache()


def _push_profiles_to_users():
	"""Re-save every holder of an office profile, so the new role lands now.

	``RoleProfile.on_update`` enqueues this on the long queue after commit; a site whose
	worker is asleep would keep showing the same error until someone opened each User and
	saved it. Saving here is the same call the job makes — ``populate_role_profile_roles``
	syncs the user's roles to the union of their profiles.
	"""
	users = frappe.get_all(
		"User Role Profile",
		filters={"role_profile": ["in", OFFICE_ROLES], "parenttype": "User"},
		pluck="parent",
	)
	users += frappe.get_all("User", filters={"role_profile_name": ["in", OFFICE_ROLES]}, pluck="name")
	for user in sorted(set(users)):
		if frappe.db.exists("Has Role", {"parent": user, "role": EMAIL_ROLE}):
			continue
		try:
			frappe.get_doc("User", user).save(ignore_permissions=True)
		except Exception:
			# One unsaveable account must not abort the migrate for everyone else.
			frappe.log_error(title=f"grant_email_permission: {user}", message=frappe.get_traceback())
