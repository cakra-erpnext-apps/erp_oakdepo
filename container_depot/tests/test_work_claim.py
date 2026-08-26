"""Klaim pekerjaan: yang menekan "Mulai" duluan yang memegang order itu.

Satu tangki tidak boleh dikerjakan dua orang. Sejak "Mulai" ditekan, EIR / Cleaning Order /
M&R itu hilang dari worklist PWA operator lain, dan kalau mereka masuk lewat tautan
notifikasi endpoint-nya menolak dengan ``ClaimedByAnother`` (PWA menampilkan toast lalu
memulangkan mereka). Desk tidak disentuh sama sekali — pengawasan justru butuh melihat semua.

Yang dijaga tes ini, per menu: order yang belum diklaim tetap terlihat semua orang, order
yang sudah diklaim hanya terlihat pemegangnya, role bypass tetap melihat semuanya, dan
endpoint buka/detail menolak orang lain.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from container_depot.container_depot import cleaning, eir, mr
from container_depot.container_depot.exceptions import ClaimedByAnother
from container_depot.tests.test_eir import _make_container

WORKER = "claim-worker@example.com"
OTHER = "claim-other@example.com"
# Role lapangan, bukan role bypass: dua akun ini harus punya write di ketiga doctype supaya
# sampai ke pagar klaim, tapi tidak boleh lolos darinya (lihat work_claim.CLAIM_BYPASS_ROLES).
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


class TestWorkClaim(FrappeTestCase):
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

	# --- EIR -------------------------------------------------------------------
	def test_an_unstarted_eir_is_on_everyones_worklist(self):
		"""Klaim baru terjadi saat "Mulai" — sebelum itu worklist tetap milik bersama."""
		name = self._eir(self._container("CLAIMEIR0000001"))
		for user in (WORKER, OTHER):
			frappe.set_user(user)
			self.assertIn(name, self._pending_eirs(), f"{user} kehilangan EIR yang belum dimulai")

	def test_a_started_eir_leaves_the_other_operators_worklist(self):
		name = self._eir(
			self._container("CLAIMEIR0000002"),
			work_started_by=WORKER, work_started_on=now_datetime(),
		)
		frappe.set_user(WORKER)
		self.assertIn(name, self._pending_eirs(), "pemegangnya harus tetap melihat pekerjaannya")
		frappe.set_user(OTHER)
		self.assertNotIn(name, self._pending_eirs())

	def test_opening_a_started_eir_from_a_notification_link_is_refused(self):
		"""Worklist sudah menyembunyikannya, tapi bel dikirim ke seluruh role — jadi
		endpoint-nya sendiri yang harus menolak, dan menyebut siapa pemegangnya."""
		name = self._eir(
			self._container("CLAIMEIR0000003"),
			work_started_by=WORKER, work_started_on=now_datetime(),
		)
		frappe.set_user(OTHER)
		with self.assertRaises(ClaimedByAnother) as caught:
			eir.open_draft_by_name(name)
		self.assertIn(WORKER.split("@")[0], str(caught.exception).lower())

	def test_a_second_mulai_on_the_same_eir_is_refused(self):
		name = self._eir(
			self._container("CLAIMEIR0000004"),
			work_started_by=WORKER, work_started_on=now_datetime(),
		)
		frappe.set_user(OTHER)
		with self.assertRaises(ClaimedByAnother):
			eir.start_eir(name)

	def test_administrator_still_sees_and_opens_claimed_work(self):
		"""Bypass: tanpa ini tidak ada yang bisa membereskan job yang macet di lapangan."""
		name = self._eir(
			self._container("CLAIMEIR0000005"),
			work_started_by=WORKER, work_started_on=now_datetime(),
		)
		frappe.set_user("Administrator")
		self.assertIn(name, self._pending_eirs())

	# --- Cleaning --------------------------------------------------------------
	def test_a_started_cleaning_order_leaves_the_other_operators_worklist(self):
		container = self._container("CLAIMCLN0000001")
		co = frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": "In_Progress",
			"assigned_to": WORKER,
		}).insert(ignore_permissions=True)

		frappe.set_user(WORKER)
		self.assertIn(co.name, {r["name"] for r in cleaning.list_open_cleaning_orders(page_length=0)["items"]})
		frappe.set_user(OTHER)
		self.assertNotIn(co.name, {r["name"] for r in cleaning.list_open_cleaning_orders(page_length=0)["items"]})
		with self.assertRaises(ClaimedByAnother):
			cleaning.get_cleaning_order_detail(co.name)

	def test_a_cleaning_order_sent_for_review_is_no_longer_claimed(self):
		"""Selesai dari lapangan = lepas dari tangan operator: siapa pun di branch boleh
		membacanya (dan menariknya kembali), persis seperti sebelum ada klaim."""
		container = self._container("CLAIMCLN0000002")
		co = frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": "Pending Review",
			"assigned_to": WORKER,
		}).insert(ignore_permissions=True)
		frappe.set_user(OTHER)
		self.assertEqual(cleaning.get_cleaning_order_detail(co.name)["name"], co.name)

	# --- M&R -------------------------------------------------------------------
	def test_a_started_mr_leaves_the_other_operators_worklist(self):
		container = self._container("CLAIMMR00000001")
		ro = frappe.get_doc({
			"doctype": "Repair Order", "container": container, "status": "In Progress",
			"billing_status": "Unbilled", "started_by": WORKER,
		}).insert(ignore_permissions=True)

		frappe.set_user(WORKER)
		self.assertIn(ro.name, {r["name"] for r in mr.list_open_mr_orders(page_length=0)["items"]})
		frappe.set_user(OTHER)
		self.assertNotIn(ro.name, {r["name"] for r in mr.list_open_mr_orders(page_length=0)["items"]})
		self.assertNotIn(ro.name, {r["name"] for r in mr.list_mr_execution(page_length=0)["items"]})
		with self.assertRaises(ClaimedByAnother):
			mr.get_mr_order_detail(ro.name)

	def test_mulai_stamps_who_is_working_the_mr(self):
		"""``started_by`` diisi dari yang menekan Mulai — itu yang jadi klaimnya, dan itu
		juga yang dibaca Desk di blok "Sistem"."""
		container = self._container("CLAIMMR00000002")
		ro = frappe.get_doc({
			"doctype": "Repair Order", "container": container, "status": "Pending",
			"billing_status": "Unbilled",
		}).insert(ignore_permissions=True)

		frappe.set_user(WORKER)
		mr.start_repair(ro.name)
		self.assertEqual(frappe.db.get_value("Repair Order", ro.name, "started_by"), WORKER)
		frappe.set_user(OTHER)
		with self.assertRaises(ClaimedByAnother):
			mr.start_repair(ro.name)
