"""Notification routing lives in data, and these tests hold it to that promise.

The whole reason ``Depot Notification Rule`` is a doctype rather than a dict is that
recipients get re-tuned constantly in the first months live. So the load-bearing test
here is ``test_changing_rule_roles_changes_recipients``: edit a rule, recipients change,
no deploy. Everything else guards the ways that could go quietly wrong — a disabled rule
that still sends, a missing rule that broadcasts to everyone, a cache that serves the old
routing after an edit.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.install import NOTIFICATION_RULES, setup_notification_rules
from container_depot.container_depot import notify as notify_mod
from container_depot.container_depot.notify import notify

FIELD_USER = "notif-field@example.com"      # Team Cleaning
FINANCE_USER = "notif-finance@example.com"  # Finance
ACTOR = "notif-actor@example.com"           # submits things; never notified about them
PROBE_EVENT = "zz_probe_event"
DOC = "NOTIF-TEST-DOC"


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


def _logs_for(user: str) -> int:
	return frappe.db.count("Notification Log", {"for_user": user, "document_name": DOC})


class TestNotificationRouting(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		_user(FIELD_USER, "Team Cleaning")
		_user(FINANCE_USER, "Finance")
		_user(ACTOR, "Admin Ops")
		setup_notification_rules()
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for email in (FIELD_USER, FINANCE_USER, ACTOR):
			frappe.db.delete("Notification Log", {"for_user": email})
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, ignore_permissions=True, force=True)
		frappe.db.delete("Notification Log", {"document_name": DOC})
		if frappe.db.exists("Depot Notification Rule", PROBE_EVENT):
			frappe.delete_doc("Depot Notification Rule", PROBE_EVENT, ignore_permissions=True, force=True)
		# Two tests rewrite the `invoice_submitted` roles and commit, so restore them here
		# rather than at the tail of a test body: a run interrupted mid-test (or a second
		# run racing this one) otherwise leaves the site routing invoices to Team Cleaning
		# for good, and every later run of this class fails on data, not on code.
		cls._restore_rule("invoice_submitted", ["Cashier", "Finance"])
		# Leave the master switch and the seeded rules as we found them.
		settings = frappe.get_single("Depot Notification Settings")
		settings.notifications_enabled = 1
		settings.save(ignore_permissions=True)
		notify_mod.clear_rule_cache()
		frappe.db.commit()
		super().tearDownClass()

	@classmethod
	def _restore_rule(cls, event_key: str, roles: list) -> None:
		if not frappe.db.exists("Depot Notification Rule", event_key):
			return
		doc = frappe.get_doc("Depot Notification Rule", event_key)
		doc.roles = []
		for role in roles:
			doc.append("roles", {"role": role})
		doc.enabled = 1
		doc.save(ignore_permissions=True)

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.delete("Notification Log", {"document_name": DOC})
		notify_mod.clear_rule_cache()
		super().setUp()

	def _fire(self, event_key: str) -> int:
		return notify(doctype="Container", name=DOC, subject="probe", event_key=event_key)

	def _set_rule_roles(self, event_key: str, roles: list, enabled: int = 1) -> None:
		doc = frappe.get_doc("Depot Notification Rule", event_key)
		doc.roles = []
		for role in roles:
			doc.append("roles", {"role": role})
		doc.enabled = enabled
		doc.save(ignore_permissions=True)
		frappe.db.commit()

	# --- routing ----------------------------------------------------------------

	def test_invoice_notification_skips_field_roles(self):
		self._fire("invoice_submitted")
		self.assertEqual(_logs_for(FINANCE_USER), 1)
		self.assertEqual(_logs_for(FIELD_USER), 0)

	def test_cleaning_notification_skips_finance(self):
		# `cleaning_order_forwarded`, not `..._created`: the crew is rung on the handoff out
		# of Service Setup, never when the order is filed. See install.NOTIFICATION_RULES.
		self._fire("cleaning_order_forwarded")
		self.assertEqual(_logs_for(FIELD_USER), 1)
		self.assertEqual(_logs_for(FINANCE_USER), 0)

	def test_revision_requests_are_routed_not_broadcast(self):
		"""EIR and cleaning "Ajukan Revisi" used to call notify() with no event_key at all.

		That path skips the role filter entirely (see `_recipients`), so a request only Admin
		Ops can act on reached every enabled user in the branch — Finance included. The M&R
		twin was fixed at the time and these two were missed; this pins all three.
		"""
		for event_key in (
			"eir_revision_requested",
			"cleaning_revision_requested",
			"repair_revision_requested",
		):
			with self.subTest(event=event_key):
				frappe.db.delete("Notification Log", {"document_name": DOC})
				self._fire(event_key)
				self.assertEqual(_logs_for(FINANCE_USER), 0)
				self.assertEqual(_logs_for(FIELD_USER), 0)

	def test_actor_is_never_notified_about_their_own_action(self):
		frappe.set_user(ACTOR)
		try:
			self._fire("cleaning_order_forwarded")  # Admin Ops is on this rule
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(_logs_for(ACTOR), 0)
		self.assertEqual(_logs_for(FIELD_USER), 1)

	def test_changing_rule_roles_changes_recipients(self):
		# The point of the whole doctype: routing changes with no deploy.
		self._fire("invoice_submitted")
		self.assertEqual(_logs_for(FIELD_USER), 0)

		self._set_rule_roles("invoice_submitted", ["Team Cleaning"])
		frappe.db.delete("Notification Log", {"document_name": DOC})
		self._fire("invoice_submitted")
		self.assertEqual(_logs_for(FIELD_USER), 1)
		self.assertEqual(_logs_for(FINANCE_USER), 0)

		self._set_rule_roles("invoice_submitted", ["Cashier", "Finance"])

	def test_rule_cache_invalidated_on_update(self):
		# Warm the cache with the seeded routing, then edit the rule WITHOUT clearing the
		# cache by hand. on_update must do it, or the site keeps the stale routing.
		self._fire("invoice_submitted")
		self.assertEqual(_logs_for(FIELD_USER), 0)

		doc = frappe.get_doc("Depot Notification Rule", "invoice_submitted")
		doc.append("roles", {"role": "Team Cleaning"})
		doc.save(ignore_permissions=True)
		frappe.db.commit()

		frappe.db.delete("Notification Log", {"document_name": DOC})
		self._fire("invoice_submitted")
		self.assertEqual(_logs_for(FIELD_USER), 1)

		self._set_rule_roles("invoice_submitted", ["Cashier", "Finance"])

	# --- fail-safe behaviour -----------------------------------------------------

	def test_unknown_event_key_falls_back_not_broadcast(self):
		# A missing rule routes to fallback_roles (Admin Ops, SPV Lapangan) — NEVER to
		# every user. A silent broadcast is the exact bug this release removes.
		sent = self._fire("event_that_does_not_exist")
		self.assertEqual(_logs_for(FIELD_USER), 0)
		self.assertEqual(_logs_for(FINANCE_USER), 0)
		enabled_users = frappe.db.count("User", {"enabled": 1})
		self.assertLess(sent, enabled_users)

	def test_disabled_rule_sends_nothing(self):
		self._set_rule_roles("cleaning_order_forwarded", ["Team Cleaning"], enabled=0)
		try:
			self.assertEqual(self._fire("cleaning_order_forwarded"), 0)
			self.assertEqual(_logs_for(FIELD_USER), 0)
		finally:
			self._set_rule_roles(
				"cleaning_order_forwarded", ["Team Cleaning", "SPV Lapangan", "Admin Ops"]
			)

	def test_master_switch_off_sends_nothing(self):
		settings = frappe.get_single("Depot Notification Settings")
		settings.notifications_enabled = 0
		settings.save(ignore_permissions=True)
		frappe.db.commit()
		try:
			self.assertEqual(self._fire("cleaning_order_created"), 0)
			self.assertEqual(frappe.db.count("Notification Log", {"document_name": DOC}), 0)
		finally:
			settings.notifications_enabled = 1
			settings.save(ignore_permissions=True)
			frappe.db.commit()

	def test_rule_with_empty_roles_is_rejected_on_validate(self):
		doc = frappe.get_doc("Depot Notification Rule", "cleaning_order_created")
		doc.roles = []
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)
		doc.reload()

	# --- seeding -----------------------------------------------------------------

	def test_seeder_covers_every_event_and_is_idempotent(self):
		keys = {row[0] for row in NOTIFICATION_RULES}
		seeded = set(
			frappe.get_all("Depot Notification Rule", pluck="event_key", limit_page_length=0)
		)
		self.assertTrue(keys <= seeded)

		before = frappe.db.count("Depot Notification Rule")
		setup_notification_rules()
		self.assertEqual(frappe.db.count("Depot Notification Rule"), before)

	def test_field_teams_are_only_told_on_handoff(self):
		"""The crews hear "this job is yours", never "a document exists".

		Creation-time bells (a Cleaning Order still in Service Setup, an unapproved M&R draft,
		an Order Muat submit) all describe work Admin Ops has not released yet. Routing them to
		the crew trains it to chase orders it may not start, and to tune out the one bell that
		matters. So each team is allowed on its handoff event and nothing else.

		Team EIR's handoff is `eir_created` and that is not a loophole: no Admin Ops step stands
		in front of an EIR, so the draft landing in `/eir` IS the job arriving. They stay off
		`order_muat_survey` (fires on the bon) and `eir_submitted` (fires when an inspection is
		already finished). Pinned here because the regression is a one-word edit to a rule row.
		"""
		allowed = {
			"Team Cleaning": {"cleaning_order_forwarded"},
			"Team Repair": {"repair_order_forwarded"},
			"Team EIR": {"eir_created"},
			# Survey posisi splits one doctype across two menus, so it has two handoffs — the
			# survey arriving for Team Survey, the recorded position arriving for Team Kalmar.
			# Neither is on `position_confirmed`: by then both are done.
			"Team Survey": {"position_survey_pending"},
			"Team Kalmar": {"position_surveyed", "order_gate_out", "gate_out"},
		}
		for event_key, _label, _desc, roles in NOTIFICATION_RULES:
			for role in roles:
				if role not in allowed:
					continue
				with self.subTest(event=event_key, role=role):
					self.assertIn(
						event_key,
						allowed[role],
						f"{role} is on '{event_key}', which is not a handoff to them",
					)

	def test_seeder_never_overwrites_admin_tuning(self):
		self._set_rule_roles("gate_out", ["Team Cleaning"])
		setup_notification_rules()
		doc = frappe.get_doc("Depot Notification Rule", "gate_out")
		self.assertEqual([r.role for r in doc.roles], ["Team Cleaning"])
		self._set_rule_roles("gate_out", ["Security", "Team Kalmar", "Admin Ops", "Cashier"])


class TestNoDuplicateBellRows(FrappeTestCase):
	def test_seeded_duplicate_notifications_are_gone(self):
		# The five built-in Notification rules that used to double up on our own events.
		# One submit, one bell row per recipient — not two, and not three for Order Muat.
		leftovers = frappe.get_all(
			"Notification",
			filters={
				"document_type": [
					"in",
					["Order Bongkar", "Order Muat", "Container Booking", "Inspection", "Depot Contract"],
				],
				"is_standard": 0,
			},
			fields=["name", "subject"],
		)
		seeded_subjects = {
			"Bon Bongkar {{ doc.name }} diterbitkan",
			"Bon Muat {{ doc.name }} diterbitkan",
			"Kontrak Depo {{ doc.name }} dibuat",
			"Booking {{ doc.name }} dikonfirmasi",
			"EIR {{ doc.name }} disubmit",
		}
		self.assertEqual([n for n in leftovers if n.subject in seeded_subjects], [])


class TestPwaNotificationEndpoints(FrappeTestCase):
	def test_list_and_mark_read(self):
		from container_depot.ess import notifications

		log = frappe.get_doc(
			{
				"doctype": "Notification Log",
				"subject": "Test EIR notif",
				"for_user": frappe.session.user,
				"type": "Alert",
				"read": 0,
			}
		).insert(ignore_permissions=True)

		res = notifications.list_notifications(limit=20)
		self.assertIn(log.name, [i["name"] for i in res["items"]])
		self.assertGreaterEqual(res["unread"], 1)

		notifications.mark_read(log.name)
		self.assertEqual(frappe.db.get_value("Notification Log", log.name, "read"), 1)

	def test_list_is_always_bounded(self):
		"""However many notifications exist, and whatever the caller asks for, the bell
		gets a bounded page and a bounded badge.

		Notification Log is never pruned — it is not registered with Log Settings and has
		no ``clear_old_logs`` — so "it is small today" is not a reason to leave a read
		unbounded. A caller can also pass any ``limit`` it likes; the clamp is the server's
		job, not the PWA's.
		"""
		from container_depot.ess import notifications

		user = frappe.session.user
		made = [
			frappe.get_doc({
				"doctype": "Notification Log",
				"subject": f"Bulk notif {i}",
				"for_user": user,
				"type": "Alert",
				"read": 0,
			}).insert(ignore_permissions=True).name
			for i in range(notifications._MAX_LIMIT + 15)
		]
		try:
			self.assertLessEqual(
				len(notifications.list_notifications(limit=9999)["items"]),
				notifications._MAX_LIMIT,
				"an absurd limit must be clamped, not honoured",
			)
			self.assertLessEqual(len(notifications.list_notifications()["items"]), notifications._DEFAULT_LIMIT)
			# The badge never reports more than the cap, so it never needs a full scan.
			self.assertLessEqual(
				notifications.list_notifications()["unread"], notifications._UNREAD_CAP + 1
			)
		finally:
			for name in made:
				frappe.delete_doc("Notification Log", name, ignore_permissions=True, force=True)

	def test_mark_all_read(self):
		from container_depot.ess import notifications

		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"subject": "Another notif",
				"for_user": frappe.session.user,
				"type": "Alert",
				"read": 0,
			}
		).insert(ignore_permissions=True)

		notifications.mark_all_read()
		self.assertEqual(
			frappe.db.count("Notification Log", {"for_user": frappe.session.user, "read": 0}), 0
		)


class TestEirCreatedReachesTeamEir(FrappeTestCase):
	"""Team EIR's only bell, tested on the DOCUMENT rather than on the rule table.

	``test_field_teams_are_only_told_on_handoff`` above pins who ``eir_created`` is routed
	to; a rule row cannot prove the event ever fires. The hook lives on
	``Inspection.after_insert`` precisely so that every path an EIR is born through rings it
	— the two bon provisioners, the Desk form, the legacy REST create — so what is worth
	pinning is that an ordinary insert is enough, and that a finished EIR is not.
	"""

	EIR_USER = "notif-eir@example.com"  # Team EIR
	CNO = "NEIR1000001"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		_user(cls.EIR_USER, "Team EIR")
		setup_notification_rules()
		from container_depot.tests.test_api import ensure_test_customer

		cls.container = frappe.get_doc({
			"doctype": "Container",
			"container_no": cls.CNO,
			"container_type": "ISO Tank",
			"status": "In_Depot",
			"principal": ensure_test_customer("EIR Notif Principal"),
		}).insert(ignore_permissions=True).name
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.db.delete("Notification Log", {"for_user": cls.EIR_USER})
		frappe.db.delete("Inspection", {"container": cls.container})
		frappe.db.delete("Container", {"name": cls.container})
		if frappe.db.exists("User", cls.EIR_USER):
			frappe.delete_doc("User", cls.EIR_USER, ignore_permissions=True, force=True)
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.delete("Notification Log", {"for_user": self.EIR_USER})
		frappe.db.delete("Inspection", {"container": self.container})

	def _subjects(self):
		return frappe.get_all(
			"Notification Log",
			filters={"for_user": self.EIR_USER, "depot_event": "eir_created"},
			pluck="subject",
		)

	def _draft(self, inspection_type):
		return frappe.get_doc({
			"doctype": "Inspection",
			"inspection_type": inspection_type,
			"container": self.container,
		}).insert(ignore_permissions=True)

	def test_an_eir_in_draft_rings_team_eir_and_says_the_tank_is_arriving(self):
		self._draft("EIR-In")
		subjects = self._subjects()
		self.assertEqual(len(subjects), 1, "one draft, one bell")
		self.assertIn("EIR-In", subjects[0])
		self.assertIn(self.CNO, subjects[0])
		# Direction is the point of the message — which checklist, and which way the tank goes.
		self.assertIn("tank masuk", subjects[0])

	def test_an_eir_out_draft_says_the_tank_is_leaving(self):
		self._draft("EIR-Out")
		subjects = self._subjects()
		self.assertEqual(len(subjects), 1)
		self.assertIn("EIR-Out", subjects[0])
		self.assertIn("tank akan keluar", subjects[0])

	def test_the_bell_opens_the_draft_it_is_about(self):
		"""A notification the crew cannot act on is the failure mode this replaces."""
		from container_depot.ess.notification_routes import route_for

		doc = self._draft("EIR-In")
		self.assertEqual(route_for("Inspection", doc.name, "eir_created"), f"/eir?e={doc.name}&t=in")

	def test_an_eir_created_already_finished_rings_nobody(self):
		"""``create_eir(submit=True)`` records an inspection that already happened. There is
		no draft to pick up, so "siap diperiksa" would point Team EIR at a submitted doc."""
		from container_depot.container_depot import eir

		eir.create_eir(inspection_type="EIR-In", container=self.container, submit=True)
		self.assertEqual(self._subjects(), [])
