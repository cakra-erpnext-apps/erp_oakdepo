import frappe
from frappe import _
from frappe.model.document import Document
import datetime
import hashlib

class CleaningOrder(Document):
	def before_insert(self):
		"""Generate cleaning order ID"""
		self.order_id = self.generate_order_id()
		self.order_created = datetime.datetime.now()
		self.created_by = frappe.session.user

	def generate_order_id(self):
		"""Generate unique cleaning order ID"""
		timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
		unique = hashlib.md5(f"{timestamp}{frappe.generate_hash()[:10]}".encode()).hexdigest()[:8].upper()
		return f"CO-{unique}"

	def before_save(self):
		"""Auto-populate container info + price the owner's chosen cleaning services."""
		if self.container:
			container = frappe.get_doc("Container", self.container)
			self.container_no = container.container_no
			self.last_cargo = container.last_cargo
			self.zone = container.yard_zone
		self._resolve_cleaning_services()

	def _resolve_cleaning_services(self):
		"""Seed every chosen cleaning Service (one or more) from the contract that owns the
		container, so the order starts on the rates negotiated with the tank owner.

		Each row carries the two things the contract states about that service, side by side
		and NEVER merged into one number:
		  * ``rate``         — the tariff (money), summed into ``cleaning_total``
		  * ``manhour_rate`` — the labour hours it books, summed into ``manhour_total``

		The hours are not costed here on purpose: billing totals the manhours of everything
		on the invoice and charges them once, on their own line. Adding them to the tariff
		would mean paying for labour twice.

		Both are only a BASE PRICE: they are seeded once (when the row is still at 0) and
		never overwritten afterwards, so Admin Ops can negotiate a one-off figure on the
		order without a later save silently resetting it back to the contract.
		No contract / no price list leaves them at 0 for Admin Ops to fill in.
		"""
		from frappe.utils import flt

		from container_depot import pricing

		price_list = price_list_for_container(self.container)
		# Tarif ditampilkan dalam mata uang Price List kontrak (bisa beda dari mata uang company).
		self.currency = (
			(frappe.db.get_value("Price List", price_list, "currency") if price_list else None)
			or frappe.defaults.get_global_default("currency")
		)
		service_total = manhour_total = 0.0
		for row in self.cleaning_services:
			row.currency = self.currency
			if not row.cleaning_item:
				row.rate = 0
			else:
				if not row.item_name:
					row.item_name = frappe.db.get_value("Item", row.cleaning_item, "item_name")
				if not flt(row.rate):
					row.rate = base_rate_for(row.cleaning_item, price_list)
				if not flt(row.manhour_rate):
					row.manhour_rate = pricing.manhour_for(row.cleaning_item, price_list)
			service_total += flt(row.rate)
			manhour_total += flt(row.manhour_rate)
		self.cleaning_total = service_total
		self.manhour_total = manhour_total

	def _cleaning_method_label(self) -> str:
		"""Human label of the chosen cleaning services (printed on the cleaning report)."""
		names = [r.item_name or r.cleaning_item for r in self.cleaning_services if r.cleaning_item]
		return ", ".join(names) if names else (self.cleaning_item or "")

	def calculate_priority_score(self):
		"""
		Calculate priority score for cleaning queue.
		Higher score = higher priority.
		"""
		score = 0

		# Factor 1: Release date urgency (if known)
		# This would need integration with release orders

		# Factor 2: Time in queue (older = higher priority)
		if self.order_created:
			hours_in_queue = (datetime.datetime.now() - self.order_created).total_seconds() / 3600
			score += hours_in_queue * 0.5

		# Factor 3: Last cargo type (hazardous = higher priority)
		hazardous_cargos = ["Chemical", "Toxic", "Corrosive", "Flammable"]
		if self.last_cargo:
			for cargo in hazardous_cargos:
				if cargo.lower() in self.last_cargo.lower():
					score += 50
					break

		# Factor 4: Customer tier (premium customers get priority)
		# This would need integration with customer master

		self.priority_score = score
		return score

	def before_submit(self):
		"""A normal (non-re-clean) order can only be submitted once cleaning has started,
		and submitting it = Completed. (Re-cleaning keeps its own approval-driven flow.)"""
		if self.is_recleaning:
			return
		if not self.cleaning_start:
			frappe.throw(_("Mulai cleaning dulu sebelum submit (selesaikan) order ini."))
		self.status = "Completed"
		if not self.cleaning_end:
			self.cleaning_end = datetime.datetime.now()
		if not self.completed_by:
			self.completed_by = frappe.session.user
		if not self.signed_by:
			self.signed_by = frappe.session.user
		if not self.date_of_issue:
			self.date_of_issue = frappe.utils.today()

	def on_submit(self):
		"""Update container status when cleaning order is submitted. For a normal clean
		this completes the tank (-> Available, parked in the Cleaning Bay). A submitted
		Completed order IS the TANK OUT proof — Order Muat checks for it directly."""
		self._propagate_to_container(log_always=True)

	def on_update_after_submit(self):
		"""Status / approval edits after submit also drive the container so a
		re-clean can progress Pending -> In_Progress -> Completed over time."""
		self._propagate_to_container()

	def _propagate_to_container(self, log_always=False):
		"""Mirror the cleaning order's progress onto its container.

		Re-cleaning (post-survey) uses the portal lifecycle states; a normal
		first clean keeps the original behaviour (-> Available).
		"""
		if not self.container:
			return
		before = self.get_doc_before_save()
		prev_status = before.status if before else None
		container = frappe.get_doc("Container", self.container)

		# Only the informational cleaning_status / certification_status hints are set here;
		# the main Container.status is presence-based now and recomputed below.
		if self.status == "In_Progress":
			container.cleaning_status = "In_Progress"
		elif self.status == "Completed":
			container.cleaning_status = "Completed"
			if not self.is_recleaning:
				container.certification_status = "Completed"

		# Controller-driven save: bypass the manual-transition guard.
		frappe.flags.in_status_automation = True
		try:
			container.save(ignore_permissions=True)
		finally:
			frappe.flags.in_status_automation = False

		# Flip In_Depot <-> Available now that this cleaning order's state changed.
		from container_depot.operations.container_status import recompute_availability

		recompute_availability(self.container)

		# Log a Cleaning milestone on start / completion (deduped against unrelated
		# after-submit edits).
		if self.status in ("In_Progress", "Completed") and (log_always or self.status != prev_status):
			from container_depot.operations.container_activity import log_container_activity

			label = "re-clean" if self.is_recleaning else "clean"
			log_container_activity(
				self.container, "Cleaning",
				reference_doctype=self.doctype, reference_name=self.name,
				to_status=container.status,
				performed_by=self.get("completed_by") or self.get("assigned_to"),
				summary=f"Cleaning {self.status.lower().replace('_', ' ')} ({label})",
			)


