"""Customer portal user provisioning.

Wires the ``Customer Portal User`` lifecycle to the two things that actually grant a
customer account its access:

* a **User Permission** ``allow=Customer`` — the company flag, and the only thing that
  scopes the data (``install.ensure_customer_user_permission`` + ``customer_scope``);
* the **roles**: ERPNext's stock ``Customer`` (website portal) plus ``Customer Desk``,
  which is what carries ``desk_access`` and the read-only DocPerms on the depot
  doctypes (``install.CUSTOMER_DESK_ROLE``).

Both are granted when the row goes Active and **withdrawn when it does not**: a portal
user switched to Inactive is someone who left the customer's payroll, and leaving their
login able to read the yard because the row was only ever add-only is not an option.
"""

from __future__ import annotations

import frappe

from container_depot.install import CUSTOMER_DESK_ROLE, ensure_customer_user_permission

PORTAL_ROLES = ("Customer", CUSTOMER_DESK_ROLE)

# The only module a customer account may see in the Desk sidebar. Every OTHER module is
# written to `User.block_modules`, because that list — not the role — is what
# `desk.desktop.get_workspace_sidebar_items` filters the workspace menu by: without it a
# customer with nothing but read on six depot doctypes still gets Helpdesk, Stock, HR,
# Website, Users and Integrations in their sidebar, each mostly empty and none of it
# theirs.
ALLOWED_MODULES = ("Container Depot",)


def sync_portal_user_permission(doc, method=None):
	if not doc.user or not doc.customer:
		return
	if doc.approval_status == "Active":
		ensure_customer_user_permission(doc.user, doc.customer)
		for role in PORTAL_ROLES:
			_ensure_role(doc.user, role)
		_restrict_modules(doc.user)
	else:
		_revoke(doc.user, doc.customer)


def _revoke(user: str, customer: str) -> None:
	"""Drop this customer's scope from the account, and the portal roles with it.

	The roles go only when NO other Active row still links the account to a customer —
	one person may hold logins for two customer companies, and deactivating one of them
	must not shut the other.
	"""
	for name in frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": "Customer", "for_value": customer},
		pluck="name",
	):
		frappe.delete_doc("User Permission", name, ignore_permissions=True, force=True)

	if frappe.db.exists(
		"Customer Portal User", {"user": user, "approval_status": "Active"}
	):
		return
	if not frappe.db.exists("User", user):
		return
	u = frappe.get_doc("User", user)
	keep = [row for row in u.roles if row.role not in PORTAL_ROLES]
	if len(keep) == len(u.roles):
		return
	# Through the document, not frappe.db.delete: dropping the last desk role has to run
	# User.validate_user_type, which is what demotes the account back to a Website User.
	u.set("roles", keep)
	u.save(ignore_permissions=True)


def _restrict_modules(user: str) -> None:
	"""Cut the Desk sidebar down to the depot module. First provisioning only.

	Written once, when the account blocks nothing yet — after that the list belongs to the
	admin, the same rule the permission seeder follows. Re-asserting it on every save would
	undo a deliberate "let this customer see module X too".
	"""
	u = frappe.get_doc("User", user)
	if u.get("block_modules"):
		return
	blocked = [
		m for m in frappe.get_all("Module Def", pluck="name") if m not in ALLOWED_MODULES
	]
	if not blocked:
		return
	u.set("block_modules", [{"module": m} for m in blocked])
	u.save(ignore_permissions=True)


def _ensure_role(user: str, role: str):
	if not frappe.db.exists("User", user):
		return
	if not frappe.db.exists("Role", role):
		return
	if frappe.db.exists("Has Role", {"parent": user, "role": role}):
		return
	u = frappe.get_doc("User", user)
	u.append("roles", {"role": role})
	u.save(ignore_permissions=True)
