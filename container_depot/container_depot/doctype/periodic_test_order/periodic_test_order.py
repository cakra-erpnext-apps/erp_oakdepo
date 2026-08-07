"""Periodic Test Order controller — mirrors the Repair Order (M&R) controller.

An owner-approval work order for a container's periodic pressure test. The status machine
(PT_TRANSITIONS) is enforced here; costs are grouped per currency like M&R; and on
completion the order pushes the next due-date onto the Container master (the single source
of truth for the reminder cron + dashboard KPI), issues any stockable parts, and logs a
Container Activity milestone.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, flt, getdate, now_datetime

from container_depot.container_depot.booking_link import apply_booking_link
from container_depot.container_depot.periodic import PT_INTERVAL_MONTHS, PT_TRANSITIONS


class PeriodicTestOrder(Document):
	def before_insert(self):
		if not self.order_created:
			self.order_created = now_datetime()

	def validate(self):
		# Usually blank: a periodic test is scheduled off Container.next_pt_due, not raised
		# from an EIR, so it genuinely belongs to no booking. The reference exists for the
		# case where a surveyor's finding is what triggered the test.
		apply_booking_link(self)
		self._fetch_principal()
		self._compute_due_date()
		self._validate_status_transition()

	def before_save(self):
		self.calculate_totals()

	def on_update(self):
		self._on_status_change()
		# Flip the container In_Depot <-> Available: an open Periodic Test is unfinished work
		# that must be done before the tank may leave (same gate as Cleaning / M&R).
		from container_depot.container_depot.container_status import recompute_availability

		recompute_availability(self.container)

	# --- helpers -------------------------------------------------------------
	def _fetch_principal(self):
		if not self.container:
			return
		principal = frappe.db.get_value("Container", self.container, "principal")
		if principal:
			self.principal = principal
			if not self.billed_to:
				self.billed_to = principal

	def _compute_due_date(self):
		"""Next due = Periodic Date + interval(test_type). Computed only when both are set."""
		months = PT_INTERVAL_MONTHS.get(self.test_type)
		if self.periodic_date and months:
			self.due_date = getdate(add_to_date(getdate(self.periodic_date), months=months))

	def _validate_status_transition(self):
		"""Enforce the owner-approval status machine (PT_TRANSITIONS). A direct edit that skips
		a step (e.g. Draft -> In Progress) is rejected; a new doc may start at Draft."""
		before = self.get_doc_before_save()
		if not before or before.status == self.status:
			return
		if self.status not in PT_TRANSITIONS.get(before.status, []):
			frappe.throw(
				_("Tidak bisa mengubah status Periodic Test dari {0} ke {1}.").format(before.status, self.status)
			)

	def owner_price_list(self):
		"""Selling Price List for this order's owner/principal — drives every line rate."""
		from container_depot.pricing_model import price_list_for_customer

		principal = self.principal or frappe.db.get_value("Container", self.container, "principal")
		return price_list_for_customer(principal) if principal else None

	def calculate_totals(self):
		"""Cost each Used-Items line = Qty x Item Rate, seeded from the owner's Item Price and
		grouped per currency (an order can mix currencies). Rejected lines are excluded. Mirrors
		RepairOrder.calculate_totals (minus the deprecated manhour split)."""
		from container_depot.pricing_model import item_rate_breakdown

		price_list = self.owner_price_list()
		# Fallback currency = owner's price-list currency (contract currency), not site default.
		default_currency = (
			(frappe.db.get_value("Price List", price_list, "currency") if price_list else None)
			or frappe.db.get_default("currency")
		)
		numeric_total = 0.0
		by_currency = {}
		for row in self.get("used_items") or []:
			row.is_stock_item = 1 if row.item and frappe.db.get_value("Item", row.item, "is_stock_item") else 0
			breakdown = item_rate_breakdown(row.item, price_list) if row.item else {}
			if row.item:
				row.currency = breakdown.get("currency") or row.currency or default_currency
				if not flt(row.item_rate):
					row.item_rate = breakdown.get("item_rate") or 0.0
			row.item_amount = flt(row.quantity or 0.0) * flt(row.item_rate)
			row.amount = row.item_amount
			if (row.get("decision") or "Pending") != "Rejected":
				numeric_total += row.amount
				cur = row.currency or default_currency
				by_currency[cur] = by_currency.get(cur, 0.0) + row.amount
		self.total_cost = numeric_total
		self.set("totals", [])
		for cur, amt in sorted(by_currency.items()):
			self.append("totals", {"currency": cur, "total": amt})

	def _on_status_change(self):
		before = self.get_doc_before_save()
		prev = before.status if before else None
		if self.status == prev:
			return
		if self.status == "Completed":
			self._complete()

	def _complete(self):
		"""On completion: issue approved stockable parts, push the new due-date onto the
		Container (single source of truth), and log the milestone."""
		from container_depot.container_depot import periodic
		from container_depot.container_depot.container_activity import log_container_activity

		se = periodic.issue_parts_stock(self)
		if se:
			self.db_set("stock_entry", se, update_modified=False)
		if not self.completion_date:
			self.db_set("completion_date", now_datetime(), update_modified=False)
		self._push_due_to_container()
		log_container_activity(
			self.container, "Periodic Test",
			reference_doctype=self.doctype, reference_name=self.name,
			activity_time=self.get("periodic_date"),
			summary=f"{self.get('test_type') or 'Periodic'} test selesai, due {self.get('due_date')}",
		)

	def _push_due_to_container(self):
		"""Advance the tank's next-due watermark. Container.next_pt_due backs TANK OUT gating,
		the reminder cron and the dashboard KPI — this is the only writer of it now."""
		if not self.container:
			return
		vals = {}
		if self.due_date:
			vals["next_pt_due"] = getdate(self.due_date)
		if self.periodic_date:
			vals["last_test_date"] = getdate(self.periodic_date)
		if vals:
			frappe.db.set_value("Container", self.container, vals, update_modified=False)


