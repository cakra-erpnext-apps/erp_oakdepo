"""Phase 6 tests — real role list + permission matrix + Customer scoping."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.install import (
	PHASE6_ROLES,
	ROLE_DOCTYPE_PERMISSIONS,
	ensure_customer_user_permission,
)
from container_depot.tests.test_api import ensure_test_customer


class TestRolesCreated(FrappeTestCase):
	def test_phase6_roles_exist(self):
		for role in PHASE6_ROLES:
			self.assertTrue(
				frappe.db.exists("Role", role),
				f"Role {role} should be created by ensure_roles_exist().",
			)

	def test_sst_service_role_exists(self):
		self.assertTrue(frappe.db.exists("Role", "Container Depot SST Service"))


class TestPermissionMatrix(FrappeTestCase):
	def test_matrix_doctypes_have_custom_docperms(self):
		# Sample: every doctype declared in the matrix should have at least one
		# Custom DocPerm row created by setup_permissions for the listed roles.
		for dt, role_map in ROLE_DOCTYPE_PERMISSIONS.items():
			if not frappe.db.exists("DocType", dt):
				continue
			for role in role_map:
				self.assertTrue(
					frappe.db.exists("Custom DocPerm", {"parent": dt, "role": role}),
					f"Missing Custom DocPerm parent={dt} role={role}",
				)

	def test_customer_only_reads_bookings(self):
		# Customer's matrix entry for Isotank Booking grants read+create+report+
		# export but not submit/write/delete.
		perms = frappe.db.get_value(
			"Custom DocPerm",
			{"parent": "Isotank Booking", "role": "Customer"},
			["read", "write", "create", "submit", "delete", "report"],
			as_dict=True,
		)
		self.assertEqual(perms.read, 1)
		self.assertEqual(perms.create, 1)
		self.assertEqual(perms.submit, 0)
		self.assertEqual(perms.write or 0, 0)
		self.assertEqual(perms.delete or 0, 0)

	def test_security_role_cannot_submit_depot_contract(self):
		# Security has no entry under Depot Contract → no Custom DocPerm row.
		self.assertFalse(
			frappe.db.exists("Custom DocPerm", {"parent": "Depot Contract", "role": "Security"}),
			"Security must NOT have any DocPerm on Depot Contract",
		)

	def test_management_can_read_contract(self):
		row = frappe.db.get_value(
			"Custom DocPerm",
			{"parent": "Depot Contract", "role": "Management"},
			["read", "write", "create"],
			as_dict=True,
		)
		self.assertEqual(row.read, 1)
		self.assertEqual(row.write or 0, 0)
		self.assertEqual(row.create or 0, 0)


class TestCustomerScoping(FrappeTestCase):
	"""ensure_customer_user_permission scopes a portal user to one Customer."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.user_email = "customer-portal-test@example.com"
		cls.customer = ensure_test_customer("Phase6 Portal Customer")
		if not frappe.db.exists("User", cls.user_email):
			frappe.get_doc({
				"doctype": "User",
				"email": cls.user_email,
				"first_name": "Portal",
				"last_name": "Tester",
				"send_welcome_email": 0,
				"roles": [{"role": "Customer"}],
			}).insert(ignore_permissions=True)

	@classmethod
	def tearDownClass(cls):
		frappe.db.delete("User Permission", {"user": cls.user_email})
		frappe.db.delete("User", {"email": cls.user_email})
		super().tearDownClass()

	def test_ensure_user_permission_creates_row(self):
		frappe.db.delete("User Permission", {"user": self.user_email})
		ensure_customer_user_permission(self.user_email, self.customer)
		self.assertTrue(
			frappe.db.exists(
				"User Permission",
				{
					"user": self.user_email,
					"allow": "Customer",
					"for_value": self.customer,
				},
			)
		)

	def test_ensure_user_permission_idempotent(self):
		ensure_customer_user_permission(self.user_email, self.customer)
		ensure_customer_user_permission(self.user_email, self.customer)
		rows = frappe.db.count(
			"User Permission",
			{"user": self.user_email, "allow": "Customer", "for_value": self.customer},
		)
		self.assertEqual(rows, 1)
