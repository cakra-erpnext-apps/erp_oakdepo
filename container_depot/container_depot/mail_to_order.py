"""Email → Order bridge.

An incoming email (a ``Communication`` of medium Email, ``Received``) is the paper trail
behind the two things a customer books by mail: tanks coming in or going out ("mohon
dibooking 5 tank berikut", "kami ambil tank ini minggu depan"). This module lets an
operator turn that email into a **Container Booking** — inbound or outbound — straight from
the Communication form, and pull new mail on demand — the desk mirror of the Email Account
"Pull Emails" button, but scoped to the accounts set on the user.

Only those two: Cleaning / M&R / Survey are work the depot decides on after inspecting a
tank, not something a customer asks for by mail. They used to be offered here and are still
*reported* by :func:`linked_orders`, so an email that spawned one of them back then still
says so.

One email almost always names *several* tanks, so everything here is container-list shaped:

* :func:`scan_email_containers` reads the container numbers straight out of the mail body,
  so the operator starts from a filled list instead of retyping from the message.
* :func:`resolve_containers` says, per number, whether a Container master exists, what state
  it is in, and whether the booking's own direction gate would refuse it.
* :func:`parse_container_file` / :func:`download_container_template` do the same from an
  .xlsx — and refuse any number the Container master does not already know.
* :func:`get_order_prefill` seeds a fresh order form, **including its container child
  table** (booking items / gate-out lines).

Nothing here writes: the operator gets a fresh, unsaved form and saves it themselves, so no
half-empty drafts leak into the DB.
"""

from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.utils import strip_html_tags

# order_type (as sent by the client) -> (target doctype, customer field, direction).
#
# BOTH are a Container Booking now; the direction is what tells them apart. The lift-on half
# used to raise a Gate Out Plan — a separate notice document that authorised nothing and
# whose only real effect was stamping a pickup date on the tank. That is now the outbound
# booking's own job, so an email announcing a pickup becomes the document the tanks actually
# leave on, instead of a note somebody had to turn into one later.
#
# The party field differs with the direction, and deliberately: an inbound mail comes from
# whoever is being billed, an outbound one from the tank's OWNER. Bill-to on a lift-on is a
# separate question the operator answers on the booking form.
ORDER_MAP = {
	"Booking": ("Container Booking", "customer", "Tank In"),
	"Gate Out": ("Container Booking", "principal", "Tank Out"),
}

# Where the email body lands.
_NOTE_FIELD = {
	"Container Booking": "remarks",
}

# The link back to the source email. Deliberately NOT `reff_doc`: that field is the
# vendor's own document number (it propagates booking → bon → EIR → Cleaning / M&R and
# is hand-entered), so stuffing an email reference in there would corrupt that chain. The
# dialog does offer `reff_doc` as its own input — but only ever carrying what the operator
# read off the mail and typed, never an internal reference.
# `reff_email` is read-only and only ever written here.
_EMAIL_REF_FIELD = "reff_email"

_SNIPPET_LEN = 600

# How each order is summarised back on the email that spawned it: (state field, the one
# field that identifies it at a glance). The state field is NOT shared — Container Booking
# is submittable and calls it ``booking_status``.
#
# Deliberately WIDER than ORDER_MAP: this is the read side. Cleaning / M&R can no
# longer be raised from an email, but ones raised back when they could are still linked to
# theirs, and an email that already became work must not look untouched. Every doctype in
# ORDER_MAP has to appear here too — a new order type says how it is summarised rather than
# quietly going missing from the email's list.
_ORDER_SUMMARY = {
	"Container Booking": ("booking_status", "customer"),
	"Repair Order": ("status", "container_no"),
	"Cleaning Order": ("status", "container_no"),
}

# Where each order keeps its containers. Both orders raised from here are table-shaped —
# one order carries the whole email's list. Maps doctype -> the Table fieldname.
_CONTAINER_TABLE = {
	"Container Booking": "items",
}


# ---------------------------------------------------------------------------
# container numbers
# ---------------------------------------------------------------------------

# ISO-ish tank number: 4 letters + 6-7 digits, tolerating the space / dash people type
# ("TEMU 1234567", "TEMU-1234567"). Used only to *suggest* numbers found in a mail body —
# the Container master itself does not length-check (real depot data carries odd numbers),
# so anything the operator types by hand is still accepted verbatim.
_CONTAINER_RE = re.compile(r"\b([A-Z]{4})[\s\-]?(\d{6,7})\b")


