"""Tests for the Beranda (PWA home) endpoint ``container_depot.ess.home.get_home_summary``.

The endpoint is an aggregation of counts over separately-tested worklists, so what is
tested here is what it adds on top of them:

* the response **shape** — every tile key Beranda reads is present, so a missing key
  cannot silently blank a card;
* the ``today`` counts move by the right **delta** when a fixture is added (delta rather
  than exact, because an unrestricted user counts instance-wide on a shared site);
* ``_queue`` — the "Menunggu Anda" row builder — names the container only when the queue
  holds exactly one item, which is the rule the whole section's wording depends on;
* Guest is rejected.

The ``waiting`` LIST itself is asserted only through ``_queue``: the endpoint caps it at
six rows sorted by age, so on a site with older work of its own a freshly created fixture
may legitimately fall off the end.

FrappeTestCase wraps each test in a transaction and rolls it back; ``_teardown`` clears
anything a committing controller slipped through, before and after the class.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime, today

from container_depot.container_depot import cleaning, eir, mr
from container_depot.ess.home import (
	DEFAULT_TILES,
	MAX_WAITING,
	TILE_MENU,
	_queue,
	_wanted_tiles,
	get_home_summary,
)
from container_depot.tests.test_api import ensure_test_branch, ensure_test_customer
from container_depot.tests.test_work_claim import TEAM_ROLES, _user

DEPOT = "HOMET"
PREFIX = "HOME"
PRINCIPAL = "Home Summary Test Principal"


def _teardown():
	names = frappe.get_all("Container", filters={"container_no": ["like", f"{PREFIX}%"]}, pluck="name")
	if names:
		for dt in ["Container Movement", "Container Activity", "Cleaning Order", "Repair Order", "Inspection"]:
			frappe.db.delete(dt, {"container": ["in", names]})
		frappe.db.delete("Container", {"name": ["in", names]})
	if frappe.db.exists("Depot", DEPOT):
		frappe.db.delete("Depot", {"name": DEPOT})
	# The test principal too: `ensure_test_customer` commits, so it would otherwise outlive
	# the run and pile up in the customer list of a working site.
	for cust in frappe.get_all("Customer", filters={"customer_name": PRINCIPAL}, pluck="name"):
		frappe.delete_doc("Customer", cust, force=True, ignore_permissions=True, delete_permanently=True)
	frappe.db.commit()


class TestHomeSummary(FrappeTestCase):
	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		_teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		_teardown()
		frappe.get_doc({
			"doctype": "Depot",
			"depot_code": DEPOT,
			"depot_name": "Home Summary Test Depot",
			"branch": ensure_test_branch(),
		}).insert(ignore_permissions=True)
		self.principal = ensure_test_customer(PRINCIPAL)

	def _container(self, no, status="Available"):
		frappe.get_doc({
			"doctype": "Container",
			"container_no": no,
			"container_type": "ISO Tank",
			"status": status,
			"depot": DEPOT,
			"principal": self.principal,
		}).insert(ignore_permissions=True)
		return no

	# --- shape -------------------------------------------------------------
	def test_summary_shape(self):
		res = get_home_summary()
		self.assertTrue(res["success"])
		self.assertTrue(res["menu"], "Administrator should hold every PWA menu")
		# One key per tile Beranda draws; a missing one blanks a card rather than erroring.
		for key in (
			"gate_in", "gate_out", "booking_out",
			"eir_open", "eir_review", "eir_review_age",
			"cleaning_open", "cleaning_idle",
		):
			self.assertIn(key, res["today"])
		self.assertIsInstance(res["waiting"], list)
		for row in res["waiting"]:
			self.assertEqual(set(row), {"key", "count", "ref", "age"})
			self.assertGreater(row["count"], 0)

	# --- today's tiles (delta, instance-wide) ------------------------------
	def test_gate_in_delta(self):
		c = self._container("HOME0000010")
		before = get_home_summary()["today"]
		frappe.get_doc({
			"doctype": "Container Activity",
			"container": c,
			"activity_type": "Gate In",
			"activity_time": now_datetime(),
			"depot": DEPOT,
		}).insert(ignore_permissions=True)
		after = get_home_summary()["today"]
		self.assertEqual(after["gate_in"], before["gate_in"] + 1)
		self.assertEqual(after["gate_out"], before["gate_out"])  # unrelated type untouched

	def test_cleaning_and_eir_review_deltas(self):
		c = self._container("HOME0000020")
		before = get_home_summary()["today"]

		frappe.get_doc(
			{"doctype": "Cleaning Order", "container": c, "status": "Pending"}
		).insert(ignore_permissions=True)
		insp = frappe.get_doc({
			"doctype": "Inspection",
			"container": c,
			"inspection_type": "EIR-In",
			"inspector": "Administrator",
		}).insert(ignore_permissions=True)
		# Straight to the field the endpoint filters on: "Pending Review" is reached from
		# the PWA by finishing a checklist, which is not what this test is about.
		frappe.db.set_value("Inspection", insp.name, "status", "Pending Review", update_modified=False)

		after = get_home_summary()["today"]
		self.assertEqual(after["cleaning_open"], before["cleaning_open"] + 1)
		self.assertEqual(after["cleaning_idle"], before["cleaning_idle"] + 1)
		self.assertEqual(after["eir_review"], before["eir_review"] + 1)
		# A queue with something in it always has an age; the tile prints it as "tertua 2 jam".
		self.assertIsNotNone(after["eir_review_age"])
		self.assertGreaterEqual(after["eir_review_age"], 0)
		# The EIR is awaiting review, so it is NOT in the "belum dikerjakan" count.
		self.assertEqual(after["eir_open"], before["eir_open"])

	# --- kartu yang diminta klien ------------------------------------------
	# Beranda mengirim kunci kartu yang akan digambar (operator memilihnya, maks 4). Yang
	# diuji di sini adalah kontraknya: yang diminta dihitung, yang tidak TIDAK dihitung —
	# itu satu-satunya alasan katalognya boleh berisi sebelas kartu tanpa memperlambat
	# pembukaan aplikasi.
	def test_default_tiles_when_param_absent(self):
		today = get_home_summary()["today"]
		# Empat bawaan hadir…
		for key in ("gate_in", "gate_out", "eir_review", "cleaning_open"):
			self.assertIn(key, today)
		# …dan angka milik kartu yang tidak diminta tidak ikut dihitung.
		for key in ("mr_open", "depot_total", "schedule_today", "survey_today", "unlocated"):
			self.assertNotIn(key, today)

	def test_requested_tiles_are_the_only_ones_counted(self):
		today = get_home_summary(tiles="mr,monitor")["today"]
		for key in ("mr_open", "mr_approval", "depot_total"):
			self.assertIn(key, today)
		for key in ("gate_in", "cleaning_open", "eir_review"):
			self.assertNotIn(key, today)

	def test_every_catalogued_tile_produces_its_numbers(self):
		# Administrator memegang semua menu, jadi setiap kartu di katalog harus bisa
		# dihitung. Kartu yang tidak menghasilkan angka akan tampil sebagai kartu kosong.
		today = get_home_summary(tiles=",".join(TILE_MENU))["today"]
		for key in (
			"gate_in", "gate_out", "booking_out", "eir_open", "eir_out", "eir_review",
			"cleaning_open", "cleaning_idle", "mr_open", "mr_approval", "depot_total",
			"schedule_today", "schedule_open", "survey_today", "lowering", "unlocated",
		):
			self.assertIn(key, today)

	def test_unknown_and_unpermitted_tiles_are_dropped(self):
		menu = {"gate"}
		# Kunci yang menunya tidak dipegang dibuang diam-diam — klien tidak bisa memaksa
		# server menghitung layar yang tidak boleh ia buka.
		self.assertEqual(_wanted_tiles("gateIn,mr,monitor", menu), {"gateIn"})
		# Begitu juga kunci karangan.
		self.assertEqual(_wanted_tiles("gateIn,tidakAda", menu), {"gateIn"})
		# Param kosong / placeholder frappe-ui = empat bawaan, disaring menu yang sama.
		self.assertEqual(_wanted_tiles(None, set(TILE_MENU.values())), set(DEFAULT_TILES))
		self.assertEqual(_wanted_tiles("undefined", {"gate"}), {"gateIn", "gateOut"})

	# --- antrean per menu ---------------------------------------------------
	# Delta, bukan angka pasti: site dev punya pekerjaan sendiri. Kalau daftarnya sudah
	# mentok di MAX_WAITING baris, antrean termuda memang dipotong — test-nya dilewati
	# daripada mengarang harapan yang tidak dijanjikan endpoint.
	def _waiting_count(self, res, key) -> int:
		row = next((r for r in res["waiting"] if r["key"] == key), None)
		return row["count"] if row else 0

	def _skip_if_capped(self, res):
		if len(res["waiting"]) >= MAX_WAITING:
			self.skipTest("daftar 'Menunggu Anda' sudah mentok — baris baru sah terpotong")

	def test_cleaning_review_queue(self):
		c = self._container("HOME0000030")
		before = get_home_summary()
		self._skip_if_capped(before)
		co = frappe.get_doc(
			{"doctype": "Cleaning Order", "container": c, "status": "Pending"}
		).insert(ignore_permissions=True)
		# Langsung ke field-nya: "Pending Review" dicapai dari PWA dengan menyelesaikan
		# cucian, dan itu bukan yang diuji di sini.
		frappe.db.set_value("Cleaning Order", co.name, "status", "Pending Review", update_modified=False)

		after = get_home_summary()
		self.assertEqual(
			self._waiting_count(after, "cleaningReview"),
			self._waiting_count(before, "cleaningReview") + 1,
		)
		# Sudah diajukan review = bukan lagi "belum dimulai".
		self.assertEqual(
			self._waiting_count(after, "cleaningIdle"),
			self._waiting_count(before, "cleaningIdle"),
		)

	def test_mr_review_queue(self):
		c = self._container("HOME0000040")
		before = get_home_summary()
		self._skip_if_capped(before)
		ro = frappe.get_doc(
			{"doctype": "Repair Order", "container": c, "status": "Draft", "billing_status": "Unbilled"}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Repair Order", ro.name, "status", "Pending Review", update_modified=False)

		after = get_home_summary()
		self.assertEqual(
			self._waiting_count(after, "mrReview"),
			self._waiting_count(before, "mrReview") + 1,
		)
		# Menunggu review bukan menunggu persetujuan — dua antrean, dua orang.
		self.assertEqual(
			self._waiting_count(after, "mrApproval"),
			self._waiting_count(before, "mrApproval"),
		)

	def test_schedule_overdue_queue(self):
		# Pekerjaan terencana yang tanggalnya sudah lewat dan belum beres. Cleaning Order
		# dengan plan_date kemarin adalah fixture termurah untuk itu (lihat SOURCES di
		# container_depot/schedule.py); aturannya sendiri milik kalender, bukan endpoint ini.
		c = self._container("HOME0000050")
		before = get_home_summary()
		self._skip_if_capped(before)
		frappe.get_doc({
			"doctype": "Cleaning Order",
			"container": c,
			"status": "Pending",
			"plan_date": add_days(today(), -3),
		}).insert(ignore_permissions=True)

		after = get_home_summary()
		self.assertEqual(
			self._waiting_count(after, "scheduleOverdue"),
			self._waiting_count(before, "scheduleOverdue") + 1,
		)
		row = next(r for r in after["waiting"] if r["key"] == "scheduleOverdue")
		# Umurnya diukur dari hari tertua yang tertinggal — itu yang menaruhnya di atas.
		self.assertIsNotNone(row["age"])
		self.assertGreater(row["age"], 0)

	def test_unlocated_tank_alone_is_not_a_waiting_row(self):
		"""Tanpa survey yang menunggunya, tank tanpa letak cuma catatan — bukan antrean.

		Kartunya tetap menghitungnya (ratusan tank di yard memang tidak pernah dicatat), tapi
		barisnya tidak: "Menunggu Anda" berisi pekerjaan yang ada tenggatnya dan ada orangnya.
		Siapa yang MASUK antrean adalah aturan container_position.open_position_orders dan
		diuji di sana bersama booking-nya — di sini yang diuji cuma bahwa beranda memakainya.
		"""
		before = get_home_summary(tiles="unlocated")
		self._skip_if_capped(before)
		self._container("HOME0000060")

		after = get_home_summary(tiles="unlocated")
		self.assertEqual(after["today"]["unlocated"], before["today"]["unlocated"] + 1)
		self.assertEqual(
			self._waiting_count(after, "positionOrder"),
			self._waiting_count(before, "positionOrder"),
		)
		self.assertFalse(
			[r for r in after["waiting"] if r["key"] == "unlocated"],
			"'unlocated' tidak lagi jadi baris antrean",
		)

	# --- "Menunggu Anda" row builder ---------------------------------------
	def test_queue_names_the_container_only_when_alone(self):
		a = self._container("HOME0000030")
		b = self._container("HOME0000031")
		filters = {"status": ["in", ("Service Setup", "Pending")], "docstatus": ["<", 2], "depot": DEPOT}
		self.assertIsNone(_queue("cleaningIdle", "Cleaning Order", filters), "empty queue = no row")

		frappe.get_doc({"doctype": "Cleaning Order", "container": a, "status": "Pending"}).insert(
			ignore_permissions=True
		)
		row = _queue("cleaningIdle", "Cleaning Order", filters)
		self.assertEqual(row["count"], 1)
		self.assertEqual(row["ref"], a)
		self.assertIsNotNone(row["age"])

		frappe.get_doc({"doctype": "Cleaning Order", "container": b, "status": "Pending"}).insert(
			ignore_permissions=True
		)
		row = _queue("cleaningIdle", "Cleaning Order", filters)
		self.assertEqual(row["count"], 2)
		self.assertIsNone(row["ref"], "two items: the row counts, it does not pick a favourite")

	# --- auth guard --------------------------------------------------------
	def test_guest_is_rejected(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				get_home_summary()
		finally:
			frappe.set_user("Administrator")


# Dua branch, satu depot masing-masing: satu-satunya cara membuktikan bahwa angka Beranda
# adalah angka PENGGUNANYA adalah dengan menaruh pekerjaan di branch yang tidak dipegangnya.
BRANCH_A = "Home Scope Branch A"
BRANCH_B = "Home Scope Branch B"
DEPOT_A = "HSCPA"
DEPOT_B = "HSCPB"
SCOPED_USER = "home-scope-a@example.com"


class TestHomeSummaryIsScopedToTheUsersBranch(FrappeTestCase):
	"""Angka di Beranda = isi layar yang dibukanya, dan hanya untuk branch penggunanya.

	Dua hal yang gampang berselisih diam-diam, dan keduanya pernah:

	* **Branch.** Operator branch A tidak boleh menghitung pekerjaan branch B — sama seperti
	  lonceng notifikasi, yang sudah lama begitu (``notify._recipients``). Yang menjaganya
	  adalah ``user_branch.get_user_depots``, dipakai kartu maupun worklist.
	* **Angka vs isi.** Kartu menghitung dengan ``frappe.db.count`` sementara layarnya
	  memanggil worklist, jadi keduanya hanya cocok selama filternya sama. Sampai 2026-09-10
	  keduanya memang tidak cocok: worklist membuang order yang sudah "Mulai" ditekan orang
	  lain (``work_claim``, sudah dicabut) sedangkan kartunya tetap menghitungnya, dan kartu
	  "EIR diajukan review" menghitung EIR-In saja padahal daftarnya berisi In + Out.

	Angkanya PASTI, bukan delta seperti kelas di atas: branch-nya baru dibuat di sini, jadi
	tidak ada pekerjaan site lain yang bisa masuk hitungan.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls._wipe()
		for branch, depot in ((BRANCH_A, DEPOT_A), (BRANCH_B, DEPOT_B)):
			ensure_test_branch(branch)
			frappe.get_doc({
				"doctype": "Depot", "depot_code": depot,
				"depot_name": f"Home Scope Depot {depot}", "branch": branch,
			}).insert(ignore_permissions=True)
		cls.principal = ensure_test_customer(PRINCIPAL)
		# Akun lapangan yang dikunci ke branch A. Role-nya sengaja hanya role lapangan: yang
		# diuji adalah scope, dan role kantor akan memberinya menu yang bukan pokok soal.
		_user(SCOPED_USER, *TEAM_ROLES)
		user = frappe.get_doc("User", SCOPED_USER)
		user.set("branch", [{"branch": BRANCH_A}])
		user.save(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		cls._wipe()
		super().tearDownClass()

	@classmethod
	def _wipe(cls):
		cls._wipe_work()
		for depot in (DEPOT_A, DEPOT_B):
			frappe.db.delete("Depot", {"name": depot})
		if frappe.db.exists("User", SCOPED_USER):
			frappe.delete_doc("User", SCOPED_USER, ignore_permissions=True, force=True)
		for branch in (BRANCH_A, BRANCH_B):
			if frappe.db.exists("Branch", branch):
				frappe.delete_doc("Branch", branch, ignore_permissions=True, force=True)
		frappe.db.commit()

	def setUp(self):
		frappe.set_user("Administrator")
		# Per test, bukan per kelas: sebagian controller order melakukan commit sendiri, jadi
		# rollback bawaan FrappeTestCase tidak selalu menghapus fixture test sebelumnya — dan
		# angka di sini PASTI, bukan delta, sehingga satu baris sisa langsung membuatnya merah.
		self._wipe_work()

	def tearDown(self):
		frappe.set_user("Administrator")
		self._wipe_work()
		super().tearDown()

	@classmethod
	def _wipe_work(cls):
		names = frappe.get_all(
			"Container", filters={"container_no": ["like", "HSCP%"]}, pluck="name"
		)
		if not names:
			return
		for dt in ("Container Movement", "Container Activity", "Cleaning Order",
				   "Repair Order", "Inspection"):
			frappe.db.delete(dt, {"container": ["in", names]})
		frappe.db.delete("Container", {"name": ["in", names]})
		frappe.db.commit()

	# --- fixtures ---------------------------------------------------------
	def _container(self, no, depot):
		frappe.get_doc({
			"doctype": "Container", "container_no": no, "container_type": "ISO Tank",
			"status": "Available", "depot": depot, "principal": self.principal,
		}).insert(ignore_permissions=True)
		return no

	def _cleaning(self, no, depot, status="Pending"):
		return frappe.get_doc({
			"doctype": "Cleaning Order", "container": self._container(no, depot), "status": status,
		}).insert(ignore_permissions=True).name

	def _eir(self, no, depot, inspection_type="EIR-In", status="Draft"):
		# `depot` diisi tegas: Inspection tidak mengambilnya sendiri dari tangkinya (depot
		# sebuah EIR boleh berbeda dari master-nya — lihat ``eir._voucher_depot``), dan justru
		# kolom itulah yang menyaringnya ke branch penggunanya.
		doc = frappe.get_doc({
			"doctype": "Inspection", "container": self._container(no, depot),
			"inspection_type": inspection_type, "status": "Draft", "depot": depot,
		}).insert(ignore_permissions=True, ignore_mandatory=True)
		if status != "Draft":
			frappe.db.set_value("Inspection", doc.name, "status", status, update_modified=False)
		return doc.name

	def _summary(self, tiles):
		frappe.set_user(SCOPED_USER)
		try:
			return get_home_summary(tiles=tiles)["today"]
		finally:
			frappe.set_user("Administrator")

	def _as_scoped(self, fn, *args, **kwargs):
		frappe.set_user(SCOPED_USER)
		try:
			return fn(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	# --- branch -----------------------------------------------------------
	def test_the_other_branchs_work_is_not_counted_and_not_listed(self):
		"""Satu order di tiap branch. Yang dipegang penggunanya satu — di angkanya maupun di
		daftarnya."""
		mine = self._cleaning("HSCP0000001", DEPOT_A)
		theirs = self._cleaning("HSCP0000002", DEPOT_B)

		self.assertEqual(self._summary("cleaning")["cleaning_open"], 1)
		worklist = self._as_scoped(cleaning.list_open_cleaning_orders, page_length=0)
		self.assertEqual({r["name"] for r in worklist["items"]}, {mine})
		self.assertNotIn(theirs, {r["name"] for r in worklist["items"]})

	def test_a_second_branch_on_the_account_adds_its_work(self):
		""""Kecuali di-assign keduanya" — itu isi tabel Branch di User, bukan aturan lain."""
		self._cleaning("HSCP0000003", DEPOT_A)
		self._cleaning("HSCP0000004", DEPOT_B)
		self.assertEqual(self._summary("cleaning")["cleaning_open"], 1)

		user = frappe.get_doc("User", SCOPED_USER)
		user.set("branch", [{"branch": BRANCH_A}, {"branch": BRANCH_B}])
		user.save(ignore_permissions=True)
		try:
			self.assertEqual(self._summary("cleaning")["cleaning_open"], 2)
		finally:
			user.set("branch", [{"branch": BRANCH_A}])
			user.save(ignore_permissions=True)

	# --- angka vs isi -----------------------------------------------------
	def test_the_eir_tile_and_the_eir_worklist_agree(self):
		"""Termasuk EIR yang sudah ditekan "Mulai" oleh orang lain: sejak pagar klaim dicabut
		ia tetap di daftar semua orang, jadi kartunya pun tidak boleh menghitung lebih."""
		self._eir("HSCP0000010", DEPOT_A)
		started = self._eir("HSCP0000011", DEPOT_A)
		frappe.db.set_value(
			"Inspection", started,
			{"work_started_by": "Administrator", "work_started_on": now_datetime()},
			update_modified=False,
		)
		self._eir("HSCP0000012", DEPOT_B)  # branch lain — tidak masuk dua-duanya

		self.assertEqual(
			self._summary("eirOpen")["eir_open"],
			self._as_scoped(eir.list_pending_eirs, page_length=1)["total"],
		)
		self.assertEqual(self._summary("eirOpen")["eir_open"], 2)

	def test_the_review_tile_counts_eir_out_too(self):
		"""Kartunya membuka daftar "Diajukan Review", dan daftar itu berisi In + Out."""
		self._eir("HSCP0000020", DEPOT_A, status="Pending Review")
		self._eir("HSCP0000021", DEPOT_A, inspection_type="EIR-Out", status="Pending Review")
		self._eir("HSCP0000022", DEPOT_B, status="Pending Review")

		self.assertEqual(
			self._summary("eirReview")["eir_review"],
			self._as_scoped(eir.list_review_eirs, page_length=1)["total"],
		)
		self.assertEqual(self._summary("eirReview")["eir_review"], 2)

	def test_the_mr_tile_and_its_worklist_agree(self):
		container = self._container("HSCP0000030", DEPOT_A)
		frappe.get_doc({
			"doctype": "Repair Order", "container": container, "status": "In Progress",
			"billing_status": "Unbilled", "started_by": "Administrator",
		}).insert(ignore_permissions=True)
		other = self._container("HSCP0000031", DEPOT_B)
		frappe.get_doc({
			"doctype": "Repair Order", "container": other, "status": "In Progress",
			"billing_status": "Unbilled",
		}).insert(ignore_permissions=True)

		self.assertEqual(
			self._summary("mr")["mr_open"],
			self._as_scoped(mr.list_open_mr_orders, page_length=1)["total"],
		)
		self.assertEqual(self._summary("mr")["mr_open"], 1)
