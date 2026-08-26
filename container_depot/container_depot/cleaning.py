"""Core cleaning logic for the PWA Cleaning Order flow.

Mirrors ``container_depot/eir.py``: deliberately free of ``@frappe.whitelist`` so the
same functions back both the ESS PWA wrappers (``ess/cleaning.py``) and any Desk /
automation caller — the endpoint layer only adds auth + whitelisting.

Flow: EIR (Empty Dirty) -> Cleaning Order (auto-created, Pending) -> the team starts
it (In_Progress) -> signs off and submits -> Completed. A submitted Completed order IS
the TANK OUT proof; the sign-off detail (remarks + surveyor signature) lives on it.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, now_datetime, today

from container_depot.container_depot.exceptions import AlreadySettled
from container_depot.container_depot.work_claim import filter_claimed, guard_claim
from container_depot.container_depot.worklist import sort_by_priority
from container_depot.container_depot.user_branch import assert_in_user_branch, get_user_branches

# Tank-spec fields read from the Container master for the form header + print.
_CONTAINER_FIELDS = [
	"name", "container_no", "container_type", "manufacture_date", "last_test_date",
	"tare_weight", "max_gross_weight", "capacity", "principal", "last_cargo",
	"depot",
]


def _guard_container_branch(container_name) -> None:
	"""Block cleaning actions on a container outside the user's branch."""
	depot = frappe.db.get_value("Container", container_name, "depot")
	assert_in_user_branch(depot=depot)


def get_cleaning_masters() -> dict:
	"""Master defaults for the PWA cleaning form (none for now — remarks start blank)."""
	return {}


def _latest_eir(container: str) -> str | None:
	"""The newest submitted EIR for the container (the cleaning's source / anchor)."""
	return frappe.db.get_value(
		"Inspection",
		{"container": container, "docstatus": 1, "inspection_type": ["in", ["EIR-In", "EIR-Out"]]},
		"name",
		order_by="creation desc",
	)


def _default_place_of_issue(user, depot) -> str | None:
	"""Branch default for ``place_of_issue`` — the user's first branch, else the depot."""
	branches = get_user_branches(user)
	if branches:
		return branches[0]
	return depot


def cargo_history(container, limit=4) -> list:
	"""The container's recent cargo history, straight from its submitted EIRs — newest to
	oldest, capped at ``limit`` (default 4).

	The EIR is where a cargo is recorded (and written back to ``Container.last_cargo`` on
	submit), so it is the source of truth. An EIR-Out normally carries the container's
	current cargo forward unchanged, which would repeat the EIR-In that recorded it —
	consecutive repeats of the same cargo are collapsed into one entry.
	"""
	limit = cint(limit) or 4
	rows = frappe.get_all(
		"Inspection",
		filters={
			"container": container,
			"docstatus": 1,
			"cargo": ["is", "set"],
			"inspection_type": ["in", ["EIR-In", "EIR-Out"]],
		},
		fields=["cargo", "eir_date", "creation"],
		order_by="eir_date desc, creation desc",
		limit_page_length=limit * 4,  # room to collapse in/out repeats before capping
	)
	history = []
	for r in rows:
		if history and history[-1]["cargo"] == r.cargo:
			continue  # same cargo carried forward by the next EIR — one entry is enough
		history.append({"cargo": r.cargo, "date": str(r.eir_date or r.creation)[:10]})
		if len(history) == limit:
			break
	return history


