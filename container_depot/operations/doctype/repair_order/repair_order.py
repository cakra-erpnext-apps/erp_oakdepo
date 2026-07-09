import frappe
from frappe.model.document import Document
import datetime
import hashlib

class RepairOrder(Document):
	def before_insert(self):
		"""Generate unique repair order ID"""
		self.repair_order_id = self.generate_repair_order_id()

	def generate_repair_order_id(self):
		"""Generate unique repair order ID"""
		timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
		unique = hashlib.md5(f"{timestamp}{frappe.generate_hash()[:10]}".encode()).hexdigest()[:8].upper()
		return f"RO-{unique}"

	def validate(self):
		self._validate_status_transition()

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
		self.update_container_status()

	def on_update(self):
		# This order's new status is now persisted — flip the container In_Depot <->
		# Available based on whether any related order is still open.
		from container_depot.operations.container_status import recompute_availability

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
		"""Cost each Service & Parts line as ``manhour × manhour_rate + material_cost`` (per
		unit) × qty. The manhour / rate / material inputs default from the owner's Item Price
		the first time a line is added, then stay ADJUSTABLE — Admin Ops can override them.

		Each line's currency follows its own Item Price, so a Repair Order can MIX currencies.
		Totals are therefore grouped by currency into the ``totals`` table (one row per
		currency); ``total_cost`` stays as the plain numeric sum (kept for the worklists /
		billing report that still read a single figure). The copied ``damages`` carry no cost."""
		from frappe.utils import flt

		from container_depot.pricing_model import item_rate_breakdown

		price_list = self.owner_price_list()
		default_currency = frappe.db.get_default("currency")
		numeric_total = 0.0
		by_currency = {}

		for row in self.get("used_items") or []:
			row.is_stock_item = (
				1 if row.item and frappe.db.get_value("Item", row.item, "is_stock_item") else 0
			)
			breakdown = item_rate_breakdown(row.item, price_list) if row.item else {}
			# Currency always follows the item's own Item Price (fixes the old default-to-IDR).
			if row.item:
				row.currency = breakdown.get("currency") or row.currency or default_currency
			# Seed the cost inputs from the owner's Item Price the first time a line is added
			# (a fresh line carries only item + qty); manual edits are kept afterwards.
			if row.item and not (
				flt(row.manhour) or flt(row.manhour_rate) or flt(row.material_cost)
				or flt(row.manhour_amount) or flt(row.rate)
			):
				row.manhour = breakdown.get("manhour") or 0.0
				row.manhour_rate = breakdown.get("manhour_rate") or 0.0
				row.material_cost = breakdown.get("material_cost") or 0.0
			# Manhour Cost and Rate are adjustable: derive them when blank, otherwise TRUST the
			# entered value (the Desk grid keeps them in sync live). Amount always = qty × rate.
			if not flt(row.manhour_amount):
				row.manhour_amount = flt(row.manhour) * flt(row.manhour_rate)
			if not flt(row.rate):
				row.rate = flt(row.manhour_amount) + flt(row.material_cost)
			row.amount = flt(row.quantity or 0.0) * flt(row.rate)
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
		if self.status == "Draft":
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
