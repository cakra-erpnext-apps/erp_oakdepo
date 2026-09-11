"""Shared writer for the Container Activity timeline.

Every business action against a container (gate, EIR, cleaning, certificate,
repair, release, orders, booking) calls
:func:`log_container_activity` from its finalize hook (usually ``on_submit``).
The rich source doctype keeps the detail; this writes one thin, append-only
row that links back to it — giving monitoring a single chronological feed.

Kept dependency-light (only ``frappe``) because ~10 controllers import it, and
deliberately resilient: a logging failure is swallowed (logged to the Error Log)
so it can never break the primary action it is recording.
"""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime


def log_container_activity(
	container,
	activity_type,
	*,
	reference_doctype=None,
	reference_name=None,
	from_status=None,
	to_status=None,
	summary=None,
	performed_by=None,
	activity_time=None,
):
	"""Append one Container Activity row. Never raises — best-effort audit.

	``principal`` / ``depot`` are denormalized from the Container so the feed can
	be filtered by owner / depot without a join.
	"""
	if not container:
		return None
	try:
		principal, depot = frappe.db.get_value("Container", container, ["principal", "depot"]) or (None, None)
		doc = frappe.get_doc({
			"doctype": "Container Activity",
			"container": container,
			"activity_time": activity_time or now_datetime(),
			"activity_type": activity_type,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"from_status": from_status,
			"to_status": to_status,
			"summary": summary,
			"performed_by": performed_by or frappe.session.user,
			"principal": principal,
			"depot": depot,
		})
		doc.insert(ignore_permissions=True)
		return doc.name
	except Exception:
		# Audit logging must never break the action it records.
		frappe.log_error(frappe.get_traceback(), "container_depot Container Activity log failed")
		return None


def count_gate_movements(filters: dict, types=("Gate In", "Gate Out")) -> dict:
	"""Berapa tank masuk / keluar, dengan yang DIBATALKAN tidak ikut terhitung.

	``filters`` adalah saringan biasa untuk Container Activity (rentang waktu + scope depot);
	kuncinya di kembaliannya adalah ``activity_type``.

	Kenapa butuh fungsi sendiri: Container Activity itu log append-only — membatalkan bon
	tidak menghapus baris "Gate In"-nya, ia hanya membuat Gate Entry yang dirujuknya
	berstatus ``Cancelled`` (``Order Bongkar._release_gate_in`` / ``GateEntry.on_cancel``).
	Jadi menghitung barisnya mentah-mentah menjawab "berapa truk yang sempat dicatat", bukan
	"berapa tank yang benar-benar masuk hari ini" — dan satu kedatangan yang salah bon lalu
	dibatalkan akan tetap duduk di angka hari itu selamanya.

	Dikerjakan dua langkah, bukan join: yang dibaca cuma pergerakan satu hari (puluhan baris),
	dan hanya Gate Entry yang benar-benar dirujuk hari itu yang ditanyakan statusnya — beda
	dengan menarik seluruh daftar Gate Entry yang dibatalkan sepanjang sejarah depo.
	"""
	rows = frappe.get_all(
		"Container Activity",
		filters={**filters, "activity_type": ["in", list(types)]},
		fields=["activity_type", "reference_doctype", "reference_name"],
	)
	refs = {r.reference_name for r in rows if r.reference_doctype == "Gate Entry" and r.reference_name}
	voided = (
		set(
			frappe.get_all(
				"Gate Entry",
				filters={"name": ["in", list(refs)], "status": "Cancelled"},
				pluck="name",
			)
		)
		if refs
		else set()
	)
	counts = {t: 0 for t in types}
	for r in rows:
		# Baris tanpa rujukan Gate Entry (data lama) tetap dihitung: tidak ada yang bisa
		# membantahnya, dan menganggapnya batal akan menghilangkan kedatangan yang nyata.
		if r.reference_name in voided:
			continue
		counts[r.activity_type] = counts.get(r.activity_type, 0) + 1
	return counts


def log_doc_note(doctype, name, message) -> None:
	"""Append one timeline comment to a document — best-effort, never raises.

	Companion to :func:`log_container_activity` for the deliberate raw-write paths
	(``db_set`` / ``frappe.db.set_value``) that bypass the document layer: those leave no
	``Version`` row, so without this the change is invisible on the order's own timeline.
	Prefer ``doc.save()`` where it is safe — reach for this only when saving is impossible
	(docstatus flips, non-``allow_on_submit`` fields on a submitted doc).
	"""
	try:
		frappe.get_doc({
			"doctype": "Comment",
			"comment_type": "Comment",
			"comment_email": frappe.session.user,
			"reference_doctype": doctype,
			"reference_name": name,
			"content": message,
		}).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"container_depot timeline note failed: {doctype} {name}")