def list_open_cleaning_orders(start=0, page_length=20, search=None) -> dict:
	"""Open Cleaning Orders (Pending / In_Progress) the cleaning team still has to
	work — the PWA Cleaning menu's worklist. Depot-scoped to the caller's branch."""
	from container_depot.container_depot.user_branch import get_user_depots

	filters = {"status": ["in", ["Pending", "In_Progress"]], "docstatus": 0}
	depots = get_user_depots()
	if depots is not None:
		filters["depot"] = ["in", depots or [""]]  # restricted user: only their depots
	or_filters = None
	search = (search or "").strip()
	if search and search.lower() != "undefined":  # guard the literal "undefined" string
		or_filters = {"container_no": ["like", f"%{search}%"], "order_id": ["like", f"%{search}%"]}
	items = frappe.get_all(
		"Cleaning Order",
		filters=filters,
		or_filters=or_filters,
		# container_principal: the tank OWNER, shown next to the container number in the
		# worklist — two tanks in the queue are told apart by whose they are.
		# assigned_to: who pressed "Mulai". Not shown on the row — it is what hides an order
		# already being washed from everyone else's worklist (see work_claim).
		fields=["name", "order_id", "container", "container_no", "container_principal", "status",
			"cleaning_type", "last_cargo", "depot", "target_lift_on", "order_created", "assigned_to"],
		order_by="order_created asc",
		limit_page_length=0,
	)
	items = filter_claimed(items, "assigned_to")
	total = len(items)
	# Gate-out priority, then the wash already in this operator's hands, then the rest —
	# see ``worklist.sort_by_priority`` for why that order.
	items = sort_by_priority(items, lambda r: r.get("status") == "In_Progress", start, page_length)
	# Number of chosen cleaning services per order (NOT the price — hidden from the depot PWA).
	names = [i.name for i in items]
	if names:
		from collections import Counter

		counts = Counter(frappe.get_all("Cleaning Order Service", filters={"parent": ["in", names]}, pluck="parent"))
		for i in items:
			i["service_count"] = counts.get(i.name, 0)
	return {"items": items, "total": total}


def list_cleaning_history(start=0, page_length=10, search=None) -> dict:
	"""Finished Cleaning Orders (Completed / Cancelled) — the PWA Cleaning "Riwayat" feed,
	newest first, paginated + searchable, depot-scoped to the caller's branch. Detail reuses
	``get_cleaning_order_detail``."""
	from container_depot.container_depot.user_branch import get_user_depots

	filters = {"status": ["in", ["Completed", "Cancelled"]]}
	depots = get_user_depots()
	if depots is not None:
		filters["depot"] = ["in", depots or [""]]
	or_filters = None
	search = (search or "").strip()
	if search and search.lower() != "undefined":
		or_filters = {"container_no": ["like", f"%{search}%"], "order_id": ["like", f"%{search}%"]}
	items = frappe.get_all(
		"Cleaning Order",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "order_id", "container", "container_no", "container_principal", "status",
			"cleaning_type", "last_cargo", "depot", "cleaning_end", "order_created",
			"revision_requested"],
		order_by="creation desc",
		limit_start=cint(start),
		limit_page_length=cint(page_length),
	)
	names = [i.name for i in items]
	if names:
		from collections import Counter

		counts = Counter(frappe.get_all("Cleaning Order Service", filters={"parent": ["in", names]}, pluck="parent"))
		for i in items:
			i["service_count"] = counts.get(i.name, 0)
	return {"items": items, "total": frappe.db.count("Cleaning Order", filters)}


def start_cleaning(cleaning_order):
	"""Move a Cleaning Order from Pending to In_Progress (the team has started work) and
	mirror it onto the container (-> Cleaning_In_Progress). The order stays a draft — it
	is only submitted (Completed) when the operator signs it off."""
	co = frappe.db.get_value(
		"Cleaning Order", cleaning_order, ["name", "container", "status", "docstatus"], as_dict=True
	)
	if not co:
		frappe.throw(_("Cleaning Order {0} not found.").format(cleaning_order))
	if co.docstatus == 1 or co.status == "Completed":
		frappe.throw(_("Cleaning Order sudah selesai."), exc=AlreadySettled)
	if co.status == "Pending Review":
		frappe.throw(
			_("Cleaning Order sudah dikirim untuk review. Tarik kembali dulu kalau mau diperbaiki."),
			exc=AlreadySettled,
		)
	_guard_container_branch(co.container)
	# First press wins — see work_claim.
	claim = frappe.db.get_value("Cleaning Order", co.name, ["assigned_to", "order_id"], as_dict=True)
	guard_claim(claim.assigned_to, _("Cleaning Order {0}").format(claim.order_id or co.name))

	if co.status != "In_Progress":
		# doc.save() and not db.set_value: Cleaning Order tracks changes, and only the
		# document path writes the Version row that puts "Mulai" on the order's timeline.
		doc = frappe.get_doc("Cleaning Order", co.name)
		doc.status = "In_Progress"
		doc.cleaning_start = now_datetime()
		# Who is doing the work is whoever pressed "Mulai" here — not whoever raised the
		# order in Desk. Same rule as the EIR's inspector (see Inspection.work_started_by),
		# and it is what the container's Cleaning activity is later attributed to.
		doc.assigned_to = frappe.session.user
		doc.save()  # NOT ignore_permissions — same rule as complete(): the caller holds write.
	# An open cleaning order keeps the tank In_Depot.
	from container_depot.container_depot.container_status import recompute_availability

	recompute_availability(co.container)

	from container_depot.container_depot.container_activity import log_container_activity

	# Read after recompute_availability: this is the tank's status now, not the one it
	# carried when the order was picked up.
	container_status = frappe.db.get_value("Container", co.container, "status")
	log_container_activity(
		co.container, "Cleaning",
		reference_doctype="Cleaning Order", reference_name=co.name,
		to_status=container_status, summary="Cleaning started (In Progress)",
	)
	return {"success": True, "name": co.name, "status": "In_Progress", "container_status": container_status}


