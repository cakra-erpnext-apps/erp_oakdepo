"""Container Position Survey (Lift On) — provision from an outbound Container Booking,
Surveyor records a free-text location note (+ photos), Operator Kalmar approves
("udah turun") → Confirmed. No yard zones / Container Movement — the location is a note.

Self-cleaning: every fixture created here is hard-deleted in tearDown so the shared
erp.localhost instance is left as it was.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.operations import position_survey as ps
from container_depot.tests.test_eir import _make_container

DEPOT = "OAK1"


class TestContainerPositionSurvey(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._containers = []
		self._bookings = []

	def tearDown(self):
		frappe.db.delete("Container Position Survey", {"container": ["in", self._containers or [""]]})
		for b in self._bookings:
			frappe.db.delete("Container Booking Item", {"parent": b})
			frappe.db.delete("Container Booking", {"name": b})
		for c in self._containers:
			frappe.db.delete("Container", {"name": c})
		frappe.db.commit()
		super().tearDown()

	# --- helpers -------------------------------------------------------------
	def _container(self, cno):
		c = _make_container(cno, depot=DEPOT)
		self._containers.append(c)
		return c

	def _tank_out_booking(self, container):
		"""Minimal outbound (Tank Out) Container Booking carrying ``container`` — validation
		+ mandatory bypassed (mirrors test_eir._make_order_muat)."""
		doc = frappe.get_doc({
			"doctype": "Container Booking", "direction": "Tank Out", "depot": DEPOT,
			"items": [{"container": container}],
		})
		doc.flags.ignore_validate = True
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		self._bookings.append(doc.name)
		return doc.name

	def _new_survey(self, container):
		doc = frappe.get_doc({
			"doctype": "Container Position Survey", "container": container,
			"depot": DEPOT, "status": ps.PENDING,
		}).insert(ignore_permissions=True)
		return doc.name

	# --- tests ---------------------------------------------------------------
	def test_provision_one_per_container_idempotent(self):
		c = self._container("CPSPROV0001")
		bk = self._tank_out_booking(c)

		created = ps.provision_position_survey_for_booking(bk)
		self.assertEqual(len(created), 1)
		survey = frappe.get_doc("Container Position Survey", created[0])
		self.assertEqual(survey.container, c)
		self.assertEqual(survey.status, ps.PENDING)
		self.assertEqual(survey.booking, bk)

		# Idempotent: a second run does not open a duplicate.
		self.assertEqual(ps.provision_position_survey_for_booking(bk), [])

	def test_record_position_saves_note_and_photos(self):
		c = self._container("CPSREC00001")
		name = self._new_survey(c)

		res = ps.record_survey_position(
			name, "blok kanan dekat pos, tumpukan 2",
			photos=["/files/pos1.jpg", "/files/pos2.jpg"], notes="ketemu di test",
		)
		self.assertTrue(res["success"])

		doc = frappe.get_doc("Container Position Survey", name)
		self.assertEqual(doc.status, ps.SURVEYED)
		self.assertEqual(doc.location_note, "blok kanan dekat pos, tumpukan 2")
		self.assertEqual(doc.survey_notes, "ketemu di test")
		self.assertEqual(len(doc.position_photos), 2)
		self.assertEqual(doc.surveyed_by, "Administrator")
		# The survey never touches the container status / yard mapping.
		self.assertEqual(frappe.db.count("Container Movement", {"container": c, "event_type": "Yard"}), 0)

	def test_record_requires_location_note(self):
		c = self._container("CPSNOTE0001")
		name = self._new_survey(c)
		with self.assertRaises(frappe.ValidationError):
			ps.record_survey_position(name, "")

	def test_approve_confirms_and_submits(self):
		c = self._container("CPSAPP00001")
		name = self._new_survey(c)
		ps.record_survey_position(name, "ground slot A1")

		out = ps.approve_position(name, note="ok udah turun")
		self.assertTrue(out["success"])
		doc = frappe.get_doc("Container Position Survey", name)
		self.assertEqual(doc.status, ps.CONFIRMED)
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(doc.approved_by, "Administrator")

	def test_record_rejects_non_pending(self):
		c = self._container("CPSGUARD001")
		name = self._new_survey(c)
		ps.record_survey_position(name, "posisi 1")  # -> Surveyed
		# Recording again (no longer Pending) must be rejected.
		with self.assertRaises(frappe.ValidationError):
			ps.record_survey_position(name, "posisi 2")

	def test_worklists_split_by_status(self):
		c1 = self._container("CPSWL000001")
		c2 = self._container("CPSWL000002")
		n1 = self._new_survey(c1)  # stays Pending
		n2 = self._new_survey(c2)
		ps.record_survey_position(n2, "posisi 2")  # -> Surveyed

		pending_names = {i["name"] for i in ps.list_pending_surveys(page_length=100)["items"]}
		surveyed_names = {i["name"] for i in ps.list_surveyed(page_length=100)["items"]}
		self.assertIn(n1, pending_names)
		self.assertNotIn(n1, surveyed_names)
		self.assertIn(n2, surveyed_names)
		self.assertNotIn(n2, pending_names)
