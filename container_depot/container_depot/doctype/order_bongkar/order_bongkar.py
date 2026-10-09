import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, now_datetime

from container_depot.container_depot.doctype.container_booking.container_booking import (
	_find_booking_conflicts,
	build_container_summary,
	refresh_bon_status,
)
from container_depot.container_depot import last_orders
from container_depot.container_depot.container_activity import log_container_activity
from container_depot.container_depot.visit_dates import bon_day

# A single bon/voucher may carry at most this many containers.
MAX_CONTAINERS_PER_ORDER = 2


class OrderBongkar(Document):
	def validate(self):
		_sync_booking(self)
		_validate_booking_code(self, "Tank In")
		_mirror_lines(self)
		_sync_container_summary(self)
		_validate_tank_position(self, present=False)

	def onload(self):
		from container_depot.container_depot.order_generation import order_undoable

		self.set_onload("undoable", order_undoable(self))

	def on_update_after_submit(self):
		# Tanggal Bongkar stays editable after submit (a mistyped realisation is corrected in
		# place); the booking lines read their Realisation Date from it, and the tanks their
		# day in (visit_dates).
		refresh_bon_status(self.get("booking"))
		from container_depot.container_depot.visit_dates import follow_bongkar

		follow_bongkar(self)

	def on_update(self):
		_reconcile_codes(self)
		# A bon sent back to draft (revert_order_to_draft) may lose a row: its Leak Check
		# order goes with it now, not at the next submit.
		if self.docstatus == 0:
			_leak_checks(self, "release_removed_rows")
			_release_removed_tanks(self)

	def on_submit(self):
		# Sync depot/status first so the activity log + ex_vessel see the arrived tank.
		_sync_container_arrival(self)
		_log_order_activity(self, "Order Bongkar")
		# EMKL / Shipper / Ex Vessel on the Container master. Recomputed from the bons
		# (``last_orders``) rather than written straight through, so a later cancel lands on
		# the bon before instead of leaving this one's stamp on a tank it never hauled.
		# Called HERE and not left to the doc_event that fires after ``on_submit``, because
		# ``_provision_eirs`` below reads ``ex_vessel`` back off the master; the doc_event
		# runs again afterwards and finds nothing left to change.
		last_orders.refresh_for_doc(self)
		_ensure_order_qr(self)
		# Open the gate log for this visit (the IN half of Riwayat Gate).
		_record_gate_in(self)
		# Auto-create the per-container draft EIRs + stamp each container's latest voucher.
		_provision_eirs(self)
		# One Leak Check order per container (leak_check.provision_for_order_bongkar).
		_leak_checks(self, "provision_for_order_bongkar")
		# A bon of only tanks taken without an EIR owes nothing more: done at issue (no_eir.py).
		refresh_completion(self.name)
		from container_depot.container_depot.notify import notify_order_gate
		notify_order_gate(self, "in")
		# A re-submit after an edit: the drafts and the gate log above were kept, not re-made.
		from container_depot.container_depot.order_generation import refresh_bon_followers
		refresh_bon_followers(self.doctype, self.name)

	def on_cancel(self):
		from container_depot.container_depot.bon_revision import _assert_storage_not_invoiced

		# First, before anything moves: a billed visit cannot lose its arrival.
		_assert_storage_not_invoiced(self, _("bon tidak bisa dibatalkan"))
		_release_codes(self)
		_release_eirs(self, "EIR-In")
		_leak_checks(self, "release_for_cancelled_order")
		_release_gate_in(self)
		_cancel_unstarted_work(self)
		# LAST: the arrival itself.
		_release_container_arrival(self)

	def before_discard(self):
		# Frappe's bare Discard (REST / form.save.discard) voids the draft without any of
		# on_cancel's unwind — codes stay Used, an arrival stays stamped. The one road is
		# order_generation.void_order (the red Cancel), which does the full unwind.
		frappe.throw(_("Pakai tombol Cancel untuk membatalkan bon ini."))

	def on_trash(self):
		# A bon is never deleted — Cancel it (draft or submitted) to release its
		# containers and keep the audit trail. The UI Delete / Duplicate / New
		# actions are stripped in the form script; raw maintenance
		# (frappe.db.delete) bypasses this guard.
		frappe.throw(_("An Order Bongkar cannot be deleted — use Cancel to void it instead."))