def list_review_cleaning_orders(start=0, page_length=20, search=None) -> dict:
	"""Cleaning Orders awaiting Admin Ops review — the PWA "Diajukan Review" list.

	These were finished in the field: docstatus 0, status "Pending Review", not yet
	finalized. Depot-scoped to the caller's branch exactly like the worklist (NOT
	owner-scoped: a cleaning order is auto-created from an EIR, so it is rarely owned by the
	operator who washed the tank). Newest first, searchable by container no / order id.
	"""
	from container_depot.container_depot.user_branch import get_user_depots

	filters = {"status": "Pending Review", "docstatus": 0}
	depots = get_user_depots()
	if depots is not None:
		filters["depot"] = ["in", depots or [""]]
	or_filters = None
	search = (search or "").strip()
	if search and search.lower() != "undefined":
		or_filters = {"container_no": ["like", f"%{search}%"], "order_id": ["like", f"%{search}%"]}
	items = frappe.get_all(
		"Cleaning Order",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "order_id", "container", "container_no", "container_principal", "status",
			"last_cargo", "depot", "cleaning_end", "order_created"],
		order_by="cleaning_end desc, creation desc",
		limit_start=cint(start),
		limit_page_length=cint(page_length),
	)
	return {"items": items, "total": frappe.db.count("Cleaning Order", filters)}


def withdraw_review(cleaning_order) -> dict:
	"""Operator pulls a "Pending Review" order back so they can fix it — before Admin Ops
	finalizes it. No Admin Ops needed: the order returns to the worklist as In_Progress and
	goes back through "Kirim untuk Review" when it is right.

	Depot-scoped (not owner) to mirror the worklist: a cleaning order is auto-created from an
	EIR, so it is rarely owned by the operator who washed the tank. Only valid while the order
	is actually awaiting review (docstatus 0 + Pending Review).
	"""
	if not cleaning_order:
		frappe.throw(_("cleaning_order is required."))
	co = frappe.get_doc("Cleaning Order", cleaning_order)
	_guard_container_branch(co.container)
	if co.docstatus != 0 or co.status != "Pending Review":
		frappe.throw(_("Hanya order berstatus 'Menunggu Review' yang bisa ditarik untuk diperbaiki."))

	# Back to work-in-progress. cleaning_start stays (the wash did happen), cleaning_end is
	# cleared so the next "Kirim untuk Review" re-times the finish.
	co.status = "In_Progress"
	co.cleaning_end = None
	co.save()  # NOT ignore_permissions — the operator holds Cleaning Order write.
	return {"success": True, "name": co.name, "status": co.status}