def _email_text(html: str | None) -> str:
	"""Flatten mail HTML into searchable, readable text.

	Every tag becomes a space first: container numbers arrive as one ``<li>`` (or one
	``<td>``) per tank, and dropping the tags without leaving a separator glues
	``…0001MTOU…`` into a single run that neither the operator nor the number regex can
	read. Runs of blank space are collapsed back so the snippet quoted into the order's
	remarks still looks like prose.
	"""
	text = re.sub(r"<[^>]+>", " ", html or "").replace("&nbsp;", " ")
	text = strip_html_tags(text)
	text = re.sub(r"[ \t]{2,}", " ", text)
	return re.sub(r"\n{3,}", "\n\n", text)


def _normalise(number: str | None) -> str:
	return re.sub(r"[\s\-]+", "", (number or "")).strip().upper()


def parse_container_input(raw) -> list[str]:
	"""Turn whatever the operator pasted into a de-duplicated list of container numbers.

	Accepts a JSON/py list or a free-text blob. The blob is split on line breaks, commas,
	semicolons and tabs — *not* on plain spaces, because "TEMU 1234567" is one number, not
	two. A line that contains recognisable container numbers yields those matches (so
	"ABCU1234567 ABCU1234568" on one line still gives two); any other non-empty line is
	taken verbatim as a single number, which is what lets non-ISO depot numbers through.
	"""
	if isinstance(raw, str):
		raw = raw.strip()
		if raw.startswith("["):
			raw = frappe.parse_json(raw)
	if isinstance(raw, (list, tuple)):
		parts = [str(p) for p in raw]
	else:
		parts = re.split(r"[\n\r,;\t]+", str(raw or ""))

	out: list[str] = []
	for part in parts:
		found = [m.group(1) + m.group(2) for m in _CONTAINER_RE.finditer(part.upper())]
		candidates = found or ([part] if part.strip() else [])
		for c in candidates:
			c = _normalise(c)
			if c and c not in out:
				out.append(c)
	return out


# Values the dialog's container grid may carry per row (as opposed to once for the whole
# order): the cargo this tank last held, which is per-tank by nature. Kept as a tuple so
# the client can never post an arbitrary field into a child row.
_ROW_FIELDS = ("cargo",)

# Where such a row field is actually allowed to land. Only a booking line has a cargo of
# its own; on every other order the column is context read off the Container master.
_PER_ROW_FIELDS = {"Container Booking": ("cargo",)}


def parse_container_rows(raw) -> list[dict]:
	"""Normalise the container input into ``[{container_no, **row fields}]``.

	The dialog sends its grid: a list of row objects carrying the picked ``container``, the
	typed ``container_no`` and whatever per-row field applies. Older / scripted callers send
	a pasted blob or a plain list of numbers, which :func:`parse_container_input` handles —
	both end up in the same shape here so the rest of the module only knows one.
	"""
	if isinstance(raw, str) and raw.strip().startswith("["):
		raw = frappe.parse_json(raw)
	if not isinstance(raw, (list, tuple)) or not any(isinstance(r, dict) for r in raw):
		return [{"container_no": n} for n in parse_container_input(raw)]

	out, seen = [], set()
	for item in raw:
		if isinstance(item, dict):
			number = _normalise(item.get("container_no") or item.get("container"))
			extra = {f: item[f] for f in _ROW_FIELDS if item.get(f)}
		else:
			number = _normalise(item)
			extra = {}
		if not number or number in seen:
			continue
		seen.add(number)
		out.append({"container_no": number, **extra})
	return out


def _resolve_rows(numbers: list[str]) -> list[dict]:
	"""Look each container number up in the master, keeping the operator's order."""
	rows = []
	for number in numbers:
		master = frappe.db.get_value(
			"Container",
			{"container_no": number},
			["name", "status", "principal", "depot", "last_cargo"],
			as_dict=True,
		)
		rows.append(
			{
				"container_no": number,
				"container": master.name if master else None,
				"status": master.status if master else None,
				"principal": master.principal if master else None,
				"depot": master.depot if master else None,
				"last_cargo": master.last_cargo if master else None,
				"known": bool(master),
			}
		)
	return rows