def _mirror_lines(order: Document):
	"""The bon is a copy of its booking lines (order_generation.mirror_booking_lines)."""
	from container_depot.container_depot.order_generation import mirror_booking_lines
	mirror_booking_lines(order)


def _provision_eirs(order: Document):
	"""Auto-create the per-container draft EIRs and stamp each container's latest Order
	Bongkar voucher (see ``container_depot.eir.provision_eirs_for_order_bongkar``). Best-effort:
	an EIR hiccup is logged and never blocks the bon submit."""
	try:
		from container_depot.container_depot.eir import provision_eirs_for_order_bongkar
		provision_eirs_for_order_bongkar(order.name)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"provision EIRs for {order.name}")


def _leak_checks(order: Document, fn: str):
	"""Provision / release this bon's Leak Check orders. Best-effort, like the EIRs."""
	try:
		from container_depot.container_depot.doctype.leak_check import leak_check
		getattr(leak_check, fn)(order.name)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"Leak Check {fn} for {order.name}")


def _release_eirs(order: Document, inspection_type: str, containers=None):
	"""Unwind the draft EIRs this bon provisioned (see
	``container_depot.eir.release_eirs_for_cancelled_order``). Shared by Order Bongkar
	(EIR-In) and Order Muat (EIR-Out). Best-effort — an EIR hiccup never blocks a cancel.
	"""
	try:
		from container_depot.container_depot.eir import release_eirs_for_cancelled_order
		release_eirs_for_cancelled_order(order.name, inspection_type, containers)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"release EIRs for {order.name}")


def _order_rows(doc: Document):
	"""Authoritative container rows for an order (the ``containers`` child table)."""
	return doc.get("containers") or []


def _validate_tank_position(doc: Document, present: bool):
	"""A bon moves a tank, so it must find the tank on the side it moves it from: a Tank In
	bon (``present=False``) needs it away, a Tank Out bon (``present=True``) needs it here.

	The booking no longer guarantees this. One tank may carry an open Tank In and an open
	Tank Out at once (booked ahead of the other move — see ``_find_booking_conflicts``), so
	the bon is where "not yet" is said, and what stops a tank coming in or going out twice.

	A Tank In bon on a tank already here is refused only while a Tank Out is still booked on
	it — the booked-back-in case this guard exists for. Without one, a present tank getting a
	Tank In bon is the long-standing tolerated path (a re-submit, a hand-registered master)
	and is left alone, as is a bon re-submitted over its own arrival (``last_order_bongkar``).
	"""
	from container_depot.container_depot.container_status import PRESENT

	for row in _order_rows(doc):
		if not row.get("container"):
			continue
		cur = frappe.db.get_value(
			"Container", row.container, ["status", "last_order_bongkar"], as_dict=True
		)
		if not cur or (cur.status in PRESENT) == present:
			continue
		if not present and (
			cur.last_order_bongkar == doc.name
			or not _find_booking_conflicts(None, [(row.container, row.get("container_no"))], "Tank Out")
		):
			continue
		message = (
			_("Row {0} ({1}): tank belum ada di depo (status {2}) — bon muat baru bisa dibuat setelah tank masuk.")
			if present else
			_("Row {0} ({1}): tank masih ada di depo (status {2}) — bon bongkar baru bisa dibuat setelah tank keluar.")
		)
		frappe.throw(
			message.format(row.idx, row.get("container_no") or row.container, cur.status or "-"),
			title=_("Posisi Tank Tidak Sesuai"),
		)


def _sync_container_summary(doc: Document):
	"""Denormalise the row container numbers onto a single Data field, because a Desk list
	column cannot render a child table — without this the two bon lists show a booking and a
	status but never say which tank the bon is for, which is the one thing the operator is
	scanning the list to find.

	Must run AFTER ``_validate_booking_code``: that is what copies ``container_no`` down from
	each row's Booking Code, so reading the rows any earlier sees blanks on a manual add.

	Shared with Container Booking's builder so all three lists format identically. A bon caps
	at ``MAX_CONTAINERS_PER_ORDER`` containers and so never reaches its truncation, but
	borrowing the function is still cheaper than a second way of joining the same numbers.
	"""
	doc.container_summary = build_container_summary(
		[r.container_no for r in _order_rows(doc) if r.container_no]
	)