@frappe.whitelist()
def revert_to_draft(name: str) -> dict:
	"""Return a submitted Cleaning Order to an editable draft (Desk-only action).

	This is the other half of the PWA's "Ajukan Revisi": the request only notifies Admin Ops,
	and THIS is where they act on it. The record is flipped back to ``In_Progress`` — the same
	document, not an amended copy — so it reappears in the operator's PWA worklist, can be
	corrected, and goes through review again.

	Also available WITHOUT a revision request: Admin Ops may spot the mistake themselves.

	Whitelisted here (this module is otherwise free of ``@frappe.whitelist`` — see the module
	docstring) because it is a Desk button with no ESS counterpart, exactly like
	:func:`container_depot.container_depot.eir.revert_to_draft`.
	"""
	from container_depot.container_depot.container_activity import log_container_activity, log_doc_note
	from container_depot.container_depot.container_status import recompute_availability

	doc = frappe.get_doc("Cleaning Order", name)
	# Un-submitting is cancelling: same permission, so this stays away from the field roles.
	doc.check_permission("cancel")
	if doc.docstatus != 1:
		frappe.throw(_("Hanya cleaning order yang sudah disubmit yang bisa dikembalikan ke draft."))
	# Billed work is settled work. Reopening it would let the wash be edited (or re-billed)
	# under an invoice that already went to the customer — cancel the invoice first.
	if doc.get("sales_invoice"):
		frappe.throw(_(
			"Cleaning order ini sudah masuk invoice {0}. Batalkan invoice-nya dulu sebelum "
			"dikembalikan ke draft."
		).format(doc.sales_invoice))

	# Back to work-in-progress: the wash is open again, so the tank is not free to leave.
	# cleaning_end is cleared so the next sign-off re-times the finish; the signature and
	# who did the work stay — before_submit only fills what is empty.
	frappe.db.set_value(
		"Cleaning Order", doc.name,
		{
			"docstatus": 0,
			"status": "In_Progress",
			"cleaning_end": None,
			"revision_requested": 0,
			"revision_note": None,
		},
	)
	# A backwards docstatus flip can never go through doc.save(), so no Version row is
	# written — put it on the order's timeline by hand.
	log_doc_note("Cleaning Order", doc.name, _(
		"Cleaning order dikembalikan ke draft oleh {0} (dari Completed)."
	).format(frappe.session.user))

	# Recomputed AFTER the flip: a still-submitted order is invisible to
	# ``container_open_orders``, so the tank would keep reading Available.
	recompute_availability(doc.container)

	# Inverse entry for the audit trail (the on_submit one stays — the log is append-only).
	# Never let a logging failure block the revert.
	try:
		log_container_activity(
			doc.container, "Cleaning",
			reference_doctype=doc.doctype, reference_name=doc.name,
			to_status=frappe.db.get_value("Container", doc.container, "status"),
			summary=_("Cleaning {0} dikembalikan ke draft").format(doc.order_id or doc.name),
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "cleaning revert_to_draft activity log")

	return {"name": doc.name, "docstatus": 0, "status": "In_Progress"}


def request_revision(cleaning_order, reason: str | None = None) -> dict:
	"""Operator asks Admin Ops to reopen a submitted Cleaning Order for revision.

	Mirrors :func:`container_depot.container_depot.eir.request_revision`. A submitted order
	can't be edited from the PWA, so this raises a REQUEST rather than touching the work: it
	drops an audit comment on the order's timeline, flags it so the Desk list shows "Revisi
	Diminta" with the reason, and notifies Admin Ops (+ ops oversight) in the container's
	branch. Reopening itself stays a human decision on the Desk side — cancelling the order
	clears the flag (``CleaningOrder.on_cancel``).
	"""
	from container_depot.container_depot import notify as _notify
	from container_depot.container_depot.container_activity import log_doc_note

	if not cleaning_order:
		frappe.throw(_("cleaning_order is required."))
	doc = frappe.get_doc("Cleaning Order", cleaning_order)
	if doc.docstatus != 1:
		frappe.throw(_("Hanya cleaning order yang sudah selesai (submitted) yang bisa diajukan revisi."))
	_guard_container_branch(doc.container)

	reason = (reason or "").strip()
	user = frappe.session.user
	note = _("Permintaan revisi cleaning oleh {0}").format(user)
	if reason:
		note += ": " + reason
	# Audit trail on the order's timeline (visible in Desk). Best-effort — the notification
	# is what matters, so a comment-permission hiccup must not fail the request.
	log_doc_note("Cleaning Order", doc.name, note)

	# Raw set_value: the order is submitted, and both fields are allow_on_submit.
	frappe.db.set_value(
		"Cleaning Order", doc.name, {"revision_requested": 1, "revision_note": note},
	)

	sent = _notify.notify_cleaning_revision_requested(doc.name, reason=reason)
	return {"success": True, "notified": sent, "cleaning_order": doc.name}