def _rows_for(containers) -> list[dict]:
	"""Resolve the caller's container input against the master, keeping its per-row fields."""
	rows = parse_container_rows(containers)
	resolved = _resolve_rows([r["container_no"] for r in rows])
	for row, info in zip(rows, resolved):
		info.update({k: v for k, v in row.items() if k != "container_no"})
	return resolved


def _short_block(mismatch: dict) -> str:
	"""One grid cell's worth of why this tank cannot go this direction."""
	status = mismatch.get("status") or "-"
	if mismatch.get("direction") == "Tank In":
		return _("{0} · sudah ada di depo").format(status)
	open_orders = mismatch.get("open_orders") or []
	if open_orders:
		return _("{0} · {1} order belum selesai").format(status, len(open_orders))
	return _("{0} · tidak ada di depo").format(status)


@frappe.whitelist()
def resolve_containers(containers, order_type: str | None = None, direction: str | None = None) -> list[dict]:
	"""Per container number: does a master exist, what state is it in, and may it go this
	way at all?

	Feeds the dialog's grid so the operator sees the problem *before* the order is built.
	The two directions are not symmetric, and that asymmetry is the whole point:

	* **Tank In** may name a tank with no master — it is announcing an arrival, and the
	  booking mints the Container on save (``ContainerBooking._resolve_containers``). That
	  is what ``will_create`` flags. What it may NOT name is a tank already in the depot.
	* **Tank Out** must point at an existing master that is actually free to leave. An
	  unknown number is refused outright here; a known one is judged by the booking's own
	  gate, so the dialog and the submit can never disagree.

	That gate is ``status_direction_warnings`` (→ ``_find_status_mismatches``), and for a
	Tank Out it asks only whether the tank is HERE. Unfinished work does not disqualify it
	any more: the booking is how the depot learns a pickup is coming, and the work is
	prioritised off the booking's own load date instead.
	"""
	rows = _resolve_rows(parse_container_input(containers))
	target = ORDER_MAP.get(order_type or "")
	# Both order types raise a Container Booking now, so both are checked. The direction is
	# the type's own unless the dialog picked one.
	direction = direction or (target[2] if target else "Tank In")
	for row in rows:
		row["will_create"] = bool(target and direction == "Tank In" and not row["known"])
		row["blocked"] = None
	if not target:
		return rows

	if direction == "Tank Out":
		for row in rows:
			if not row["known"]:
				row["blocked"] = _("belum ada di master — Tank Out wajib pilih dari master")

	from container_depot.container_depot.doctype.container_booking.container_booking import (
		status_direction_warnings,
	)

	mismatches = {
		m["container_no"]: m
		for m in status_direction_warnings(
			direction=direction,
			containers=[
				{"container": r["container"], "container_no": r["container_no"]}
				for r in rows
				if r["known"]
			],
		)
	}
	for row in rows:
		hit = mismatches.get(row["container_no"])
		if hit:
			row["blocked"] = _short_block(hit)
	return rows


@frappe.whitelist()
def scan_email_containers(communication: str) -> list[dict]:
	"""Container numbers mentioned in the email (subject + body), already resolved.

	Retyping ten tank numbers out of a mail is exactly the step that produces typos, so
	the dialog opens with this list already in the box. It is a suggestion: the operator
	edits the list freely before anything is built.
	"""
	frappe.has_permission("Communication", "read", doc=communication, throw=True)
	comm = frappe.get_doc("Communication", communication)
	text = " ".join(filter(None, [comm.subject, _email_text(comm.content)])).upper()
	numbers = []
	for match in _CONTAINER_RE.finditer(text):
		number = match.group(1) + match.group(2)
		if number not in numbers:
			numbers.append(number)
	rows = _resolve_rows(numbers)
	for row in rows:
		row["will_create"] = not row["known"]
	return rows


_FILE_HEADERS = {"container", "container no", "kontainer", "no kontainer", "no container"}