def _log_order_activity(order: Document, activity_type: str):
	"""Append one Container Activity per container row when a bon is submitted
	(shared by Order Bongkar + Order Muat)."""
	for row in _order_rows(order):
		if row.get("container"):
			log_container_activity(
				row.container, activity_type,
				reference_doctype=order.doctype, reference_name=order.name,
				summary=f"{activity_type} issued" + (f" (EMKL {order.get('emkl')})" if order.get("emkl") else ""),
			)


def _ensure_order_qr(order: Document):
	"""Render a scannable QR (payload ``OAK|{name}``) into ``qr_image`` once the bon
	exists, so a printed bon can be scanned at the gate. Best-effort — mirrors Booking
	Code's QR; skips if already set or if the ``qrcode`` lib is unavailable."""
	if order.get("qr_image"):
		return
	try:
		import base64
		from io import BytesIO

		import qrcode

		img = qrcode.make(f"OAK|{order.name}")
		buf = BytesIO()
		img.save(buf, format="PNG")
		b64 = base64.b64encode(buf.getvalue()).decode("ascii")
		order.db_set("qr_image", f"data:image/png;base64,{b64}", update_modified=False)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "order qr")


def _booking_depot(order: Document):
	"""The depot this bon serves. A Tank In bon has no depot field of its own — the
	booking is the only place it is recorded."""
	return (
		frappe.db.get_value("Container Booking", order.booking, "depot")
		if order.get("booking")
		else None
	)


def _record_gate_in(order: Document):
	"""Open a Gate Entry per container on Tank In submit — the arrival half of the gate log.

	WHY THIS EXISTS: a Gate Entry is designed to span a tank's whole depot visit (it carries
	BOTH ``gate_in_timestamp`` and ``gate_out_timestamp``), but for a long time nothing on the
	depot flow ever wrote the IN half. ``mark_gate_out`` was the only creator, so every record
	in "Riwayat Gate" read as a departure and the reuse branch in
	``gate._resolve_or_create_gate_entry`` never once fired. The arrival WAS recorded — on the
	bon and on the Container Movement — just not where the gate log looks. This closes that.

	Three deliberate choices:

	* **Draft, not submitted.** ``GateEntry.on_submit`` forces the container to ``In_Depot``
	  and refuses a tank that is already present — and ``_sync_container_arrival`` has just
	  put it there. Submitting here would throw on every bon. ``mark_gate_out`` leaves its
	  records drafts for the same reason; the list view is taught to read ``status`` instead
	  of docstatus (see ``gate_entry_list.js``).
	* **Idempotent per visit.** A bon reverted to draft and re-submitted, or a second bon on
	  a tank that never left, must not open a second record — the open one is reused, which
	  is also what lets ``mark_gate_out`` stamp the SAME row on the way out.
	* **Best-effort.** Same contract as ``_provision_eirs``: this is an audit record, and a
	  hiccup writing it must never block a truck at the gate.
	"""
	from container_depot.container_depot.gate import open_gate_entry_for

	depot = _booking_depot(order)
	when = order.get("gate_in_time") or now_datetime()
	for row in _order_rows(order):
		container_no = row.get("container_no") or frappe.db.get_value(
			"Container", row.get("container"), "container_no"
		)
		if not container_no:
			continue
		try:
			if open_gate_entry_for(container_no):
				continue
			doc = frappe.new_doc("Gate Entry")
			doc.container = row.get("container")
			doc.container_no = container_no
			doc.booking_code = row.get("booking_code")
			doc.depot = depot
			doc.order_doctype = "Order Bongkar"
			doc.order_ref = order.name
			doc.security_guard = order.owner
			# Truck + driver the guard typed at the gate. Tank In carries them per
			# container (the bon's rows ARE Container Booking Item rows), and the field
			# is `driver` there vs `driver_name` on Gate Entry. Without this the gate log
			# has the columns but nothing ever fills them, so "Riwayat Gate" showed "—"
			# for every arrival while the data sat one doctype away on the bon.
			doc.truck_plate = row.get("truck_plate")
			doc.driver_name = row.get("driver")
			doc.gate_in_timestamp = when
			doc.in_date = bon_day(order)
			doc.status = "Gate_In_Completed"
			doc.inspection_status = "Pending"
			doc.insert(ignore_permissions=True)
			# Dan satu baris "Gate In" di timeline tank — pasangan dari "Gate Out" yang
			# ditulis ``gate.mark_gate_out``, dan baris yang sama persis dengan yang ditulis
			# ``GateEntry.on_submit`` untuk kedatangan lewat kiosk SST.
			#
			# WHY: Container Activity adalah SATU tabel yang dibaca setiap penghitung
			# pergerakan — kartu "Tank masuk" di Beranda PWA (``ess/home.py``), kartu hari ini
			# di monitor Desk (``ess/inventory.py``), dan umur tank di depo yang jatuh ke
			# aktivitas Gate In kalau EIR-In belum ada. Kedatangan lewat bon tidak pernah
			# menulisnya: Gate Entry-nya sengaja ditinggal DRAFT (lihat docstring di atas),
			# jadi ``on_submit``-nya — satu-satunya penulis baris itu — tidak pernah jalan.
			# Akibatnya semua kedatangan jalur normal terhitung nol, sementara jalur kiosk
			# yang jarang dipakai justru terhitung.
			#
			# Waktunya memakai ``when`` yang sama dengan ``gate_in_timestamp``, supaya
			# hitungan "hari ini" tidak pernah berbeda antara timeline dan Riwayat Gate.
			log_container_activity(
				row.container, "Gate In",
				reference_doctype="Gate Entry", reference_name=doc.name,
				to_status=frappe.db.get_value("Container", row.container, "status"),
				performed_by=order.owner,
				activity_time=when,
				summary=f"Gate-in (Bon {order.name})",
			)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"gate-in log for {order.name}/{container_no}")