# ---------------------------------------------------------------------------
# Base pricing: the contract that owns the container.
# ---------------------------------------------------------------------------
def price_list_for_container(container) -> str | None:
	"""The Price List that carries the base prices for this container's cleaning.

	An Active ``Depot Contract`` publishes its negotiated tariff lines to a customer Price
	List (``generated_price_list``); that contract — the one the tank Owner (Principal)
	holds — is the source of truth for what cleaning costs them. A tank whose owner has no
	active contract (walk-in) falls back to the owner's rate card, then the site default.
	"""
	from container_depot import pricing, pricing_model

	principal = frappe.db.get_value("Container", container, "principal") if container else None
	if not principal:
		return None
	return pricing.contract_price_list(principal) or pricing_model.price_list_for_customer(principal)


def base_rate_for(item_code, price_list) -> float:
	"""Contract base price of one cleaning Service (0 when unpriced / no contract)."""
	from container_depot import pricing_model

	if not (item_code and price_list):
		return 0.0
	return pricing_model.resolve_price(item_code, price_list) or 0.0


# ---------------------------------------------------------------------------
# Link query: the cleaning Service items the container Owner is priced for.
# ---------------------------------------------------------------------------
@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def cleaning_item_query(doctype, txt, searchfield, start, page_len, filters):
	"""Items for the Cleaning Order's "Metode Cleaning (Service)" field: the members of the
	Depot Service Menu "Cleaning" that ALSO have a selling Item Price in the Price List of
	the contract owning the container. The contract is resolved from the container's
	principal — never picked by hand — so the surveyor only sees services the owner is
	billable for. No contract / no price list → no options.
	"""
	from container_depot.operations import service_menu

	flt = filters or {}
	container = flt.get("container")
	price_list = price_list_for_container(container) if container else None
	if not price_list and flt.get("principal"):
		from container_depot import pricing_model

		price_list = pricing_model.price_list_for_customer(flt.get("principal"))
	if not price_list:
		return []
	items = service_menu.items_in_menu(
		"Cleaning", txt=txt, base_price_list=price_list, limit=frappe.utils.cint(page_len) or 20
	)
	return [[i["item_code"], i.get("item_name")] for i in items]


# ---------------------------------------------------------------------------
# Live pricing for the Desk form (so the grid fills on pick, not only on save).
# ---------------------------------------------------------------------------
@frappe.whitelist()
def service_pricing(container=None, item_code=None) -> dict:
	"""Base figures of one cleaning Service under the contract that owns the container:
	its tariff and the labour hours the contract books for it.

	The Desk form calls this the moment a Service is picked so the row's Tarif and Manhour
	(and the totals) fill in immediately instead of only after a save. Both are just a
	starting point — the fields stay editable and the seeded value is never re-applied.
	Read-only lookup.
	"""
	from container_depot import pricing

	price_list = price_list_for_container(container)
	currency = (
		(frappe.db.get_value("Price List", price_list, "currency") if price_list else None)
		or frappe.defaults.get_global_default("currency")
	)
	return {
		"rate": base_rate_for(item_code, price_list),
		"manhour_rate": pricing.manhour_for(item_code, price_list),
		"currency": currency,
		"item_name": frappe.db.get_value("Item", item_code, "item_name") if item_code else None,
		"price_list": price_list,
	}