@frappe.whitelist(methods=["GET"])
def download_container_template():
	"""The .xlsx the dialog's importer reads back: ``Container`` , ``Last Cargo``.

	Two columns, not the booking template's three — the dialog does not ask for a condition,
	and a third column here would only be a column :func:`parse_container_file` ignores. The
	Last Cargo cells are a dropdown onto the Cargo master (written to the second sheet), so
	a filled-in template cannot carry a cargo spelling the import then has to reject.
	"""
	from container_depot.xlsx_utils import cargo_sheet, finish_sheet, new_sheet

	headers = ["Container", "Last Cargo"]
	output, wb, ws, fmts = new_sheet("Template", headers, [24, 28])
	ws.write_row(1, 0, ["ABCD1234567", ""])
	n_cargo = cargo_sheet(wb, fmts)
	if n_cargo:
		# Range, not an inline list: Excel caps an inline source at 255 characters, and the
		# cargo master is far past that.
		ws.data_validation(
			1, 1, 1000, 1, {"validate": "list", "source": f"=Cargo!$A$2:$A${n_cargo + 1}"}
		)
	finish_sheet(output, wb, ws, "container_email_template.xlsx", 1, len(headers) - 1)


@frappe.whitelist()
def parse_container_file(file_url: str, principal: str | None = None) -> dict:
	"""Read an uploaded .xlsx into dialog grid rows: ``Container`` , ``Last Cargo``.

	Deliberately its own parser rather than the booking grid's ``parse_container_xlsx``:
	that one reads column B as the line's *condition* and drops any row whose value is not
	one of the three conditions — which is exactly what a file listing cargo would hit. The
	dialog asks for the two things an email actually states, so it reads those two.

	A number with no Container master is **refused**, not imported: a spreadsheet is exactly
	where a typo'd tank number comes from, and letting one through would either mint a
	phantom master or ride along as a number nobody can act on. Those numbers come back in
	``skipped`` so the operator is told which lines did not make it, and creating the master
	is a deliberate step taken in Container (or "+ Create New" on the picker) — never a
	side effect of reading a file.

	``principal`` is the owner the operator answered for in the dialog, and it is what the
	file is judged against: a tank the master says belongs to somebody else is not this
	job's to move, so it comes back in ``refused`` — named, with the owner — instead of
	landing on the order for the save to reject. The check mirrors
	``container_booking._import_block``, ownership half: a **blank** owner on the master
	passes (nothing to contradict), and a blank ``principal`` here checks nothing at all,
	which is what keeps scripted callers and the mail scan working unchanged. The desk
	dialog makes it mandatory, because an import is the one door into the grid that never
	passes the Container picker's owner filter.

	Pure read, like everything else in the prefill path. An unknown cargo is milder: the
	tank is real, so the row is kept with the cargo left blank and the spelling reported in
	``errors``.
	"""
	from frappe.utils.xlsxutils import read_xlsx_file_from_attached_file

	if not file_url:
		frappe.throw(_("Belum ada file yang dipilih."))

	rows, skipped, errors, refused, seen = [], [], [], [], set()
	for cells in read_xlsx_file_from_attached_file(file_url=file_url) or []:
		if not cells:
			continue
		number = _normalise(str(cells[0])) if cells[0] is not None else ""
		if not number or number.lower() in _FILE_HEADERS:
			continue
		if number in seen:
			continue
		seen.add(number)
		master = frappe.db.get_value(
			"Container", {"container_no": number}, ["name", "principal"], as_dict=True
		)
		if not master:
			skipped.append(number)
			continue
		if principal and master.principal and master.principal != principal:
			refused.append(
				_("{0}: milik principal lain ({1})").format(number, master.principal)
			)
			continue
		raw_cargo = str(cells[1]).strip() if len(cells) > 1 and cells[1] is not None else ""
		cargo = None
		if raw_cargo:
			cargo = frappe.db.get_value("Cargo", {"cargo_name": raw_cargo})
			if not cargo:
				errors.append(_("{0}: cargo tidak dikenal ({1})").format(number, raw_cargo))
		rows.append({"container_no": number, "container": master.name, "cargo": cargo})
	return {"rows": rows, "skipped": skipped, "errors": errors, "refused": refused}


def _unanimous(rows: list[dict], key: str) -> str | None:
	"""The one value shared by every resolved container, or None when they disagree.

	Used to seed depot / principal: five tanks of the same owner should not make the
	operator pick that owner by hand, but a mixed list must not guess.
	"""
	values = {r.get(key) for r in rows if r.get(key)}
	return values.pop() if len(values) == 1 else None


def _resolve_customer(email: str | None) -> str | None:
	"""Best-effort: find the Customer behind a sender email via its Contact.

	Returns None (never raises) when nothing matches — the operator then picks the
	Customer by hand on the new order.
	"""
	if not email:
		return None
	email = email.strip().lower()
	contacts = frappe.get_all(
		"Contact Email", filters={"email_id": ("like", email)}, pluck="parent"
	)
	for contact in contacts:
		customer = frappe.db.get_value(
			"Dynamic Link",
			{
				"parent": contact,
				"parenttype": "Contact",
				"link_doctype": "Customer",
			},
			"link_name",
		)
		if customer:
			return customer
	return None


