"""Tapping a notification must land somewhere real, and only where you are allowed.

Two failure modes to keep out of the depot:

  * A notification that goes nowhere. The route table is keyed by event, and an event whose
    resolver reads the wrong doctype resolves to None every single time while looking
    perfectly reasonable in the source. That bug shipped once during development
    (``order_muat_survey`` fires on an Order Muat and was pointed at a resolver that reads a
    Container Position Survey); ``test_no_resolver_reads_a_doctype_it_was_not_given`` is what
    caught it. Its sequel was quieter and lived longer: the replacement resolver read nothing
    at all, so this test passed while the event still pointed at ``/survey-position`` — the
    wrong menu, worked by a different team, for an event about an EIR-Out. A resolver reading
    no doctype is not the same as a resolver being right, which is why
    ``test_an_event_lands_on_the_menu_its_subject_names`` now pins the menu too.

  * A notification that becomes a side door. The PWA menu gate must be the same gate the
    tile filter and the router guard use, or a notification would let an operator into a
    menu their role does not carry.
"""

from __future__ import annotations

import pathlib
import re
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.ess import notification_routes as nr
from container_depot.ess.context import _MENU

FIELD_ROLE_USER = "nr-field@example.com"
OFFICE_USER = "nr-office@example.com"

# What `notify()` actually emits: every event key, paired with the doctype the Notification
# Log will carry for it. This is the specification the route table is held to — keep it in
# step with `container_depot/container_depot/notify.py`.
#
# `None` for the route means "Desk only, deliberately" (see `_none` in the route module).
EVENT_DOCTYPES = [
	("eir_submitted", "Inspection"),
	("eir_pending_review", "Inspection"),
	("cleaning_order_created", "Cleaning Order"),
	("cleaning_pending_review", "Cleaning Order"),
	("repair_order_created", "Repair Order"),
	# Historic key, current meaning: the M&R staging step it was named for is gone, and it
	# now fires when the repair team sends a finished job to Desk for review. Kept because
	# the key is what install.py's rules and _BY_EVENT are wired to, and the audience —
	# "an M&R needs Admin Ops" — never changed.
	("repair_order_service_setup", "Repair Order"),
	("repair_order_forwarded", "Repair Order"),
	("repair_order_pending_approval", "Repair Order"),
	("repair_order_decided", "Repair Order"),
	("repair_revision_requested", "Repair Order"),
	("eir_revision_requested", "Inspection"),
	("cleaning_revision_requested", "Cleaning Order"),
	("order_gate_in", "Order Bongkar"),
	("order_gate_out", "Order Muat"),
	("order_muat_survey", "Order Muat"),
	("eir_out_hold", "Order Muat"),
	("eir_out_hold", "Container"),
	("gate_out", "Gate Entry"),
	("booking_created", "Container Booking"),
	("booking_submitted", "Container Booking"),
	("contract_created", "Depot Contract"),
	("contract_activated", "Depot Contract"),
	("invoice_submitted", "Sales Invoice"),
]

DESK_ONLY_EVENTS = {
	"booking_created",
	"booking_submitted",
	"contract_created",
	"contract_activated",
	"invoice_submitted",
}


