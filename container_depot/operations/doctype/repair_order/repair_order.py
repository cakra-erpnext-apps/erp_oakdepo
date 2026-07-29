import frappe
from frappe.model.document import Document
import datetime
import hashlib

class RepairOrder(Document):
	def before_insert(self):
		"""Generate unique repair order ID + stamp the creation time (list column)."""
		self.repair_order_id = self.generate_repair_order_id()
		if not self.order_created:
			self.order_created = datetime.datetime.now()

	def generate_repair_order_id(self):
		"""Generate unique repair order ID"""
		timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
		unique = hashlib.md5(f"{timestamp}{frappe.generate_hash()[:10]}".encode()).hexdigest()[:8].upper()
		return f"RO-{unique}"

	def validate(self):
		self._validate_status_transition()
		self._validate_stock_available()

	def _validate_stock_available(self):
		"""A part may only sit on an M&R when its own gudang actually holds it.

		Placed in validate() so it covers every path — the Desk grid, the PWA, and
		``mr.save_mr_order`` alike. Closed orders are skipped: Completed has *already*
		issued its parts (on-hand is now lower by exactly that amount, so re-checking would
		always fail), and Cancelled / Rejected must stay closable whatever the stock says.
		"""
		if self.status in ("Completed", "Cancelled", "Rejected"):
			return
		from container_depot.operations.mr import assert_stock_available

		assert_stock_available(self)

	def _validate_status_transition(self):
		"""Enforce the owner-approval status machine (MR_TRANSITIONS). The transition
		functions in operations/mr.py drive these; a direct status edit that skips a step
		(e.g. Draft -> In Progress without approval) is rejected. New docs may start at
		Draft (the default) so EIR auto-create / tests can seed them."""
		from container_depot.operations.mr import MR_TRANSITIONS

		before = self.get_doc_before_save()
		if not before or before.status == self.status:
			return
		if self.status not in MR_TRANSITIONS.get(before.status, []):
			frappe.throw(
				frappe._("Tidak bisa mengubah status M&R dari {0} ke {1}.").format(before.status, self.status)
			)

	def before_save(self):
		"""Auto-fetch principal, calculate costs, and update container status"""
		self.fetch_principal_from_container()
		self.calculate_totals()
		self.stamp_on_hand()
		self.update_container_status()

	def stamp_on_hand(self):
		"""Fill each part row's Stok from **its own gudang**, so the grid shows what is still
		usable without opening the item picker.

		Written as text, not a number: a service must show BLANK, and a Float renders None as
		0,000 — which reads as "habis" on the very rows that can never run out. Stamped on
		every save; the Desk form also refreshes it live (see repair_order.js).
		"""
		from frappe.utils import flt

		from container_depot.operations.mr import _on_hand, row_warehouse

		for row in self.get("used_items") or []:
			if not (row.item and row.is_stock_item):
				row.on_hand = None
				continue
			wh = row_warehouse(self, row)
			row.on_hand = f"{flt(_on_hand(row.item, wh)):g}" if wh else None

	def on_update(self):
		# This order's new status is now persisted — flip the container In_Depot <->
		# Available based on whether any related order is still open.
		from container_depot.operations.container_status import recompute_availability

		recompute_availability(self.container)
		self._revoke_notifications_if_cancelled()

	def _revoke_notifications_if_cancelled(self):
		"""An M&R is not submittable, so Cancelled is its void — clear the "perlu
		perbaikan" / "menunggu persetujuan owner" prompts still in the bell.

		Rejected is deliberately NOT swept: the owner's refusal is an outcome the M&R
		team has to see, and ``notify_repair_order_decided`` announces it.
		"""
		before = self.get_doc_before_save()
		if before and before.status != self.status and self.status == "Cancelled":
			from container_depot.operations.notify import revoke

			revoke(self.doctype, self.name)

	def on_update_after_submit(self):
		self.on_update()

	def fetch_principal_from_container(self):
		"""Fetch principal from Container master record"""
		if self.container:
			principal = frappe.db.get_value("Container", self.container, "principal")
			if principal:
				self.principal = principal

	def owner_price_list(self):
		"""The selling Price List for this M&R's owner/principal — drives every rate
		(harga ikut Item Price per principal). None when the owner has no price list."""
		from container_depot.pricing_model import price_list_for_customer

		principal = self.principal or frappe.db.get_value("Container", self.container, "principal")
		return price_list_for_customer(principal) if principal else None

	def calculate_totals(self):
		"""Cost each Service & Parts line from the item alone:

		    Amount Item Rate    = quantity × item_rate
		    Total Cost (amount) = Amount Item Rate

		**Labour is not costed here.** It is charged on the invoice, which stamps every billed
		line with the manhour its contract books for that item and totals them once in the
		header (``invoicing.apply_manhour_charge``). That only works because an M&R is billed
		item by item — see ``consolidated_billing._mr_lines``. The ``manhour`` /
		``manhour_rate`` / ``manhour_amount`` fields are kept on the row (hidden) so historical
		orders keep their figures, but nothing recomputes or totals them.

		``quantity`` and ``item_rate`` are the ADJUSTABLE inputs (seeded from the owner's Item
		Price when a line is first added); the amounts are always derived here, so they stay
		read-only in the UI.

		Each line's currency follows its own Item Price, so a Repair Order can MIX currencies.
		Totals are therefore grouped by currency into the ``totals`` table (one row per
		currency); ``total_cost`` stays as the plain numeric sum (kept for the worklists /
		billing report that still read a single figure). The copied ``damages`` carry no cost."""
		from frappe.utils import flt

		from container_depot.pricing_model import item_rate_breakdown

		price_list = self.owner_price_list()
		# Fallback currency for a line whose item has no Item Price = the OWNER'S price-list
		# currency (i.e. the contract currency, e.g. USD for Bertschi), NOT the site default
		# (IDR). Otherwise an item missing from the price list silently drags the line — and
		# the empty grid — back to IDR even though the whole M&R is priced in the owner's
		# currency. Falls back to the site default only when the owner has no price list.
		default_currency = (
			(frappe.db.get_value("Price List", price_list, "currency") if price_list else None)
			or frappe.db.get_default("currency")
		)
		numeric_total = 0.0
		by_currency = {}

		from container_depot.operations.mr import default_warehouse

		for row in self.get("used_items") or []:
			row.is_stock_item = (
				1 if row.item and frappe.db.get_value("Item", row.item, "is_stock_item") else 0
			)
			# Jenis is an INPUT while the row is empty (it narrows the item picker), but once
			# an item is chosen the Item master is the truth — otherwise a row could claim to
			# be Jasa while holding a stock part, and skip the stock guard entirely.
			if row.item:
				row.line_type = "Part" if row.is_stock_item else "Jasa"
			if row.line_type == "Jasa":
				row.warehouse = None  # a service is not taken out of a gudang
			elif row.item and not row.warehouse:
				# Show the gudang actually used instead of leaving the column blank while the
				# stock silently comes from the branch default.
				row.warehouse = default_warehouse(self)
			breakdown = item_rate_breakdown(row.item, price_list) if row.item else {}
			# Currency always follows the item's own Item Price (fixes the old default-to-IDR).
			if row.item:
				row.currency = breakdown.get("currency") or row.currency or default_currency
			# Seed the adjustable rate from the owner's Item Price the first time a line is
			# added (a fresh line carries only item + qty); manual edits are kept afterwards.
			if row.item and not flt(row.item_rate):
				row.item_rate = breakdown.get("item_rate") or 0.0
			# Derived amounts (read-only in the UI). Labour is the invoice's job.
			row.item_amount = flt(row.quantity or 0.0) * flt(row.item_rate)
			row.amount = row.item_amount
			# Owner-rejected lines aren't repaired or billed — exclude from every total.
			if (row.get("decision") or "Pending") != "Rejected":
				numeric_total += row.amount
				cur = row.currency or default_currency
				by_currency[cur] = by_currency.get(cur, 0.0) + row.amount

		self.total_cost = numeric_total
		self.set("totals", [])
		for cur, amt in sorted(by_currency.items()):
			self.append("totals", {"currency": cur, "total": amt})

	def update_container_status(self):
		"""Update container's status and repair_status based on this Repair Order"""
		if not self.container:
			return

		before = self.get_doc_before_save()
		prev_status = before.status if before else None
		container_doc = frappe.get_doc("Container", self.container)

		# Only the informational repair_status hint is mirrored here — the main
		# Container.status is presence-based now and recomputed in on_update once this
		# order's new status is persisted (In_Depot while open, Available when done).
		if self.status in ("Draft", "Service Setup"):
			# Service Setup is still estimate-building (Admin Ops arranging it) — the owner
			# has not been asked yet, so it is not "awaiting approval".
			container_doc.repair_status = "Pending_Estimate"
		elif self.status in ("Pending Approval", "Revision Requested"):
			container_doc.repair_status = "Awaiting_Approval"
		elif self.status in ["Approved", "In Progress"]:
			container_doc.repair_status = "In_Progress"
		elif self.status == "Completed":
			container_doc.repair_status = "Completed"
		elif self.status in ("Cancelled", "Rejected"):
			container_doc.repair_status = "Not_Required"

		# Controller-driven status change: bypass the manual-transition guard.
		frappe.flags.in_status_automation = True
		try:
			container_doc.save(ignore_permissions=True)
		finally:
			frappe.flags.in_status_automation = False

		# Log a Repair milestone when the order is approved / progressed / finished.
		if self.status in ("Approved", "In Progress", "Completed") and self.status != prev_status:
			from container_depot.operations.container_activity import log_container_activity

			log_container_activity(
				self.container, "Repair",
				reference_doctype=self.doctype, reference_name=self.name,
				to_status=container_doc.status,
				performed_by=self.get("technician"),
				summary=f"Repair {self.status}" + (f" (cost {self.total_cost})" if self.get("total_cost") else ""),
			)


