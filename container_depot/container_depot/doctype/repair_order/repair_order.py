import frappe
from frappe.model.document import Document

from container_depot.container_depot.container_status import assert_container_active
import datetime
import hashlib

from container_depot.container_depot.booking_link import apply_booking_link

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
		# A retired tank takes no new work (container_status.assert_container_active);
		# only checked when the link is set or moved, so a finished order stays editable
		# after its tank leaves the fleet.
		if self.container and self.has_value_changed("container"):
			assert_container_active(self.container)
		self._validate_status_transition()
		self._validate_stock_available()
		self._bind_work_photos()

	def _bind_work_photos(self):
		"""Tie every evidence photo to a Service & Parts line it can actually belong to.

		The photos are a table of their own, so nothing structural stops someone attaching one
		to an item that is not on this order — and a photo captioned with a part the owner is
		not being charged for is worse than no photo at all, because it reads as proof of work
		nobody agreed to. So the item must be on the order.

		``used_item`` is filled in from the item when it is blank. It only earns its keep when
		one item appears on the order twice (two corner posts, two visits), which is why no
		human is ever asked for it: the first matching line is right in every other case, and
		the PWA stamps the exact row anyway.
		"""
		rows = self.get("work_photos") or []
		if not rows:
			return
		by_name = {r.name: r for r in (self.used_items or []) if r.name}
		first_for_item = {}
		for r in self.used_items or []:
			if r.item and r.item not in first_for_item:
				first_for_item[r.item] = r
		for p in rows:
			line = by_name.get(p.used_item) if p.used_item else None
			if line is None:
				line = first_for_item.get(p.item)
			if line is None:
				frappe.throw(
					frappe._("Foto bukti #{0}: item {1} tidak ada di Service & Parts order ini.").format(
						p.idx, p.item or "-"
					)
				)
			# Keep the pair honest in both directions: a row picked by name decides the item,
			# not the other way round.
			p.used_item = line.name
			p.item = line.item

	def _validate_stock_available(self):
		"""A part may only sit on an M&R when its own gudang actually holds it.

		Placed in validate() so it covers every path — the Desk grid, the PWA, and
		``mr.save_mr_order`` alike.

		An order that has already ISSUED its parts is skipped: on-hand is now lower by exactly
		this order's amount, so re-checking the estimate against it would fail on every order
		that ever took a part. Parts leave at approval now (``mr.issue_parts_on_approval``), so
		that covers most of an M&R's life — ``stock_entry`` is the honest test for it, not the
		status. Cancelled / Rejected are skipped too: they must stay closable whatever the
		stock says.
		"""
		if self.get("stock_entry") or self.status in ("Completed", "Cancelled", "Rejected"):
			return
		from container_depot.container_depot.mr import assert_stock_available

		assert_stock_available(self)

	def _validate_status_transition(self):
		"""Enforce the owner-approval status machine (MR_TRANSITIONS). The transition
		functions in container_depot/mr.py drive these; a direct status edit that skips a step
		(e.g. Draft -> In Progress without approval) is rejected. New docs may start at
		Draft (the default) so EIR auto-create / tests can seed them."""
		from container_depot.container_depot.mr import MR_TRANSITIONS

		before = self.get_doc_before_save()
		if not before or before.status == self.status:
			return
		if self.status not in MR_TRANSITIONS.get(before.status, []):
			frappe.throw(
				frappe._("Tidak bisa mengubah status M&R dari {0} ke {1}.").format(before.status, self.status)
			)
		# Completed -> In Progress is legal in the state machine so that mr.reopen_completed's
		# own save passes validate — but ONLY that function may walk it. Without this, any
		# holder of write permission could un-finish a closed order through the generic
		# status endpoint, undoing a completion that may already be on its way to an invoice.
		if before.status == "Completed" and not self.flags.get("oak_reopen"):
			frappe.throw(
				frappe._("M&R yang sudah selesai hanya bisa dibuka kembali lewat Setujui Revisi (Admin Ops).")
			)

	def before_save(self):
		"""Auto-fetch principal, calculate costs, and update container status"""
		# Parts leave the warehouse at approval, so any road BACK from there has to bring
		# them home again — checked here rather than in each caller because the state machine
		# lets Draft / Cancelled be reached from five different statuses and three different
		# entry points (Desk buttons, ESS endpoints, a direct status edit).
		self._return_parts_if_rewound()
		# File this M&R under the booking its EIR was raised on. Blank when there is no
		# EIR — an ad-hoc repair belongs to no visit in particular.
		apply_booking_link(self)
		self.fetch_principal_from_container()
		self.calculate_totals()
		self.stamp_on_hand()
		self.update_container_status()

	def _return_parts_if_rewound(self):
		"""Cancel this order's Material Issue when it is rewound to Draft or dropped.

		``mr.issue_parts_on_approval`` takes the parts out the moment the estimate is agreed;
		if that agreement is then undone — Admin Ops rewinds it to Draft to fix a wrong item,
		or the whole job is cancelled — the warehouse would otherwise stay short of parts that
		were never fitted to anything.

		Reads the value as it was BEFORE this save: ``stock_entry`` is what says parts went
		out, and clearing it is how this marks them returned.
		"""
		before = self.get_doc_before_save()
		if not before or not before.get("stock_entry"):
			return
		if self.status not in ("Draft", "Cancelled", "Rejected"):
			return
		from container_depot.container_depot.mr import return_parts_stock

		return_parts_stock(self)

	def stamp_on_hand(self):
		"""Fill each part row's Stok from **its own gudang**, so the grid shows what is still
		usable without opening the item picker.

		Written as text, not a number: a service must show BLANK, and a Float renders None as
		0,000 — which reads as "habis" on the very rows that can never run out. Stamped on
		every save; the Desk form also refreshes it live (see repair_order.js).
		"""
		from frappe.utils import flt

		from container_depot.container_depot.mr import _on_hand, row_warehouse

		for row in self.get("used_items") or []:
			if not (row.item and row.is_stock_item):
				row.on_hand = None
				continue
			wh = row_warehouse(self, row)
			row.on_hand = f"{flt(_on_hand(row.item, wh)):g}" if wh else None

	def on_update(self):
		# This order's new status is now persisted — flip the container In_Depot <->
		# Available based on whether any related order is still open.
		from container_depot.container_depot.container_status import recompute_availability

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
			from container_depot.container_depot.notify import revoke

			revoke(self.doctype, self.name)

	def after_delete(self):
		# A deleted draft order is work that no longer exists — the tank it was holding
		# In_Depot has to be recomputed, or it stays "busy" with nothing open.
		from container_depot.container_depot.container_status import recompute_availability

		recompute_availability(self.container)

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
		``manhour_rate`` / ``manhour_amount`` fields on the row are a read-only PREVIEW of that
		invoice charge, shown beside Total Cost so the estimate says what the labour will come
		to; they never enter the line amount or the order total.

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

		from container_depot.container_depot.mr import default_warehouse

		# The labour PREVIEW stamped on every row. It is never priced into the line: the
		# invoice books each billed line's hours (``Item.manhour``) and multiplies the SUM by
		# ONE hourly tariff in its header (``invoicing.apply_manhour_charge``). That tariff is
		# read here exactly the way the invoice reads it — the customer's own rate card, and
		# 0 when they have no contract — so the estimate previews what will actually be
		# charged, and nothing when nothing will be. Deliberately NOT scaled by qty: the hours
		# are what the line books as a whole, which is how the invoice reads them too.
		from container_depot import pricing

		manhour_hour = flt(pricing.manhour_rate_for(self.principal)) if self.principal else 0.0

		for row in self.get("used_items") or []:
			row.is_stock_item = (
				1 if row.item and frappe.db.get_value("Item", row.item, "is_stock_item") else 0
			)
			# Jenis is an INPUT while the row is empty (it narrows the item picker). Once an
			# item is chosen the Item master decides what can be TRUE of it: a stock item is
			# always "Part" (it has a gudang and must face the stock guard), and a non-stock
			# item can never be. Which of the two non-stock labels it wears — plain work
			# ("Jasa") or a part bought for this job ("Part (Beli Langsung)") — is the user's
			# call, because nothing in the system can tell them apart; it only changes how the
			# line reads on the estimate the owner approves.
			if row.item:
				if row.is_stock_item:
					row.line_type = "Part"
				elif row.line_type not in ("Jasa", "Part (Beli Langsung)"):
					row.line_type = "Jasa"
			# Keyed on the ITEM, not the label: only a stock item is ever issued from a gudang,
			# so only a stock item may name one.
			if not row.is_stock_item:
				row.warehouse = None
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
			row.manhour = flt(breakdown.get("manhour"))
			# Biaya Manhour is the INPUT: seeded once from the owner's rate card, then left
			# alone — Admin Ops may negotiate the labour on a job, and re-deriving it every
			# save would undo the edit before anyone saw it. Same bargain as item_rate above.
			if not flt(row.manhour_amount):
				row.manhour_amount = flt(row.manhour) * manhour_hour
			# ...and the hourly tariff is what falls OUT of it. The invoice can only bill
			# labour one way — total hours × a single tariff in the header — so a typed amount
			# reaches it as the rate it implies (see consolidated_billing._negotiated_manhour_hour).
			# A line whose item books no standard hours therefore has no way to carry labour to
			# the invoice; there is nothing to multiply.
			row.manhour_rate = flt(row.manhour_amount) / flt(row.manhour) if flt(row.manhour) else 0.0
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
		"""Log this Repair Order's milestones against its container.

		The container used to mirror a ``repair_status`` hint here (Pending_Estimate /
		Awaiting_Approval / ...). Nothing read it except two report columns, and nothing
		reset it once the M&R closed, so a tank repaired a year ago still read "Completed".
		The Repair Order's own status is the answer, and ``container_open_orders`` is what
		decides whether the tank may leave — so only the activity log is left here.
		"""
		if not self.container:
			return

		before = self.get_doc_before_save()
		prev_status = before.status if before else None

		# Log a Repair milestone when the order is approved / progressed / finished.
		if self.status in ("Approved", "In Progress", "Completed") and self.status != prev_status:
			from container_depot.container_depot.container_activity import log_container_activity

			log_container_activity(
				self.container, "Repair",
				reference_doctype=self.doctype, reference_name=self.name,
				to_status=frappe.db.get_value("Container", self.container, "status"),
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
	Delegates to ``container_depot.mr.mr_item_search`` (same menu ∩ price-list logic); it falls
	back safely to all items only when the owner has no price list / the menu is unset.

	Each option carries a third column telling the two kinds apart at a glance — "Jasa" for
	a service (nothing to run out of) or the on-hand qty for a part, so the picker answers
	"can I still use this, and how many?" before the row is even added. Frappe joins the
	columns after the first into the option's description (desk/search.py
	``build_for_autosuggest``). Parts the row's own gudang cannot supply are already absent
	(``mr._out_of_stock_items``), so a shown qty is always usable.
	"""
	from frappe.utils import flt as _flt

	from container_depot.container_depot import mr

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

	from container_depot.container_depot import mr

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

	from container_depot.container_depot.mr import _on_hand, default_warehouse

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
