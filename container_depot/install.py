import frappe

# Legacy blanket-grant role list. Kept for backwards compatibility on existing
# sites — the real per-role matrix below now supersedes it. Anything still in
# this list also gets unrestricted DocPerms on every Operations doctype.
ROLES_TO_GRANT = ["System Manager", "Container Depot"]

# Narrow service role used by SST / agent traffic. Created (idempotently) on
# install and on every migrate, but kept out of ROLES_TO_GRANT so it does not
# accidentally pick up the blanket DocPerm grant.
SST_SERVICE_ROLE = "Container Depot SST Service"

# Real per-role matrix introduced in Phase 6. Roles listed here are created on
# install + every migrate; the permission matrix in ROLE_DOCTYPE_PERMISSIONS
# below decides who can see / change what.
PHASE6_ROLES = [
	"Customer",                       # ERPNext built-in; we scope via User Permission.
	"Depot Driver (SST)",
	"Security",
	"Admin Ops",
	"Surveyor",
	"Operator Kalmar",
	"Ops Supervisor",
	"Commercial",
	"Management",
	"IT Support",
]

# Permission matrix: doctype -> {role: perm_dict}. perm_dict keys match the
# Custom DocPerm fields (read/write/create/delete/submit/cancel/amend/export
# /report/share). Missing keys default to 0. permlevel defaults to 0.
#
# Design notes:
# - System Manager always gets full perms; not enumerated here.
# - Customer perms are written but only become visible-per-row via the
#   User Permission link to Customer (auto-created by ensure_customer_user_permission).
# - Append-only logs (SST Activity Log, Container Movement) deny delete to
#   everyone except System Manager.
ROLE_DOCTYPE_PERMISSIONS = {
	"Isotank Booking": {
		"Customer":          {"read": 1, "create": 1, "submit": 0, "report": 1, "export": 1},
		"Commercial":        {"read": 1, "create": 1, "write": 1, "submit": 1, "cancel": 1, "amend": 1, "report": 1, "export": 1, "share": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "submit": 1, "cancel": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "write": 1, "report": 1},
		"Security":          {"read": 1, "report": 1},
		"Surveyor":          {"read": 1, "report": 1},
		"Operator Kalmar":   {"read": 1, "report": 1},
		"Management":        {"read": 1, "report": 1, "export": 1},
		"IT Support":        {"read": 1, "report": 1},
	},
	"Booking Code": {
		"Customer":          {"read": 1, "report": 1},
		"Security":          {"read": 1, "report": 1},
		"Admin Ops":         {"read": 1, "write": 1, "create": 1, "report": 1},
		"Commercial":        {"read": 1, "write": 1, "create": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "report": 1},
		"Management":        {"read": 1, "report": 1},
	},
	"Order Bongkar": {
		"Customer":          {"read": 1, "report": 1},
		"Security":          {"read": 1, "write": 1, "create": 1, "submit": 1, "report": 1},
		"Surveyor":          {"read": 1, "write": 1, "report": 1},
		"Admin Ops":         {"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "write": 1, "report": 1},
		"Operator Kalmar":   {"read": 1, "report": 1},
	},
	"Order Muat": {
		"Customer":          {"read": 1, "report": 1},
		"Security":          {"read": 1, "write": 1, "create": 1, "submit": 1, "report": 1},
		"Surveyor":          {"read": 1, "write": 1, "report": 1},
		"Admin Ops":         {"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "write": 1, "report": 1},
		"Operator Kalmar":   {"read": 1, "report": 1},
	},
	"Depot Contract": {
		"Customer":          {"read": 1, "report": 1},
		"Commercial":        {"read": 1, "create": 1, "write": 1, "submit": 1, "cancel": 1, "amend": 1, "report": 1},
		"Management":        {"read": 1, "report": 1, "export": 1},
		"IT Support":        {"read": 1, "report": 1},
	},
	"Container": {
		"Customer":          {"read": 1, "report": 1},
		"Security":          {"read": 1, "report": 1},
		"Surveyor":          {"read": 1, "write": 1, "report": 1},
		"Operator Kalmar":   {"read": 1, "write": 1, "report": 1},
		"Admin Ops":         {"read": 1, "write": 1, "create": 1, "delete": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "write": 1, "report": 1},
	},
	"Gate Entry": {
		"Customer":          {"read": 1, "report": 1},
		"Security":          {"read": 1, "create": 1, "write": 1, "submit": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "submit": 1, "cancel": 1, "report": 1},
	},
	"Inspection": {
		"Customer":          {"read": 1, "report": 1},
		"Surveyor":          {"read": 1, "create": 1, "write": 1, "submit": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "submit": 1, "cancel": 1, "report": 1},
		"Operator Kalmar":   {"read": 1, "report": 1},
	},
	"Cleaning Certificate": {
		"Customer":          {"read": 1, "report": 1},
		"Surveyor":          {"read": 1, "create": 1, "write": 1, "submit": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "write": 1, "submit": 1, "cancel": 1, "report": 1},
	},
	"SST Activity Log": {
		"IT Support":        {"read": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "report": 1},
		# create-only for the SST service role lives in the doctype JSON itself.
	},
	"Container Movement": {
		"Operator Kalmar":   {"read": 1, "create": 1, "report": 1},
		"Admin Ops":         {"read": 1, "create": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "report": 1},
		"IT Support":        {"read": 1, "report": 1},
	},
	"Self Service Terminal": {
		"IT Support":        {"read": 1, "create": 1, "write": 1, "delete": 1, "report": 1},
		"Ops Supervisor":    {"read": 1, "report": 1},
	},
}


def after_install():
	"""Run after install hook for container_depot app"""
	ensure_roles_exist()
	setup_permissions()
	setup_workspace()


def after_migrate():
	"""Idempotent post-migrate hook: ensure roles + DocPerms stay in sync."""
	ensure_roles_exist()
	# setup_permissions() is idempotent (existence-check on Custom DocPerm) so
	# running it on every migrate just picks up new DocTypes as they're added.
	setup_permissions()


def ensure_roles_exist():
	"""Create app-specific roles referenced by setup_permissions if missing."""
	for role_name in ROLES_TO_GRANT + PHASE6_ROLES:
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc({
				"doctype": "Role",
				"role_name": role_name,
				"desk_access": 0 if role_name == "Customer" else 1,
			}).insert(ignore_permissions=True)
	# SST Service role: API-only (no desk access). Created here so the
	# Frappe token-auth path can reject anonymous traffic against the SST API.
	if not frappe.db.exists("Role", SST_SERVICE_ROLE):
		frappe.get_doc({
			"doctype": "Role",
			"role_name": SST_SERVICE_ROLE,
			"desk_access": 0,
		}).insert(ignore_permissions=True)
	frappe.db.commit()


def setup_permissions():
	"""Sync DocPerms.

	1. Legacy: every role in ROLES_TO_GRANT keeps unrestricted DocPerms on
	   every Operations doctype (back-compat for existing sites).
	2. Phase-6 matrix: ROLE_DOCTYPE_PERMISSIONS adds narrow per-role grants
	   on top, so the real role list is in effect for new doctypes.
	"""
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

	# Phase-6 narrow matrix.
	for dt, role_map in ROLE_DOCTYPE_PERMISSIONS.items():
		if not frappe.db.exists("DocType", dt):
			continue
		meta = frappe.get_meta(dt)
		for role, perms in role_map.items():
			if frappe.db.exists("Custom DocPerm", {"parent": dt, "role": role}):
				continue
			row = {
				"doctype": "Custom DocPerm",
				"parent": dt,
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": role,
				"permlevel": 0,
			}
			row.update(perms)
			# submit/cancel/amend only make sense on submittable doctypes.
			if not meta.is_submittable:
				row.pop("submit", None)
				row.pop("cancel", None)
				row.pop("amend", None)
			frappe.get_doc(row).insert(ignore_permissions=True)

	frappe.db.commit()


def ensure_customer_user_permission(user: str, customer: str) -> None:
	"""Create a User Permission row scoping a user to a single Customer.

	Idempotent. Used by the on-signup hook (and tests) so a Customer-role user
	can only see records linked to *their* Customer through standard Frappe
	permission filtering.
	"""
	if not user or not customer:
		return
	if frappe.db.exists(
		"User Permission",
		{"user": user, "allow": "Customer", "for_value": customer},
	):
		return
	frappe.get_doc({
		"doctype": "User Permission",
		"user": user,
		"allow": "Customer",
		"for_value": customer,
		"apply_to_all_doctypes": 1,
	}).insert(ignore_permissions=True)


def setup_workspace():
	"""Pin Container Depot workspace to the top of the sidebar."""
	if frappe.db.exists("Workspace", "Container Depot"):
		frappe.db.set_value("Workspace", "Container Depot", "sequence_id", 0)
		frappe.db.set_value("Workspace", "Container Depot", "parent_page", "")
		frappe.db.commit()