# ---------------------------------------------------------------------------
# Voided rows: an action whose source document was later cancelled.
# ---------------------------------------------------------------------------
# The timeline is APPEND-ONLY, and it has to stay that way — it is the depot's record of
# what was done, and "the EIR says X but somebody voided it afterwards" is exactly the
# argument the depot cannot win without one. So a cancel never deletes or rewrites the row
# it undoes.
#
# But an unmarked row reads as a fact: a voided EIR-Out still says "Gate-out / load
# complete", and a reader scrolling the feed has no way to know the tank never went. So the
# void is shown ON the row instead — DERIVED from the source document every time it is read,
# never stored here.
#
# Derived rather than stamped for the same reason ``last_orders`` recomputes its pointers
# from source: a flag written at cancel time has to be written from every cancel path
# (there are eight), backfilled for everything already logged, and can silently drift. A
# question answered from the source document cannot go stale, and needs no migration.
#
# How a source says "I am void", per doctype. Submittable ones answer with docstatus 2; the
# two that are not submittable (and the ones that carry a terminal status alongside their
# docstatus) answer with a status field.
_VOID_STATUS_FIELD = {
	"Inspection": "status",
	"Cleaning Order": "status",
	"Repair Order": "status",
	"Gate Entry": "status",
	"Container Booking": "booking_status",
}
_VOID_STATUS = "Cancelled"


def _voided_names(doctype: str, names: list[str]) -> set:
	"""Which of ``names`` are cancelled — one query per doctype, whatever the row count.

	A name that no longer resolves is NOT counted: the app refuses to delete the documents
	that log activity (``on_trash`` throws on bons and bookings), so a missing row means
	maintenance or a purged test fixture, and reading that as "cancelled" would put a badge
	on history nobody voided.
	"""
	if not names:
		return set()
	try:
		meta = frappe.get_meta(doctype)
	except Exception:
		return set()
	or_filters = {}
	if meta.is_submittable:
		or_filters["docstatus"] = 2
	field = _VOID_STATUS_FIELD.get(doctype)
	if field and meta.has_field(field):
		or_filters[field] = _VOID_STATUS
	if not or_filters:
		return set()
	return set(
		frappe.get_all(
			doctype, filters={"name": ["in", names]}, or_filters=or_filters, pluck="name"
		)
	)


def annotate_voided(rows) -> list:
	"""Stamp ``voided`` on every row whose source document has been cancelled.

	Mutates and returns ``rows`` (dicts). Rows with no source document — a bare status
	change — are never void: there is nothing that could have been undone.
	"""
	rows = rows or []
	by_doctype: dict[str, set] = {}
	for row in rows:
		doctype, name = row.get("reference_doctype"), row.get("reference_name")
		if doctype and name:
			by_doctype.setdefault(doctype, set()).add(name)
	voided = {dt: _voided_names(dt, list(names)) for dt, names in by_doctype.items()}
	for row in rows:
		row["voided"] = bool(
			row.get("reference_name") in voided.get(row.get("reference_doctype"), ())
		)
	return rows


# ---------------------------------------------------------------------------
# Riwayat (history): read the Container Activity timeline.
# ---------------------------------------------------------------------------
def list_activity_history(start=0, page_length=10, search=None, container=None) -> dict:
	"""Container Activity timeline (Gate / EIR / Cleaning / Repair / Status… events) — the
	PWA Monitor "Riwayat" feed, newest first, paginated + searchable, depot-scoped to the
	caller's branch. (``Container.name == container_no``, so search matches the number.)"""
	from frappe.utils import cint
	from container_depot.container_depot.user_branch import get_user_depots

	filters = {}
	depots = get_user_depots()
	if depots is not None:
		filters["depot"] = ["in", depots or [""]]
	# Satu tank saja — jejak yang dibaca dari kartu detail container. Filter, bukan endpoint
	# tersendiri: pertanyaannya sama ("apa yang terjadi"), yang berbeda cuma cakupannya, dan
	# dua fungsi berarti dua urutan yang bisa menyimpang diam-diam.
	container = (container or "").strip()
	if container and container.lower() not in ("undefined", "null", "none"):
		filters["container"] = container
	or_filters = None
	search = (search or "").strip()
	if search and search.lower() not in ("undefined", "null", "none"):
		or_filters = {"container": ["like", f"%{search}%"], "summary": ["like", f"%{search}%"]}
	items = frappe.get_all(
		"Container Activity", filters=filters, or_filters=or_filters,
		fields=["name", "container", "activity_type", "from_status", "to_status",
			"reference_doctype", "reference_name", "performed_by", "summary",
			"activity_time", "depot", "principal"],
		order_by="activity_time desc",
		limit_start=cint(start), limit_page_length=cint(page_length),
	)
	return {
		"items": annotate_voided(items),
		"total": frappe.db.count("Container Activity", filters),
	}


def get_activity_detail(name) -> dict:
	"""One Container Activity record (the action + its source-doc link), branch-guarded."""
	from container_depot.container_depot.user_branch import assert_in_user_branch

	if not name:
		frappe.throw("name is required.")
	a = frappe.get_doc("Container Activity", name)
	assert_in_user_branch(depot=a.depot)
	return annotate_voided([{
		"name": a.name,
		"container": a.container,
		"activity_type": a.activity_type,
		"from_status": a.from_status,
		"to_status": a.to_status,
		"reference_doctype": a.reference_doctype,
		"reference_name": a.reference_name,
		"performed_by": a.performed_by,
		"summary": a.summary,
		"activity_time": str(a.activity_time) if a.activity_time else None,
		"depot": a.depot,
		"principal": a.principal,
	}])[0]