@frappe.whitelist()
def used_item_query(doctype, txt, searchfield, start, page_len, filters):
	"""Link-field query for the Repair Order "Used Items" item picker.

	Restricts the catalogue to exactly what the PWA M&R picker shows: members of the Depot
	Service Menu "Maintenance" that ALSO have a selling Item Price in the container owner's
	price list (the owner's contract rate card). So Desk and the PWA never offer different
	items, and Admin Ops can't pick a service the owner isn't priced/contracted for.
	Delegates to ``operations.mr.mr_item_search`` (same menu ∩ price-list logic); it falls
	back safely to all items only when the owner has no price list / the menu is unset.

	Each option carries a third column telling the two kinds apart at a glance — "Jasa" for
	a service (nothing to run out of) or the on-hand qty for a part, so the picker answers
	"can I still use this, and how many?" before the row is even added. Frappe joins the
	columns after the first into the option's description (desk/search.py
	``build_for_autosuggest``). Parts the row's own gudang cannot supply are already absent
	(``mr._out_of_stock_items``), so a shown qty is always usable.
	"""
	from frappe.utils import flt as _flt

	from container_depot.operations import mr

	filters = filters or {}
	res = mr.mr_item_search(
		search=txt,
		repair_order=filters.get("repair_order"),
		warehouse=filters.get("warehouse"),
		line_type=filters.get("line_type"),
		start=start,
		page_length=page_len,
	)
	known_warehouse = bool(res.get("warehouse"))
	out = []
	for i in res.get("items", []):
		if not i.get("is_stock_item"):
			hint = frappe._("Jasa")
		elif known_warehouse:
			hint = frappe._("Stok {0} {1}").format(f"{_flt(i.get('on_hand')):g}", i.get("stock_uom") or "").strip()
		else:
			# No source warehouse resolved: say so rather than show a company-wide total
			# that this M&R could not actually issue.
			hint = frappe._("Pilih Gudang Sumber Part dulu")
		out.append([i["item_code"], i.get("item_name"), hint])
	return out


