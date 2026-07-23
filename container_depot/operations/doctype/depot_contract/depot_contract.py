import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, today

# Status workflow — the only transitions the action buttons (set_status) allow.
# Draft is editable; Active and the terminal states are locked. A draft is
# submitted straight to Active (the old Negotiation step was dropped), and an
# Active contract ends either Void ("Invalid") or Expired.
ALLOWED_TRANSITIONS = {
	"Draft": ("Active", "Void"),
	"Active": ("Expired", "Void"),
	"Expired": (),
	"Void": (),
}
EDITABLE_STATUSES = ("Draft",)


class DepotContract(Document):
	# --- lifecycle ------------------------------------------------------
	def validate(self):
		self._validate_status_transition()
		self._validate_date_window()
		self._validate_payment_type()
		self._validate_currency_vs_base_list()
		self._validate_no_duplicate_lines()

	def before_save(self):
		# Clear TOP-only fields when payment is Cash
		if self.payment_type == "Cash":
			self.payment_terms = None
			self.credit_limit = 0
		# Each line's currency follows the contract (drives Rate/Manhour formatting).
		for row in self.tariff_lines or []:
			row.currency = self.currency

	def after_insert(self):
		from container_depot.operations.notify import notify_contract_created
		notify_contract_created(self)

	def on_update(self):
		# Auto-expire on date rollover (may flip status to Expired in-place).
		self._auto_expire_on_rollover()
		# Publish / retire the customer Price List based on the status transition.
		self._sync_published_price_list()
		self._notify_status_change()

	def _notify_status_change(self):
		"""A contract is not submittable, so its status move IS its lifecycle: Active
		announces the live tariff, Void kills the contract and with it the "menunggu
		aktivasi" prompt still sitting in everyone's bell."""
		before = self.get_doc_before_save()
		if not before or before.status == self.status:
			return
		if self.status == "Active":
			from container_depot.operations.notify import notify_contract_activated
			notify_contract_activated(self)
		elif self.status == "Void":
			from container_depot.operations.notify import revoke
			revoke(self.doctype, self.name)

	def _auto_expire_on_rollover(self):
		if self.status == "Active" and self.valid_to and getdate(self.valid_to) < getdate(today()):
			self.db_set("status", "Expired", update_modified=False)

	# --- validation -----------------------------------------------------
	def _validate_status_transition(self):
		"""Only allow status moves that follow the workflow (buttons drive these;
		the field itself is read-only). New docs may start at any status so tests /
		data patches can seed an Active contract directly."""
		before = self.get_doc_before_save()
		if not before or before.status == self.status:
			return
		if self.status not in ALLOWED_TRANSITIONS.get(before.status, ()):
			frappe.throw(
				_("Cannot change contract status from {0} to {1}.").format(before.status, self.status)
			)

	def _validate_date_window(self):
		if self.valid_from and self.valid_to and getdate(self.valid_to) < getdate(self.valid_from):
			frappe.throw(_("Valid To must be on or after Valid From."))

	def _validate_payment_type(self):
		# "Both" allows TOP bookings too, so it carries the same credit requirements.
		if self.payment_type in ("TOP", "Both"):
			if not self.payment_terms:
				frappe.throw(_("Payment Terms is required for {0} contracts.").format(self.payment_type))
			if not self.credit_limit or self.credit_limit <= 0:
				frappe.throw(
					_("Credit Limit must be greater than zero for {0} contracts.").format(self.payment_type)
				)
		if self.status == "Active" and not (self.tariff_lines and len(self.tariff_lines) > 0):
			frappe.throw(_("An Active contract must declare at least one Price List line."))

	def _validate_currency_vs_base_list(self):
		"""The published Item Prices inherit the Price List currency, so the contract
		currency must match the base rate card it is negotiated from."""
		if self.currency and self.base_price_list:
			base_cur = frappe.db.get_value("Price List", self.base_price_list, "currency")
			if base_cur and base_cur != self.currency:
				frappe.throw(
					_("Contract currency {0} must match the Base Price List currency {1}.").format(
						self.currency, base_cur
					)
				)

	def _validate_no_duplicate_lines(self):
		seen = set()
		for row in self.tariff_lines or []:
			key = (row.item, row.uom or None)
			if key in seen:
				frappe.throw(
					_("Duplicate Price List line for Item {0} (UoM {1}).").format(row.item, row.uom or "-")
				)
			seen.add(key)

	# --- price-list publishing -----------------------------------------
	def _sync_published_price_list(self):
		"""Keep a customer Price List (named after the contract) in lock-step with
		this contract's status, so the newest agreed prices apply automatically.

		* Active   -> (re)publish the list from the lines + disable the customer's
		  previous contract-published list.
		* terminal (Expired / Rejected / Void) after having been Active -> disable
		  this contract's own published list.
		"""
		before = self.get_doc_before_save()
		prev_status = before.status if before else None

		if self.status == "Active":
			self._publish_price_list()
			self._disable_other_generated_lists()
		elif prev_status == "Active" and self.status in ("Expired", "Void"):
			self._disable_own_generated_list()

	def _resolve_currency(self):
		if self.currency:
			return self.currency
		if self.base_price_list:
			cur = frappe.db.get_value("Price List", self.base_price_list, "currency")
			if cur:
				return cur
		return (
			frappe.db.get_value("Customer", self.customer, "default_currency")
			or frappe.defaults.get_global_default("currency")
			or "IDR"
		)

	def _publish_price_list(self):
		"""Create-or-refresh the customer Price List named after this contract and
		write its Item Prices from the agreed lines. Idempotent."""
		if not (self.tariff_lines and len(self.tariff_lines) > 0):
			return
		currency = self._resolve_currency()
		# Name the list by Customer + contract number, e.g. "Acme Ltd - DCNT-2026-00001".
		customer_name = frappe.db.get_value("Customer", self.customer, "customer_name") or self.customer
		pl_name = f"{customer_name} - {self.name}"

		if frappe.db.exists("Price List", pl_name):
			pl = frappe.get_doc("Price List", pl_name)
			pl.update({"currency": currency, "customer": self.customer, "selling": 1, "buying": 0, "enabled": 1})
			pl.save(ignore_permissions=True)
		else:
			frappe.get_doc({
				"doctype": "Price List",
				"price_list_name": pl_name,
				"currency": currency,
				"customer": self.customer,
				"selling": 1,
				"buying": 0,
				"enabled": 1,
			}).insert(ignore_permissions=True)

		if self.generated_price_list != pl_name:
			self.db_set("generated_price_list", pl_name, update_modified=False)

		self._sync_item_prices(pl_name)

		# Unify walk-in + contract pricing on the latest agreed list.
		frappe.db.set_value("Customer", self.customer, "default_price_list", pl_name, update_modified=False)
		if not frappe.db.get_value("Customer", self.customer, "default_currency"):
			frappe.db.set_value("Customer", self.customer, "default_currency", currency, update_modified=False)

	def _sync_item_prices(self, pl_name):
		# Track the Item Prices we wrote by name (uom may be defaulted to the item's
		# stock UOM by Item Price.validate, so prune by name rather than (item, uom)).
		kept = set()
		for row in self.tariff_lines:
			kept.add(self._upsert_item_price(pl_name, row))
		for name in frappe.get_all("Item Price", filters={"price_list": pl_name, "selling": 1}, pluck="name"):
			if name not in kept:
				frappe.delete_doc("Item Price", name, ignore_permissions=True)

	def _upsert_item_price(self, pl_name, row):
		flt = {"item_code": row.item, "price_list": pl_name, "selling": 1}
		if row.uom:
			flt["uom"] = row.uom
		existing = frappe.db.get_value("Item Price", flt, "name")
		if existing:
			ip = frappe.get_doc("Item Price", existing)
			ip.price_list_rate = row.rate or 0
			ip.manhour_rate = row.manhour_rate or 0
			if row.uom:
				ip.uom = row.uom
			ip.save(ignore_permissions=True)
			return ip.name
		payload = {
			"doctype": "Item Price",
			"item_code": row.item,
			"price_list": pl_name,
			"price_list_rate": row.rate or 0,
			"manhour_rate": row.manhour_rate or 0,
			"selling": 1,
		}
		if row.uom:
			payload["uom"] = row.uom
		# currency is copied from the Price List by Item Price.validate().
		doc = frappe.get_doc(payload)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _disable_other_generated_lists(self):
		"""Disable the customer's other selling Price Lists (older contract lists) so
		only this contract's list is active for the customer. Base / standard rate
		cards are customer-less, so they are never touched."""
		others = frappe.get_all(
			"Price List",
			filters={
				"customer": self.customer,
				"enabled": 1,
				"selling": 1,
				"name": ["!=", self.generated_price_list or ""],
			},
			pluck="name",
		)
		for pl in others:
			frappe.db.set_value("Price List", pl, "enabled", 0, update_modified=False)

	def _disable_own_generated_list(self):
		if self.generated_price_list and frappe.db.exists("Price List", self.generated_price_list):
			frappe.db.set_value("Price List", self.generated_price_list, "enabled", 0, update_modified=False)


