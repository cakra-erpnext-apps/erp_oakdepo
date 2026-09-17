"""An external customer account sees its OWN company's depot records and nothing else.

Two customers, two tanks, one gate row and one movement row each — then everything is
read back as a logged-in customer user. What is being pinned:

* the company flag is ONE User Permission (allow=Customer), written by the Customer
  Portal User lifecycle, and withdrawn again when the row leaves Active;
* the doctypes Frappe cannot scope by itself are scoped anyway (Gate Entry and Container
  Movement carry no Customer link);
* a second Customer link on a record does NOT hide it from its owner — the and-joined
  User Permission conditions are exactly the trap ``ignore_user_permissions`` is set for
  (a tank owned by A whose last EMKL was B must stay in A's list);
* the role is read-only.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.customer_scope import get_user_customers
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

	def test_gate_entry_filtered_through_the_tank(self):
		frappe.set_user(USER)
		names = frappe.get_list("Gate Entry", pluck="name")
		self.assertIn(self.gates[OWNER], names)
		self.assertNotIn(self.gates[OTHER], names)

	def test_container_movement_filtered_through_the_tank(self):
		frappe.set_user(USER)
		names = frappe.get_list("Container Movement", pluck="name")
		self.assertIn(self.moves[OWNER], names)
		self.assertNotIn(self.moves[OTHER], names)

	def test_rate_card_is_its_own_contract_only(self):
		"""The rate card is the contract now, and Frappe scopes it by its Customer link —
		nothing in this app grants a customer any doctype outside the module."""
		frappe.set_user(USER)
		names = frappe.get_list("Depot Contract", pluck="name")
		self.assertEqual(names, [CONTRACTS[OWNER]])

	def test_opening_another_customers_record_is_refused(self):
		frappe.set_user(USER)
		self.assertTrue(frappe.has_permission("Gate Entry", doc=self.gates[OWNER]))
		self.assertFalse(frappe.has_permission("Gate Entry", doc=self.gates[OTHER]))
		self.assertFalse(frappe.has_permission("Container Movement", doc=self.moves[OTHER]))

	# --- the menu ----------------------------------------------------------

	def test_no_report_links_are_offered(self):
		"""`boot.get_allowed_reports` ends with a `frappe.get_list("Report")`, so closing
		the Report doctype is what empties the report links out of the workspace cards and
		the sidebar — instead of drawing a link that throws "You don't have permission to
		get a report on:" when clicked."""
		frappe.set_user(USER)
		frappe.clear_cache(user=USER)
		from frappe.boot import get_allowed_reports

		self.assertEqual(get_allowed_reports(), {})

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
		for row in perms:
			self.assertEqual(row.read, 1, row.parent)
			# `report` is denied with the rest: a Query Report runs raw SQL, which none of
			# the scoping in customer_scope.py touches. See the `v` grammar in install.py.
			for flag in ("write", "create", "submit", "delete", "email", "report"):
				self.assertEqual(row.get(flag), 0, f"{row.parent}.{flag}")

	def test_query_reports_are_refused(self):
		"""The one path that would bypass every filter in customer_scope: a Query Report
		builds its own SQL. It is gated by the ref doctype's `report` permission, which the
		customer role does not hold."""
		frappe.set_user(USER)
		self.assertTrue(frappe.has_permission("Container Booking", "read"))
		self.assertFalse(frappe.has_permission("Container Booking", "report"))

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
