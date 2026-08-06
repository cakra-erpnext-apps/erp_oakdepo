"""The ESS endpoints refuse callers who have no right to the menu behind them.

This is the layer that actually secures the PWA — the Home.vue filter and the router
guard are cosmetic, and a caller with curl never sees either. Every test runs as a real
non-Administrator user, because Administrator bypasses permissions and would pass these
tests no matter how wrong the rules were.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.ess import gate as ess_gate
from container_depot.ess import position_survey as ess_position
from container_depot.ess import repairs as ess_repairs
from container_depot.ess.guard import require_menu

USERS = {
	"Security": "guard-security@example.com",
	"Team Cleaning": "guard-cleaning@example.com",
	"Cashier": "guard-cashier@example.com",
	"Team Survey": "guard-survey@example.com",
}


def _user(email: str, role: str) -> None:
	if frappe.db.exists("User", email):
		frappe.delete_doc("User", email, ignore_permissions=True, force=True)
	doc = frappe.get_doc({
		"doctype": "User",
		"email": email,
		"first_name": email.split("@")[0],
		"send_welcome_email": 0,
		"user_type": "System User",
	}).insert(ignore_permissions=True)
	doc.add_roles(role)


class TestEssGuard(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		for role, email in USERS.items():
			_user(email, role)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for email in USERS.values():
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, ignore_permissions=True, force=True)
		frappe.db.commit()
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def test_cashier_cannot_call_gate_out(self):
		# Cashier holds Gate Entry READ (billing context), never write. gate_out is the
		# `readyOut` menu, which keys on write.
		frappe.set_user(USERS["Cashier"])
		with self.assertRaises(frappe.PermissionError):
			ess_gate.gate_out(container="NOPE")

	def test_team_cleaning_cannot_call_mr_start(self):
		frappe.set_user(USERS["Team Cleaning"])
		with self.assertRaises(frappe.PermissionError):
			ess_repairs.mr_start(repair_order="NOPE")

	def test_security_can_call_gate_out(self):
		# Security has Gate Entry rwcs, so the guard lets them through. The call then
		# fails on the bogus container — a business error, NOT a PermissionError, which
		# is exactly what "the guard let me past" looks like.
		frappe.set_user(USERS["Security"])
		require_menu("readyOut")  # does not raise
		with self.assertRaises(frappe.ValidationError):
			ess_gate.gate_out(container="NOPE-NOT-A-CONTAINER")

	def test_survey_cannot_approve_position(self):
		# The write/submit split, enforced at the endpoint: Team Survey records surveys
		# but does not sign them off.
		frappe.set_user(USERS["Team Survey"])
		require_menu("surveyPos")  # does not raise
		with self.assertRaises(frappe.PermissionError):
			ess_position.position_approve(name="NOPE")

	def test_unknown_menu_key_is_refused(self):
		# Fail closed: a typo in a guard call must not silently grant access.
		frappe.set_user(USERS["Security"])
		with self.assertRaises(frappe.PermissionError):
			require_menu("no-such-menu")

	def test_guest_rejected_everywhere(self):
		frappe.set_user("Guest")
		try:
			for menu_key in ("gate", "readyOut", "eir", "cleaning", "mr", "monitor"):
				with self.assertRaises(frappe.PermissionError):
					require_menu(menu_key)
		finally:
			frappe.set_user("Administrator")