def _arrived_on(order: Document, container: str):
	"""``{status, ex_vessel}`` of a tank whose arrival is still THIS bon's to undo, else None.

	Still PRESENT (one that has since gated out is on a later chapter of its life), and this
	bon is still its latest arrival voucher (``last_order_bongkar``, read before the
	``last_orders`` cache hook re-points it) — a newer bon owns the visit otherwise.
	"""
	from container_depot.container_depot.container_status import PRESENT

	if not container or not frappe.db.exists("Container", container):
		return None
	cur = frappe.db.get_value(
		"Container", container, ["status", "last_order_bongkar", "ex_vessel"], as_dict=True
	)
	if not cur or cur.status not in PRESENT:
		return None
	if cur.last_order_bongkar and cur.last_order_bongkar != order.name:
		return None
	return cur


# The work a voided arrival takes down with it: only orders nobody has started (user,
# 2026-10-09). EIR-In and Leak Check are released by their own hooks above.
_UNSTARTED_WORK = {"Cleaning Order": ("Service Setup", "Pending"), "Repair Order": ("Draft",)}


def _release_removed_tanks(order: Document):
	"""A row taken off a bon that went back to draft: that tank's arrival is undone exactly as
	a void undoes it — gate-in, EIR-In draft, unstarted work, status. It used to keep only the
	code release, and the tank stood In_Depot for good (2026-10-09 audit)."""
	before = order.get_doc_before_save()
	if not before:
		return
	keep = {r.container for r in _order_rows(order) if r.get("container")}
	gone = [r.container for r in _order_rows(before) if r.get("container") and r.container not in keep]
	if not gone:
		return
	_release_eirs(order, "EIR-In", gone)
	_release_gate_in(order, gone)
	_cancel_unstarted_work(order, gone)
	_release_container_arrival(order, gone)