def _email_reference(comm) -> str:
	"""Human-readable provenance line stuffed into the order's remarks/notes."""
	body = _email_text(comm.content).strip()
	if len(body) > _SNIPPET_LEN:
		body = body[:_SNIPPET_LEN].rstrip() + "…"
	lines = [
		_("Dibuat dari email:"),
		_("Subjek: {0}").format(comm.subject or "-"),
		_("Dari: {0}").format(comm.sender or "-"),
		_("Tanggal: {0}").format(comm.communication_date or comm.creation or "-"),
	]
	if body:
		lines += ["", body]
	return "\n".join(lines)


def _child_rows(doctype: str, direction: str, rows: list[dict], options: dict) -> list[dict]:
	"""Build the container child rows for the booking.

	A row carries the ``container`` link when the master exists and always carries
	``container_no``; a Tank In booking turns a bare number into a pre-arrival master on
	save. The direction-level extras (condition, unload date, load date) are the row's own
	*mandatory* fields — asking for them once in the dialog beats filling the same value into
	twenty grid rows by hand.
	"""
	# Keyed by DIRECTION, not by doctype: both order types are a Container Booking now, and
	# what a line needs is exactly what its direction is about — the day the tank is unloaded
	# or the day it is loaded. Asking for it once in the dialog beats typing the same date
	# into twenty grid rows.
	defaults: dict[str, dict] = {
		"Tank In": {
			# Condition is mandatory on a booking line but is not something an email states,
			# so every row starts Empty Dirty and is corrected on the booking form itself —
			# which is why the dialog does not ask for it.
			"condition": "EMPTY DIRTY",
			"tanggal_bongkar": options.get("tanggal_bongkar"),
		},
		"Tank Out": {"tanggal_muat": options.get("tanggal_muat")},
	}[direction]

	out = []
	for row in rows:
		child = {"container_no": row["container_no"]}
		if row["container"]:
			child["container"] = row["container"]
		child.update({k: v for k, v in defaults.items() if v})
		# What the grid carries per row (picked there, or read out of the imported file),
		# and only onto a doctype whose lines actually have the field.
		child.update({k: row[k] for k in _PER_ROW_FIELDS.get(doctype, ()) if row.get(k)})
		out.append(child)
	return out


@frappe.whitelist()
def get_order_prefill(communication: str, order_type: str, containers=None, options=None) -> dict:
	"""Return {doctype, values, table} to seed a new order form from an email.

	Read-only: creates nothing. The client opens a fresh order form pre-filled with these
	values (customer resolved from sender, email content copied into remarks, source email
	linked via the read-only `reff_email`) plus one container row per number the operator
	listed, so a ten-tank email becomes a ten-line booking in one step.

	``table`` is None only when no container was listed at all — opening a blank order form
	from an email is allowed.
	"""
	target = ORDER_MAP.get(order_type)
	if not target:
		frappe.throw(_("Tipe order tidak dikenal: {0}").format(order_type))
	doctype, customer_field, direction = target

	frappe.has_permission("Communication", "read", doc=communication, throw=True)
	if not frappe.has_permission(doctype, "create"):
		frappe.throw(
			_("Anda tidak punya izin membuat {0}.").format(_(doctype)),
			frappe.PermissionError,
		)

	comm = frappe.get_doc("Communication", communication)
	options = frappe.parse_json(options) if isinstance(options, str) else (options or {})
	rows = _rows_for(containers)

	values: dict = {
		_NOTE_FIELD[doctype]: _email_reference(comm),
		_EMAIL_REF_FIELD: comm.name,
	}
	if customer_field:
		values[customer_field] = _resolve_customer(comm.sender) or _unanimous(rows, "principal")
		if not values[customer_field]:
			values.pop(customer_field)

	# The Tank Owner picked in the dialog (where it also scopes the container picker). An
	# explicit pick beats both the sender lookup and the unanimous guess — and on a Tank In
	# booking it is who the pre-arrival Container masters are born under. Only where the
	# field is a real party Link: on an M&R `principal` is a Data mirror of the container's.
	principal_df = frappe.get_meta(doctype).get_field("principal")
	if options.get("principal") and principal_df and principal_df.fieldtype == "Link":
		values["principal"] = options["principal"]

	# The depot is the same for every tank in a normal email; a mixed list is left blank.
	depot = _unanimous(rows, "depot")
	if depot and frappe.get_meta(doctype).has_field("depot"):
		values["depot"] = depot
	# The order type already decides the direction (Booking = Tank In, Gate Out = Tank Out).
	# The dialog may still override it for the inbound type, which is where the operator
	# picks between the two by hand.
	values["direction"] = options.get("direction") or direction
	direction = values["direction"]
	# The customer's own document number for this job, as printed on the mail. This is the
	# one place it may be written from here: `reff_doc` is hand-entered by design (it
	# propagates booking → bon → EIR → Cleaning / M&R), and the operator is typing it — the
	# email link itself still lives in the read-only `reff_email`.
	if options.get("reff_doc") and frappe.get_meta(doctype).has_field("reff_doc"):
		values["reff_doc"] = options["reff_doc"]

	table = None
	fieldname = _CONTAINER_TABLE.get(doctype)
	if fieldname and rows:
		table = {
			"fieldname": fieldname,
			"doctype": frappe.get_meta(doctype).get_field(fieldname).options,
			"rows": _child_rows(doctype, direction, rows, options),
		}

	return {"doctype": doctype, "values": values, "table": table}


