"""Container Position Survey (Lift On) — provision from an outbound Container Booking,
Surveyor records a free-text location note (+ photos), Operator Kalmar approves
("udah turun") → Confirmed. No yard zones / Container Movement — the location is a note.

Self-cleaning: every fixture created here is hard-deleted in tearDown so the shared
erp.localhost instance is left as it was.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.container_depot import position_survey as ps
from container_depot.container_depot.exceptions import ClaimedByAnother
from container_depot.tests.test_eir import _make_container
from container_depot.tests.test_work_claim import _user

DEPOT = "OAK1"


class TestContainerPositionSurvey(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._containers = []
		self._bookings = []

	def tearDown(self):
		# The bell rows too: every provision / record / approve here writes a Notification Log
		# for whoever holds the routed roles, and those outlive the survey they point at.
		surveys = frappe.get_all(
			"Container Position Survey",
			filters={"container": ["in", self._containers or [""]]},
			pluck="name",
		)
		if surveys:
			frappe.db.delete("Notification Log", {
				"document_type": "Container Position Survey", "document_name": ["in", surveys],
			})
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
	def test_saving_an_outbound_draft_already_tasks_the_surveyor(self):
		"""Provisioning happens on the DRAFT, not at submit.

		Finding a tank in a full yard is preparation, and preparation that starts at Submit
		starts too late — the booking is written days ahead precisely so the yard can get
		ready. So merely saving the outbound booking opens the survey.
		"""
		c = self._container("CPSPROV0001")
		bk = self._tank_out_booking(c)

		created = frappe.get_all("Container Position Survey", filters={"booking": bk}, pluck="name")
		self.assertEqual(len(created), 1)
		survey = frappe.get_doc("Container Position Survey", created[0])
		self.assertEqual(survey.container, c)
		self.assertEqual(survey.status, ps.PENDING)
		self.assertEqual(survey.booking, bk)

		# Idempotent: saving again (or calling the provisioner directly) opens no duplicate.
		self.assertEqual(ps.provision_position_survey_for_booking(bk), [])

	def test_a_resubmitted_booking_does_not_provision_a_second_survey(self):
		# A booking can be returned to draft (revert_booking_to_draft) and submitted again;
		# it is only refused once a bon exists or a code is Used, both of which come AFTER
		# the survey. A finished survey is submitted, so the open-survey check cannot see it
		# and a duplicate used to be opened for the same booking.
		c = self._container("CPSPROV0002")
		bk = self._tank_out_booking(c)
		created = frappe.get_all("Container Position Survey", filters={"booking": bk}, pluck="name")[0]
		frappe.db.set_value("Container Position Survey", created, {"docstatus": 1, "status": ps.CONFIRMED})

		self.assertEqual(ps.provision_position_survey_for_booking(bk), [])
		self.assertEqual(frappe.db.count("Container Position Survey", {"container": c}), 1)

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

	def test_worklist_leads_with_the_customers_pickup_date(self):
		"""Tier 1 of the shared worklist order, on real rows: a tank the customer has a date
		for outranks one that has been waiting longer. The rule itself lives in
		``worklist.sort_by_priority`` (see test_worklist_order)."""
		from frappe.utils import add_days, today

		older = self._container("CPSSORT0001")
		booked = self._container("CPSSORT0002")
		self._new_survey(older)          # created first, no pickup date
		name = self._new_survey(booked)
		frappe.db.set_value("Container Position Survey", name, "target_lift_on", add_days(today(), 1))

		nos = [i["container_no"] for i in ps.list_pending_surveys(page_length=100)["items"]]
		self.assertLess(nos.index("CPSSORT0002"), nos.index("CPSSORT0001"))

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

	# --- autosave draft ------------------------------------------------------
	def test_draft_saves_without_advancing_status(self):
		"""The PWA autosaves while the surveyor types; that must not look like a finished
		survey to the Kalmar worklist."""
		c = self._container("CPSDRAFT001")
		name = self._new_survey(c)

		ps.save_survey_draft(name, "blok kiri, tumpukan 1", photos=["/files/d1.jpg"], notes="wip")

		doc = frappe.get_doc("Container Position Survey", name)
		self.assertEqual(doc.location_note, "blok kiri, tumpukan 1")
		self.assertEqual(doc.survey_notes, "wip")
		self.assertEqual(len(doc.position_photos), 1)
		# Untouched: status, and the stamps that say a human finished the job.
		self.assertEqual(doc.status, ps.PENDING)
		self.assertFalse(doc.surveyed_by)
		self.assertFalse(doc.surveyed_on)
		# Still on the surveyor's worklist, not the approver's.
		self.assertIn(name, {i["name"] for i in ps.list_pending_surveys(page_length=100)["items"]})
		self.assertNotIn(name, {i["name"] for i in ps.list_surveyed(page_length=100)["items"]})

	def test_draft_accepts_an_empty_note(self):
		"""An autosave fires mid-typing. Refusing a half-filled form there would mean the
		first thing the surveyor writes is the first thing that fails to save."""
		c = self._container("CPSDRAFT002")
		name = self._new_survey(c)
		ps.save_survey_draft(name, "", photos=["/files/d2.jpg"])
		doc = frappe.get_doc("Container Position Survey", name)
		self.assertEqual(doc.location_note, "")
		self.assertEqual(len(doc.position_photos), 1)
		self.assertEqual(doc.status, ps.PENDING)

	def test_draft_then_record_finishes_normally(self):
		c = self._container("CPSDRAFT003")
		name = self._new_survey(c)
		ps.save_survey_draft(name, "sementara", photos=["/files/d3.jpg"])

		# The final Simpan carries the full payload and overwrites the draft wholesale.
		ps.record_survey_position(name, "final", photos=["/files/f1.jpg", "/files/f2.jpg"])

		doc = frappe.get_doc("Container Position Survey", name)
		self.assertEqual(doc.status, ps.SURVEYED)
		self.assertEqual(doc.location_note, "final")
		self.assertEqual([p.photo for p in doc.position_photos], ["/files/f1.jpg", "/files/f2.jpg"])
		self.assertEqual(doc.surveyed_by, "Administrator")

	def test_draft_rejects_non_pending(self):
		"""A late autosave must not reopen a survey somebody has already finished."""
		c = self._container("CPSDRAFT004")
		name = self._new_survey(c)
		ps.record_survey_position(name, "sudah disurvei")
		with self.assertRaises(frappe.ValidationError):
			ps.save_survey_draft(name, "ketikan yang telat sampai")

	# --- notifications -------------------------------------------------------
	#
	# One doctype, two menus, two teams: each half of the workflow has to ring the team that
	# picks it up. The events are asserted on rather than the recipients — who receives what
	# is routing data an admin may retune (Depot Notification Rule), the fact that the event
	# fires at all is code.
	def _fired(self, fn, *args, **kwargs):
		"""Run ``fn`` with notify() spied on; return the event keys it emitted."""
		with patch("container_depot.container_depot.notify.notify") as spy:
			fn(*args, **kwargs)
		return [c.kwargs.get("event_key") for c in spy.call_args_list]

	def test_provisioning_rings_the_survey_team(self):
		# Saved through the booking, which is what provisions now — the notification has to
		# survive the move from submit to the draft save.
		c = self._container("CPSNOTIF001")
		# Both notifications now come out of the same save: the booking announces itself
		# (after_insert) and the survey it opens rings the surveyors (on_update).
		self.assertEqual(
			self._fired(self._tank_out_booking, c),
			["booking_created", "position_survey_pending"],
		)

	def test_recording_a_position_rings_kalmar(self):
		c = self._container("CPSNOTIF002")
		name = self._new_survey(c)
		self.assertEqual(
			self._fired(ps.record_survey_position, name, "blok kanan"),
			["position_surveyed"],
		)

	def test_approving_rings_oversight(self):
		c = self._container("CPSNOTIF003")
		name = self._new_survey(c)
		ps.record_survey_position(name, "ground slot B2")
		self.assertEqual(
			self._fired(ps.approve_position, name),
			["position_confirmed"],
		)

	def test_an_autosave_rings_nobody(self):
		"""The draft fires on every typing pause. A bell there would be a notification storm
		about a survey nobody has finished."""
		c = self._container("CPSNOTIF004")
		name = self._new_survey(c)
		self.assertEqual(self._fired(ps.save_survey_draft, name, "setengah jalan"), [])


class TestPositionSurveyWork(FrappeTestCase):
	"""Mulai / selesai / buka lagi — the two halves of the workflow, each claimed on its own
	column and each able to undo itself.

	Runs as two real field users rather than Administrator: the claim fence has a bypass for
	ops roles (``work_claim.CLAIM_BYPASS_ROLES``), so an Administrator would sail through the
	very thing these tests exist to pin.
	"""

	SURVEYOR = "cps-surveyor@example.com"
	OTHER_SURVEYOR = "cps-surveyor2@example.com"
	KALMAR = "cps-kalmar@example.com"

	def setUp(self):
		frappe.set_user("Administrator")
		self._containers = []
		_user(self.SURVEYOR, "Team Survey")
		_user(self.OTHER_SURVEYOR, "Team Survey")
		_user(self.KALMAR, "Team Kalmar")

	def tearDown(self):
		frappe.set_user("Administrator")
		surveys = frappe.get_all(
			DOCTYPE_FILTER := "Container Position Survey",
			filters={"container": ["in", self._containers or [""]]},
			pluck="name",
		)
		if surveys:
			frappe.db.delete("Notification Log", {
				"document_type": DOCTYPE_FILTER, "document_name": ["in", surveys],
			})
			frappe.db.delete("Comment", {
				"reference_doctype": DOCTYPE_FILTER, "reference_name": ["in", surveys],
			})
		frappe.db.delete(DOCTYPE_FILTER, {"container": ["in", self._containers or [""]]})
		for c in self._containers:
			frappe.db.delete("Container", {"name": c})
		for email in (self.SURVEYOR, self.OTHER_SURVEYOR, self.KALMAR):
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, ignore_permissions=True, force=True)
		frappe.db.commit()
		super().tearDown()

	def _survey(self, cno):
		c = _make_container(cno, depot=DEPOT)
		self._containers.append(c)
		return frappe.get_doc({
			"doctype": "Container Position Survey", "container": c,
			"depot": DEPOT, "status": ps.PENDING,
		}).insert(ignore_permissions=True).name

	def _status(self, name):
		return frappe.db.get_value("Container Position Survey", name, ["status", "docstatus"])

	def _names(self, listing):
		return {i["name"] for i in listing["items"]}

	# --- Mulai ---------------------------------------------------------------
	def test_mulai_claims_the_survey_and_hides_it_from_other_surveyors(self):
		name = self._survey("CPSWORK0001")

		frappe.set_user(self.SURVEYOR)
		ps.start_survey(name)
		self.assertEqual(self._status(name), (ps.IN_SURVEY, 0))
		# Still on the worklist of whoever holds it — the job is not finished, just taken.
		self.assertIn(name, self._names(ps.list_pending_surveys(page_length=100)))

		frappe.set_user(self.OTHER_SURVEYOR)
		self.assertNotIn(name, self._names(ps.list_pending_surveys(page_length=100)))
		# ...and the notification link is refused too, not just the list hidden.
		with self.assertRaises(ClaimedByAnother):
			ps.start_survey(name)

	def test_the_fix_half_is_claimed_on_its_own_column(self):
		"""A survey held by a surveyor earlier must not read as claimed to the Kalmar later."""
		name = self._survey("CPSWORK0002")
		frappe.set_user(self.SURVEYOR)
		ps.start_survey(name)
		ps.record_survey_position(name, "blok kanan")

		frappe.set_user(self.KALMAR)
		self.assertIn(name, self._names(ps.list_surveyed(page_length=100)))
		ps.start_fix(name)
		self.assertEqual(self._status(name), (ps.IN_FIX, 0))
		ps.approve_position(name)
		self.assertEqual(self._status(name), (ps.CONFIRMED, 1))

	def test_pressing_mulai_twice_is_a_no_op(self):
		"""A retry from a dead spot must not read as a failure."""
		name = self._survey("CPSWORK0003")
		frappe.set_user(self.SURVEYOR)
		ps.start_survey(name)
		self.assertEqual(ps.start_survey(name)["status"], ps.IN_SURVEY)

	def test_finishing_without_mulai_still_claims_the_job(self):
		"""The handset that came back from a dead spot straight into Simpan."""
		name = self._survey("CPSWORK0004")
		frappe.set_user(self.SURVEYOR)
		ps.record_survey_position(name, "langsung simpan")
		self.assertEqual(
			frappe.db.get_value("Container Position Survey", name, "survey_started_by"),
			self.SURVEYOR,
		)

	def test_a_started_job_sits_above_an_untouched_one(self):
		"""Tier 2: finishing what is already open beats opening something new — and a
		half-filled form at the bottom of a long list is how a tank gets worked twice."""
		untouched = self._survey("CPSSORT0003")
		started = self._survey("CPSSORT0004")
		frappe.set_user(self.SURVEYOR)
		ps.start_survey(started)

		names = [i["name"] for i in ps.list_pending_surveys(page_length=100)["items"]]
		self.assertLess(names.index(started), names.index(untouched))

	def test_the_fix_worklist_uses_the_same_order(self):
		"""One habit covers both menus: the Kalmar list is read exactly like the survey one."""
		untouched = self._survey("CPSSORT0005")
		started = self._survey("CPSSORT0006")
		frappe.set_user(self.SURVEYOR)
		for n in (untouched, started):
			ps.record_survey_position(n, "posisi")
		frappe.set_user(self.KALMAR)
		ps.start_fix(started)

		names = [i["name"] for i in ps.list_surveyed(page_length=100)["items"]]
		self.assertLess(names.index(started), names.index(untouched))

	# --- buka lagi (revisi / rollback) ---------------------------------------
	def test_reopen_survey_unsubmits_and_returns_it_to_the_surveyor(self):
		name = self._survey("CPSWORK0005")
		frappe.set_user(self.SURVEYOR)
		ps.start_survey(name)
		ps.record_survey_position(name, "posisi awal")
		frappe.set_user(self.KALMAR)
		ps.start_fix(name)
		ps.approve_position(name)
		self.assertEqual(self._status(name), (ps.CONFIRMED, 1))

		# The Kalmar operator standing at the wrong stack sends it back.
		ps.reopen_survey(name, note="tanknya tidak ada di situ")
		doc = frappe.get_doc("Container Position Survey", name)
		self.assertEqual((doc.status, doc.docstatus), (ps.IN_SURVEY, 0))
		# The step being redone is wiped; the note the surveyor has to correct is NOT.
		self.assertFalse(doc.surveyed_by)
		self.assertFalse(doc.approved_by)
		self.assertFalse(doc.fix_started_by)
		self.assertEqual(doc.location_note, "posisi awal")
		self.assertIn("tanknya tidak ada di situ", doc.reopen_note)

		# Back in the survey worklist, gone from the Kalmar one.
		frappe.set_user(self.SURVEYOR)
		self.assertIn(name, self._names(ps.list_pending_surveys(page_length=100)))
		frappe.set_user(self.KALMAR)
		self.assertNotIn(name, self._names(ps.list_surveyed(page_length=100)))

	def test_reopen_fix_leaves_the_surveyors_work_alone(self):
		name = self._survey("CPSWORK0006")
		frappe.set_user(self.SURVEYOR)
		ps.start_survey(name)
		ps.record_survey_position(name, "ground slot A1", photos=["/files/p1.jpg"])
		frappe.set_user(self.KALMAR)
		ps.start_fix(name)
		ps.approve_position(name, note="udah turun")

		ps.reopen_fix(name, note="kepencet, belum turun")
		doc = frappe.get_doc("Container Position Survey", name)
		self.assertEqual((doc.status, doc.docstatus), (ps.IN_FIX, 0))
		self.assertFalse(doc.approved_by)
		self.assertFalse(doc.approval_note)
		# Untouched: nobody walks out to the tank again for an approval pressed too early.
		self.assertEqual(doc.surveyed_by, self.SURVEYOR)
		self.assertEqual(doc.location_note, "ground slot A1")
		self.assertEqual(len(doc.position_photos), 1)
		self.assertIn(name, self._names(ps.list_surveyed(page_length=100)))

	def test_reopen_fix_refuses_a_survey_that_was_never_confirmed(self):
		"""Otherwise "buka lagi approval" would drop a tank nobody has located into the
		Kalmar worklist with no position note to approve."""
		name = self._survey("CPSWORK0007")
		frappe.set_user(self.SURVEYOR)
		with self.assertRaises(frappe.ValidationError):
			ps.reopen_fix(name)

	def test_reopening_a_reopened_survey_is_a_no_op(self):
		name = self._survey("CPSWORK0008")
		frappe.set_user(self.SURVEYOR)
		ps.record_survey_position(name, "posisi")
		ps.reopen_survey(name)
		self.assertEqual(ps.reopen_survey(name)["status"], ps.IN_SURVEY)

	def test_a_redone_step_clears_the_reopen_note(self):
		"""The reason it came back stops being news once the redo lands."""
		name = self._survey("CPSWORK0009")
		frappe.set_user(self.SURVEYOR)
		ps.record_survey_position(name, "posisi awal")
		ps.reopen_survey(name, note="salah blok")
		self.assertTrue(frappe.db.get_value("Container Position Survey", name, "reopen_note"))
		ps.record_survey_position(name, "posisi benar")
		self.assertFalse(frappe.db.get_value("Container Position Survey", name, "reopen_note"))

	def test_reopen_rings_the_queue_it_lands_in(self):
		name = self._survey("CPSWORK0010")
		frappe.set_user(self.SURVEYOR)
		ps.record_survey_position(name, "posisi")
		with patch("container_depot.container_depot.notify.notify") as spy:
			ps.reopen_survey(name, note="ulangi")
		self.assertEqual(
			[c.kwargs.get("event_key") for c in spy.call_args_list],
			["position_survey_pending"],
		)


class TestPositionSurveyMenuGates(FrappeTestCase):
	"""The endpoint layer, not the logic: who may call what.

	One doctype behind two menus is exactly the shape where a gate ends up on the wrong
	half — and the two endpoints that serve BOTH menus (`require_any_menu`) are new, so the
	thing worth pinning is that "either" never quietly became "anyone".
	"""

	SURVEYOR = "cps-gate-survey@example.com"
	KALMAR = "cps-gate-kalmar@example.com"
	OUTSIDER = "cps-gate-none@example.com"

	def setUp(self):
		frappe.set_user("Administrator")
		self._containers = []
		_user(self.SURVEYOR, "Team Survey")
		_user(self.KALMAR, "Team Kalmar")
		_user(self.OUTSIDER)  # a login with no depot role at all
		c = _make_container("CPSGATE0001", depot=DEPOT)
		self._containers.append(c)
		self.survey = frappe.get_doc({
			"doctype": "Container Position Survey", "container": c,
			"depot": DEPOT, "status": ps.PENDING,
		}).insert(ignore_permissions=True).name

	def tearDown(self):
		frappe.set_user("Administrator")
		# The bell rows and the timeline comments a reopen leaves behind outlive the survey
		# they point at, so they go first — see the same block in TestPositionSurveyWork.
		frappe.db.delete("Notification Log", {
			"document_type": "Container Position Survey", "document_name": self.survey,
		})
		frappe.db.delete("Comment", {
			"reference_doctype": "Container Position Survey", "reference_name": self.survey,
		})
		frappe.db.delete("Container Position Survey", {"container": ["in", self._containers or [""]]})
		for c in self._containers:
			frappe.db.delete("Container", {"name": c})
		for email in (self.SURVEYOR, self.KALMAR, self.OUTSIDER):
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, ignore_permissions=True, force=True)
		frappe.db.commit()
		super().tearDown()

	def _refused(self, user, fn, *args, **kwargs):
		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			fn(*args, **kwargs)

	def test_each_half_owns_its_own_start(self):
		from container_depot.ess import position_survey as ess

		frappe.set_user(self.SURVEYOR)
		self.assertEqual(ess.position_start(name=self.survey)["status"], ps.IN_SURVEY)
		self._refused(self.SURVEYOR, ess.position_fix_start, name=self.survey)

		frappe.set_user(self.SURVEYOR)
		ess.position_record(name=self.survey, location_note="blok kanan")
		frappe.set_user(self.KALMAR)
		self.assertEqual(ess.position_fix_start(name=self.survey)["status"], ps.IN_FIX)
		self._refused(self.KALMAR, ess.position_record, name=self.survey, location_note="x")

	def test_riwayat_and_the_survey_reopen_are_open_to_both_menus(self):
		from container_depot.ess import position_survey as ess

		for user in (self.SURVEYOR, self.KALMAR):
			with self.subTest(user=user):
				frappe.set_user(user)
				self.assertIn("items", ess.position_history())
				self.assertIn("status", ess.position_detail(name=self.survey))

		# Both may send a located survey back to the surveyor — the Kalmar is the one who
		# finds the tank missing, so refusing them would put the undo out of reach.
		frappe.set_user(self.SURVEYOR)
		ess.position_record(name=self.survey, location_note="posisi")
		frappe.set_user(self.KALMAR)
		self.assertEqual(ess.position_reopen_survey(name=self.survey)["status"], ps.IN_SURVEY)

	def test_the_approval_reopen_stays_with_kalmar(self):
		"""`require_any_menu` must not have leaked into the one that is single-menu."""
		from container_depot.ess import position_survey as ess

		self._refused(self.SURVEYOR, ess.position_reopen_fix, name=self.survey)

	def test_an_account_with_no_depot_role_is_refused_everywhere(self):
		from container_depot.ess import position_survey as ess

		for fn in (ess.position_history, ess.position_pending, ess.position_surveyed):
			with self.subTest(fn=fn.__name__):
				self._refused(self.OUTSIDER, fn)
		self._refused(self.OUTSIDER, ess.position_detail, name=self.survey)
		self._refused(self.OUTSIDER, ess.position_reopen_survey, name=self.survey)