def _cancel_unstarted_work(order: Document, containers=None):
	"""Cancel this visit's Cleaning / M&R that nobody has started. Started or finished work is
	left for Admin Ops to decide on by hand — and no longer holds the tank in the yard
	(:func:`_release_container_arrival`). Best-effort per order, like the EIRs."""
	from container_depot.container_depot.container_status import container_open_orders

	note = _("Dibatalkan otomatis: bon {0} dibatalkan.").format(order.name)
	for container in containers or dict.fromkeys(r.get("container") for r in _order_rows(order)):
		if not _arrived_on(order, container):
			continue
		for o in container_open_orders(container):
			if o["status"] not in _UNSTARTED_WORK.get(o["doctype"], ()):
				continue
			try:
				doc = frappe.get_doc(o["doctype"], o["name"])
				doc.flags.ignore_permissions = True
				if doc.doctype == "Cleaning Order":
					doc.flags.oak_cancel = True
					doc.discard()
				else:
					doc.status = "Cancelled"
					doc.save()
				doc.add_comment("Info", note)
			except Exception:
				frappe.log_error(frappe.get_traceback(), f"cancel {o['name']} with {order.name}")


def _release_container_arrival(order: Document, containers=None):
	"""Un-arrive the tanks whose arrival THIS bon stamped (:func:`_sync_container_arrival`).

	The bon is what puts the tank in the depot, so voiding it ALWAYS takes it back out (user,
	2026-10-09) — status, ``in_date``, and the vessel it wrote. Work already done on the tank
	does not hold it: it used to (a submitted EIR-In, or any open order — including the
	started EIR-In draft a cancel deliberately keeps), and the bon was voided while the tank
	silently stayed In_Depot. That work is left for Admin Ops to decide on.

	Only a tank still exactly where this bon put it is touched (:func:`_arrived_on`).

	Where it goes back to is decided the same way the booking decides it: ``Booked`` while a
	live booking is still expecting the tank (its Booking Codes went back to ``Active`` a
	moment ago, so it is expected again), otherwise ``Gate_Out``. Never ``Available``: a tank
	that never arrived is not standing in the yard, and saying so would put a phantom back
	into the inventory.
	"""
	for container in containers or [r.get("container") for r in _order_rows(order)]:
		cur = _arrived_on(order, container)
		if cur:
			roll_back_arrival(order, container, cur)


def _last_out_date(container_no: str):
	"""The day the tank last left, from the newest closed gate record — None if it never did."""
	return frappe.db.get_value(
		"Gate Entry",
		{"container_no": container_no, "status": "Gate_Out_Completed", "docstatus": ["<", 2]},
		"out_date",
		order_by="gate_out_timestamp desc",
	)


def roll_back_arrival(order, container: str, cur) -> str:
	"""Put ``container`` back where it stood before ``order`` (an Order Bongkar) brought it in.
	``cur``: its ``{status, ex_vessel}`` now. Returns the status it went back to."""
	from container_depot.container_depot.container_status import GATE_OUT

	# The booking this bon was cut from, if it is still standing. Asked of THIS booking only —
	# a tank also listed on some outbound booking is not "expected to arrive".
	booking = frappe.db.get_value(
		"Container Booking", order.get("booking"), ["docstatus", "booking_status"], as_dict=True
	) if order.get("booking") else None
	back_to = "Booked" if (
		booking and booking.docstatus < 2 and booking.booking_status != "Cancelled"
	) else GATE_OUT
	# Through the ORM, not a raw write, and this is the whole point of the automation flag:
	# `Container.on_update` is what logs the Status Container Movement and re-derives the
	# storage visit, so a roll-back written underneath it would leave the tank's own audit
	# trail ending at a status it no longer has — and a storage stay still open on a visit
	# that never happened. `before_save` re-derives `inventory_stage` for the same reason.
	# The flag only bypasses the MANUAL-transition guard (`Container.validate`).
	frappe.flags.in_status_automation = True
	try:
		tank = frappe.get_doc("Container", container)
		tank.status = back_to
		tank.in_date = None
		# The arrival cleared the previous visit's day out; a tank that never came back in is
		# still out since that day (2026-10-09 audit).
		tank.out_date = _last_out_date(tank.container_no or container)
		# Only the vessel THIS bon wrote comes off; a value that was already there (or that a
		# later document set) is the tank's own history and is left alone.
		if order.get("ex_vessel") and tank.ex_vessel == order.get("ex_vessel"):
			tank.ex_vessel = None
		tank.save(ignore_permissions=True)
	finally:
		frappe.flags.in_status_automation = False
	log_container_activity(
		container, "Status Change",
		reference_doctype=order.doctype, reference_name=order.name,
		from_status=cur.status, to_status=back_to,
		summary=f"{order.doctype} dibatalkan — kedatangan tank dibatalkan",
	)
	return back_to