# The Depot Service Menu that declares which items a periodic test may bill. Scoping lives in
# the menu — not in this query — so an operator can change what the picker offers without a
# code change (see container_depot/service_menu.DEFAULT_MENU_GROUPS).
PT_MENU = "Periodic Test"


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def used_item_query(doctype, txt, searchfield, start, page_len, filters):
	"""Link query for a Periodic Test Order Used-Items row.

	Offers the "Periodic Test" service menu ∩ the owner's price list — the same contract the
	M&R picker honours, so a periodic test can never bill an item the owner has no rate for,
	and the two menus stay the single place where the catalogue is decided. Before this the
	field had no query at all: the whole Item catalogue was on offer, unpriced items included.

	Both narrowings fall back OPEN rather than empty, so a half-configured site is still
	workable: no owner price list -> every sellable item; menu missing / inactive / empty ->
	no group filter.
	"""
	from frappe.utils import cint as _cint

	from container_depot.container_depot.service_menu import filter_items_by_menu, is_real_menu

	filters = filters or {}
	price_list = None
	order = filters.get("periodic_test_order")
	if order and frappe.db.exists("Periodic Test Order", order):
		price_list = frappe.get_doc("Periodic Test Order", order).owner_price_list()

	if price_list:
		candidate = frappe.get_all(
			"Item Price",
			filters={"price_list": price_list, "selling": 1},
			pluck="item_code",
			distinct=True,
		)
	else:
		candidate = frappe.get_all(
			"Item", filters={"disabled": 0, "is_sales_item": 1}, pluck="name"
		)
	if is_real_menu(PT_MENU):
		candidate = filter_items_by_menu(candidate, PT_MENU)
	if not candidate:
		return []

	or_filters = None
	txt = (txt or "").strip()
	if txt and txt.lower() != "undefined":
		or_filters = {"item_code": ["like", f"%{txt}%"], "item_name": ["like", f"%{txt}%"]}
	# Narrowed BEFORE the limit so a page of 20 never comes back short.
	return frappe.get_all(
		"Item",
		filters={"name": ["in", candidate], "disabled": 0},
		or_filters=or_filters,
		fields=["name", "item_name"],
		order_by="item_name asc",
		limit_start=_cint(start),
		limit_page_length=_cint(page_len),
		as_list=True,
	)
