"""Customer portal user provisioning.

Wires the (already-present) ``ensure_customer_user_permission`` helper to the
``Customer Portal User`` lifecycle: when a row becomes Active, the linked User
is scoped to its Customer and granted the Customer role — so Desk-created portal
users are provisioned automatically (no portal UI required).
"""

from __future__ import annotations

import frappe

from container_depot.install import ensure_customer_user_permission


def sync_portal_user_permission(doc, method=None):
	if not doc.user or not doc.customer:
		return
	if doc.approval_status == "Active":
		ensure_customer_user_permission(doc.user, doc.customer)
		_ensure_role(doc.user, "Customer")


def _ensure_role(user: str, role: str):
	if not frappe.db.exists("User", user):
		return
	if frappe.db.exists("Has Role", {"parent": user, "role": role}):
		return
	u = frappe.get_doc("User", user)
	u.append("roles", {"role": role})
	u.save(ignore_permissions=True)