class TestNotificationRouteTable(FrappeTestCase):
	"""The mapping itself — no users, no permissions, no fixtures."""

	def test_every_event_notify_can_emit_is_registered(self):
		"""A new event shipped without a route silently loses its click-through."""
		src = pathlib.Path(
			frappe.get_app_path("container_depot", "container_depot", "notify.py")
		).read_text()
		emitted = sorted(set(re.findall(r'event_key="([a-z_]+)"', src)))
		self.assertTrue(emitted, "the event keys should be readable from notify.py")
		unregistered = [k for k in emitted if k not in nr._BY_EVENT]
		self.assertEqual(unregistered, [], "every notify() event needs a row in _BY_EVENT")

	def test_the_spec_table_here_matches_what_notify_emits(self):
		"""Keeps THIS file honest — a test table that drifts proves nothing."""
		src = pathlib.Path(
			frappe.get_app_path("container_depot", "container_depot", "notify.py")
		).read_text()
		emitted = set(re.findall(r'event_key="([a-z_]+)"', src))
		covered = {e for e, _dt in EVENT_DOCTYPES}
		self.assertEqual(emitted - covered, set(), "EVENT_DOCTYPES is missing an event notify() emits")

	def test_no_resolver_reads_a_doctype_it_was_not_given(self):
		"""The bug class this module is most prone to.

		A resolver that looks up a doctype other than the one the notification carries finds
		nothing, every time, and returns None — a dead notification that reads as correct
		code. Rather than assert on routes (which would need a fixture per doctype), watch
		what each resolver actually asks the database for.
		"""
		for event, doctype in EVENT_DOCTYPES:
			with self.subTest(event=event, doctype=doctype):
				asked = []

				def _spy(dt, name, fields):
					asked.append(dt)
					return None

				with patch.object(nr, "_state", _spy):
					nr.route_for(doctype, "SOME-NAME-0001", event)

				for dt in asked:
					self.assertEqual(
						dt,
						doctype,
						f"{event} carries a {doctype}, but its resolver went looking for a {dt} — "
						"it will resolve to None for every real notification",
					)

	# Events whose resolver returns a fixed path (no document read), and the menu that must
	# own it. A static resolver is exactly where a wrong-but-plausible route hides: nothing
	# fails, the operator just arrives somewhere else.
	STATIC_EVENT_MENUS = {
		"order_muat_survey": "eir",
		"eir_out_hold": "eir",
		"order_gate_in": "gate",
		"order_gate_out": "gate",
		"gate_out": "gate",
	}

	def test_an_event_lands_on_the_menu_its_subject_names(self):
		for event, doctype in EVENT_DOCTYPES:
			expected = self.STATIC_EVENT_MENUS.get(event)
			if not expected:
				continue
			with self.subTest(event=event):
				route = nr.route_for(doctype, "X-0001", event)
				self.assertIsNotNone(route, f"{event} resolves nowhere")
				self.assertEqual(nr.menu_for_route(route)[0], expected)

	def test_desk_only_events_offer_no_pwa_route(self):
		"""An invoice has no PWA screen. Sending the operator to Beranda instead would look
		exactly like a tap that failed."""
		for event, doctype in EVENT_DOCTYPES:
			if event not in DESK_ONLY_EVENTS:
				continue
			with self.subTest(event=event):
				self.assertIsNone(nr.route_for(doctype, "X-0001", event))

	def test_every_route_the_table_produces_belongs_to_a_menu(self):
		"""A route with no owning menu can never pass `can_open_menu`, so it would be a
		click-through that always refuses."""
		shapes = [
			"/eir?e=X&t=in",
			"/eir/history?open=X",
			"/cleaning?o=X",
			"/cleaning/history?open=X",
			"/mr?o=X",
			"/mr/history?open=X",
			"/survey-position",
			"/survey-position/history?open=X",
			"/position-fix",
			"/gate",
			"/gate/history?open=X",
			"/monitor",
		]
		for route in shapes:
			with self.subTest(route=route):
				self.assertIsNotNone(nr.menu_for_route(route), f"{route} maps to no menu")

	def test_no_rule_routes_a_field_role_to_a_menu_it_cannot_open(self):
		"""The recipient table and the menu gate are two files that must agree.

		They drifted, and the failure was invisible from either side: the bell rang for Team
		Cleaning and Team Repair on `eir_submitted` (Inspection is read-only for them, `/eir`
		needs write), and for Team Survey on `order_muat_survey` (no Inspection perm at all).
		Nothing errored — the operator tapped and got "Anda tidak punya akses ke menu ini".

		Checked against the SHIPPED matrix rather than the seeded DocPerms on purpose: this
		has to fail in review when someone adds a role to a rule, not months later on a site.

		Office roles are skipped. They hold no field role, so the PWA refuses them every menu
		by design — they read the same notification on the Desk bell, which is the point.
		"""
		from container_depot.install import FIELD_ROLE_MATRIX, FIELD_ROLES, NOTIFICATION_RULES

		letters = {"read": "r", "write": "w", "create": "c", "submit": "s"}
		perms = {dt: dict(zip(FIELD_ROLES, cols)) for dt, cols in FIELD_ROLE_MATRIX}
		menu_ptype = {key: (dt, ptype) for key, _route, dt, ptype in _MENU}
		doctype_of = dict(EVENT_DOCTYPES)

		for event_key, _label, _desc, roles in NOTIFICATION_RULES:
			menu = self._menu_of(event_key, doctype_of.get(event_key))
			if not menu:
				continue  # Desk-only event; every recipient reads it on the Desk bell
			menu_dt, ptype = menu_ptype[menu]
			for role in roles:
				if role not in FIELD_ROLES:
					continue
				with self.subTest(event=event_key, role=role):
					self.assertIn(
						letters[ptype],
						perms.get(menu_dt, {}).get(role, ""),
						f"{event_key} routes to the '{menu}' menu, which needs {ptype} on "
						f"{menu_dt} — {role} does not have it, so the bell leads nowhere",
					)

	def _menu_of(self, event_key, doctype):
		"""The PWA menu an event's route belongs to, or None for a Desk-only event.

		Derived by asking the real route table with a stand-in document, so there is no second
		copy of the mapping to drift. The stand-in is a fresh/open document: the finished
		variants of every resolver land in the same menu (`/eir/history` is still `eir`), so
		the menu answer does not depend on which one is used.
		"""
		if not doctype:
			return None
		open_doc = frappe._dict(
			{"docstatus": 0, "status": "Draft", "inspection_type": "EIR-In"}
		)
		with patch.object(nr, "_state", lambda dt, name, fields: open_doc):
			route = nr.route_for(doctype, "X-0001", event_key)
		return nr.menu_for_route(route)[0] if route else None

	def test_longest_prefix_wins(self):
		"""`/survey-position/history` is surveyPos, not a near-miss on some shorter route."""
		self.assertEqual(nr.menu_for_route("/survey-position/history?open=X")[0], "surveyPos")
		self.assertEqual(nr.menu_for_route("/position-fix")[0], "posFix")
		self.assertEqual(nr.menu_for_route("/gate/history")[0], "gate")

	def test_a_route_outside_the_pwa_owns_no_menu(self):
		self.assertIsNone(nr.menu_for_route("/app/sales-invoice/SI-0001"))
		self.assertIsNone(nr.menu_for_route(""))
		self.assertIsNone(nr.menu_for_route(None))

	def test_menu_routes_all_appear_in_the_table(self):
		"""Adding a PWA menu without teaching this module about it is a silent gap."""
		for _key, route, _dt, _ptype in _MENU:
			with self.subTest(route=route):
				self.assertIsNotNone(nr.menu_for_route(route))