@frappe.whitelist()
def linked_orders(communication: str) -> list[dict]:
	"""Orders created from this email — everything whose ``reff_email`` points at it.

	The link is written once by ``get_order_prefill`` and is read-only afterwards, but it
	was only ever visible from the order side: standing on the email you could not tell
	whether it had already been turned into work, or into how many orders. This answers that
	from the Communication form (see ``public/js/communication.js``).

	Covers every order type that ever had this bridge, not just the two it can raise today
	(see ``_ORDER_SUMMARY``) — an email that became a Cleaning Order last year still says so.

	Ordered by order type, then newest first. Read permission is checked per doctype and the
	rows go through ``get_list``, so a user is never shown an order they could not open.
	"""
	frappe.has_permission("Communication", "read", doc=communication, throw=True)

	out = []
	for doctype, (state_field, subtitle_field) in _ORDER_SUMMARY.items():
		if not frappe.has_permission(doctype, "read"):
			continue
		rows = frappe.get_list(
			doctype,
			filters={_EMAIL_REF_FIELD: communication},
			fields=["name", f"{state_field} as state", f"{subtitle_field} as subtitle"],
			order_by="creation desc",
		)
		out.extend({"doctype": doctype, **r} for r in rows)
	return out


@frappe.whitelist()
def pull_my_emails() -> dict:
	"""Pull new mail for the incoming Email Accounts set on the current user.

	Desk mirror of the Email Account "Pull Emails" button, but scoped to the accounts
	linked under the user's ``User Emails`` — so each operator only fetches their own
	inbox (nothing configured → a clear message, no error).
	"""
	user = frappe.session.user
	accounts = frappe.get_all("User Email", filters={"parent": user}, pluck="email_account")
	incoming = [
		a
		for a in dict.fromkeys(accounts)  # dedupe, keep order
		if a and frappe.db.get_value("Email Account", a, "enable_incoming")
	]
	if not incoming:
		frappe.msgprint(
			_("Belum ada Email Account (incoming) yang di-set di user Anda. "
			  "Set di User → Settings → Email Inbox terlebih dahulu."),
			title=_("Tarik Email"),
		)
		return {"pulled": [], "failed": []}

	pulled, failed = [], []
	for account in incoming:
		try:
			frappe.get_doc("Email Account", account).receive()
			pulled.append(account)
		except Exception:
			failed.append(account)
			frappe.log_error(
				title=f"pull_my_emails: {account}",
				message=frappe.get_traceback(),
			)

	if pulled:
		frappe.msgprint(
			_("Email ditarik dari: {0}").format(", ".join(pulled)),
			title=_("Tarik Email"),
			indicator="green",
		)
	if failed:
		frappe.msgprint(
			_("Gagal menarik dari: {0}. Cek konfigurasi/kata sandi akun tersebut.").format(
				", ".join(failed)
			),
			title=_("Tarik Email"),
			indicator="orange",
		)
	return {"pulled": pulled, "failed": failed}