def _release_gate_in(order: Document, containers=None):
	"""Void the gate-in records this bon opened when the bon itself is cancelled.

	Only records still covering an open visit are touched: a tank that has already gated out
	owns a completed record, and un-writing history is not what cancelling a bon means. The
	record is kept (status ``Cancelled``) rather than deleted — Riwayat Gate is an audit log.
	"""
	from container_depot.container_depot.gate import GATE_ENTRY_CLOSED

	filters = {
		"order_doctype": "Order Bongkar",
		"order_ref": order.name,
		"status": ["not in", GATE_ENTRY_CLOSED],
		"docstatus": ["<", 2],
	}
	if containers is not None:
		nos = [frappe.db.get_value("Container", c, "container_no") or c for c in containers]
		filters["container_no"] = ["in", nos or [""]]
	for name in frappe.get_all("Gate Entry", filters=filters, pluck="name"):
		frappe.db.set_value("Gate Entry", name, "status", "Cancelled")


# Statuses a tank may sit in *before* it has physically arrived. Only these advance
# to Gate_In on a Tank In bon, so a tank already in process is never regressed.
_ARRIVAL_SOURCE_STATUS = {None, "", "Booked", "Available", "Gate_Out"}


def _sync_container_arrival(order: Document):
	"""On Tank In (bongkar) submit, push the arrival facts the bon knows onto the
	Container master:

	* ``depot`` — always set from the booking's depot (it is never written anywhere
	  else, so without this a gated-in tank keeps a blank depot — which breaks
	  Depot Storage zone recommendation).
	* ``status`` -> ``Gate_In`` for a not-yet-arrived tank.
	* ``in_date`` — the bon's Tanggal Bongkar, the day the tank came in (``visit_dates``),
	  for a tank arriving now; ``out_date`` is cleared with it, since the tank has not left
	  this visit. A tank that was already inside (a second bon on a visit that never ended)
	  keeps the day it really came in. An EIR-In never moves either date.

	Saved through the ORM so ``Container.before_save`` keeps ``inventory_stage`` in
	step (-> Incoming) and ``Container.on_update`` logs the Status Container Movement.
	The transitions used (Booked / Available / Gate_Out -> Gate_In) are all valid in
	the state machine, so no automation bypass is needed.
	"""
	from container_depot.container_depot.container_status import PRESENT, recompute_availability

	depot = _booking_depot(order)
	for row in _order_rows(order):
		if not row.get("container"):
			continue
		container = frappe.get_doc("Container", row.container)
		changed = False
		if depot and container.depot != depot:
			container.depot = depot
			changed = True
		if container.status not in PRESENT or not container.in_date:
			container.in_date = bon_day(order)
			container.out_date = None
			changed = True
		if container.status in _ARRIVAL_SOURCE_STATUS:
			container.status = "In_Depot"
			changed = True
		if changed:
			container.save(ignore_permissions=True)
		# In_Depot means "here WITH open work" — settle on the computed state so a tank
		# that arrived with nothing open is not left looking busy (see container_status).
		recompute_availability(row.container)


def _sync_booking(doc: Document):
	"""Derive the header ``booking`` from the first container row's Booking Code
	(so a bon always belongs to exactly one booking), then carry the booking's
	Principal (Tank Owner) onto the header."""
	rows = _order_rows(doc)
	if not doc.get("booking") and rows and rows[0].booking_code:
		booking = frappe.db.get_value("Booking Code", rows[0].booking_code, "booking")
		if booking:
			doc.booking = booking
	if doc.get("booking") and doc.meta.has_field("principal") and not doc.get("principal"):
		doc.principal = frappe.db.get_value("Container Booking", doc.booking, "principal")
	# Carry the booking's depot Branch onto the bon so per-branch User Permissions can
	# scope orders (Order Bongkar/Muat have no native branch of their own).
	if doc.get("booking") and doc.meta.has_field("branch") and not doc.get("branch"):
		doc.branch = frappe.db.get_value("Container Booking", doc.booking, "branch")