class TestNotificationRoutePermission(FrappeTestCase):
	"""The gates. A notification is never a way past them."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		for email, roles in ((FIELD_ROLE_USER, ["Team Cleaning"]), (OFFICE_USER, ["Cashier"])):
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, ignore_permissions=True, force=True)
			frappe.get_doc({
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"user_type": "System User",
			}).insert(ignore_permissions=True).add_roles(*roles)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for email in (FIELD_ROLE_USER, OFFICE_USER):
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, ignore_permissions=True, force=True)
		frappe.db.commit()
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def test_a_menu_the_user_does_not_hold_is_refused(self):
		"""Team Cleaning works the cleaning queue and nothing else — a notification about an
		M&R order must not open one."""
		self.assertTrue(nr.can_open_menu("/cleaning?o=X", FIELD_ROLE_USER))
		self.assertFalse(nr.can_open_menu("/mr?o=X", FIELD_ROLE_USER))

	def test_an_office_role_gets_no_pwa_route_at_all(self):
		"""Cashier holds no field role, so the PWA is empty for them — including this door."""
		for route in ("/cleaning?o=X", "/monitor", "/gate"):
			with self.subTest(route=route):
				self.assertFalse(nr.can_open_menu(route, OFFICE_USER))

	def test_the_menu_gate_is_the_same_one_the_tiles_use(self):
		"""Not a second copy of the rule: `allowed_menu` and this must always agree, or a
		notification becomes a side door into a menu the operator cannot otherwise see."""
		from container_depot.ess.context import allowed_menu

		frappe.set_user(FIELD_ROLE_USER)
		try:
			tiles = set(allowed_menu())
			for key, route, _dt, _ptype in _MENU:
				self.assertEqual(
					nr.can_open_menu(route),
					key in tiles,
					f"menu {key}: click-through and tile filter disagree",
				)
		finally:
			frappe.set_user("Administrator")

	def test_a_missing_document_refuses_on_both_surfaces_with_a_reason(self):
		out = nr.resolve("Cleaning Order", "CO-DOES-NOT-EXIST-0001", "cleaning_order_created")
		self.assertFalse(out["allowed"])
		self.assertFalse(out["desk_allowed"])
		self.assertEqual(out["reason"], "missing")
		self.assertTrue(out["message"], "a refusal without a reason is a dead tap")

	def test_a_notification_with_no_document_refuses_cleanly(self):
		"""Frappe raises plain Alert/Share rows carrying neither doctype nor name."""
		out = nr.resolve(None, None, None)
		self.assertFalse(out["allowed"])
		self.assertFalse(out["desk_allowed"])
		self.assertTrue(out["message"])

	def test_desk_and_pwa_verdicts_are_independent(self):
		"""The reason the two are computed separately.

		A Container Booking has no PWA screen, but an Admin Ops user has every right to open
		it on the Desk. Running the Desk answer through the PWA menu gate would block a link
		that has always worked.
		"""
		booking = frappe.get_all("Container Booking", pluck="name", limit=1)
		if not booking:
			self.skipTest("no Container Booking on this site")
		out = nr.resolve("Container Booking", booking[0], "booking_submitted")
		self.assertFalse(out["allowed"], "the PWA has no screen for a booking")
		self.assertEqual(out["reason"], "no_screen")
		self.assertTrue(out["desk_allowed"], "Administrator may open it on the Desk")
		self.assertTrue(out["desk_route"].startswith("/app/container-booking/"))

	def test_a_document_the_user_cannot_read_offers_no_desk_route(self):
		"""A refusal must not leak the URL either — no "you may not open this, here is where
		it lives"."""
		booking = frappe.get_all("Container Booking", pluck="name", limit=1)
		if not booking:
			self.skipTest("no Container Booking on this site")
		with patch.object(nr, "can_read_doc", return_value=False):
			out = nr.resolve("Container Booking", booking[0], "booking_submitted")
		self.assertFalse(out["desk_allowed"])
		self.assertIsNone(out["desk_route"])
		self.assertTrue(out["desk_message"])

	def test_a_broken_permission_check_fails_closed(self):
		"""An exception while checking permission is not a licence to navigate."""
		with patch("frappe.has_permission", side_effect=RuntimeError("boom")):
			self.assertFalse(nr.can_read_doc("Cleaning Order", "CO-0001"))


