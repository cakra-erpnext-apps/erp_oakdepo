"""Branch-scoping backbone + scoped ESS endpoints (Depot PWA branch filter)."""
from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.operations.user_branch import (
	get_user_branches,
	get_user_depots,
	assert_in_user_branch,
)
from container_depot.ess.context import get_user_context
from container_depot.ess.inventory import get_tank_list, get_inventory_summary
from container_depot.ess.yard import yard_overview
from container_depot.api import gate_lookup
from container_depot.operations.eir import prefill, open_draft, create_eir
from container_depot.ess.notifications import list_notifications
from container_depot.tests._booking_helpers import make_booking_code
from container_depot.tests.test_api import ensure_test_customer

BR_MEDAN = "Oak Depot Medan"
BR_SBY = "Oak Depot Surabaya"
USER_MEDAN = "branchtest_medan@oak.local"
USER_ALL = "branchtest_all@oak.local"


def _ensure_branch(name):
	if not frappe.db.exists("Branch", name):
		frappe.get_doc({"doctype": "Branch", "branch": name}).insert(ignore_permissions=True)


def _ensure_depot(code, name, branch):
	if not frappe.db.exists("Depot", code):
		frappe.get_doc({
			"doctype": "Depot", "depot_code": code, "depot_name": name,
			"branch": branch, "is_active": 1,
		}).insert(ignore_permissions=True)
	else:
		frappe.db.set_value("Depot", code, "branch", branch)


def _ensure_user(email, branches):
	if not frappe.db.exists("User", email):
		frappe.get_doc({
			"doctype": "User", "email": email, "first_name": email.split("@")[0],
			"send_welcome_email": 0, "roles": [{"role": "System Manager"}],
		}).insert(ignore_permissions=True)
	frappe.db.delete("User Permission", {"user": email, "allow": "Branch"})
	for b in branches:
		frappe.get_doc({
			"doctype": "User Permission", "user": email, "allow": "Branch",
			"for_value": b, "apply_to_all_doctypes": 1,
		}).insert(ignore_permissions=True)


def _build_scoping_fixtures():
	_ensure_branch(BR_MEDAN)
	_ensure_branch(BR_SBY)
	_ensure_depot("BST_MD1", "Branch Test Medan 1", BR_MEDAN)
	_ensure_depot("BST_SB1", "Branch Test Surabaya 1", BR_SBY)
	_ensure_user(USER_MEDAN, [BR_MEDAN])
	_ensure_user(USER_ALL, [])  # no branch UP = all branches
	frappe.db.commit()


def _teardown_scoping_fixtures():
	for u in (USER_MEDAN, USER_ALL):
		frappe.db.delete("User Permission", {"user": u})
		if frappe.db.exists("User", u):
			frappe.delete_doc("User", u, force=True, ignore_permissions=True)
	for d in ("BST_MD1", "BST_SB1"):
		if frappe.db.exists("Depot", d):
			frappe.db.delete("Depot", {"name": d})
	frappe.db.commit()