@frappe.whitelist()
def used_item_warehouse_query(doctype, txt, searchfield, start, page_len, filters):
	"""Gudang picker for a Used-Items row.

	The row IS the choice of source warehouse now, so the branch scoping that used to sit on
	the order's single Source Warehouse belongs here: real, enabled warehouses of the company,
	limited to the container's branch and to the warehouses the caller's own branch allows
	(``mr.list_warehouses``). The branch is shown as the option's description.
	"""
	from frappe.utils import cint as _cint

	from container_depot.operations import mr

	rows = mr.list_warehouses(repair_order=(filters or {}).get("repair_order"))["warehouses"]
	needle = (txt or "").strip().lower()
	if needle and needle != "undefined":
		rows = [r for r in rows if needle in (r.name or "").lower() or needle in (r.warehouse_name or "").lower()]
	start, page_len = _cint(start), _cint(page_len)
	return [[r.name, r.branch or ""] for r in rows[start : start + page_len]]


@frappe.whitelist()
def used_items_on_hand(pairs, repair_order=None):
	"""Live stock for the Used-Items grid's Stok column, keyed ``"item::warehouse"``.

	Keyed by the pair because each row names its own gudang — the same part can legitimately
	show a different number on two rows. ``pairs`` is ``[{item, warehouse}]`` off the live
	form; a pair with no gudang yet falls back to the container's branch default, the same
	resolution the picker and the stock guard use. Services are never asked for.
	"""
	import json as _json

	from container_depot.operations.mr import _on_hand, default_warehouse

	if isinstance(pairs, str):
		pairs = _json.loads(pairs or "[]")
	fallback = None
	if repair_order and frappe.db.exists("Repair Order", repair_order):
		fallback = default_warehouse(frappe.get_doc("Repair Order", repair_order))

	out = {}
	for p in pairs or []:
		item = p.get("item")
		if not item or not frappe.db.get_value("Item", item, "is_stock_item"):
			continue
		wh = p.get("warehouse") or fallback
		if not wh:
			continue
		out[f"{item}::{p.get('warehouse') or ''}"] = _on_hand(item, wh)
	return out
