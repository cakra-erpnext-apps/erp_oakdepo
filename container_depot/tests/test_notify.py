"""Depot event notifications — recipients are role + branch scoped, and an EIR /
order submit drops a Notification Log into the right users' feed (PWA + Desk bell)."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.operations import eir as eir_ops
from container_depot.operations.notify import (
	EIR_ROLES,
	_recipients,
	notify,
	notify_booking_created,
)
from container_depot.tests.test_api import ensure_test_branch, ensure_test_customer

BR_A = "Notify Branch A"
BR_B = "Notify Branch B"
U_A = "notify-a@example.com"   # restricted to branch A
U_B = "notify-b@example.com"   # restricted to branch B
U_HQ = "notify-hq@example.com"  # unrestricted (all branches)
DEPOT_A = "NOTIFDEPA"


def _user(email, branch=None):
	if not frappe.db.exists("User", email):
		frappe.get_doc({
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"send_welcome_email": 0,
			"roles": [{"role": "Depot PWA"}],
		}).insert(ignore_permissions=True)
	# Branch scope via a native Branch User Permission (empty = all branches).
	if branch and not frappe.db.exists(
		"User Permission", {"user": email, "allow": "Branch", "for_value": branch}
	):
		frappe.get_doc({
			"doctype": "User Permission",
			"user": email,
			"allow": "Branch",
			"for_value": branch,
			"apply_to_all_doctypes": 1,
		}).insert(ignore_permissions=True)


class TestDepotNotify(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		ensure_test_branch(BR_A)
		ensure_test_branch(BR_B)
		_user(U_A, BR_A)
		_user(U_B, BR_B)
		_user(U_HQ, None)
		if not frappe.db.exists("Depot", DEPOT_A):
			frappe.get_doc({
				"doctype": "Depot",
				"depot_code": DEPOT_A,
				"depot_name": "Notify Depot A",
				"branch": BR_A,
			}).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		for u in (U_A, U_B, U_HQ):
			frappe.db.delete("Notification Log", {"for_user": u})
			frappe.db.delete("User Permission", {"user": u})
			if frappe.db.exists("User", u):
				frappe.delete_doc("User", u, ignore_permissions=True, force=True)
		frappe.db.delete("Container", {"name": ["like", "NOTIFC%"]})
		if frappe.db.exists("Depot", DEPOT_A):
			frappe.db.delete("Depot", {"name": DEPOT_A})
		frappe.db.commit()
		super().tearDownClass()

	def test_recipients_scoped_by_branch_and_role(self):
		# Branch A event reaches the A user + the unrestricted HQ user, never the B user.
		recips = set(_recipients(BR_A, EIR_ROLES))
		self.assertIn(U_A, recips)
		self.assertIn(U_HQ, recips)
		self.assertNotIn(U_B, recips)

	def test_recipients_excludes_users_without_the_role(self):
		# A role set the users don't hold yields nobody (Depot PWA is the only role here).
		self.assertEqual(_recipients(BR_A, {"Some Other Role"}), [])

	def test_notify_creates_one_log_per_recipient_and_skips_actor(self):
		frappe.set_user(U_A)  # actor is the A user
		try:
			n = notify(
				doctype="Inspection", name="NOTIF-DOC-X", subject="hi", branch=BR_A, roles=EIR_ROLES
			)
			# A user is the actor (skipped); only the HQ user remains for branch A.
			self.assertEqual(n, 1)
			self.assertTrue(frappe.db.exists("Notification Log", {"for_user": U_HQ, "document_name": "NOTIF-DOC-X"}))
			self.assertFalse(frappe.db.exists("Notification Log", {"for_user": U_A, "document_name": "NOTIF-DOC-X"}))
		finally:
			frappe.set_user("Administrator")
			frappe.db.delete("Notification Log", {"document_name": "NOTIF-DOC-X"})

	def test_booking_created_notifies_booking_roles_in_branch(self):
		frappe.set_user("Administrator")
		fake = frappe._dict(
			name="BKG-NOTIF-1", customer=None, branch=BR_A, payment_type="Cash", direction="Tank In"
		)
		try:
			notify_booking_created(fake)
			# Depot PWA is in BOOKING_ROLES, so the in-branch A user is notified.
			self.assertTrue(
				frappe.db.exists("Notification Log", {"for_user": U_A, "document_name": "BKG-NOTIF-1"})
			)
			# Out-of-branch user is not.
			self.assertFalse(
				frappe.db.exists("Notification Log", {"for_user": U_B, "document_name": "BKG-NOTIF-1"})
			)
		finally:
			frappe.db.delete("Notification Log", {"document_name": "BKG-NOTIF-1"})

	def test_eir_submit_notifies_in_branch(self):
		frappe.set_user("Administrator")
		frappe.get_doc({
			"doctype": "Container",
			"container_no": "NOTIFC00011",
			"container_type": "ISO Tank",
			"status": "In_Depot",
			"depot": DEPOT_A,
			"principal": ensure_test_customer("Notify Test Principal"),
		}).insert(ignore_permissions=True)
		try:
			eir_ops.create_eir(
				inspection_type="EIR-In",
				container="NOTIFC00011",
				tank_status="Empty Dirty",
				submit=True,
			)
			logs = frappe.get_all(
				"Notification Log",
				filters={"for_user": U_A, "document_type": "Inspection"},
				fields=["subject"],
			)
			self.assertTrue(logs, "branch-A user should have received the EIR notification")
			# Subject carries the container + inspection type (no yard category anymore).
			self.assertTrue(any("NOTIFC00011" in (l.subject or "") for l in logs))
			self.assertTrue(any("EIR-In" in (l.subject or "") for l in logs))
			# The out-of-branch user must NOT be notified.
			self.assertFalse(
				frappe.db.exists("Notification Log", {"for_user": U_B, "document_type": "Inspection"})
			)
		finally:
			frappe.db.delete("Inspection", {"container": "NOTIFC00011"})
			frappe.db.delete("Notification Log", {"document_type": "Inspection"})
			frappe.db.delete("Container", {"name": "NOTIFC00011"})
			frappe.db.commit()
