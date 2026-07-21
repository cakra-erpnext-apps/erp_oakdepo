import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

# A single bon/voucher may carry at most this many containers.
MAX_CONTAINERS_PER_ORDER = 2


class OrderBongkar(Document):
	def validate(self):
		_sync_booking(self)
		_validate_booking_code(self, "Tank In")

	def on_update(self):
		_reconcile_codes(self)

	def on_submit(self):
		# Sync depot/status first so the activity log + ex_vessel see the arrived tank.
		_sync_container_arrival(self)
		_log_order_activity(self, "Order Bongkar")
		_update_container_ex_vessel(self)
		_ensure_order_qr(self)
		# Auto-create the per-container draft EIRs + stamp each container's latest voucher.
		_provision_eirs(self)
		from container_depot.operations.notify import notify_order_gate
		notify_order_gate(self, "in")

	def on_cancel(self):
		_release_codes(self)
		_release_eirs(self, "EIR-In")

	def on_trash(self):
		# A bon is never deleted — Cancel it (draft or submitted) to release its
		# containers and keep the audit trail. The UI Delete / Duplicate / New
		# actions are stripped in the form script; raw maintenance
		# (frappe.db.delete) bypasses this guard.
		frappe.throw(_("An Order Bongkar cannot be deleted — use Cancel to void it instead."))


def _provision_eirs(order: Document):
	"""Auto-create the per-container draft EIRs and stamp each container's latest Order
	Bongkar voucher (see ``operations.eir.provision_eirs_for_order_bongkar``). Best-effort:
	an EIR hiccup is logged and never blocks the bon submit."""
	try:
		from container_depot.operations.eir import provision_eirs_for_order_bongkar
		provision_eirs_for_order_bongkar(order.name)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"provision EIRs for {order.name}")


def _release_eirs(order: Document, inspection_type: str):
	"""Unwind the draft EIRs this bon provisioned (see
	``operations.eir.release_eirs_for_cancelled_order``). Shared by Order Bongkar
	(EIR-In) and Order Muat (EIR-Out). Best-effort — an EIR hiccup never blocks a cancel.
	"""
	try:
		from container_depot.operations.eir import release_eirs_for_cancelled_order
		release_eirs_for_cancelled_order(order.name, inspection_type)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"release EIRs for {order.name}")


def _order_rows(doc: Document):
	"""Authoritative container rows for an order (the ``containers`` child table)."""
	return doc.get("containers") or []


def _log_order_activity(order: Document, activity_type: str):
	"""Append one Container Activity per container row when a bon is submitted
	(shared by Order Bongkar + Order Muat)."""
	from container_depot.operations.container_activity import log_container_activity

	for row in _order_rows(order):
		if row.get("container"):
			log_container_activity(
				row.container, activity_type,
				reference_doctype=order.doctype, reference_name=order.name,
				summary=f"{activity_type} issued" + (f" (shipper {order.get('shipper')})" if order.get("shipper") else ""),
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


def _update_container_ex_vessel(order: Document):
	"""Stamp each container's ``ex_vessel`` from the bon's Ex Vessel on submit, so the
	Container master reflects the vessel the tank last arrived on (read back by the EIR
	header). Plain field write — no Container controller side-effects."""
	ex_vessel = order.get("ex_vessel")
	if not ex_vessel:
		return
	for row in _order_rows(order):
		if row.get("container"):
			frappe.db.set_value("Container", row.container, "ex_vessel", ex_vessel)


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

	Saved through the ORM so ``Container.before_save`` keeps ``inventory_stage`` in
	step (-> Incoming) and ``Container.on_update`` logs the Status Container Movement.
	The transitions used (Booked / Available / Gate_Out -> Gate_In) are all valid in
	the state machine, so no automation bypass is needed.
	"""
	depot = (
		frappe.db.get_value("Container Booking", order.booking, "depot")
		if order.get("booking")
		else None
	)
	for row in _order_rows(order):
		if not row.get("container"):
			continue
		container = frappe.get_doc("Container", row.container)
		changed = False
		if depot and container.depot != depot:
			container.depot = depot
			changed = True
		if container.status in _ARRIVAL_SOURCE_STATUS:
			container.status = "In_Depot"
			changed = True
		if changed:
			container.save(ignore_permissions=True)


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
		# Auto-populate the row's container + booking-line detail from the booking line.
		# Order Bongkar reuses Container Booking Item, whose condition / cargo / Tgl.
		# Bongkar are required, so a manually added container inherits the booking's
		# values (the generate path fills these too).
		if not row.get("container_no") and bc.container_no:
			row.container_no = bc.container_no
		item = (
			frappe.db.get_value(
				"Container Booking Item",
				{"parent": bc.booking, "container_no": row.get("container_no")},
				["container", "condition", "cargo", "tanggal_bongkar", "truck_plate",
				 "driver", "driver_phone", "ro", "remarks"],
				as_dict=True,
			)
			if row.get("container_no")
			else None
		)
		if not row.get("container"):
			row.container = bc.container or (item.container if item else None)
		if item:
			for f in (
				"condition", "cargo", "tanggal_bongkar", "truck_plate",
				"driver", "driver_phone", "ro", "remarks",
			):
				if not row.get(f) and item.get(f):
					row.set(f, item.get(f))


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


def _release_codes(doc: Document):
	"""Free this bon's codes back to Active (e.g. on cancel)."""
	for r in _order_rows(doc):
		if r.booking_code and frappe.db.get_value("Booking Code", r.booking_code, "state") == "Used":
			frappe.db.set_value("Booking Code", r.booking_code, "state", "Active", update_modified=False)


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