def _cleaning_item_options(container) -> list:
	"""Cleaning Service items the container's Owner (Principal) is priced for: members of the
	Depot Service Menu "Cleaning" that have a selling Item Price in the owner's active Price
	List. Drives the PWA "Metode Cleaning" picker. The owner's RATE is deliberately NOT
	exposed to the depot PWA (it's resolved + stored server-side for billing only). Empty
	when there is no principal / no price list."""
	from container_depot import pricing_model
	from container_depot.container_depot import service_menu

	principal = frappe.db.get_value("Container", container, "principal") if container else None
	price_list = pricing_model.price_list_for_customer(principal) if principal else None
	if not price_list:
		return []
	return [
		{"item_code": i["item_code"], "item_name": i.get("item_name")}
		for i in service_menu.items_in_menu("Cleaning", base_price_list=price_list)
	]


def get_cleaning_order_detail(cleaning_order) -> dict:
	"""Everything the PWA form needs for one Cleaning Order: the order's own cleanliness
	state, the tank spec from the Container master, recent cargo history and the issue
	defaults."""
	co = frappe.get_doc("Cleaning Order", cleaning_order)
	_guard_container_branch(co.container)
	# Only while the washing is actually running: a notification tap must not drop a second
	# operator into a form somebody else is filling in. Once it is sent for review or closed
	# the claim is over and the Riwayat detail stays readable to the whole branch.
	if co.status == "In_Progress":
		guard_claim(co.assigned_to, _("Cleaning Order {0}").format(co.order_id or co.name))
	c = frappe.db.get_value("Container", co.container, _CONTAINER_FIELDS, as_dict=True) or frappe._dict()
	user = frappe.session.user
	return {
		"name": co.name,
		"order_id": co.order_id,
		"status": co.status,
		"docstatus": co.docstatus,
		"container": co.container,
		"container_no": co.container_no or c.container_no,
		# A standing revision request — the Riwayat detail shows it instead of offering the
		# button a second time.
		"revision_requested": 1 if co.get("revision_requested") else 0,
		"revision_note": co.get("revision_note"),
		"inspection": co.inspection or _latest_eir(co.container),
		"cleaning_type": co.cleaning_type,
		# "Metode Cleaning" = one OR MORE billable Services from the Cleaning menu. The owner's
		# rate/total is NOT sent to the depot PWA (billing-only); ``cleaning_services`` is what's
		# chosen on this order, ``cleaning_items`` the full pickable catalogue for this owner.
		"cleaning_services": [
			{"item_code": r.cleaning_item, "item_name": r.item_name}
			for r in co.cleaning_services
		],
		"cleaning_items": _cleaning_item_options(co.container),
		# Free-text instruction Admin Ops leaves on the order — read-only for the operator.
		"cleaning_instructions": co.cleaning_instructions or "",
		"reff_doc": co.reff_doc,
		"remarks": co.remarks or "",
		# Who worked it and when — the Riwayat detail is the record of the job, so it shows
		# the same facts the Desk form keeps under "Sistem".
		"depot": co.depot,
		"assigned_to": co.assigned_to,
		"completed_by": co.completed_by,
		"cleaning_start": co.cleaning_start,
		"cleaning_end": co.cleaning_end,
		"order_created": co.order_created,
		# The signature is autosaved like any other field, so reopening the order has to bring
		# it back — otherwise a form restored from an autosave (or from the offline cache)
		# looks unsigned and the operator signs a second time.
		"signature": co.surveyor_signature or "",
		"signed_by": co.signed_by or user,
		"date_of_issue": co.date_of_issue or today(),
		"place_of_issue": co.place_of_issue or _default_place_of_issue(user, c.depot),
		# Tank spec (read-only, from the Container master).
		"tank_type": c.container_type,
		"date_of_manufacture": c.manufacture_date,
		"last_test_date": c.last_test_date,
		"tare": c.tare_weight,
		"mgw": c.max_gross_weight,
		"capacity": c.capacity,
		"client": c.principal,
		"previous_cargo": c.last_cargo,
		# Recent cargo history.
		"cargo_history": cargo_history(co.container),
		# QC photos already on the order (uploaded straight from the field phone).
		"qc_photos": [{"photo": r.photo, "caption": r.caption} for r in co.qc_photos],
	}


def _coerce_list(value) -> list:
	if isinstance(value, str):
		value = json.loads(value) if value.strip() else []
	return value or []


def _as_bool(value) -> bool:
	if isinstance(value, str):
		return value.strip().lower() in ("1", "true", "yes")
	return bool(value)