def _resolve_code_from_container(doc: Document, row) -> None:
	"""Manual grid add: the operator picks a Container (not the hidden Booking
	Code). Resolve its still-pending (``Active``) Booking Code on THIS voucher's
	booking so the row carries a code — keeping a single bon to one booking."""
	if row.booking_code or not doc.get("booking"):
		return
	if not (row.get("container") or row.get("container_no")):
		return
	base = {"booking": doc.booking, "state": "Active"}
	code = None
	if row.get("container"):
		code = frappe.db.get_value("Booking Code", {**base, "container": row.container}, "name")
	if not code and row.get("container_no"):
		code = frappe.db.get_value("Booking Code", {**base, "container_no": row.container_no}, "name")
	if code:
		row.booking_code = code


def _code_owned_by_order(doc: Document, code: str) -> bool:
	"""True if ``code`` is already persisted on THIS order — i.e. it was consumed
	by this very bon (so its ``Used`` state is expected, not an error). Uses the
	order's OWN container child table (Container Booking Item for Order Bongkar,
	Order Container Item for Order Muat) so re-validation on submit works for both."""
	if doc.is_new() or not doc.name:
		return False
	child_dt = doc.meta.get_field("containers").options
	return bool(
		frappe.db.exists(
			child_dt,
			{"parent": doc.name, "parenttype": doc.doctype, "booking_code": code},
		)
	)


def _validate_booking_code(doc: Document, expected_direction: str):
	"""Validate every container row's Booking Code: right direction, in this
	booking, 1..3 cap. A NEWLY added code must be ``Active``; a code already on
	this order may be ``Used`` (it was consumed by this bon).
	"""
	rows = _order_rows(doc)
	if not (1 <= len(rows) <= MAX_CONTAINERS_PER_ORDER):
		frappe.throw(
			_("An order must have between 1 and {0} containers (got {1}).").format(
				MAX_CONTAINERS_PER_ORDER, len(rows)
			)
		)
	seen = set()
	for row in rows:
		# Manual add picks a Container; back-resolve its Active Booking Code first.
		_resolve_code_from_container(doc, row)
		if not row.booking_code:
			frappe.throw(_("Row {0}: Booking Code is required.").format(row.idx))
		if row.booking_code in seen:
			frappe.throw(_("Booking Code {0} is listed more than once.").format(row.booking_code))
		seen.add(row.booking_code)
		bc = frappe.db.get_value(
			"Booking Code",
			row.booking_code,
			["state", "direction", "container", "container_no", "booking"],
			as_dict=True,
		)
		if not bc:
			frappe.throw(_("Booking Code {0} not found.").format(row.booking_code))
		if bc.direction != expected_direction:
			frappe.throw(
				_("Booking Code {0} is for {1}, not {2}.").format(
					row.booking_code, bc.direction, expected_direction
				)
			)
		if doc.get("booking") and bc.booking and bc.booking != doc.booking:
			frappe.throw(
				_("Booking Code {0} does not belong to booking {1}.").format(
					row.booking_code, doc.booking
				)
			)
		# The Active check only applies to a code being newly placed on this order.
		if not _code_owned_by_order(doc, row.booking_code):
			if bc.state != "Active":
				frappe.throw(
					_("Booking Code {0} state is {1}; must be Active.").format(row.booking_code, bc.state)
				)
		# A manually added container takes its tank from the code / booking line; the rest of
		# the line's detail is copied by ``_mirror_lines``.
		if not row.get("container_no") and bc.container_no:
			row.container_no = bc.container_no
		if not row.get("container"):
			row.container = bc.container or (
				row.get("container_no")
				and frappe.db.get_value(
					"Container Booking Item", {"parent": bc.booking, "container_no": row.container_no}, "container"
				)
			)