class TestNotificationEndpoint(FrappeTestCase):
	"""The endpoint both bells call."""

	def test_open_target_refuses_someone_elses_notification(self):
		from container_depot.ess.notifications import open_target

		log = frappe.get_doc({
			"doctype": "Notification Log",
			"for_user": "Administrator",
			"type": "Alert",
			"subject": "route test",
			"document_type": "Container Booking",
			"document_name": "BKG-TEST-0001",
			"depot_event": "booking_submitted",
		}).insert(ignore_permissions=True)
		try:
			if frappe.db.exists("User", FIELD_ROLE_USER):
				frappe.set_user(FIELD_ROLE_USER)
				with self.assertRaises(frappe.PermissionError):
					open_target(name=log.name)
		finally:
			frappe.set_user("Administrator")
			frappe.delete_doc("Notification Log", log.name, ignore_permissions=True, force=True)
			frappe.db.commit()

	def test_open_target_marks_the_notification_read(self):
		"""Tapping is reading. Doing it in the same call means a bad link cannot leave a
		notification that navigated but stayed bold."""
		from container_depot.ess.notifications import open_target

		log = frappe.get_doc({
			"doctype": "Notification Log",
			"for_user": "Administrator",
			"type": "Alert",
			"subject": "route test",
			"document_type": "Container Booking",
			"document_name": "BKG-TEST-0002",
			"depot_event": "booking_submitted",
			"read": 0,
		}).insert(ignore_permissions=True)
		try:
			out = open_target(name=log.name)
			self.assertEqual(frappe.db.get_value("Notification Log", log.name, "read"), 1)
			self.assertIn("allowed", out)
			self.assertEqual(out["name"], log.name)
		finally:
			frappe.delete_doc("Notification Log", log.name, ignore_permissions=True, force=True)
			frappe.db.commit()

	def test_the_list_tags_each_row_with_whether_it_leads_anywhere(self):
		from container_depot.ess.notifications import list_notifications

		data = list_notifications(limit=5)
		for item in data["items"]:
			self.assertIn("openable", item, "the bell styles rows on this flag")
			self.assertIsInstance(item["openable"], bool)
