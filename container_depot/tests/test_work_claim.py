"""Pekerjaan lapangan dipakai BERSAMA — menekan "Mulai" tidak menyembunyikannya dari siapa pun.

Sampai 2026-09-10 modul ``work_claim`` mengunci order ke orang yang menekan "Mulai": order itu
hilang dari worklist PWA operator lain, dan endpoint-nya menolak mereka dengan
``ClaimedByAnother``. Pagar itu dicabut atas permintaan depo — satu tangki memang sering
dikerjakan bergantian (shift berganti, satu orang memfoto sementara yang lain mengisi
checklist), dan pekerjaan yang lenyap dari layar rekan jauh lebih mahal daripada dua orang yang
kebetulan membuka form yang sama.

Berkas ini sekarang menjaga arah sebaliknya, dan itu sengaja tetap ada tesnya: yang hilang dari
worklist orang lain adalah regresi, bukan fitur.

Yang TIDAK ikut dicabut, dan ikut dijaga di sini:

* **Capnya**. ``work_started_by`` / ``assigned_to`` / ``started_by`` tetap diisi oleh yang
  menekan Mulai duluan dan tidak ditimpa penekan kedua — itu yang dibaca Desk ("siapa yang
  mengerjakan"), yang jadi ``inspector`` sebuah EIR, dan yang menghitung lama pekerjaan.
* **Branch**. Yang membatasi siapa melihat apa sekarang tinggal satu: depot order itu harus ada
  di branch penggunanya (``user_branch.get_user_depots``). Lihat
  ``test_home_summary.TestHomeSummaryIsScopedToTheUsersBranch`` untuk sisi angkanya.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from container_depot.container_depot import cleaning, eir, mr
from container_depot.tests.test_eir import _make_container

WORKER = "claim-worker@example.com"
OTHER = "claim-other@example.com"
# Role lapangan, bukan role kantor: dua akun ini harus punya write di ketiga doctype supaya
# benar-benar sampai ke endpoint-nya, tanpa hak istimewa apa pun yang bisa menutupi hasilnya.
TEAM_ROLES = ("Team EIR", "Team Cleaning", "Team Repair")


def _user(email, *roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc({
			"doctype": "User", "email": email, "first_name": email.split("@")[0],
			"send_welcome_email": 0, "user_type": "System User",
		}).insert(ignore_permissions=True)
	doc = frappe.get_doc("User", email)
	if roles:
		doc.add_roles(*roles)
	return email


class TestFieldWorkIsShared(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._containers = []
		_user(WORKER, *TEAM_ROLES)
		_user(OTHER, *TEAM_ROLES)

	def tearDown(self):
		frappe.set_user("Administrator")
		for c in self._containers:
			frappe.db.delete("Repair Order", {"container": c})
			frappe.db.delete("Cleaning Order", {"container": c})
			frappe.db.delete("Inspection", {"container": c})
			frappe.db.delete("Container Activity", {"container": c})
			frappe.db.delete("Container", {"name": c})
		for email in (WORKER, OTHER):
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, ignore_permissions=True, force=True)
		frappe.db.commit()
		super().tearDown()

	def _container(self, cno):
		name = _make_container(cno)
		self._containers.append(name)
		return name

	def _eir(self, container, **kw):
		doc = frappe.get_doc({
			"doctype": "Inspection", "container": container, "inspection_type": "EIR-In",
			"status": "Draft", **kw,
		}).insert(ignore_permissions=True, ignore_mandatory=True)
		return doc.name

	@staticmethod
	def _pending_eirs():
		return {r["name"] for r in eir.list_pending_eirs(page_length=0)["items"]}

	@staticmethod
	def _editors(doctype, name) -> list:
		"""Siapa saja yang menulis ke dokumen ini, urut. Baris Version-lah jejak resminya —
		ketiga doctype ini ``track_changes``, dan tiap ``doc.save()`` menulis satu baris berisi
		pengubah + field yang berubah."""
		return [
			v.owner
			for v in frappe.get_all(
				"Version",
				filters={"ref_doctype": doctype, "docname": name},
				fields=["owner"],
				order_by="creation asc",
			)
		]

	# --- jejak siapa yang mengubah ---------------------------------------------
	def test_every_edit_records_who_made_it(self):
		"""Pasangan wajib dari pekerjaan yang dipakai bersama.

		Begitu dua orang boleh menulis ke order yang sama, "siapa yang mengubah ini" berubah
		dari pertanyaan iseng menjadi pertanyaan yang harus ada jawabannya — dan jawabannya
		tidak boleh bergantung pada ingatan orang. Tiap simpan lewat ``doc.save()`` menulis
		satu baris Version atas nama pengubahnya, dan ``modified_by`` menunjuk yang terakhir.

		Dijaga di sini karena godaan mengganti ``doc.save()`` dengan ``frappe.db.set_value``
		(lebih ringan, dan sekilas setara) akan menghapus jejak itu tanpa satu pun test lain
		berubah warna.
		"""
		container = self._container("CLAIMAUD0000001")
		insp = self._eir(container, work_started_by=WORKER, work_started_on=now_datetime())
		co = frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": "In_Progress",
			"assigned_to": WORKER, "cleaning_start": now_datetime(),
		}).insert(ignore_permissions=True)
		ro = frappe.get_doc({
			"doctype": "Repair Order", "container": container, "status": "In Progress",
			"billing_status": "Unbilled", "started_by": WORKER,
		}).insert(ignore_permissions=True)

		# ``Document._save`` mematikan penulisan Version selama test (`flags.ignore_version =
		# frappe.in_test`), jadi tanpa ini yang diuji hanyalah kolom ``modified_by`` — separuh
		# dari jejak, dan bukan separuh yang menyimpan APA yang berubah. Dinyalakan hanya
		# selama simpanannya berlangsung.
		with patch.object(frappe, "in_test", False):
			frappe.set_user(WORKER)
			eir.save_draft(inspection=insp, remarks="isi pertama")
			cleaning.save_cleaning_order(cleaning_order=co.name, remarks="cuci awal")
			mr.save_mr_order(repair_order=ro.name, remarks="mulai las")

			frappe.set_user(OTHER)
			eir.save_draft(inspection=insp, remarks="dilanjut rekan")
			cleaning.save_cleaning_order(cleaning_order=co.name, remarks="dilanjut rekan")
			mr.save_mr_order(repair_order=ro.name, remarks="dilanjut rekan")

		frappe.set_user("Administrator")
		for doctype, name in (
			("Inspection", insp), ("Cleaning Order", co.name), ("Repair Order", ro.name)
		):
			with self.subTest(doctype=doctype):
				editors = self._editors(doctype, name)
				self.assertIn(WORKER, editors, f"{doctype}: suntingan pertama tidak tercatat")
				self.assertEqual(editors[-1], OTHER, f"{doctype}: pengubah terakhir salah")
				self.assertEqual(
					frappe.db.get_value(doctype, name, "modified_by"),
					OTHER,
					f"{doctype}: modified_by tidak ikut pindah",
				)

	def test_the_form_shows_the_colleague_who_touched_it_last(self):
		"""Catatan yang hanya ada di timeline Desk tidak menolong yang sedang berdiri di
		samping tangki, jadi ketiga detail membawanya sendiri — dengan NAMA, bukan login."""
		container = self._container("CLAIMAUD0000002")
		co = frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": "In_Progress",
			"assigned_to": WORKER, "cleaning_start": now_datetime(),
		}).insert(ignore_permissions=True)
		ro = frappe.get_doc({
			"doctype": "Repair Order", "container": container, "status": "In Progress",
			"billing_status": "Unbilled", "started_by": WORKER,
		}).insert(ignore_permissions=True)
		full_name = frappe.db.get_value("User", WORKER, "full_name")

		frappe.set_user(WORKER)
		cleaning.save_cleaning_order(cleaning_order=co.name, remarks="cuci awal")
		mr.save_mr_order(repair_order=ro.name, remarks="mulai las")

		frappe.set_user(OTHER)
		wash = cleaning.get_cleaning_order_detail(co.name)
		job = mr.get_mr_order_detail(ro.name)
		for label, detail in (("cleaning", wash), ("mr", job)):
			with self.subTest(detail=label):
				self.assertEqual(detail["updated_by"], WORKER)
				self.assertEqual(detail["updated_by_name"], full_name)
				self.assertTrue(detail["updated_on"])

	# --- EIR -------------------------------------------------------------------
	def test_an_eir_someone_started_stays_on_everyones_worklist(self):
		"""Regresi yang dijaga berkas ini: dulu baris ini lenyap dari layar rekan."""
		name = self._eir(
			self._container("CLAIMEIR0000002"),
			work_started_by=WORKER, work_started_on=now_datetime(),
		)
		for user in (WORKER, OTHER):
			frappe.set_user(user)
			self.assertIn(name, self._pending_eirs(), f"{user} kehilangan EIR yang sedang dikerjakan")

	def test_a_colleague_may_open_an_eir_that_is_already_being_worked(self):
		"""Tautan notifikasi dikirim ke seluruh role, dan sekarang memang boleh dibuka —
		termasuk dari HP kedua yang memfoto tangki yang sama."""
		name = self._eir(
			self._container("CLAIMEIR0000003"),
			work_started_by=WORKER, work_started_on=now_datetime(),
		)
		frappe.set_user(OTHER)
		self.assertEqual(eir.open_draft_by_name(name)["inspection"], name)

	def test_the_worklist_row_says_who_is_already_inside(self):
		"""Pengganti pagar yang dicabut. Barisnya tetap ada di daftar semua orang — dan
		menyebut nama pemegangnya, karena "sedang dikerjakan" tanpa OLEH SIAPA justru
		mengundang orang kedua masuk ke form yang sama tanpa tahu.

		Namanya, bukan login-nya: alamat email tidak menjawab pertanyaan itu dari jarak satu
		meter di lapangan.
		"""
		name = self._eir(
			self._container("CLAIMEIR0000005"),
			work_started_by=WORKER, work_started_on=now_datetime(),
		)
		full_name = frappe.db.get_value("User", WORKER, "full_name")
		frappe.set_user(OTHER)
		row = next(r for r in eir.list_pending_eirs(page_length=0)["items"] if r["name"] == name)
		self.assertEqual(row["started_by_name"], full_name)

	def test_the_cleaning_and_mr_rows_say_it_too(self):
		"""Aturan yang sama untuk ketiga worklist — kalau tidak, hanya satu tim yang tahu."""
		co = frappe.get_doc({
			"doctype": "Cleaning Order", "container": self._container("CLAIMCLN0000004"),
			"status": "In_Progress", "assigned_to": WORKER,
		}).insert(ignore_permissions=True)
		ro = frappe.get_doc({
			"doctype": "Repair Order", "container": self._container("CLAIMMR00000003"),
			"status": "In Progress", "billing_status": "Unbilled", "started_by": WORKER,
		}).insert(ignore_permissions=True)
		full_name = frappe.db.get_value("User", WORKER, "full_name")

		frappe.set_user(OTHER)
		wash = next(
			r for r in cleaning.list_open_cleaning_orders(page_length=0)["items"]
			if r["name"] == co.name
		)
		self.assertEqual(wash["assigned_to_name"], full_name)
		job = next(
			r for r in mr.list_mr_execution(page_length=0)["items"] if r["name"] == ro.name
		)
		self.assertEqual(job["started_by_name"], full_name)

	def test_a_second_mulai_keeps_the_first_starters_stamp(self):
		"""Boleh ditekan, tapi tidak menulis ulang siapa dan sejak kapan: cap itu yang jadi
		``inspector`` EIR-nya dan yang menghitung lama pemeriksaan."""
		started = now_datetime()
		name = self._eir(
			self._container("CLAIMEIR0000004"),
			work_started_by=WORKER, work_started_on=started,
		)
		frappe.set_user(OTHER)
		eir.start_eir(name)
		row = frappe.db.get_value(
			"Inspection", name, ["work_started_by", "work_started_on"], as_dict=True
		)
		self.assertEqual(row.work_started_by, WORKER)
		self.assertEqual(row.work_started_on, started)

	# --- Cleaning --------------------------------------------------------------
	def test_a_cleaning_order_being_washed_stays_visible_and_openable(self):
		container = self._container("CLAIMCLN0000001")
		co = frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": "In_Progress",
			"assigned_to": WORKER,
		}).insert(ignore_permissions=True)

		for user in (WORKER, OTHER):
			frappe.set_user(user)
			names = {r["name"] for r in cleaning.list_open_cleaning_orders(page_length=0)["items"]}
			self.assertIn(co.name, names, f"{user} kehilangan cuci yang sedang berjalan")
		frappe.set_user(OTHER)
		self.assertEqual(cleaning.get_cleaning_order_detail(co.name)["name"], co.name)

	def test_a_second_mulai_does_not_take_the_wash_over(self):
		container = self._container("CLAIMCLN0000003")
		co = frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": "In_Progress",
			"assigned_to": WORKER, "cleaning_start": now_datetime(),
		}).insert(ignore_permissions=True)
		frappe.set_user(OTHER)
		cleaning.start_cleaning(co.name)
		self.assertEqual(frappe.db.get_value("Cleaning Order", co.name, "assigned_to"), WORKER)

	def test_a_cleaning_order_sent_for_review_stays_readable(self):
		"""Selesai dari lapangan = siapa pun di branch boleh membacanya (dan menariknya
		kembali) — dulu pun begitu, dan itu tidak berubah."""
		container = self._container("CLAIMCLN0000002")
		co = frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": "Pending Review",
			"assigned_to": WORKER,
		}).insert(ignore_permissions=True)
		frappe.set_user(OTHER)
		self.assertEqual(cleaning.get_cleaning_order_detail(co.name)["name"], co.name)

	# --- M&R -------------------------------------------------------------------
	def test_an_mr_in_progress_stays_on_every_worklist(self):
		container = self._container("CLAIMMR00000001")
		ro = frappe.get_doc({
			"doctype": "Repair Order", "container": container, "status": "In Progress",
			"billing_status": "Unbilled", "started_by": WORKER,
		}).insert(ignore_permissions=True)

		for user in (WORKER, OTHER):
			frappe.set_user(user)
			self.assertIn(ro.name, {r["name"] for r in mr.list_open_mr_orders(page_length=0)["items"]})
			self.assertIn(ro.name, {r["name"] for r in mr.list_mr_execution(page_length=0)["items"]})
		frappe.set_user(OTHER)
		self.assertEqual(mr.get_mr_order_detail(ro.name)["name"], ro.name)

	def test_mulai_stamps_who_started_the_mr_and_a_second_press_is_a_no_op(self):
		"""Penekan kedua tidak ditolak dan tidak mengubah apa pun — dulu ia dapat
		``ClaimedByAnother``, lalu (tanpa pagar itu) akan dapat "teruskan ke team dulu",
		yang sama-sama bukan jawaban untuk job yang jelas-jelas sedang berjalan."""
		container = self._container("CLAIMMR00000002")
		ro = frappe.get_doc({
			"doctype": "Repair Order", "container": container, "status": "Pending",
			"billing_status": "Unbilled",
		}).insert(ignore_permissions=True)

		frappe.set_user(WORKER)
		mr.start_repair(ro.name)
		self.assertEqual(frappe.db.get_value("Repair Order", ro.name, "started_by"), WORKER)

		frappe.set_user(OTHER)
		self.assertEqual(mr.start_repair(ro.name)["status"], "In Progress")
		self.assertEqual(frappe.db.get_value("Repair Order", ro.name, "started_by"), WORKER)
