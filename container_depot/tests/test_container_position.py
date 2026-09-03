"""Container Position — where a tank stands, recorded by anyone, at any time.

The feature is deliberately NOT tied to a booking: a tank's position changes because a
reachstacker moved it, and the next person who needs it may be a washer, a mechanic, a surveyor
or the gate. So every reading is a document of its own, and the newest one is mirrored onto the
``Container`` master along with WHEN it was taken — the age is half of what makes a position
usable.

Self-cleaning: every fixture created here is hard-deleted in tearDown.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from container_depot.container_depot import container_position as cp
from container_depot.tests.test_eir import _make_container
from container_depot.tests.test_work_claim import _user

DEPOT = "OAK1"
DOCTYPE = "Container Position"


class _Base(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._containers = []

	def tearDown(self):
		frappe.set_user("Administrator")
		containers = self._containers or [""]
		readings = frappe.get_all(DOCTYPE, filters={"container": ["in", containers]}, pluck="name")
		if readings:
			frappe.db.delete("Container Position Photo", {"parent": ["in", readings]})
		frappe.db.delete(DOCTYPE, {"container": ["in", containers]})
		frappe.db.delete("Container", {"name": ["in", containers]})
		frappe.db.commit()
		super().tearDown()

	def _container(self, cno):
		c = _make_container(cno, depot=DEPOT)
		self._containers.append(c)
		return c

	def _master(self, container):
		return frappe.db.get_value(
			"Container", container,
			["current_location", "location_updated_on", "location_updated_by"],
			as_dict=True,
		)


class TestRecordingAPosition(_Base):
	def test_a_reading_lands_on_the_master(self):
		"""The master is what every other screen reads, so a reading that does not reach it has
		not happened as far as the depot is concerned."""
		c = self._container("CPOS00000001")
		self.assertIsNone(self._master(c).current_location)

		cp.record_position(c, "blok kanan dekat pos, tumpukan 2")

		m = self._master(c)
		self.assertEqual(m.current_location, "blok kanan dekat pos, tumpukan 2")
		self.assertEqual(m.location_updated_by, "Administrator")
		self.assertIsNotNone(m.location_updated_on)

	def test_a_reading_needs_a_location(self):
		c = self._container("CPOS00000002")
		with self.assertRaises(frappe.ValidationError):
			cp.record_position(c, "   ")
		self.assertEqual(frappe.db.count(DOCTYPE, {"container": c}), 0)

	def test_a_correction_is_a_second_reading_not_an_edit(self):
		"""The yard has to be able to see that a tank was reported in two places and when the
		story changed. Overwriting the first reading would erase exactly that."""
		c = self._container("CPOS00000003")
		cp.record_position(c, "blok kanan")
		cp.record_position(c, "ternyata blok kiri")

		self.assertEqual(frappe.db.count(DOCTYPE, {"container": c}), 2)
		self.assertEqual(self._master(c).current_location, "ternyata blok kiri")
		self.assertEqual(
			[h["location_note"] for h in cp.get_container_position(c)["history"]],
			["ternyata blok kiri", "blok kanan"],
		)

	def test_the_master_follows_the_NEWEST_reading_not_the_last_written(self):
		"""A correction typed after the fact must not leave the master quoting a newer row that
		describes an older moment — the mirror is by timestamp, not by write order."""
		c = self._container("CPOS00000004")
		cp.record_position(c, "pagi: blok kanan")
		old = frappe.get_doc({
			"doctype": DOCTYPE, "container": c, "location_note": "kemarin: blok kiri",
			"recorded_on": add_to_date(now_datetime(), days=-1),
		}).insert(ignore_permissions=True)

		self.assertEqual(self._master(c).current_location, "pagi: blok kanan")
		self.assertTrue(old.name)

	def test_deleting_the_newest_reading_hands_the_master_back(self):
		"""Otherwise the tank keeps pointing at a position nobody stands behind any more."""
		c = self._container("CPOS00000005")
		cp.record_position(c, "blok kanan")
		second = cp.record_position(c, "blok kiri")["name"]
		self.assertEqual(self._master(c).current_location, "blok kiri")

		frappe.delete_doc(DOCTYPE, second, ignore_permissions=True)
		self.assertEqual(self._master(c).current_location, "blok kanan")


class TestReadingItBack(_Base):
	def test_never_located_is_a_different_state_from_located_long_ago(self):
		"""The screen says these two differently — "Lokasi belum terdata" versus a stale badge —
		and an operator has to be able to tell a blank from a guess."""
		blank = self._container("CPOS00000010")
		stale = self._container("CPOS00000011")
		cp.record_position(stale, "blok kanan")
		frappe.db.set_value(
			"Container", stale, "location_updated_on", add_to_date(now_datetime(), days=-30)
		)

		self.assertFalse(cp.get_container_position(blank)["located"])
		s = cp.get_container_position(stale)
		self.assertTrue(s["located"])
		self.assertFalse(s["fresh"])
		self.assertGreater(s["hours"], cp.FRESH_HOURS)

	def test_a_fresh_reading_reads_as_fresh(self):
		c = self._container("CPOS00000012")
		cp.record_position(c, "blok kanan")
		self.assertTrue(cp.get_container_position(c)["fresh"])

	def test_the_finder_can_narrow_to_tanks_nobody_has_located(self):
		"""The list this feature exists to empty."""
		blank = self._container("CPOS00000013")
		known = self._container("CPOS00000014")
		cp.record_position(known, "blok kanan")

		found = {r["name"] for r in cp.search_containers(search="CPOS000000", only_unlocated=1)["items"]}
		self.assertIn(blank, found)
		self.assertNotIn(known, found)

	def test_the_finder_matches_on_the_tank_number(self):
		"""The only thing anyone standing in a yard has to hand."""
		c = self._container("CPOS00000015")
		names = {r["name"] for r in cp.search_containers(search="CPOS00000015")["items"]}
		self.assertEqual(names, {c})



class TestPhotos(_Base):
	"""A position's photos — the half of the answer that cannot be argued with.

	"Blok kanan tumpukan 2" is somebody's description; the picture is what the next person
	matches against the stack in front of them. So the pictures belong to the READING, and
	every read that hands back readings hands back their photos.
	"""

	def test_a_reading_keeps_every_photo_it_was_given(self):
		c = self._container("CPOSPHOTO0001")
		out = cp.record_position(c, "blok kanan", photos=["/files/a.jpg", "/files/b.jpg"])
		self.assertEqual(out["photos"], ["/files/a.jpg", "/files/b.jpg"])

	def test_photos_arrive_in_any_of_the_shapes_a_client_may_send(self):
		"""A bare url list, a list of ``{photo}`` rows, or either of those as a JSON string —
		the PWA sends the first, the Desk grid the second."""
		c = self._container("CPOSPHOTO0002")
		self.assertEqual(cp._coerce_photos(["/files/a.jpg"]), ["/files/a.jpg"])
		self.assertEqual(cp._coerce_photos([{"photo": "/files/a.jpg"}]), ["/files/a.jpg"])
		self.assertEqual(cp._coerce_photos('["/files/a.jpg"]'), ["/files/a.jpg"])
		# Blanks are dropped rather than stored as empty child rows.
		self.assertEqual(cp._coerce_photos(["", None, "  "]), [])

	def test_the_history_carries_each_reading_s_own_photos(self):
		"""Not the tank's photos — each READING's. A tank photographed in a bay it has since
		left must not show that picture against the reading that moved it."""
		c = self._container("CPOSPHOTO0003")
		cp.record_position(c, "bay lama", photos=["/files/old.jpg"])
		cp.record_position(c, "bay baru", photos=["/files/new1.jpg", "/files/new2.jpg"])
		history = cp.get_container_position(c)["history"]
		self.assertEqual(history[0]["photos"], ["/files/new1.jpg", "/files/new2.jpg"])
		self.assertEqual(history[1]["photos"], ["/files/old.jpg"])

	def test_a_reading_with_no_photos_reports_an_empty_list_not_a_missing_key(self):
		"""The screens iterate this. A missing key renders as a broken row, an empty list as
		no thumbnails — which is the truth."""
		c = self._container("CPOSPHOTO0004")
		cp.record_position(c, "blok kiri")
		self.assertEqual(cp.get_container_position(c)["history"][0]["photos"], [])

	def test_the_readings_feed_carries_them_too(self):
		c = self._container("CPOSPHOTO0005")
		cp.record_position(c, "blok kanan", photos=["/files/x.jpg"])
		row = cp.list_position_history(container=c)["items"][0]
		self.assertEqual(row["photos"], ["/files/x.jpg"])

	def test_photos_are_optional(self):
		"""Somebody standing at a tank in the rain must not be blocked from correcting a
		position because they cannot get a clean shot."""
		c = self._container("CPOSPHOTO0006")
		cp.record_position(c, "blok tengah", photos=None)
		self.assertEqual(self._master(c).current_location, "blok tengah")


class TestWhoMayRecord(FrappeTestCase):
	"""Every field team, and that is the design rather than an oversight: a wrong position costs
	whoever walks to the wrong stack next, whichever crew they are on."""

	USERS = {
		"Team Cleaning": "cpos-cleaning@example.com",
		"Team Kalmar": "cpos-kalmar@example.com",
		"Team Survey": "cpos-survey@example.com",
	}
	OUTSIDER = "cpos-none@example.com"

	def setUp(self):
		frappe.set_user("Administrator")
		for role, email in self.USERS.items():
			_user(email, role)
		_user(self.OUTSIDER)  # a login with no depot role at all
		self.container = _make_container("CPOSPERM0001", depot=DEPOT)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.delete(DOCTYPE, {"container": self.container})
		frappe.db.delete("Container", {"name": self.container})
		for email in (*self.USERS.values(), self.OUTSIDER):
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, ignore_permissions=True, force=True)
		frappe.db.commit()
		super().tearDown()

	def test_every_field_team_may_correct_a_position(self):
		from container_depot.ess import container_position as ess

		for role, email in self.USERS.items():
			with self.subTest(role=role):
				frappe.set_user(email)
				res = ess.position_record(container=self.container, location_note=f"dari {role}")
				self.assertTrue(res["success"])
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.count(DOCTYPE, {"container": self.container}), len(self.USERS))

	def test_an_account_with_no_depot_role_is_refused(self):
		from container_depot.ess import container_position as ess

		frappe.set_user(self.OUTSIDER)
		for call in (
			lambda: ess.tank_search(),
			lambda: ess.tank_position(container=self.container),
			lambda: ess.position_record(container=self.container, location_note="x"),
		):
			with self.assertRaises(frappe.PermissionError):
				call()
