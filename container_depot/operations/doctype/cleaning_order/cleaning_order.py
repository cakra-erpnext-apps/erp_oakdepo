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
		"""Price every chosen cleaning Service (one or more) from the container Owner's
		(Principal's) active Price List, so the order is ready to bill the tank owner. Each
		row's ``rate`` is resolved; ``cleaning_total`` is their sum. No principal / no price
		list leaves every rate (and the total) at 0."""
		from container_depot import pricing_model

		principal = frappe.db.get_value("Container", self.container, "principal") if self.container else None
		price_list = pricing_model.price_list_for_customer(principal) if principal else None
		# Tarif ditampilkan dalam mata uang Price List Owner (bisa beda dari mata uang company).
		self.currency = (
			(frappe.db.get_value("Price List", price_list, "currency") if price_list else None)
			or frappe.defaults.get_global_default("currency")
		)
		total = 0
		for row in self.cleaning_services:
			row.currency = self.currency
			if not row.cleaning_item:
				row.rate = 0
				continue
			if not row.item_name:
				row.item_name = frappe.db.get_value("Item", row.cleaning_item, "item_name")
			row.rate = (pricing_model.resolve_price(row.cleaning_item, price_list) if price_list else 0) or 0
			total += row.rate
		self.cleaning_total = total

	def _cleaning_method_label(self) -> str:
		"""Human label of the chosen cleaning services (for the Cleaning Certificate)."""
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
		this completes the tank (-> Available, parked in the Cleaning Bay) and mints the
		no-expiry Cleaning Certificate that the TANK OUT gate checks for."""
		self._propagate_to_container(log_always=True)
		if not self.is_recleaning and self.status == "Completed":
			self.db_set("cleaning_certificate", self._mint_cleaning_certificate(), update_modified=False)

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

		if self.is_recleaning:
			if self.status == "In_Progress":
				container.cleaning_status = "In_Progress"
				container.status = "Recleaning_In_Progress"
			elif self.status == "Completed":
				container.cleaning_status = "Completed"
				container.status = "Cleaning_Completed"
		else:
			if self.status == "In_Progress":
				container.cleaning_status = "In_Progress"
			elif self.status == "Completed":
				container.cleaning_status = "Completed"
				container.certification_status = "Completed"
				container.status = "Available"
				# Park the tank in the depot's Cleaning Bay zone. Physical yard movement is
				# manual and may lag, so the system stamps the bay at completion.
				bay = self._cleaning_bay_zone(container.depot)
				if bay:
					container.yard_zone = bay

		# Controller-driven status change: bypass the manual-transition guard.
		frappe.flags.in_status_automation = True
		try:
			container.save(ignore_permissions=True)
		finally:
			frappe.flags.in_status_automation = False

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

	def _cleaning_bay_zone(self, depot):
		"""The active Cleaning Bay Yard Zone for the depot (None if none configured)."""
		if not depot:
			return None
		return frappe.db.get_value(
			"Yard Zone", {"depot": depot, "category": "Cleaning Bay", "is_active": 1}, "name"
		)

	def _mint_cleaning_certificate(self) -> str:
		"""Create + submit a no-expiry Cleaning Certificate from this completed order.

		Idempotent: returns the already-minted certificate if present. The cert is the
		gating token consumed by Order Muat / ``_latest_valid_cleaning_cert``; the rich
		cleanliness detail (checklist, gas free, seals) stays on this order. Validity is
		anchored per source EIR (no time expiry), so ``valid_until = None``."""
		if self.cleaning_certificate:
			return self.cleaning_certificate
		cert = frappe.new_doc("Cleaning Certificate")
		cert.container = self.container
		cert.cleaning_order = self.name
		cert.clean_date = self.date_of_issue or self.cleaning_end or datetime.datetime.now()
		cert.cleaning_method = self._cleaning_method_label() or self.cleaning_type or "Steam Wash"
		cert.certified_by = self.signed_by or self.completed_by or frappe.session.user
		cert.prior_cargo = frappe.db.get_value("Container", self.container, "last_cargo")
		cert.valid_until = None  # no expiry — validity is anchored per EIR
		cert.flags.no_expiry = True
		cert.remarks = (
			f"Auto-issued from Cleaning Order {self.name}"
			+ (f" (EIR {self.inspection})" if self.inspection else "")
		)
		cert.insert(ignore_permissions=True)
		cert.submit()
		return cert.name


# ---------------------------------------------------------------------------
# Link query: the cleaning Service items the container Owner is priced for.
# ---------------------------------------------------------------------------
@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def cleaning_item_query(doctype, txt, searchfield, start, page_len, filters):
	"""Items for the Cleaning Order's "Metode Cleaning (Service)" field: the members of the
	Depot Service Menu "Cleaning" that ALSO have a selling Item Price in the container
	Owner's (Principal's) active Price List. The price list is resolved from the container's
	principal — never picked by hand — so the surveyor only sees services the owner is
	billable for. No principal / no price list → no options.
	"""
	from container_depot import pricing_model
	from container_depot.operations import service_menu

	flt = filters or {}
	principal = flt.get("principal")
	if not principal and flt.get("container"):
		principal = frappe.db.get_value("Container", flt.get("container"), "principal")
	price_list = pricing_model.price_list_for_customer(principal) if principal else None
	if not price_list:
		return []
	items = service_menu.items_in_menu(
		"Cleaning", txt=txt, base_price_list=price_list, limit=frappe.utils.cint(page_len) or 20
	)
	return [[i["item_code"], i.get("item_name")] for i in items]