@frappe.whitelist()
def set_status(contract: str, target: str) -> str:
	"""Workflow-button transition. Validates against ALLOWED_TRANSITIONS and saves,
	which publishes / retires the customer Price List as a side effect."""
	doc = frappe.get_doc("Depot Contract", contract)
	if target not in ALLOWED_TRANSITIONS.get(doc.status, ()):
		frappe.throw(_("Cannot move contract from {0} to {1}.").format(doc.status, target))
	doc.status = target
	doc.save()
	return doc.status


def get_active_contract(customer: str) -> dict | None:
	"""Return the most recent Active contract for a customer (dict) or None."""
	row = frappe.db.get_value(
		"Depot Contract",
		{"customer": customer, "status": "Active"},
		["name", "payment_type", "payment_terms", "credit_limit", "valid_to"],
		as_dict=True,
		order_by="valid_from desc",
	)
	return row


# --- tariff line item picker (seeded from the contract's Base Price List) --------

@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def tariff_item_query(doctype, txt, searchfield, start, page_len, filters):
	"""Link query for a Price List line's Item: only Items that have a selling Item
	Price in the contract's Base Price List. When NO Base Price List is set, fall back
	to the full service catalog (every enabled, sellable Item) so a contract can still
	be built from scratch and priced manually."""
	base_pl = (filters or {}).get("base_price_list")
	like = f"%{txt or ''}%"
	if not base_pl:
		return frappe.db.sql(
			"""
			SELECT it.name, it.item_name
			FROM `tabItem` it
			WHERE it.is_sales_item = 1 AND it.disabled = 0
			  AND (it.name LIKE %(like)s OR it.item_name LIKE %(like)s)
			ORDER BY it.item_name
			LIMIT {start}, {page_len}
			""".format(start=cint(start), page_len=cint(page_len)),
			{"like": like},
		)
	return frappe.db.sql(
		"""
		SELECT DISTINCT ip.item_code, it.item_name
		FROM `tabItem Price` ip
		JOIN `tabItem` it ON it.name = ip.item_code
		WHERE ip.selling = 1
		  AND ip.price_list = %(pl)s
		  AND (ip.item_code LIKE %(like)s OR it.item_name LIKE %(like)s)
		ORDER BY ip.item_code
		LIMIT {start}, {page_len}
		""".format(start=cint(start), page_len=cint(page_len)),
		{"pl": base_pl, "like": like},
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def base_price_list_query(doctype, txt, searchfield, start, page_len, filters):
	"""Base Price List options: any enabled *selling* Price List that holds at least
	one selling Item Price. A contract can be seeded ("cribbed") from any rate card —
	a standard catalog (OAK 2026, Standard Selling) or another customer's agreed list,
	so a new customer can be put on the same prices as an existing one. Only empty and
	buying-only lists are hidden (there is nothing to copy from those)."""
	like = f"%{txt or ''}%"
	return frappe.db.sql(
		"""
		SELECT pl.name
		FROM `tabPrice List` pl
		WHERE pl.selling = 1 AND pl.enabled = 1
		  AND EXISTS (
		      SELECT 1 FROM `tabItem Price` ip WHERE ip.price_list = pl.name AND ip.selling = 1
		  )
		  AND pl.name LIKE %(like)s
		ORDER BY pl.name
		LIMIT {start}, {page_len}
		""".format(start=cint(start), page_len=cint(page_len)),
		{"like": like},
	)


@frappe.whitelist()
def base_price_list_lines(base_price_list: str) -> list:
	"""Every selling Item Price in the Base Price List, as tariff line dicts.

	Powers the "Get Items from Base Price List" button, which clears the lines and
	re-adds one per priced item so a contract can be seeded from a standard rate
	card and then negotiated.
	"""
	if not base_price_list:
		return []
	return frappe.get_all(
		"Item Price",
		filters={"price_list": base_price_list, "selling": 1},
		fields=["item_code as item", "uom", "price_list_rate as rate", "manhour_rate"],
		order_by="item_code",
	)


@frappe.whitelist()
def item_price_defaults(base_price_list: str, item: str) -> dict:
	"""Default uom / rate / manhour_rate for ``item`` from the Base Price List.

	uom is shown read-only on the line; rate and manhour_rate are seeded as editable
	defaults that are then negotiated. Returns {} when the item is not priced there.
	"""
	if not base_price_list or not item:
		return {}
	row = frappe.db.get_value(
		"Item Price",
		{"item_code": item, "price_list": base_price_list, "selling": 1},
		["uom", "price_list_rate", "manhour_rate"],
		as_dict=True,
	)
	if not row:
		return {}
	return {"uom": row.uom, "rate": row.price_list_rate, "manhour_rate": row.manhour_rate}


# --- bulk fill: add by menu / paste from Excel ----------------------------------

@frappe.whitelist()
def base_price_list_lines_for_menu(base_price_list: str, menu: str) -> list:
	"""Tariff line dicts for the items of ``menu`` (a Depot Service Menu) that are
	priced in the Base Price List. Powers the "Add from Menu" button — bulk-add only
	the items that belong to a given menu (e.g. all Maintenance items)."""
	if not base_price_list or not menu:
		return []
	from container_depot.operations.service_menu import filter_items_by_menu

	lines = base_price_list_lines(base_price_list)
	codes = set(filter_items_by_menu([ln["item"] for ln in lines], menu))
	return [ln for ln in lines if ln["item"] in codes]


def _parse_pasted_lines(text: str) -> list:
	"""Parse spreadsheet paste into row dicts. One item per line; columns are tab- or
	comma-separated: ``item [, rate [, manhour_rate [, uom]]]``. A header row whose
	first cell is item/kode is skipped."""
	rows = []
	for line in (text or "").splitlines():
		line = line.strip()
		if not line:
			continue
		cells = [c.strip() for c in (line.split("\t") if "\t" in line else line.split(","))]
		first = cells[0] if cells else ""
		if not first:
			continue
		if first.lower() in ("item", "item code", "kode", "kode item"):
			continue  # header
		rows.append({
			"item": first,
			"rate": cells[1] if len(cells) > 1 else None,
			"manhour_rate": cells[2] if len(cells) > 2 else None,
			"uom": cells[3] if len(cells) > 3 else None,
		})
	return rows


def _resolve_paste_item(token: str, base_price_list: str | None) -> str | None:
	"""Resolve a pasted token to an Item code: exact Item name (code) first, else an
	exact item_name match (preferring items priced in the Base Price List)."""
	if not token:
		return None
	if frappe.db.exists("Item", token):
		return token
	if base_price_list:
		priced = frappe.get_all(
			"Item Price", filters={"price_list": base_price_list, "selling": 1}, pluck="item_code", distinct=True
		)
		if priced:
			match = frappe.db.get_value("Item", {"item_name": token, "name": ["in", priced]}, "name")
			if match:
				return match
	return frappe.db.get_value("Item", {"item_name": token}, "name")


def _to_rate(value, fallback) -> float:
	return flt(value) if value not in (None, "") else flt(fallback)


@frappe.whitelist()
def import_tariff_lines(contract: str, text: str, replace=0) -> dict:
	"""Bulk-fill a Draft contract's Price List lines from pasted Excel text. Each
	line: ``item [, rate [, manhour_rate [, uom]]]`` (tab- or comma-sep).
	Blank rate/uom/manhour default from the Base Price List. Unknown items are
	collected (not fatal). Returns ``{added, skipped, errors, total_lines}``."""
	doc = frappe.get_doc("Depot Contract", contract)
	if doc.status not in EDITABLE_STATUSES:
		frappe.throw(_("Price List lines can only be imported while the contract is a Draft."))

	rows = _parse_pasted_lines(text)
	if not rows:
		frappe.throw(_("No rows found in the pasted text."))

	if cint(replace):
		doc.set("tariff_lines", [])

	seen = {(r.item, r.uom or None) for r in (doc.tariff_lines or [])}
	base_pl = doc.base_price_list
	added = skipped = 0
	errors = []
	for raw in rows:
		item = _resolve_paste_item(raw["item"], base_pl)
		if not item:
			errors.append(_("Unknown item: {0}").format(raw["item"]))
			continue
		defaults = item_price_defaults(base_pl, item) if base_pl else {}
		uom = raw["uom"] or defaults.get("uom")
		key = (item, uom or None)
		if key in seen:
			skipped += 1
			continue
		seen.add(key)
		doc.append("tariff_lines", {
			"item": item,
			"uom": uom,
			"rate": _to_rate(raw["rate"], defaults.get("rate")),
			"manhour_rate": _to_rate(raw["manhour_rate"], defaults.get("manhour_rate")),
			"currency": doc.currency,
		})
		added += 1

	doc.save()
	return {
		"added": added,
		"skipped": skipped,
		"errors": errors,
		"total_lines": len(doc.tariff_lines or []),
	}


# The .xlsx builders moved to a shared module (Container Booking imports them too);
# kept under the old private names so the download functions below are untouched.
from container_depot.xlsx_utils import finish_sheet as _finish_sheet
from container_depot.xlsx_utils import new_sheet as _new_sheet


@frappe.whitelist(methods=["GET"])
def download_tariff_template():
	"""Blank import template: the exact Item / Rate / Manhour columns the grid's
	"Import Excel" button expects, with one illustrative row."""
	headers = ["Item", "Rate", "Manhour"]
	output, wb, ws, _fmts = _new_sheet("Template", headers, [46, 14, 14])
	ws.write_row(1, 0, ["CONTOH-KODE-ITEM", 250000, 25000])
	_finish_sheet(output, wb, ws, "tariff_import_template.xlsx", 1, len(headers) - 1)


@frappe.whitelist(methods=["GET"])
def download_item_master(base_price_list: str | None = None):
	"""Reference list of the sellable items valid for a Price List line — the codes to
	put in the template's Item column. Mirrors the form's item picker filter
	(``is_sales_item=1, disabled=0``). When a Base Price List is given, its Rate /
	Manhour are included so the sheet doubles as a starting rate card.

	Rows are grouped under a bold Item Group banner for readability. Note the banner
	rows are ordinary rows, so using the AutoFilter hides them along with the items
	they head — that is the trade-off of sections in a filterable sheet.
	"""
	items = frappe.get_all(
		"Item",
		filters={"disabled": 0, "is_sales_item": 1},
		fields=["name", "item_name", "stock_uom", "item_group"],
		order_by="item_group asc, item_name asc",
	)
	grouped = {}
	for it in items:
		grouped.setdefault(it.item_group or _("Ungrouped"), []).append(it)

	headers = ["Item", "Item Name", "UoM", "Rate", "Manhour"]
	output, wb, ws, fmts = _new_sheet("Items", headers, [46, 46, 10, 14, 14])
	row = 1
	for group in sorted(grouped):
		# Banner spans the full width so the section reads as one band.
		ws.write(row, 0, group, fmts["group"])
		for col in range(1, len(headers)):
			ws.write(row, col, "", fmts["group"])
		row += 1
		for it in grouped[group]:
			defaults = item_price_defaults(base_price_list, it.name) if base_price_list else {}
			ws.write_row(row, 0, [
				it.name,
				it.item_name,
				defaults.get("uom") or it.stock_uom,
				defaults.get("rate") or "",
				defaults.get("manhour_rate") or "",
			])
			row += 1
	_finish_sheet(output, wb, ws, "item_master.xlsx", row - 1, len(headers) - 1)


@frappe.whitelist()
def parse_tariff_xlsx(file_url: str, base_price_list: str | None = None) -> dict:
	"""Parse an uploaded .xlsx into Price List rows for the grid's "Import Excel" button.

	Columns by position: Item, Rate, Manhour (a 4th UoM column is honoured if present);
	a header row whose first cell is item/kode is skipped. Pure read — it resolves items
	and defaults but touches no contract, so the caller can add the rows to a still-unsaved
	form. Unknown items are collected in ``errors``, not fatal.

	Returns ``{rows: [{item, uom, rate, manhour_rate}], errors: [...]}``.
	"""
	from frappe.utils.xlsxutils import read_xlsx_file_from_attached_file

	if not file_url:
		frappe.throw(_("No file provided."))
	raw_rows = read_xlsx_file_from_attached_file(file_url=file_url) or []

	rows, errors = [], []
	seen = set()
	for cells in raw_rows:
		if not cells:
			continue
		token = (str(cells[0]).strip() if cells[0] is not None else "")
		if not token:
			continue
		if token.lower() in ("item", "item code", "kode", "kode item"):
			continue  # header
		item = _resolve_paste_item(token, base_price_list)
		if not item:
			errors.append(_("Unknown item: {0}").format(token))
			continue
		defaults = item_price_defaults(base_price_list, item) if base_price_list else {}
		uom = defaults.get("uom")
		if uom is None and len(cells) > 3 and cells[3] not in (None, ""):
			uom = str(cells[3]).strip()
		key = (item, uom or None)
		if key in seen:
			continue
		seen.add(key)
		rate = cells[1] if len(cells) > 1 else None
		manhour = cells[2] if len(cells) > 2 else None
		rows.append({
			"item": item,
			"uom": uom,
			"rate": _to_rate(rate, defaults.get("rate")),
			"manhour_rate": _to_rate(manhour, defaults.get("manhour_rate")),
		})
	return {"rows": rows, "errors": errors}