class TestBranchHelpers(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		_teardown_scoping_fixtures()
		_build_scoping_fixtures()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		_teardown_scoping_fixtures()
		super().tearDownClass()

	def test_branches_for_scoped_user(self):
		self.assertEqual(get_user_branches(USER_MEDAN), [BR_MEDAN])

	def test_branches_none_for_unscoped_user(self):
		self.assertIsNone(get_user_branches(USER_ALL))

	def test_depots_for_scoped_user(self):
		depots = get_user_depots(USER_MEDAN)
		self.assertIn("BST_MD1", depots)
		self.assertNotIn("BST_SB1", depots)

	def test_depots_none_for_unscoped_user(self):
		self.assertIsNone(get_user_depots(USER_ALL))

	def test_assert_in_branch_passes_for_own_depot(self):
		frappe.set_user(USER_MEDAN)
		try:
			assert_in_user_branch(depot="BST_MD1")  # no raise
		finally:
			frappe.set_user("Administrator")

	def test_assert_in_branch_blocks_other_depot(self):
		frappe.set_user(USER_MEDAN)
		try:
			with self.assertRaises(frappe.PermissionError):
				assert_in_user_branch(depot="BST_SB1")
		finally:
			frappe.set_user("Administrator")

	def test_assert_in_branch_noop_for_all_user(self):
		frappe.set_user(USER_ALL)
		try:
			assert_in_user_branch(depot="BST_SB1")  # no raise (all branches)
		finally:
			frappe.set_user("Administrator")


class TestUserContext(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		_teardown_scoping_fixtures()
		_build_scoping_fixtures()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		_teardown_scoping_fixtures()
		super().tearDownClass()

	def test_context_scoped_user(self):
		frappe.set_user(USER_MEDAN)
		try:
			ctx = get_user_context()
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(ctx["user"], USER_MEDAN)
		self.assertEqual(ctx["branches"], [BR_MEDAN])
		self.assertFalse(ctx["all_branches"])

	def test_context_all_user(self):
		frappe.set_user(USER_ALL)
		try:
			ctx = get_user_context()
		finally:
			frappe.set_user("Administrator")
		self.assertTrue(ctx["all_branches"])
		self.assertEqual(ctx["branches"], [])

	def test_context_rejects_guest(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				get_user_context()
		finally:
			frappe.set_user("Administrator")


class TestInventoryScoping(FrappeTestCase):
	TANKS = {"BSTU0000001": "BST_MD1", "BSTU0000002": "BST_SB1"}

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		_teardown_scoping_fixtures()
		_build_scoping_fixtures()
		for no, depot in cls.TANKS.items():
			if not frappe.db.exists("Container", no):
				frappe.get_doc({
					"doctype": "Container", "container_no": no, "container_type": "ISO Tank",
					"status": "Available", "depot": depot,
				}).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.db.delete("Container Movement", {"container": ["in", list(cls.TANKS)]})
		frappe.db.delete("Container", {"name": ["in", list(cls.TANKS)]})
		_teardown_scoping_fixtures()
		super().tearDownClass()

	def test_tank_list_scoped_to_branch(self):
		frappe.set_user(USER_MEDAN)
		try:
			res = get_tank_list()
		finally:
			frappe.set_user("Administrator")
		nos = {i["container_no"] for i in res["items"]}
		self.assertIn("BSTU0000001", nos)
		self.assertNotIn("BSTU0000002", nos)

	def test_tank_list_blocks_out_of_branch_depot_param(self):
		frappe.set_user(USER_MEDAN)
		try:
			res = get_tank_list(depot="BST_SB1")  # explicitly asking other branch
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(res["items"], [])

	def test_tank_list_unscoped_sees_all(self):
		frappe.set_user(USER_ALL)
		try:
			res = get_tank_list()
		finally:
			frappe.set_user("Administrator")
		nos = {i["container_no"] for i in res["items"]}
		self.assertTrue({"BSTU0000001", "BSTU0000002"} <= nos)


class TestYardOverviewScoping(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		_teardown_scoping_fixtures()
		_build_scoping_fixtures()
		for code, depot in (("BSTZ-MD", "BST_MD1"), ("BSTZ-SB", "BST_SB1")):
			if not frappe.db.exists("Yard Zone", code):
				frappe.get_doc({
					"doctype": "Yard Zone", "zone_code": code, "zone_name": code,
					"depot": depot, "category": "Ready", "capacity": 10,
					"max_rows": 5, "max_rows_full": 6, "max_tiers": 5, "is_active": 1,
				}).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.db.delete("Yard Zone", {"name": ["in", ["BSTZ-MD", "BSTZ-SB"]]})
		_teardown_scoping_fixtures()
		super().tearDownClass()

	def test_overview_scoped_to_branch_depots(self):
		frappe.set_user(USER_MEDAN)
		try:
			res = yard_overview()
		finally:
			frappe.set_user("Administrator")
		zone_codes = {z["zone_code"] for z in res["zones"]}
		self.assertIn("BSTZ-MD", zone_codes)
		self.assertNotIn("BSTZ-SB", zone_codes)
		depot_codes = {d["code"] for d in res["depots"]}
		self.assertIn("BST_MD1", depot_codes)
		self.assertNotIn("BST_SB1", depot_codes)

	def test_overview_depot_rollup_fields(self):
		frappe.set_user(USER_MEDAN)
		try:
			res = yard_overview()
		finally:
			frappe.set_user("Administrator")
		md = next(d for d in res["depots"] if d["code"] == "BST_MD1")
		for key in ("name", "branch", "occupied", "capacity", "utilization", "full_count", "zone_count"):
			self.assertIn(key, md)
		self.assertEqual(md["zone_count"], 1)
		self.assertEqual(md["capacity"], 10)


class TestGateBranchBlock(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		_teardown_scoping_fixtures()
		_build_scoping_fixtures()
		cls.customer = ensure_test_customer("Branch Test Customer")

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		_teardown_scoping_fixtures()
		super().tearDownClass()

	def test_gate_lookup_blocks_other_branch(self):
		# A booking whose branch is Surabaya; a Medan-scoped user must be rejected.
		code = make_booking_code(
			customer=self.customer, container_no="BSTU0000050", direction="Tank In"
		)
		frappe.db.set_value("Container Booking", code.booking, "branch", BR_SBY)
		frappe.db.commit()
		frappe.set_user(USER_MEDAN)
		try:
			res = gate_lookup(code=code.code)
		finally:
			frappe.set_user("Administrator")
		# Out-of-branch lookups return an error payload (valid is False).
		self.assertFalse(res.get("valid", False))

	def test_gate_lookup_allows_own_branch(self):
		code = make_booking_code(
			customer=self.customer, container_no="BSTU0000051", direction="Tank In"
		)
		frappe.db.set_value("Container Booking", code.booking, "branch", BR_MEDAN)
		frappe.db.commit()
		frappe.set_user(USER_MEDAN)
		try:
			res = gate_lookup(code=code.code)
		finally:
			frappe.set_user("Administrator")
		self.assertTrue(res.get("valid", False))


class TestEirBranchBlock(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		_teardown_scoping_fixtures()
		_build_scoping_fixtures()
		if not frappe.db.exists("Container", "BSTU0000060"):
			frappe.get_doc({
				"doctype": "Container", "container_no": "BSTU0000060", "container_type": "ISO Tank",
				"status": "Available", "depot": "BST_SB1",  # Surabaya
			}).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.db.delete("Container Movement", {"container": "BSTU0000060"})
		frappe.db.delete("Container", {"name": "BSTU0000060"})
		_teardown_scoping_fixtures()
		super().tearDownClass()

	def test_eir_prefill_blocks_other_branch(self):
		frappe.set_user(USER_MEDAN)
		try:
			with self.assertRaises(frappe.PermissionError):
				prefill(container_no="BSTU0000060")
		finally:
			frappe.set_user("Administrator")

	def test_eir_open_draft_blocks_other_branch(self):
		frappe.set_user(USER_MEDAN)
		try:
			with self.assertRaises(frappe.PermissionError):
				open_draft(container_no="BSTU0000060")
		finally:
			frappe.set_user("Administrator")

	def test_eir_create_blocks_other_branch(self):
		frappe.set_user(USER_MEDAN)
		try:
			with self.assertRaises(frappe.PermissionError):
				create_eir(inspection_type="EIR-In", container="BSTU0000060")
		finally:
			frappe.set_user("Administrator")


class TestNotificationScoping(FrappeTestCase):
	# Two containers in different branches act as notification source documents;
	# the notification's branch is resolved via Container.depot -> Depot.branch.
	TANKS = {"BSTU0000070": "BST_MD1", "BSTU0000071": "BST_SB1"}

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		_teardown_scoping_fixtures()
		_build_scoping_fixtures()
		for no, depot in cls.TANKS.items():
			if not frappe.db.exists("Container", no):
				frappe.get_doc({
					"doctype": "Container", "container_no": no, "container_type": "ISO Tank",
					"status": "Available", "depot": depot,
				}).insert(ignore_permissions=True)
		frappe.db.delete("Notification Log", {"for_user": USER_MEDAN})

		def _notif(subject, dt=None, dn=None):
			frappe.get_doc({
				"doctype": "Notification Log", "for_user": USER_MEDAN, "subject": subject,
				"document_type": dt, "document_name": dn, "type": "Alert",
			}).insert(ignore_permissions=True)

		_notif("Cont md", "Container", "BSTU0000070")
		_notif("Cont sb", "Container", "BSTU0000071")
		_notif("System note")  # no source doc -> unresolvable branch -> kept
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.db.delete("Notification Log", {"for_user": USER_MEDAN})
		frappe.db.delete("Container Movement", {"container": ["in", list(cls.TANKS)]})
		frappe.db.delete("Container", {"name": ["in", list(cls.TANKS)]})
		_teardown_scoping_fixtures()
		super().tearDownClass()

	def test_notifications_scoped_to_branch(self):
		frappe.set_user(USER_MEDAN)
		try:
			res = list_notifications()
		finally:
			frappe.set_user("Administrator")
		subjects = {i["subject"] for i in res["items"]}
		self.assertIn("Cont md", subjects)
		self.assertNotIn("Cont sb", subjects)

	def test_notifications_keep_unresolvable(self):
		frappe.set_user(USER_MEDAN)
		try:
			res = list_notifications()
		finally:
			frappe.set_user("Administrator")
		subjects = {i["subject"] for i in res["items"]}
		self.assertIn("System note", subjects)  # unknown branch kept (conservative)

	def test_notifications_unread_excludes_other_branch(self):
		# All three were created unread; only the Medan + system ones survive the filter.
		frappe.set_user(USER_MEDAN)
		try:
			res = list_notifications()
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(res["unread"], 2)
