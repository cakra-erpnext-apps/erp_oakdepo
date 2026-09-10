import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from container_depot.container_depot.container_status import PRESENT, container_open_orders
from container_depot.state_machine import assert_transition, stage_for_status


class Container(Document):
	def validate(self):
		# Container number is required (enforced by the field) but not length-checked —
		# real depot data carries non-ISO / short numbers, so only presence is required.

		# Guard manual status transitions against the canonical state machine.
		# Internal automation (Repair/Cleaning/Inspection controllers) and
		# migrations bypass via frappe.flags.in_status_automation.
		if not self.is_new() and self.has_value_changed("status"):
			previous = self.get_doc_before_save()
			assert_transition(previous.status if previous else None, self.status)

		self._guard_deactivation()

	def _guard_deactivation(self):
		"""Refuse to retire a tank the depot is still holding or still working on.

		``is_active`` is the archive flag: a tank sold, scrapped or otherwise out of the
		fleet stops appearing in the booking / plan / import pickers while every record it
		ever carried stays exactly where it is. Deleting it is not the alternative — its
		EIRs, orders and invoices all point here.

		So it may only be switched off once the tank is genuinely finished: out of the yard
		(not ``In_Depot`` / ``Available``), carrying no open work, and promised to nobody.
		Retiring a tank that is physically sitting on the ground would take it out of every
		picker while the depot still has to gate it out; retiring one with an open Cleaning
		/ M&R order would strand that order on a tank nobody can select
		again; and retiring one a live Container Booking still names would let it be gated
		in tomorrow on a booking made yesterday — the order gate cannot catch that, because
		it only fires when a container is newly put on a document.

		Only ever checked when the flag actually changes to off, so a retired tank stays
		editable — correcting its spec afterwards must not re-run this. Switching it back
		on is always allowed: that is how a mistake is undone.
		"""
		if self.is_active or self.is_new() or not self.has_value_changed("is_active"):
			return
		blockers = []
		if self.status in PRESENT:
			blockers.append(
				_("masih ada di depo (status {0}) — gate-out dulu").format(self.status)
			)
		# Name the work rather than just refusing: "not allowed" sends the operator hunting,
		# the order number is what they can actually go and finish.
		for order in container_open_orders(self.name):
			blockers.append(
				_("{0} {1} ({2}) belum selesai").format(
					order.get("label") or order.get("doctype"), order.get("name"), order.get("status") or "-"
				)
			)
		# A booking is not "open work" — container_open_orders deliberately counts only the
		# jobs done ON a tank — so it has to be asked for separately. Anything not cancelled
		# counts, draft included: a draft booking is a tank someone is in the middle of
		# promising to a customer.
		for booking in frappe.get_all(
			"Container Booking Item",
			filters={"container": self.name, "docstatus": ["<", 2]},
			fields=["parent"],
			distinct=True,
		):
			blockers.append(
				_("masih tercantum di Container Booking {0}").format(booking.parent)
			)
		if blockers:
			frappe.throw(
				_("Container {0} belum bisa dinonaktifkan:").format(self.container_no or self.name)
				+ "<br>• "
				+ "<br>• ".join(blockers),
				title=_("Tank Masih Terpakai"),
			)

	def before_save(self):
		"""Auto-format container number + keep the monitoring stage in step with the
		raw status (every ORM save: gate entry, inspection, cleaning, repair, release)."""
		if self.container_no:
			self.container_no = self.container_no.upper()
		self.inventory_stage = stage_for_status(self.status)

	def on_update(self):
		"""Audit-trail: log a Container Movement row whenever ``status`` changes.

		Skipped when the save was *caused* by a Container Movement (avoids the
		Movement -> Container -> Movement loop), and when the new value is the
		same as the previous one (no-op save).
		"""
		if getattr(frappe.flags, "in_container_movement", False):
			return
		if not self.has_value_changed("status"):
			return
		previous = self.get_doc_before_save()
		from_status = previous.status if previous else None
		frappe.get_doc({
			"doctype": "Container Movement",
			"container": self.name,
			"event_type": "Status",
			"movement_timestamp": now_datetime(),
			"moved_by": frappe.session.user or "Administrator",
			"from_status": from_status,
			"to_status": self.status,
		}).insert(ignore_permissions=True)

		# The same transition opens or closes a storage visit. Derived from the gate
		# records rather than from this event, so it self-heals; see storage_charge.sync.
		from container_depot import storage_charge

		storage_charge.on_container_status_change(self)


