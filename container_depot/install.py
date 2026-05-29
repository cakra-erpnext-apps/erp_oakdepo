import frappe

# Roles granted blanket DocPerms on Operations doctypes by setup_permissions.
# NOTE(Phase 6): this blanket grant is interim. The real per-role permission
# matrix lands in Phase 6; until then the SST Service role is *not* added here
# because it must remain narrowly scoped.
ROLES_TO_GRANT = ["System Manager", "Container Depot"]

# Narrow service role used by SST / agent traffic. Created (idempotently) on
# install and on every migrate, but kept out of ROLES_TO_GRANT so it does not
# accidentally pick up the blanket DocPerm grant.
SST_SERVICE_ROLE = "Container Depot SST Service"


def after_install():
	"""Run after install hook for container_depot app"""
	ensure_roles_exist()
	setup_permissions()
	setup_workspace()


def after_migrate():
	"""Idempotent post-migrate hook: ensure roles always exist on managed sites."""
	ensure_roles_exist()


def ensure_roles_exist():
	"""Create app-specific roles referenced by setup_permissions if missing."""
	for role_name in ROLES_TO_GRANT:
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc({
				"doctype": "Role",
				"role_name": role_name,
				"desk_access": 1,
			}).insert(ignore_permissions=True)
	# SST Service role: API-only (no desk access). Permissions will be wired in
	# Phase 4 when SST DocTypes land; today the role just needs to exist so the
	# Frappe token-auth path can reject anonymous traffic against the SST API.
	if not frappe.db.exists("Role", SST_SERVICE_ROLE):
		frappe.get_doc({
			"doctype": "Role",
			"role_name": SST_SERVICE_ROLE,
			"desk_access": 0,
		}).insert(ignore_permissions=True)
	frappe.db.commit()


def setup_permissions():
	"""Grant Operations DocType permissions to every role in ROLES_TO_GRANT."""
	doctypes = [d.name for d in frappe.get_all("DocType", filters={"module": "Operations"})]
	for dt in doctypes:
		meta = frappe.get_meta(dt)
		for role_name in ROLES_TO_GRANT:
			if frappe.db.exists("Custom DocPerm", {"parent": dt, "role": role_name}):
				continue
			frappe.get_doc({
				"doctype": "Custom DocPerm",
				"parent": dt,
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": role_name,
				"permlevel": 0,
				"read": 1,
				"write": 1,
				"create": 1,
				"delete": 1,
				"submit": 1 if meta.is_submittable else 0,
				"cancel": 1 if meta.is_submittable else 0,
				"amend": 1 if meta.is_submittable else 0,
				"export": 1,
				"import": 1,
				"share": 1,
				"report": 1,
			}).insert(ignore_permissions=True)
	frappe.db.commit()


def setup_workspace():
	"""Pin Container Depot workspace to the top of the sidebar."""
	if frappe.db.exists("Workspace", "Container Depot"):
		frappe.db.set_value("Workspace", "Container Depot", "sequence_id", 0)
		frappe.db.set_value("Workspace", "Container Depot", "parent_page", "")
		frappe.db.commit()