def _reconcile_codes(doc: Document):
	"""Keep Booking Code state in step with the bon's container list:
	newly added codes are consumed (Active -> Used); codes removed from the bon
	are released (Used -> Active) so they can be issued on another voucher.
	"""
	current = {r.booking_code for r in _order_rows(doc) if r.booking_code}
	prev = doc.get_doc_before_save()
	previous = {r.booking_code for r in (prev.get("containers") if prev else []) if r.booking_code}
	for code in current - previous:
		if frappe.db.get_value("Booking Code", code, "state") == "Active":
			frappe.db.set_value("Booking Code", code, "state", "Used", update_modified=False)
	for code in previous - current:
		if frappe.db.get_value("Booking Code", code, "state") == "Used":
			frappe.db.set_value("Booking Code", code, "state", "Active", update_modified=False)
	# Every flip above changes how much of the booking is still waiting for a bon. This and
	# _release_codes are the only two places a code's state moves once it has been issued, so
	# refreshing here keeps the booking's "Bon 3/5" marker honest without a scheduled job.
	refresh_bon_status(doc.get("booking"))


def _release_codes(doc: Document):
	"""Free this bon's codes back to Active (e.g. on cancel)."""
	for r in _order_rows(doc):
		if r.booking_code and frappe.db.get_value("Booking Code", r.booking_code, "state") == "Used":
			frappe.db.set_value("Booking Code", r.booking_code, "state", "Active", update_modified=False)
	# A voided bon hands its containers back to the booking — they need a new bon, and the
	# booking's marker has to say so again.
	refresh_bon_status(doc.get("booking"))


def sync_completion(eir) -> None:
	"""Close the Tank In bon once every tank on it has its EIR-In submitted; reopen it when
	one is reverted or voided.

	An Order Bongkar had no ending at all: it sat at ``Issued`` (orange "Diterbitkan") long
	after its tanks were unloaded and inspected, so a finished bon read as one still waiting
	(user, 2026-10-02). The mirror of the Order Muat, which closes at its last gate-out.

	Only ``Issued`` ↔ ``Completed`` is moved. A completed bon is terminal
	(``order_generation.ORDER_TERMINAL_STATUS``), so undoing it means reverting the EIR-In
	first — which is exactly what reopens it here.
	"""
	if eir.get("inspection_type") != "EIR-In" or eir.get("voucher_doctype") != "Order Bongkar":
		return
	refresh_completion(eir.get("referred_voucher"))


def refresh_completion(name: str | None) -> None:
	"""``Completed`` once every tank that owes an EIR-In has one submitted. A tank taken without
	an EIR owes none (no_eir.py), so a bon of only those is done the moment it is issued."""
	from container_depot.container_depot.no_eir import no_eir_containers

	bon = name and frappe.db.get_value("Order Bongkar", name, ["docstatus", "order_status"], as_dict=True)
	if not bon or bon.docstatus != 1 or bon.order_status not in ("Issued", "Completed"):
		return
	tanks = {c for c in frappe.get_all(
		"Container Booking Item", filters={"parent": name, "parenttype": "Order Bongkar"}, pluck="container"
	) if c}
	inspected = set(frappe.get_all(
		"Inspection",
		filters={"referred_voucher": name, "inspection_type": "EIR-In", "docstatus": 1},
		pluck="container",
	))
	owed = tanks - no_eir_containers(name, "Order Bongkar")
	target = "Completed" if tanks and owed <= inspected else "Issued"
	if target != bon.order_status:
		frappe.db.set_value("Order Bongkar", name, "order_status", target, update_modified=False)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def pending_container_query(doctype, txt, searchfield, start, page_len, filters):
	"""Containers still issuable onto a bon for a booking: those carrying an
	``Active`` Booking Code on that booking (i.e. not yet placed on a voucher).
	Drives the manual container picker in an Order Bongkar grid so one voucher
	can only mix containers from the SAME booking."""
	booking = (filters or {}).get("booking")
	if not booking:
		return []
	like = f"%{txt or ''}%"
	return frappe.db.sql(
		"""
		SELECT DISTINCT c.name, c.container_no
		FROM `tabContainer` c
		INNER JOIN `tabBooking Code` bc
			ON (bc.container = c.name OR bc.container_no = c.container_no)
		WHERE bc.booking = %(booking)s AND bc.state = 'Active'
		  AND (c.name LIKE %(like)s OR c.container_no LIKE %(like)s)
		ORDER BY c.container_no
		LIMIT {start}, {page_len}
		""".format(start=cint(start), page_len=cint(page_len)),
		{"booking": booking, "like": like},
	)