@frappe.whitelist()
def seal_history(container: str) -> list:
	"""The seal numbers this tank left the depot with, newest release first.

	Seals are fitted and written down on the EIR-Out at the moment the tank is released, so
	that document IS the record — the master keeps no seal fields of its own. It used to carry
	five (manhole / airline / bottom outlet / top discharge / vapour valve), but nothing ever
	wrote them: a tank is sealed once per release, so a single set on the master could only
	show the LAST one, and would read as current long after the tank came back and was
	unsealed. Dropped in ``v0_50.drop_container_seal_fields``.

	Only submitted EIR-Outs count — a draft's seal numbers are still being typed. Ordered by
	the EIR date the surveyor recorded (``creation`` only breaks ties): a backdated EIR-Out
	entered late must not jump to the top of what reads as a chronological history.
	"""
	frappe.has_permission("Container", "read", doc=container, throw=True)
	if not frappe.has_permission("Inspection", "read"):
		return []
	eirs = frappe.get_all(
		"Inspection",
		filters={"container": container, "inspection_type": "EIR-Out", "docstatus": 1},
		fields=["name", "eir_date", "out_outcome"],
		order_by="eir_date desc, creation desc",
	)
	if not eirs:
		return []
	by_eir = {}
	for row in frappe.get_all(
		"Inspection Seal",
		filters={"parent": ["in", [e.name for e in eirs]], "parenttype": "Inspection"},
		fields=["parent", "seal_no", "remarks"],
		order_by="idx asc",
	):
		by_eir.setdefault(row.parent, []).append({"seal_no": row.seal_no, "remarks": row.remarks})
	# An EIR-Out with no seal row has nothing to say here — this is the seal history, not the
	# release history (the EIRs themselves are already listed on their own doctype).
	return [
		{
			"eir": e.name,
			"eir_date": str(e.eir_date) if e.eir_date else None,
			"outcome": e.out_outcome,
			"seals": by_eir[e.name],
		}
		for e in eirs
		if by_eir.get(e.name)
	]


@frappe.whitelist(methods=["POST"])
def set_last_test_date(container: str, last_test_date=None) -> dict:
	"""Catat / perbaiki tanggal uji berkala terakhir tank, dari layar mana pun.

	Satu nilai, satu rumah. Setiap layar yang menulis "Tgl. Tes Terakhir" — EIR, Cleaning
	Order, M&R, cetakan EIR, Register Periodic Test — membaca ``Container.last_test_date``,
	jadi tanggal yang dibetulkan sambil membuka order cuci adalah tanggal yang dicetak EIR
	berikutnya. Tidak ada salinan per-order: salinan berarti satu tank punya dua jawaban.

	Uji yang dikerjakan DI SINI mengisi field ini sendiri — lihat
	``RepairOrder._stamp_last_test_date``. Fungsi ini separuh yang lain: uji di vendor atau
	di depo lain, yang tidak akan pernah punya dokumennya di sistem ini.

	Disimpan dengan ``ignore_permissions`` dengan alasan yang sama seperti
	``eir._apply_tank_master``: role lapangan memegang Container READ (§8.1), dan yang
	diberikan di sini SATU field atas tank yang ada di branch pemanggil sendiri — bukan
	write penuh atas master yang juga menyimpan status dan depot. ``track_changes`` di
	Container yang menyimpan siapa mengubah apa, dari nilai berapa.
	"""
	from frappe.utils import getdate, today

	from container_depot.container_depot.user_branch import assert_in_user_branch

	container = (container or "").strip()
	if not container:
		frappe.throw(_("Container wajib diisi."))
	frappe.has_permission("Container", "read", doc=container, throw=True)
	doc = frappe.get_doc("Container", container)
	assert_in_user_branch(depot=doc.depot)

	# Mengosongkan tidak lewat sini. Dari sebuah order, satu-satunya alasan menyentuh field
	# ini adalah karena orangnya TAHU tanggalnya; menghapus tanggal uji tank adalah keputusan
	# master yang tempatnya di form Container.
	if not last_test_date:
		frappe.throw(_("Tanggal uji wajib diisi."))
	tested = getdate(last_test_date)
	if tested > getdate(today()):
		frappe.throw(_("Tanggal uji tidak boleh di masa depan."))
	# Salah ketik tahun yang paling sering: uji yang jatuh sebelum tank-nya dibuat. Hanya
	# diperiksa kalau tanggal buatnya memang ada di master.
	if doc.manufacture_date and tested < getdate(doc.manufacture_date):
		frappe.throw(
			_("Tanggal uji ({0}) lebih awal dari tanggal pembuatan tank ({1}).").format(
				frappe.format(tested, "Date"), frappe.format(doc.manufacture_date, "Date")
			)
		)

	current = getdate(doc.last_test_date) if doc.last_test_date else None
	# Menyimpan nilai yang sama akan menulis baris Version yang tidak mengatakan apa-apa.
	if current != tested:
		doc.last_test_date = tested
		doc.save(ignore_permissions=True)
	return {"success": True, "container": doc.name, "last_test_date": str(tested)}
