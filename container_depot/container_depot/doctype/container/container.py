import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from container_depot.container_depot.container_status import GATE_OUT, PRESENT, container_open_orders
from container_depot.state_machine import assert_transition, stage_for_status


# What the system fills in on a tank once it exists: the three "(otomatis)" sections and the
# yard location (user, 2026-10-08). Typed in freely while the master is being registered; after
# that only the Administrator account changes them by hand — the form shows them as plain detail
# (``read_only_depends_on``) and :meth:`Container._guard_locked_fields` holds the same line.
LOCKED_FIELDS = (
	# Status Operasional
	"depot", "emkl", "shipper", "inventory_stage",
	# Riwayat Gate & Kargo
	"in_date", "out_date", "last_cargo", "ex_vessel", "storage_billed_until",
	# Referensi Order Lain
	"created_by_booking", "last_order_bongkar", "lift_on_booking", "target_lift_on",
	"target_survey_on", "target_urgent_on",
	# Letak Tank di Yard
	"current_location", "location_updated_on", "location_updated_by",
	"position_check_requested_on", "position_check_requested_by", "row", "bay", "tier", "yard_zone",
)


class Container(Document):
	def before_insert(self):
		"""A tank a PERSON registers is registered as ``Gate_Out`` — "known, not in my yard".

		Every other status is a fact only the system can know: ``Booked`` means a Tank In
		booking holds it, ``In_Depot`` / ``Available`` that it came through the gate. A
		master born ``Booked`` by hand (the form's Status was editable) sat in the list as
		"Dipesan" with no booking behind it, reserved by nobody and refused by the next.

		The form locks the field on a new doc (``read_only_depends_on``); this holds the same
		line for REST and Data Import. System code passes ``ignore_permissions`` (a booking's
		pre-arrival master, the gate API) or ``in_status_automation``, and keeps its status.
		"""
		if self.flags.ignore_permissions or frappe.flags.in_status_automation or frappe.flags.in_test:
			return
		self.status = GATE_OUT

	def validate(self):
		# Container number is required (enforced by the field) but not length-checked —
		# real depot data carries non-ISO / short numbers, so only presence is required.

		# Guard manual status transitions against the canonical state machine.
		# Internal automation (Repair/Cleaning/Inspection controllers) and
		# migrations bypass via frappe.flags.in_status_automation.
		if not self.is_new():
			self._guard_locked_fields()
		if not self.is_new() and self.has_value_changed("status"):
			self._guard_manual_status()
			previous = self.get_doc_before_save()
			assert_transition(previous.status if previous else None, self.status)

		self._guard_deactivation()

	def _guard_manual_status(self):
		"""By hand, only the Administrator account may change a tank's status (user, 2026-10-05).

		The form locks the field for everyone else (``read_only_depends_on``); this holds the
		same line for REST, list bulk-edit and Data Import. System code passes
		``ignore_permissions`` or ``in_status_automation`` and is never refused.
		"""
		if self.flags.ignore_permissions or frappe.flags.in_status_automation:
			return
		if frappe.session.user == "Administrator":
			return
		frappe.throw(
			_("Status container hanya bisa diubah manual oleh akun Administrator."),
			frappe.PermissionError,
			title=_("Status Terkunci"),
		)

	def _guard_locked_fields(self):
		"""By hand, only the Administrator account changes what the system fills in (user,
		2026-10-08) — REST, list bulk-edit and Data Import included. System code passes
		``ignore_permissions`` or ``in_status_automation`` and is never refused."""
		if self.flags.ignore_permissions or frappe.flags.in_status_automation:
			return
		if frappe.session.user == "Administrator":
			return
		changed = [f for f in LOCKED_FIELDS if self.has_value_changed(f)]
		if changed:
			frappe.throw(
				_("Data otomatis container hanya bisa diubah oleh akun Administrator: {0}.").format(
					", ".join(_(self.meta.get_label(f)) for f in changed)
				),
				frappe.PermissionError,
				title=_("Data Terkunci"),
			)

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


# Riwayat Order tab: (label, doctype, link table, link parenttype, date field, status field).
# The link table is how the order names this tank — the order itself, or the row it holds it on.
_HISTORY = (
	("Booking", "Container Booking", "Container Booking Item", "Container Booking", "plan_date", "booking_status"),
	("Bon Bongkar", "Order Bongkar", "Container Booking Item", "Order Bongkar", "tanggal_bongkar", "order_status"),
	("Bon Muat", "Order Muat", "Order Container Item", "Order Muat", "tanggal_muat", "order_status"),
	("EIR", "Inspection", None, None, "eir_date", "status"),
	("Leak Check", "Leak Check", None, None, "recorded_on", "status"),
	("Survey", "Survey Order", "Survey Order Tank", "Survey Order", "survey_date", None),
	("Cleaning", "Cleaning Order", None, None, "plan_date", "status"),
	("M&R", "Repair Order", None, None, "plan_date", "status"),
)
_DONE = {"Completed", "Submitted", "Survey Done"}


@frappe.whitelist()
def order_history(container: str) -> list:
	"""Every order ever raised for this tank, newest first, for the master's Riwayat Order tab.

	Dated by the order's own date (``plan_date``, Tanggal Bongkar/Muat, ``eir_date``…), never
	its creation; voided ones are listed too, marked ``cancelled``. A doctype the reader may
	not open is left out rather than leaked."""
	frappe.has_permission("Container", "read", doc=container, throw=True)
	out = []
	for kind, doctype, table, parenttype, date_field, status_field in _HISTORY:
		if not frappe.has_permission(doctype, "read"):
			continue
		meta = frappe.get_meta(doctype)
		if table:
			names = frappe.get_all(table, filters={"container": container, "parenttype": parenttype}, pluck="parent", distinct=True)
			filters = {"name": ["in", names or [""]]}
		else:
			filters = {"container": container}
		fields = ["name", "docstatus", "creation", f"{date_field} as on"]
		for f in (status_field, "reff_doc", "inspection_type", "job_type", "direction"):
			if f and meta.has_field(f):
				fields.append(f"{f} as {'status' if f == status_field else f}")
		for r in frappe.get_all(doctype, filters=filters, fields=fields):
			status = r.get("status")
			if doctype == "Survey Order":
				status = frappe.db.get_value(table, {"parent": r.name, "container": container}, "status")
			label = {
				"Inspection": r.get("inspection_type"),
				"Repair Order": "Periodic Test" if r.get("job_type") == "Periodic Test" else kind,
				"Container Booking": f"{kind} {r.get('direction') or ''}".strip(),
			}.get(doctype) or kind
			out.append({
				"kind": label, "doctype": doctype, "name": r.name, "status": status,
				"on": str(r.on or r.creation)[:10], "reff_doc": r.get("reff_doc"),
				"cancelled": r.docstatus == 2 or status == "Cancelled",
				"done": status in _DONE,
				"_sort": str(r.on or r.creation),
			})
	out.sort(key=lambda r: r.pop("_sort"), reverse=True)
	return out


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