def save_cleaning_order(
	cleaning_order=None,
	cleaning_type=None,
	cleaning_items=None,
	reff_doc=None,
	remarks=None,
	signature=None,
	qc_photos=None,
	submit=False,
) -> dict:
	"""Save the cleanliness detail onto a Cleaning Order and, when ``submit`` is true, send it
	for review.

	``submit`` from the PWA does NOT finalize the order. Exactly like the EIR flow, the
	operator's "selesai" moves it to **Pending Review** (still docstatus 0) and pings Admin
	Ops; Admin Ops checks the work in Desk and does the real Submit, which is what stamps
	Completed and frees the tank. Until then the order stays open, so the container is still
	held In_Depot.

	Permissions are NOT bypassed."""
	if not cleaning_order:
		frappe.throw(_("cleaning_order is required."))
	co = frappe.get_doc("Cleaning Order", cleaning_order)
	if co.docstatus == 1:
		frappe.throw(_("Cleaning Order sudah selesai."), exc=AlreadySettled)
	# Already handed to Admin Ops. The offline queue's worst case is a sign-off that reaches
	# the server after the order was sent for review — AlreadySettled is what tells the PWA
	# to park that row instead of retrying it for ever (see frontend/src/data/outbox.js).
	if co.status == "Pending Review":
		frappe.throw(
			_("Cleaning Order sudah dikirim untuk review Admin Ops."), exc=AlreadySettled
		)
	_guard_container_branch(co.container)
	# The operator who started it owns the form until it leaves for review — an autosave that
	# only reaches the server later (offline queue) is checked here too.
	if co.status == "In_Progress":
		guard_claim(co.assigned_to, _("Cleaning Order {0}").format(co.order_id or co.name))

	# "Metode Cleaning" is now one OR MORE billable Service items (each priced from the
	# owner's Price List); the controller resolves every row's rate + the total. The legacy
	# free-text cleaning_type is still accepted for back-compat.
	if cleaning_items is not None:
		codes = _coerce_list(cleaning_items)
		seen, rows = set(), []
		for c in codes:
			code = (c.get("item_code") if isinstance(c, dict) else c) or ""
			code = code.strip()
			if code and code not in seen:
				seen.add(code)
				rows.append({"cleaning_item": code})
		co.set("cleaning_services", rows)
	if cleaning_type is not None:
		co.cleaning_type = cleaning_type
	# QC photos — uploaded straight from the field phone (file_url already saved).
	if qc_photos is not None:
		photos = []
		for p in _coerce_list(qc_photos):
			url = (p.get("photo") if isinstance(p, dict) else p) or ""
			url = url.strip()
			if url:
				caption = (p.get("caption") or "").strip() if isinstance(p, dict) else ""
				photos.append({"photo": url, "caption": caption})
		co.set("qc_photos", photos)
	# Optional reference doc (usually pre-filled from the EIR; editable here).
	if reff_doc is not None:
		co.reff_doc = reff_doc
	co.remarks = remarks if remarks is not None else co.remarks
	if signature:
		co.surveyor_signature = signature
	if not co.signed_by:
		co.signed_by = frappe.session.user
	if not co.date_of_issue:
		co.date_of_issue = today()
	if not co.place_of_issue:
		co.place_of_issue = _default_place_of_issue(frappe.session.user, co.depot)

	if _as_bool(submit):
		# Field work is over: stamp when it ended and who did it, then hand the order to
		# Admin Ops. before_submit leaves both alone (it only fills what is empty), so the
		# reviewer's Desk Submit cannot claim the operator's work as their own.
		if not co.cleaning_end:
			co.cleaning_end = now_datetime()
		if not co.completed_by:
			co.completed_by = frappe.session.user
		co.status = "Pending Review"
	co.save()  # NOT ignore_permissions — Frappe enforces Cleaning Order write on the caller.
	if _as_bool(submit):
		# The only signal the reviewers get. on_submit's own notification fires later, when
		# Admin Ops finalizes.
		from container_depot.container_depot.notify import notify_cleaning_pending_review

		notify_cleaning_pending_review(co)

	return {
		"success": True,
		"name": co.name,
		"order_id": co.order_id,
		"status": co.status,
		"docstatus": co.docstatus,
		"pending_review": bool(_as_bool(submit)),
	}
