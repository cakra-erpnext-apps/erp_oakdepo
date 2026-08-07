"""Tests for the User -> Branch multiselect feature:

- the User's selected Branches are mirrored into Frappe User Permissions
  (empty = no restriction; one/many = a permission each), and
- Order Bongkar/Muat inherit their booking's branch so the permission scopes them.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.container_depot.order_generation import make_order
from container_depot.tests.test_multi_container_order import _booking_with_codes


def _ensure_branch(name):
	if not frappe.db.exists("Branch", name):
		frappe.get_doc({"doctype": "Branch", "branch": name}).insert(ignore_permissions=True)
	return name


def _make_user(email, branches):
	if frappe.db.exists("User", email):
		frappe.delete_doc("User", email, ignore_permissions=True, force=True)
	return frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": "Branch Test",
			"send_welcome_email": 0,
			"branch": [{"branch": b} for b in branches],
		}
	).insert(ignore_permissions=True)


def _branch_perms(user):
	return {
		p.for_value
		for p in frappe.get_all(
			"User Permission",
			filters={"user": user, "allow": "Branch"},
			fields=["for_value"],
		)
	}


class TestUserBranchPermissionSync(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for b in ("Branch UB A", "Branch UB B", "Branch UB C"):
			_ensure_branch(b)

	def test_empty_means_no_restriction(self):
		user = _make_user("ub-empty@example.com", [])
		self.assertEqual(_branch_perms(user.name), set())

	def test_single_branch_creates_one_permission(self):
		user = _make_user("ub-one@example.com", ["Branch UB A"])
		self.assertEqual(_branch_perms(user.name), {"Branch UB A"})
		# apply_to_all_doctypes is set, so every branch-linked doctype is scoped.
		perm = frappe.get_all(
			"User Permission",
			filters={"user": user.name, "allow": "Branch", "for_value": "Branch UB A"},
			fields=["apply_to_all_doctypes"],
		)[0]
		self.assertEqual(perm.apply_to_all_doctypes, 1)

	def test_multi_branch_creates_each(self):
		user = _make_user("ub-multi@example.com", ["Branch UB A", "Branch UB B"])
		self.assertEqual(_branch_perms(user.name), {"Branch UB A", "Branch UB B"})

	def test_resync_adds_and_removes(self):
		user = _make_user("ub-resync@example.com", ["Branch UB A", "Branch UB B"])
		self.assertEqual(_branch_perms(user.name), {"Branch UB A", "Branch UB B"})
		# Swap B -> C: A kept, B removed, C added.
		user.set("branch", [{"branch": "Branch UB A"}, {"branch": "Branch UB C"}])
		user.save(ignore_permissions=True)
		self.assertEqual(_branch_perms(user.name), {"Branch UB A", "Branch UB C"})
		# Clear all -> back to no restriction.
		user.set("branch", [])
		user.save(ignore_permissions=True)
		self.assertEqual(_branch_perms(user.name), set())

	def test_administrator_is_never_restricted(self):
		admin = frappe.get_doc("User", "Administrator")
		admin.set("branch", [{"branch": "Branch UB A"}])
		admin.save(ignore_permissions=True)
		self.assertEqual(_branch_perms("Administrator"), set())


class TestOrderBranchStamp(FrappeTestCase):
	def test_order_bongkar_inherits_booking_branch(self):
		branch = _ensure_branch("Branch UB ORD")
		booking, codes = _booking_with_codes(code_direction="Tank In", count=1, prefix="UBORD0")
		frappe.db.set_value("Container Booking", booking, "branch", branch)
		order = frappe.get_doc("Order Bongkar", make_order(booking, codes))
		self.assertEqual(order.branch, branch)
