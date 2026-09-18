"""An external customer account sees its OWN company's depot records and nothing else.

Two customers, two tanks, one gate row and one movement row each — then everything is
read back as a logged-in customer user. What is being pinned:

* the company flag is ONE User Permission (allow=Customer), written by the Customer
  Portal User lifecycle, and withdrawn again when the row leaves Active;
* the doctypes Frappe cannot scope by itself are scoped anyway (Gate Entry and Container
  Movement carry no Customer link) — the customer role no longer reads either, but the
  conditions stay pinned: they are one Permission Manager edit away from being live again;
* the reports it IS offered each filter by customer in their own query, which is the only
  thing that scopes a Script Report: `frappe.get_all` runs with ignore_permissions=True,
  so a report is unscoped until it asks;
* a second Customer link on a record does NOT hide it from its owner — the and-joined
  User Permission conditions are exactly the trap ``ignore_user_permissions`` is set for
  (a tank owned by A whose last EMKL was B must stay in A's list);
* the role is read-only.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.customer_scope import CUSTOMER_REPORTS, get_user_customers
from container_depot.install import CUSTOMER_DESK_ROLE

OWNER = "CS Owner Co"
OTHER = "CS Other Co"
USER = "cs-portal@example.com"
TANKS = {OWNER: "CSTU0000001", OTHER: "CSTU0000002"}
CONTRACTS: dict = {}  # customer -> its Depot Contract, filled in setUpClass


def _customer(name):
	if not frappe.db.exists("Customer", name):
		frappe.get_doc({
			"doctype": "Customer",
			"customer_name": name,
			"customer_type": "Company",
			"is_tank_owner": 1,
		}).insert(ignore_permissions=True)
	return name


def _container(no, principal, emkl=None):
	if frappe.db.exists("Container", no):
		frappe.delete_doc("Container", no, ignore_permissions=True, force=True)
	doc = frappe.get_doc({
		"doctype": "Container",
		"container_no": no,
		"container_type": "ISO Tank",
		"principal": principal,
		"status": "In_Depot",
	}).insert(ignore_permissions=True)
	if emkl:
		# Written the way the bon writes it — the field is read_only on the form.
		frappe.db.set_value("Container", no, "emkl", emkl, update_modified=False)
	return doc.name


def _gate_entry(container_no):
	return frappe.get_doc({
		"doctype": "Gate Entry",
		"container_no": container_no,
		"status": "Active",
	}).insert(ignore_permissions=True).name


def _movement(container_no):
	return frappe.get_doc({
		"doctype": "Container Movement",
		"container": container_no,
		"movement_timestamp": frappe.utils.now_datetime(),
		"event_type": "Yard",
	}).insert(ignore_permissions=True).name


def _activity(container_no, principal):
	return frappe.get_doc({
		"doctype": "Container Activity",
		"container": container_no,
		"principal": principal,
		"activity_type": "Gate In",
		"activity_time": frappe.utils.now_datetime(),
		"summary": "fixture",
	}).insert(ignore_permissions=True).name


def _contract(customer):
	"""A customer's rate card, which since 2026-09-17 IS its Depot Contract.

	Left Draft on purpose: scoping is by the Customer link, which Frappe applies whatever the
	status says, and an Active contract would drag in payment terms and a credit limit that
	have nothing to do with what is being tested here.
	"""
	from frappe.utils import add_days, today

	return frappe.get_doc({
		"doctype": "Depot Contract",
		"customer": customer,
		"currency": "IDR",
		"status": "Draft",
		"payment_type": "Cash",
		"valid_from": today(),
		"valid_to": add_days(today(), 365),
	}).insert(ignore_permissions=True).name


def _portal_row(status="Active"):
	name = frappe.db.exists("Customer Portal User", {"user": USER})
	doc = frappe.get_doc("Customer Portal User", name) if name else frappe.new_doc(
		"Customer Portal User"
	)
	doc.update({"customer": OWNER, "user": USER, "approval_status": status})
	doc.save(ignore_permissions=True)
	return doc


class TestCustomerScope(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		for c in (OWNER, OTHER):
			_customer(c)
		# The owner's tank also carries the OTHER customer as its EMKL: that is the
		# and-joined-conditions trap, and it must stay visible to its owner.
		_container(TANKS[OWNER], OWNER, emkl=OTHER)
		_container(TANKS[OTHER], OTHER)
		cls.gates = {c: _gate_entry(t) for c, t in TANKS.items()}
		cls.moves = {c: _movement(t) for c, t in TANKS.items()}
		cls.activities = {c: _activity(t, c) for c, t in TANKS.items()}
		for c in (OWNER, OTHER):
			CONTRACTS[c] = _contract(c)
		if frappe.db.exists("User", USER):
			frappe.delete_doc("User", USER, ignore_permissions=True, force=True)
		frappe.get_doc({
			"doctype": "User",
			"email": USER,
			"first_name": "CS Portal",
			"send_welcome_email": 0,
		}).insert(ignore_permissions=True)
		_portal_row()
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for name in frappe.get_all("Customer Portal User", filters={"user": USER}, pluck="name"):
			frappe.delete_doc("Customer Portal User", name, ignore_permissions=True, force=True)
		for name in cls.activities.values():
			frappe.delete_doc("Container Activity", name, ignore_permissions=True, force=True)
		for name in cls.moves.values():
			frappe.delete_doc("Container Movement", name, ignore_permissions=True, force=True)
		for name in cls.gates.values():
			frappe.delete_doc("Gate Entry", name, ignore_permissions=True, force=True)
		for tank in TANKS.values():
			frappe.delete_doc("Container", tank, ignore_permissions=True, force=True)
		for name in CONTRACTS.values():
			frappe.delete_doc("Depot Contract", name, ignore_permissions=True, force=True)
		CONTRACTS.clear()
		for perm in frappe.get_all("User Permission", filters={"user": USER}, pluck="name"):
			frappe.delete_doc("User Permission", perm, ignore_permissions=True, force=True)
		if frappe.db.exists("User", USER):
			frappe.delete_doc("User", USER, ignore_permissions=True, force=True)
		for c in (OWNER, OTHER):
			if frappe.db.exists("Customer", c):
				frappe.delete_doc("Customer", c, ignore_permissions=True, force=True)
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		_portal_row()

	def tearDown(self):
		frappe.set_user("Administrator")

	# --- provisioning ------------------------------------------------------

	def test_active_row_grants_scope_and_both_roles(self):
		roles = set(frappe.get_roles(USER))
		self.assertIn(CUSTOMER_DESK_ROLE, roles)
		self.assertIn("Customer", roles)
		self.assertEqual(get_user_customers(USER), [OWNER])

	def test_deactivating_the_row_takes_it_all_back(self):
		_portal_row(status="Inactive")
		self.assertIsNone(get_user_customers(USER))
		roles = set(frappe.get_roles(USER))
		self.assertNotIn(CUSTOMER_DESK_ROLE, roles)

	def test_internal_user_is_unrestricted(self):
		self.assertIsNone(get_user_customers("Administrator"))

	# --- data scoping ------------------------------------------------------

	def test_sees_only_own_tank_despite_other_customer_on_emkl(self):
		frappe.set_user(USER)
		names = frappe.get_list("Container", pluck="name")
		self.assertIn(TANKS[OWNER], names)
		self.assertNotIn(TANKS[OTHER], names)

	def test_the_audit_lists_are_closed_to_the_customer(self):
		"""The sidebar's "Audit" section — Gate Entry, Container Movement, Container
		Activity — is the internal movement record, and the customer reads its own half of
		it as the three reports in "Container Inventory" instead (patch v1_05). A Workspace
		Sidebar Item carries no role, so withdrawing `read` is what takes the section off
		the rail."""
		frappe.set_user(USER)
		for doctype in ("Gate Entry", "Container Movement", "Container Activity"):
			with self.subTest(doctype=doctype):
				self.assertFalse(frappe.has_permission(doctype, "read"))

	def test_the_audit_query_conditions_still_scope(self):
		"""Kept live even though the role cannot read those doctypes today: the conditions
		are one Permission Manager edit away from mattering again, and they are the only
		thing standing between a customer and the whole depot's gate log."""
		from container_depot.customer_scope import container_movement_query, gate_entry_query

		for condition in (gate_entry_query(USER), container_movement_query(USER)):
			self.assertIn(f"'{OWNER}'", condition)
			self.assertNotIn(OTHER, condition)
		frappe.set_user("Administrator")
		self.assertEqual(gate_entry_query("Administrator"), "")

	def test_rate_card_is_its_own_contract_only(self):
		"""The rate card is the contract now, and Frappe scopes it by its Customer link —
		nothing in this app grants a customer any doctype outside the module."""
		frappe.set_user(USER)
		names = frappe.get_list("Depot Contract", pluck="name")
		self.assertEqual(names, [CONTRACTS[OWNER]])

	def test_opening_another_customers_record_is_refused(self):
		"""`has_permission` hooks, tested at their own level: the role's DocPerm on these
		two is gone, so `frappe.has_permission` would answer False for both owners and prove
		nothing about the scoping."""
		from container_depot.customer_scope import (
			container_movement_permission,
			gate_entry_permission,
		)

		frappe.set_user(USER)
		self.assertTrue(gate_entry_permission(frappe._dict(container_no=TANKS[OWNER])))
		self.assertFalse(gate_entry_permission(frappe._dict(container_no=TANKS[OTHER])))
		self.assertFalse(container_movement_permission(frappe._dict(container=TANKS[OTHER])))

	# --- the menu ----------------------------------------------------------

	def test_only_the_customer_reports_are_offered(self):
		"""`boot.get_allowed_reports` ends with a `frappe.get_list("Report")`, so the name
		filter on the Report doctype is what decides which report links the workspace cards
		and the sidebar draw — the rest are never rendered, rather than rendered and then
		refused on click."""
		frappe.set_user(USER)
		frappe.clear_cache(user=USER)
		from frappe.boot import get_allowed_reports

		self.assertEqual(set(get_allowed_reports()), CUSTOMER_REPORTS)

	def test_url_shortcuts_are_hidden(self):
		"""The "Download App" tile installs the yard PWA, which a customer may not open."""
		from container_depot.boot import patch_workspace_url_shortcuts
		from frappe.desk.desktop import Workspace

		patch_workspace_url_shortcuts()
		ws = Workspace.__new__(Workspace)  # the flag is read off the session, not the doc
		frappe.set_user(USER)
		self.assertFalse(Workspace.is_item_allowed(ws, "", "URL"))
		frappe.set_user("Administrator")
		self.assertTrue(Workspace.is_item_allowed(ws, "", "URL"))

	def test_empty_sidebar_sections_are_dropped(self):
		"""A heading with every item filtered away is a menu that lies about what the
		account can do. Frappe appends Section Breaks without testing them."""
		from container_depot.boot import prune_empty_sidebar_sections

		boot = frappe._dict(workspace_sidebar_item={
			"x": {"items": [
				{"type": "Section Break", "label": "Empty"},
				{"type": "Section Break", "label": "Kept"},
				{"type": "Link", "label": "A Link"},
				{"type": "Section Break", "label": "Trailing"},
			]}
		})
		prune_empty_sidebar_sections(boot)
		self.assertEqual(
			[i["label"] for i in boot.workspace_sidebar_item["x"]["items"]],
			["Kept", "A Link"],
		)

	# --- the role itself ---------------------------------------------------

	def test_role_is_read_only(self):
		perms = frappe.get_all(
			"Custom DocPerm",
			filters={"role": CUSTOMER_DESK_ROLE},
			fields=["parent", "read", "write", "create", "submit", "delete", "email", "report"],
		)
		self.assertTrue(perms, "the customer role has no permissions seeded")
		# Container Activity is the one row with `report` and no `read`: the history is read
		# through the report, the ledger's own list stays shut (patch v1_05).
		report_only = {"Container Activity"}
		# The doctypes the offered reports hang off. `report` alone does not decide which
		# report runs — a Script Report builds its own SQL, so the gate is the report NAME
		# (customer_scope.CUSTOMER_REPORTS), tested below.
		may_report = {"Container Booking", "Container", "Container Activity"}
		for row in perms:
			self.assertEqual(row.read, 0 if row.parent in report_only else 1, row.parent)
			for flag in ("write", "create", "submit", "delete", "email"):
				self.assertEqual(row.get(flag), 0, f"{row.parent}.{flag}")
			self.assertEqual(
				row.report, 1 if row.parent in may_report else 0, f"{row.parent}.report"
			)

	def test_unlisted_reports_are_refused_on_the_run_path(self):
		"""The list filter guards the MENU; `query_report.run` never consults it and fetches
		the report with `frappe.get_doc`. `Lift On Register` hangs off the same
		`Container Booking` the customer now holds `report` on, and counts the whole depot in
		raw SQL — so the name allowlist has to hold at the run path too."""
		from container_depot.boot import patch_query_report_customer_scope

		patch_query_report_customer_scope()
		from frappe.desk import query_report

		frappe.set_user(USER)
		with self.assertRaises(frappe.PermissionError):
			query_report.get_report_doc("Lift On Register")
		self.assertTrue(query_report.get_report_doc("Container Booking Register"))

	def test_booking_register_sql_is_scoped(self):
		"""The report writes its own SELECT, so `permission_query_conditions` never sees it
		and it has to ask customer_scope for the condition by hand. Without that clause in
		the WHERE the customer reads every booking in the depot."""
		from unittest.mock import patch

		from container_depot.container_depot.report.container_booking_register import (
			container_booking_register as register,
		)
		from container_depot.customer_scope import booking_sql_filter

		frappe.set_user(USER)
		with patch.object(frappe.db, "sql", return_value=[]) as sql:
			register._rows({})
		self.assertIn(f"b.customer in ('{OWNER}')", sql.call_args[0][0])

		frappe.set_user("Administrator")
		self.assertEqual(booking_sql_filter("b"), "1=1")  # internal staff, unchanged

	# --- the reports the customer IS offered ---------------------------------

	def test_the_inventory_section_reports_run_and_show_only_own_tanks(self):
		"""The three reports that replaced the Audit lists. Each builds its own query, so
		each has to ask customer_scope for the filter by hand — `frappe.get_all` runs with
		ignore_permissions=True and a Script Report never meets
		`permission_query_conditions`. One assertion per report, because a missing filter
		looks exactly like a working report until someone else's tank shows up in it."""
		from container_depot.container_depot.report.container_activity import (
			container_activity as activity_report,
		)
		from container_depot.container_depot.report.container_inventory import (
			container_inventory as inventory_report,
		)
		from container_depot.container_depot.report.inventory_kpi_per_principal import (
			inventory_kpi_per_principal as kpi_report,
		)

		frappe.set_user(USER)

		tanks = {r["container_no"] for r in inventory_report.execute({})[1]}
		self.assertIn(TANKS[OWNER], tanks)
		self.assertNotIn(TANKS[OTHER], tanks)

		containers = {r["container"] for r in activity_report.execute({})[1]}
		self.assertIn(TANKS[OWNER], containers)
		self.assertNotIn(TANKS[OTHER], containers)

		principals = {r["principal"] for r in kpi_report.execute({})[1]}
		self.assertEqual(principals, {OWNER})

	def test_the_storage_charges_report_shows_only_own_tanks(self):
		"""Same trap, older report: it reads Container through `frappe.get_all`, which does
		NOT apply the Customer User Permission."""
		from container_depot.container_depot.report.storage_charges import storage_charges

		frappe.set_user(USER)
		tanks = {r["container"] for r in storage_charges.execute({})[1]}
		self.assertNotIn(TANKS[OTHER], tanks)

	def test_the_offered_reports_run(self):
		"""The run path's allowlist and the menu's must name the same reports — a link that
		is drawn and then refused on click is worse than no link."""
		from container_depot.boot import patch_query_report_customer_scope

		patch_query_report_customer_scope()
		from frappe.desk import query_report

		frappe.set_user(USER)
		for report in sorted(CUSTOMER_REPORTS):
			with self.subTest(report=report):
				self.assertTrue(query_report.get_report_doc(report))

	def test_own_masters_are_readable(self):
		"""The customer types its own bookings and contract lines against these."""
		frappe.set_user(USER)
		for doctype in ("Cargo", "Item", "Item Group", "Customer", "Storage Charge"):
			self.assertTrue(frappe.has_permission(doctype, "read"), doctype)
		# ...and `Customer` still only lists its own companies: a User Permission on a
		# doctype applies to that doctype's own name.
		self.assertEqual([c.name for c in frappe.get_list("Customer")], [OWNER])

	def test_another_apps_doctypes_are_closed(self):
		"""A System User inherits the stock `All` / `Desk User` reads — helpdesk tickets,
		HR ledgers, integration settings. The wildcard gate in customer_scope closes them
		without touching the Desk's own plumbing."""
		frappe.set_user(USER)
		for doctype in ("HD Ticket", "Leave Ledger Entry", "Quality Goal", "Token Cache"):
			if not frappe.db.exists("DocType", doctype):
				continue
			with self.subTest(doctype=doctype):
				self.assertEqual(frappe.get_list(doctype, limit=1), [])
		# ...and the plumbing still answers, or the Desk itself stops working. Number Card
		# is the one that needs a patch to survive an empty report allowlist — without it
		# every dashboard the account opens dies on `IN ()`. See boot.py.
		from container_depot.boot import patch_number_card_empty_report_list

		patch_number_card_empty_report_list()
		for doctype in ("ToDo", "File", "Notification Log", "Number Card", "Dashboard Chart"):
			with self.subTest(doctype=doctype):
				frappe.get_list(doctype, limit=1)

	def test_no_repair_or_cleaning_access(self):
		frappe.set_user(USER)
		for doctype in ("Repair Order", "Cleaning Order", "Inspection", "Sales Invoice"):
			self.assertFalse(
				frappe.has_permission(doctype, "read"), f"{doctype} should be closed"
			)
