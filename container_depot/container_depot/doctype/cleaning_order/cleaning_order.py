import frappe
from frappe import _
from frappe.model.document import Document

from container_depot.container_depot.container_status import assert_container_active
import datetime
import hashlib

from container_depot.container_depot.booking_link import apply_booking_link

# Item code -> Jenis Cleaning. Dikunci ke item CODE, bukan item_name: nama item bisa
# diedit finance kapan saja, dan itu persis bug yang membuat kolom PP / Methanol / Steam
# di report Inventory KPI per Principal selalu nol (matching lama pakai item_name LIKE).
_WASH_TYPE_BY_ITEM = {
	"INT-PP-WASH": "PP Wash",
	"INT-METHANOL": "Methanol Rinse",
	"INT-STEAM": "Steam Wash",
}

# Tiga wash yang diminta principal lewat email atas tank yang SUDAH bersih — lawan dari
# "Standard Cleaning" yang lahir otomatis dari EIR-In tank kotor. Diturunkan dari peta di
# atas supaya menambah satu wash khusus cukup di satu tempat.
SPECIAL_WASH_TYPES = tuple(_WASH_TYPE_BY_ITEM.values())


class CleaningOrder(Document):
	def before_insert(self):
		"""Generate cleaning order ID"""
		self.order_id = self.generate_order_id()
		# Nilai yang sudah diisi dihormati — order lama yang dicatat belakangan (register
		# manual dari sheet, atau cuci kemarin yang baru diinput hari ini) harus bisa membawa
		# tanggal aslinya. Tanpa cek ini, stempel di sini menimpanya diam-diam.
		if not self.order_created:
			self.order_created = datetime.datetime.now()
		self.created_by = frappe.session.user

	def generate_order_id(self):
		"""Generate unique cleaning order ID"""
		timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
		unique = hashlib.md5(f"{timestamp}{frappe.generate_hash()[:10]}".encode()).hexdigest()[:8].upper()
		return f"CO-{unique}"

	def validate(self):
		# A retired tank takes no new work (container_status.assert_container_active);
		# only checked when the link is set or moved, so a finished order stays editable
		# after its tank leaves the fleet.
		if self.container and self.has_value_changed("container"):
			assert_container_active(self.container)
		self._guard_dates_after_invoice()

	# Tanggal yang menentukan PERIODE TAGIHAN. consolidated_billing / monthly_invoicing
	# memilih order lewat rentang ``cleaning_end``, jadi menggesernya setelah order masuk
	# invoice memindahkan pekerjaan itu ke bulan lain — atau membuatnya hilang dari kedua
	# bulan sekaligus. ``plan_date`` tidak ikut dikunci: ia rencana, tidak dibaca penagihan.
	_BILLING_DATES = ("order_created", "cleaning_end")

	def _guard_dates_after_invoice(self):
		if self.is_new() or not self.sales_invoice:
			return
		changed = [f for f in self._BILLING_DATES if self.has_value_changed(f)]
		if changed:
			frappe.throw(
				_("Order ini sudah masuk invoice {0}. Tanggalnya ({1}) tidak bisa diubah — "
				  "batalkan dulu invoicenya kalau tanggalnya memang salah.").format(
					self.sales_invoice, ", ".join(changed)
				)
			)

	def before_save(self):
		"""Auto-populate container info + price the owner's chosen cleaning services."""
		if self.container:
			container = frappe.get_doc("Container", self.container)
			self.container_no = container.container_no
			self.last_cargo = container.last_cargo
			self.zone = container.yard_zone
		# File this order under the booking its EIR was raised on, so Container Booking can
		# list the work its visit produced. Blank when there is no EIR — a walk-in cleaning
		# has no parent booking to belong to.
		apply_booking_link(self)
		self._resolve_cleaning_services()
		self._derive_cleaning_type()

	def _derive_cleaning_type(self):
		"""Jaring pengaman untuk order yang jenisnya KOSONG. Order baru tidak pernah lewat
		sini: field-nya sudah ber-default ``Standard Cleaning``, dan semua order memang lahir
		sebagai cuci standar — wash khusus adalah keputusan Admin Ops di tahap Service Setup,
		bukan sesuatu yang disimpulkan sistem dari isi tabel service.

		Yang tersisa untuk fungsi ini hanyalah dokumen lama yang kolomnya masih kosong
		(field ini sempat dipensiunkan): begitu disimpan ulang, jenisnya disimpulkan dari
		item service — aturan yang sama dengan patch v0_84 — dan jatuh ke Standard Cleaning
		kalau tidak ada wash khusus di sana. Pilihan manusia tidak pernah ditimpa.

		Tidak ada validasi yang menolak simpan saat jenis dan service tidak sejalan: satu
		order boleh punya beberapa service sekaligus (mis. Standard Clean + Steam Wash),
		dan sebuah blocker di sini akan menghentikan pekerjaan lapangan yang sah.
		"""
		if self.cleaning_type:
			return
		for row in self.cleaning_services or []:
			found = _WASH_TYPE_BY_ITEM.get(row.cleaning_item)
			if found:
				self.cleaning_type = found
				return
		self.cleaning_type = "Standard Cleaning"

	def _resolve_cleaning_services(self):
		"""Seed every chosen cleaning Service (one or more) from the contract that owns the
		container, so the order starts on the figures negotiated with the tank owner.

		Each row carries the two PRICES the rate card states, side by side and never merged:
		  * ``rate``         — the service tariff, summed into ``cleaning_total``
		  * ``manhour_rate`` — its labour tariff, summed into ``manhour_charge_total``

		Both are taken AS THEY STAND — no hours arithmetic here. The order records what the
		price list charges; how labour is settled on the invoice is billing's business, and
		doubling it into the service tariff here would pay for it twice.

		Both are only a BASE PRICE: seeded once (while the row still reads 0) and never
		overwritten afterwards, so Admin Ops can negotiate a one-off figure on the order
		without a later save silently resetting it back to the contract. No contract / no
		price list leaves them at 0 for Admin Ops to fill in.
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
				row.rate = row.manhour_rate = 0
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
		self.manhour_charge_total = manhour_total

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

		# Factor 1: Release date urgency — nearer the customer's target lift-on (stamped by the
		# the outbound booking), higher priority. Read live off the container so the score never lags a
		# stamp that landed after this order was last saved. H-0 / overdue gets the big boost.
		from frappe.utils import getdate, nowdate

		target = self.target_lift_on or (
			frappe.db.get_value("Container", self.container, "target_lift_on") if self.container else None
		)
		if target:
			days = (getdate(target) - getdate(nowdate())).days
			score += 200 if days <= 0 else max(0.0, 100.0 - days * 10)

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
		"""Submitting a normal (non-re-clean) order IS completing it — Submit is the single
		finish action, for the PWA sign-off and the Desk form alike. (Re-cleaning keeps its
		own approval-driven flow.)

		An order that never went through the operator route — work done off-system, or a
		tank that left before anyone opened the PWA — carries no ``cleaning_start``. It is
		stamped here rather than refused: submitting asserts the cleaning happened, and a
		start equal to the end records that better than a blocked submit. This used to be a
		throw with a Desk-only "Selesaikan Langsung (Bypass Alur)" button next to Submit
		that just pre-stamped the same field; folding it in leaves one button. The operator
		route always arrives with its real start time set, so this only fires on the
		straight-to-Submit path.
		"""
		if self.is_recleaning:
			return
		if not self.cleaning_start:
			self.cleaning_start = datetime.datetime.now()
		self.status = "Completed"
		if not self.cleaning_end:
			self.cleaning_end = datetime.datetime.now()
		if not self.completed_by:
			self.completed_by = frappe.session.user
		if not self.signed_by:
			self.signed_by = frappe.session.user
		if not self.date_of_issue:
			self.date_of_issue = frappe.utils.today()

	def on_update(self):
		"""Keep the container's presence status in step from the moment the order exists.

		A DRAFT cleaning is already work in progress, so the tank is not free to leave. The
		status only moved at submit before — unlike M&R, which recomputes
		on every save — so a container could read ``Available`` while an open cleaning sat
		on it.
		"""
		from container_depot.container_depot.container_status import recompute_availability

		recompute_availability(self.container)
		self._notify_if_forwarded_to_team()

	def _notify_if_forwarded_to_team(self):
		"""Service Setup -> Pending is the handoff: ring the cleaning crew, and only here.

		"Teruskan ke Team" is a plain status edit on the form (no endpoint of its own), so
		the transition is watched on the controller — that way the PWA, a bulk edit or an
		import all reach the same bell. Order creation deliberately does not notify the crew;
		see ``install.NOTIFICATION_RULES``.
		"""
		before = self.get_doc_before_save()
		if not before or before.status == self.status:
			return
		if before.status == "Service Setup" and self.status == "Pending":
			from container_depot.container_depot.notify import notify_cleaning_forwarded_to_team

			notify_cleaning_forwarded_to_team(self.name)

	def on_cancel(self):
		# Cancelling (docstatus 2) takes the order out of `container_open_orders` — the
		# tank it was holding In_Depot has to be recomputed, exactly as a delete does.
		# The status-field route (status -> Cancelled) already goes through on_update.
		from container_depot.container_depot.container_status import recompute_availability

		recompute_availability(self.container)
		# A revision request asked for exactly this; it has been actioned, so the flag (and
		# the "Revisi Diminta" badge it drives) comes off. The amended copy starts clean —
		# both fields are no_copy.
		if self.get("revision_requested"):
			frappe.db.set_value(
				"Cleaning Order", self.name,
				{"revision_requested": 0, "revision_note": None},
				update_modified=False,
			)

	def after_delete(self):
		# A deleted draft order is work that no longer exists — the tank it was holding
		# In_Depot has to be recomputed, or it stays "busy" with nothing open.
		from container_depot.container_depot.container_status import recompute_availability

		recompute_availability(self.container)

	def on_submit(self):
		"""Update container status when cleaning order is submitted. For a normal clean
		this completes the tank (-> Available, parked in the Cleaning Bay)."""
		self._propagate_to_container(log_always=True)

	def on_update_after_submit(self):
		"""Status / approval edits after submit also drive the container so a
		re-clean can progress Pending -> In_Progress -> Completed over time."""
		self._propagate_to_container()

	def _propagate_to_container(self, log_always=False):
		"""Push this cleaning order's progress onto its container.

		The container carries no cleaning field of its own any more. It used to mirror a
		``cleaning_status`` / ``certification_status`` hint here, but nothing ever cleared
		either one — a tank cleaned last cycle still read "Completed" after it had gated
		out and come back dirty — and the open Cleaning Order is the same answer without
		the staleness. So all that is left is the presence recompute.
		"""
		if not self.container:
			return
		before = self.get_doc_before_save()
		prev_status = before.status if before else None

		# Flip In_Depot <-> Available now that this cleaning order's state changed.
		from container_depot.container_depot.container_status import recompute_availability

		recompute_availability(self.container)

		# Log a Cleaning milestone on start / completion (deduped against unrelated
		# after-submit edits).
		if self.status in ("In_Progress", "Completed") and (log_always or self.status != prev_status):
			from container_depot.container_depot.container_activity import log_container_activity

			label = "re-clean" if self.is_recleaning else "clean"
			log_container_activity(
				self.container, "Cleaning",
				reference_doctype=self.doctype, reference_name=self.name,
				to_status=frappe.db.get_value("Container", self.container, "status"),
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
	from container_depot.container_depot import service_menu

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
	"""Base figures of one cleaning Service under the contract that owns the container: its
	service tariff and its labour tariff.

	The Desk form calls this the moment a Service is picked so the row's Tarif and Tarif
	Manhour (and the totals) fill in immediately instead of only after a save. Both are just a
	starting point — the fields stay editable and a seeded value is never re-applied.
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
		# Tarif labour dari rate card pemilik tank — dipakai apa adanya di order ini.
		"manhour_rate": pricing.manhour_for(item_code, price_list),
		"currency": currency,
		"item_name": frappe.db.get_value("Item", item_code, "item_name") if item_code else None,
		"price_list": price_list,
	}
