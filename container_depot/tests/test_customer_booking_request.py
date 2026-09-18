"""A customer account raises its own booking, hands it over, and asks for it back.

The one thing a portal account DOES rather than reads. Three rules are pinned here, and
each of them is a hole if it goes:

* **whose booking it is.** The Principal is forced to the company the account belongs to,
  whatever the payload says (`_clamp_customer_request`);
* **the window.** A customer may edit its own booking while it still says ``Draft`` and
  nothing else — not once it is handed over (``Pengajuan``), never a submitted one, never
  somebody else's. `submit` is not on the account at all;
* **the inbox.** A ``Draft`` the customer has not sent is hidden from the internal lists,
  and everything from ``Pengajuan`` on is a normal draft to the office — including where a
  rollback lands, which is the one place the two names have to be told apart.

Everything past the handover (invoice, confirm, revision) stays OAK's, so the revision
request is a FLAG, not a status: the office grants it with the button it already had.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.container_depot.doctype.container_booking.container_booking import (
	request_revision,
	revert_booking_to_draft,
	rollback_to_draft,
	submit_request,
)
from container_depot.container_depot.doctype.container_booking.container_booking import (
	booking_container_query,
	parse_container_xlsx,
)
from container_depot.customer_scope import (
	_own_and_created,
	allowed_principals,
	container_booking_permission,
	container_booking_query,
	create_party,
	create_tank,
	customer_link_query,
)
from container_depot.tests.test_cash_gate import _ensure_test_depot
from container_depot.tests.test_container_booking import _cleanup_customer_world

OWNER = "CBR Owner Co"
OTHER = "CBR Other Co"
EMKL = "CBR Hauler Co"
USER = "cbr-portal@example.com"
EMKL_USER = "cbr-hauler@example.com"
STAFF = "cbr-staff@example.com"


def _customer(name, **roles):
	"""A Customer with its OAK Party Roles — the flags the whole scope hangs off."""
	if not frappe.db.exists("Customer", name):
		frappe.get_doc({
			"doctype": "Customer",
			"customer_name": name,
			"customer_type": "Company",
			**({"is_tank_owner": 1} if not roles else roles),
		}).insert(ignore_permissions=True)
	return name


def _user(email, first_name):
	if not frappe.db.exists("User", email):
		frappe.get_doc({
			"doctype": "User",
			"email": email,
			"first_name": first_name,
			"send_welcome_email": 0,
		}).insert(ignore_permissions=True)
	return email


class TestCustomerBookingRequest(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		# The DocPerm flags this whole feature rests on. Applied here rather than assumed:
		# the seeder is add-only, so on a site whose customer row predates this feature the
		# flags arrive with the patch and nowhere else.
		from container_depot.patches.v1_06.customer_booking_requests import execute as grant_perms

		grant_perms()
		_ensure_test_depot()
		for c in (OWNER, OTHER):
			_customer(c)
		# The EMKL: a transporter, NOT a tank owner. Case C in the party-role table.
		_customer(EMKL, is_transporter=1)
		_user(USER, "CBR Portal")
		_user(EMKL_USER, "CBR Hauler")
		_user(STAFF, "CBR Staff")
		for customer, user in ((OWNER, USER), (EMKL, EMKL_USER)):
			frappe.get_doc({
				"doctype": "Customer Portal User",
				"customer": customer,
				"user": user,
				"approval_status": "Active",
			}).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for c in (OWNER, OTHER, EMKL):
			_cleanup_customer_world(c)
		for user in (USER, EMKL_USER):
			for name in frappe.get_all("Customer Portal User", filters={"user": user}, pluck="name"):
				frappe.delete_doc("Customer Portal User", name, ignore_permissions=True, force=True)
			for perm in frappe.get_all("User Permission", filters={"user": user}, pluck="name"):
				frappe.delete_doc("User Permission", perm, ignore_permissions=True, force=True)
		for email in (USER, EMKL_USER, STAFF):
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, ignore_permissions=True, force=True)
		for c in (OWNER, OTHER, EMKL):
			if frappe.db.exists("Customer", c):
				frappe.delete_doc("Customer", c, ignore_permissions=True, force=True)
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")
		# Rollback FIRST: `_cleanup_customer_world` commits, so anything this test wrote is
		# still pending and would be made permanent by that commit rather than undone.
		frappe.db.rollback()
		_cleanup_customer_world(OWNER)
		# The parties these tests key in are real Customer masters, not booking fixtures —
		# and a booking billed to one is not swept by the owner's own cleanup.
		for name in frappe.get_all("Container", filters={"name": ["like", "CBRU%"]}, pluck="name"):
			frappe.db.delete("Container Movement", {"container": name})
			frappe.delete_doc("Container", name, ignore_permissions=True, force=True)
		for name in frappe.get_all("Customer", filters={"created_by_customer": OWNER}, pluck="name"):
			_cleanup_customer_world(name)
			frappe.delete_doc("Customer", name, ignore_permissions=True, force=True)
		frappe.db.commit()

	# --- fixtures ----------------------------------------------------------

	def _raise_booking(self, **overrides):
		"""A booking raised BY the customer account, through the permission path."""
		frappe.set_user(USER)
		payload = {
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": OWNER,
			"principal": OWNER,
			"payment_type": "TOP",
			"items": [{"container_no": "CBRU0000001"}],
		}
		payload.update(overrides)
		doc = frappe.get_doc(payload).insert()
		frappe.set_user("Administrator")
		return doc

	# --- whose booking it is -----------------------------------------------

	def test_it_is_stamped_and_falls_back_to_the_accounts_own_company(self):
		"""The stamp is what says WHOSE request it is — an EMKL's booking is billed to one
		company and owned by another, so neither field answers it."""
		doc = self._raise_booking(principal=None)
		self.assertEqual(doc.requested_by_customer, OWNER)
		self.assertEqual(doc.principal, OWNER, "a tank owner's blank Principal is its own")

	def test_a_booking_for_another_company_is_refused_outright(self):
		frappe.set_user(USER)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc({
				"doctype": "Container Booking",
				"direction": "Tank In",
				"customer": OTHER,
				"principal": OTHER,
				"items": [{"container_no": "CBRU0000002"}],
			}).insert()

	def test_internal_bookings_are_not_stamped(self):
		doc = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": OWNER,
			"principal": OWNER,
			"payment_type": "TOP",
			"items": [{"container_no": "CBRU0000003"}],
		}).insert(ignore_permissions=True)
		self.assertFalse(doc.requested_by_customer)

	# --- the inbox ---------------------------------------------------------

	def test_an_unsent_draft_is_hidden_from_the_internal_lists(self):
		doc = self._raise_booking()
		condition = container_booking_query(STAFF)
		self.assertIn("requested_by_customer", condition)
		self.assertIn("!= 'Draft'", condition)
		self.assertFalse(container_booking_permission(doc.as_dict(), "read", STAFF))

	def test_ajukan_puts_it_on_the_office_list(self):
		doc = self._raise_booking()
		frappe.set_user(USER)
		submit_request(doc.name)
		frappe.set_user("Administrator")
		doc.reload()
		self.assertEqual(doc.booking_status, "Pengajuan")
		self.assertTrue(container_booking_permission(doc.as_dict(), "read", STAFF))

	def test_the_customer_is_read_only_once_it_is_handed_over(self):
		doc = self._raise_booking()
		self.assertTrue(container_booking_permission(doc.as_dict(), "write", USER))
		frappe.set_user(USER)
		submit_request(doc.name)
		frappe.set_user("Administrator")
		doc.reload()
		self.assertFalse(container_booking_permission(doc.as_dict(), "write", USER))
		# And it can only be handed over once — refused by the permission itself, before
		# `submit_request` gets to look at the status.
		frappe.set_user(USER)
		with self.assertRaises(frappe.PermissionError):
			submit_request(doc.name)

	def test_confirming_is_never_the_customers(self):
		doc = self._raise_booking()
		for ptype in ("submit", "amend"):
			with self.subTest(ptype=ptype):
				self.assertFalse(container_booking_permission(doc.as_dict(), ptype, USER))

	def test_someone_elses_booking_is_invisible_whatever_the_status(self):
		other = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": OTHER,
			"principal": OTHER,
			"payment_type": "TOP",
			"items": [{"container_no": "CBRU0000004"}],
		}).insert(ignore_permissions=True)
		self.assertFalse(container_booking_permission(other.as_dict(), "read", USER))
		_cleanup_customer_world(OTHER)

	# --- OAK Party Roles decide whose tanks ---------------------------------

	def test_a_tank_owner_books_its_own_tanks_and_nobody_elses(self):
		self.assertEqual(allowed_principals(USER), [OWNER])
		frappe.set_user(USER)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc({
				"doctype": "Container Booking",
				"direction": "Tank In",
				"customer": OWNER,
				"principal": OTHER,
				"payment_type": "TOP",
				"items": [{"container_no": "CBRU0000011"}],
			}).insert()

	def test_an_emkl_books_for_any_registered_tank_owner(self):
		"""Case C: moving somebody else's tank IS the job, so every tank owner is offered —
		and the booking stays visible to the EMKL that raised it even though it neither owns
		the tanks nor is billed for them."""
		allowed = allowed_principals(EMKL_USER)
		self.assertIn(OWNER, allowed)
		self.assertIn(OTHER, allowed)
		frappe.set_user(EMKL_USER)
		doc = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": EMKL,
			"principal": OWNER,
			"payment_type": "TOP",
			"items": [{"container_no": "CBRU0000012"}],
		}).insert()
		frappe.set_user("Administrator")
		self.assertEqual(doc.requested_by_customer, EMKL)
		self.assertTrue(container_booking_permission(doc.as_dict(), "read", EMKL_USER))
		# ...and it is NOT the tank owner's own portal account's to edit.
		self.assertFalse(container_booking_permission(doc.as_dict(), "write", USER))

	def test_the_picker_and_the_excel_import_obey_the_same_list(self):
		"""The import is the one road into the grid with no picker in front of it."""
		frappe.set_user(USER)
		self.assertEqual(
			booking_container_query("Container", "", "name", 0, 20, {"principal": OTHER}), []
		)
		with self.assertRaises(frappe.PermissionError):
			parse_container_xlsx("/files/whatever.xlsx", direction="Tank In", principal=OTHER)

	def test_it_registers_a_tank_of_its_own_and_no_one_elses(self):
		"""A portal account holds `read` on Container and nothing more, so Frappe's own
		"Create a new Container" is not offered on the row's picker — this is the road round
		that wall, and it keeps the same principal list as everything else."""
		frappe.set_user(USER)
		tank = create_tank("cbru0000021", principal=OWNER)
		frappe.set_user("Administrator")
		row = frappe.db.get_value(
			"Container", tank["name"], ["principal", "status", "container_type"], as_dict=True
		)
		self.assertEqual(tank["name"], "CBRU0000021", "the number is normalised")
		self.assertEqual(row.principal, OWNER)
		self.assertEqual(row.status, "Gate_Out", "registered, not yet in the depot")
		self.assertEqual(row.container_type, "ISO Tank")

		frappe.set_user(USER)
		with self.assertRaises(frappe.PermissionError):
			create_tank("CBRU0000022", principal=OTHER)
		with self.assertRaises(frappe.ValidationError):
			create_tank("CBRU0000021", principal=OWNER)

	# --- the customer's own address book -----------------------------------

	def test_it_keys_in_its_own_party_and_the_record_says_whose_it_is(self):
		"""Not a DocPerm: a User Permission on Customer refuses every document of that
		doctype it does not name, and a record being created never is. The endpoint is the
		guard instead."""
		frappe.set_user(USER)
		party = create_party("CBR EMKL Satu", role="emkl")
		frappe.set_user("Administrator")
		row = frappe.db.get_value(
			"Customer", party["name"], ["created_by_customer", "is_transporter"], as_dict=True
		)
		self.assertEqual(row.created_by_customer, OWNER)
		self.assertTrue(row.is_transporter)

	def test_the_party_pickers_show_the_account_its_own_book_and_nothing_else(self):
		"""The fields these pickers sit on carry `ignore_user_permissions` — the flag that
		keeps a booking visible to both its payer and its tank owner, and that also switches
		OFF the only filter between a customer and OAK's whole customer book."""
		frappe.set_user(USER)
		create_party("CBR EMKL Dua", role="emkl")
		self.assertEqual(set(_own_and_created()), {OWNER, "CBR EMKL Dua"})
		names = {row[0] for row in customer_link_query("Customer", "CBR", "name", 0, 20, {})}
		self.assertIn("CBR EMKL Dua", names)
		self.assertNotIn(OTHER, names)
		# The role filter the surveyor pickers pass still applies on top.
		self.assertEqual(customer_link_query("Customer", "CBR", "name", 0, 20, {"is_surveyor": 1}), ())

	def test_only_a_portal_account_may_key_in_a_party(self):
		with self.assertRaises(frappe.PermissionError):
			create_party("CBR EMKL Tiga", role="emkl")

	def test_bill_to_may_be_a_party_the_customer_registered(self):
		frappe.set_user(USER)
		party = create_party("CBR EMKL Empat", role="emkl")
		frappe.set_user("Administrator")
		doc = self._raise_booking(customer=party["name"])
		self.assertEqual(doc.customer, party["name"], "the payer is often the EMKL")
		self.assertEqual(doc.principal, OWNER, "the tank owner is still pinned")

	def test_bill_to_outside_the_address_book_is_refused(self):
		frappe.set_user(USER)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc({
				"doctype": "Container Booking",
				"direction": "Tank In",
				"customer": OTHER,
				"principal": OWNER,
				"payment_type": "TOP",
				"items": [{"container_no": "CBRU0000009"}],
			}).insert()

	# --- where a rollback lands --------------------------------------------

	def test_rollback_returns_a_customer_booking_to_pengajuan_not_draft(self):
		"""Draft is the hidden state. A rollback that landed there would take the booking
		off the desk of the person who just pressed the button."""
		doc = self._raise_booking()
		frappe.set_user(USER)
		submit_request(doc.name)
		frappe.set_user("Administrator")
		doc.db_set("booking_status", "Pending Payment", update_modified=False)
		self.assertEqual(rollback_to_draft(doc.name)["booking_status"], "Pengajuan")

	# --- minta revisi ------------------------------------------------------

	def _confirmed_booking(self):
		doc = self._raise_booking()
		frappe.set_user(USER)
		submit_request(doc.name)
		frappe.set_user("Administrator")
		doc.reload()
		doc.submit()
		doc.reload()
		self.assertEqual(doc.booking_status, "Confirmed")
		return doc

	def test_minta_revisi_raises_a_flag_and_kembali_ke_draft_clears_it(self):
		doc = self._confirmed_booking()
		frappe.set_user(USER)
		request_revision(doc.name, reason="tanggal pickup salah")
		frappe.set_user("Administrator")
		doc.reload()
		self.assertTrue(doc.revision_requested)
		self.assertIn("tanggal pickup salah", doc.revision_note)
		self.assertEqual(doc.booking_status, "Confirmed", "the request changes no status")

		revert_booking_to_draft(doc.name)
		doc.reload()
		self.assertFalse(doc.revision_requested)
		self.assertFalse(doc.revision_note)

	def test_revision_is_only_for_a_confirmed_booking(self):
		doc = self._raise_booking()
		frappe.set_user(USER)
		with self.assertRaises(frappe.ValidationError):
			request_revision(doc.name, reason="belum dikonfirmasi")
