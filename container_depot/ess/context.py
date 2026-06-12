"""ESS PWA user-context endpoint — tells the frontend the active user's branch
scope so it can label the Depot Storage header and adapt the UI. Read-only."""
from __future__ import annotations

import frappe

from container_depot.api import _require_authenticated_user
from container_depot.operations.user_branch import get_user_branches


@frappe.whitelist(methods=["GET"])
def get_user_context():
	"""GET /api/v1/ess/user-context — {user, full_name, roles, branches, all_branches}."""
	_require_authenticated_user()
	user = frappe.session.user
	branches = get_user_branches(user)
	return {
		"success": True,
		"user": user,
		"full_name": frappe.db.get_value("User", user, "full_name") or user,
		"roles": frappe.get_roles(user),
		"branches": branches or [],
		"all_branches": branches is None,
	}
