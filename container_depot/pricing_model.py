"""Depot pricing resolution (pricing spec §2).

A single entry point that resolves the selling rate of a depot service Item for one
customer: the ``Tariff Rate`` line for that Item on the customer's Active ``Depot
Contract``. Because the rate lives on a contract line (contract + item), one Item prices
differently per principal, and a contract change flows straight through to new orders.

**The contract is the only rate card.** It used to publish its lines to a customer Price
List and everything read the copy back out of Item Price — a mirror that could be edited in
place and was then silently overwritten on the contract's next save. The mirror is gone
(2026-09-17); there is one place a price is written and one place it is read.

Labour is **not** part of that rate. Each tariff line carries a Manhour tariff beside its
Rate, and the two travel separately through every order; billing totals the hours once and
charges them once in the invoice header (see ``invoicing.apply_manhour_charge``).

Currency is a property of the CONTRACT, not of a line: ``DepotContract.before_save`` stamps
the contract currency onto every tariff line, so an item priced by a contract is priced in
that contract's currency and nothing else can disagree.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt

TARIFF_DOCTYPE = "Tariff Rate"
CONTRACT_DOCTYPE = "Depot Contract"


def active_contract(customer: str | None) -> str | None:
	"""The customer's Active Depot Contract, or ``None``.

	This is the whole of "does this customer have an agreed tariff". No contract means no
	rate card, and the caller leaves the rate at 0 for the Cashier to type — a price it is
	somebody's job to negotiate is not a default, and a visible 0 is the version the
	operator can see and fix.

	Depot Contract allows one Active contract per customer (_validate_single_active);
	``valid_from desc`` only settles legacy rows that predate that guard.
	"""
	if not customer:
		return None
	return (
		frappe.db.get_value(
			CONTRACT_DOCTYPE,
			{"customer": customer, "status": "Active"},
			"name",
			order_by="valid_from desc",
		)
		or None
	)


def tariff_row(item_code: str | None, contract: str | None) -> frappe._dict | None:
	"""The contract's tariff line for this Item, or ``None`` when it does not price it.

	``None`` is the answer to "unpriced", and callers lean on it: an item outside the rate
	card is not an error (the pickers are open to the whole catalog), it simply has no
	agreed price.
	"""
	if not (item_code and contract):
		return None
	return (
		frappe.db.get_value(
			TARIFF_DOCTYPE,
			{"parent": contract, "parenttype": CONTRACT_DOCTYPE, "item": item_code},
			["rate", "manhour_rate", "currency", "uom"],
			as_dict=True,
		)
		or None
	)


def item_rate(item_code: str, contract: str):
	"""Flat agreed rate for (item, contract), or ``None`` if the contract does not price it."""
	row = tariff_row(item_code, contract)
	return row.rate if row else None


def contract_currency(contract: str | None) -> str | None:
	"""The currency one contract is denominated in (``None`` when there is no contract)."""
	if not contract:
		return None
	return frappe.db.get_value(CONTRACT_DOCTYPE, contract, "currency") or None


def item_currency(item_code: str, contract: str) -> str | None:
	"""Currency of the agreed rate for (item, contract), or ``None`` when unpriced.

	Stamped on the line by ``DepotContract.before_save``, so it is the denomination the rate
	was agreed in. Falls back to the contract header only for a line written before that
	stamp existed.
	"""
	row = tariff_row(item_code, contract)
	if not row:
		return None
	return row.currency or contract_currency(contract)


def charge_currency(
	customer: str | None, contract: str | None, item_code: str | None, chosen: str | None = None
) -> tuple[str, bool]:
	"""Mata uang satu baris charge + apakah baris itu terkunci: ``(currency, locked)``.

	Kuncinya per BARIS, bukan per dokumen, karena yang mengikat itu kesepakatan atas
	service-nya: kalau item ini punya baris tarif di kontrak customer, rate-nya sudah dalam
	mata uang itu dan operator tidak boleh menggantinya. Item di luar rate card — picker
	memang terbuka ke seluruh katalog — tidak punya harga yang disepakati, jadi tidak ada
	yang bisa tertinggal dengan label keliru: pilihan operator (``chosen``) yang dipakai, dan
	kalau dia belum memilih, jatuh ke mata uang customer."""
	cur = item_currency(item_code, contract)
	if cur:
		return cur, True
	return (chosen or currency_for_customer(customer, contract)), False


def effective_item_rate(item_code: str, contract: str) -> float:
	"""Flat per-unit selling rate for a depot service Item under a contract (0.0 if none).

	Labour is deliberately NOT folded in here. Each tariff line carries its Manhour beside
	its Rate, and the two stay apart all the way through the order: billing totals the hours
	once and charges them on their own invoice line
	(:func:`container_depot.invoicing.apply_manhour_charge`). Merging them into one rate would
	bury labour inside every menu's price and then charge it twice at invoicing.
	"""
	if not item_code:
		return 0.0
	return flt(item_rate(item_code, contract))


def resolve_price(item_code: str, contract: str) -> float:
	"""Public entry point billing calls to price a single service line."""
	return effective_item_rate(item_code, contract)


def item_rate_breakdown(item_code: str, contract: str) -> dict:
	"""The cost inputs that default a Repair Order line: ``item_rate`` (what the line costs)
	plus ``manhour`` / ``manhour_rate`` for reference (what the INVOICE will book for it —
	see :func:`container_depot.invoicing.apply_manhour_charge`).

	``item_rate`` is ALWAYS the agreed rate from the owner's contract. It used to fall back
	to ``Item.material_cost`` whenever the item booked labour hours — a leftover from the old
	model where a line cost ``manhour × manhour_rate + material_cost``. Labour left the order
	itself long ago (``RepairOrder.calculate_totals``: the invoice totals the hours once, in
	its header), which turned that branch from a split into a silent zero: every service on a
	real rate card carries ``Item.manhour > 0`` and ``material_cost = 0``, so the agreed Rate
	never reached the line — and ``consolidated_billing`` bills straight off ``item_rate``, so
	the invoice went out at zero too. There is no split left to make; the contract Rate IS the
	line's price.

	``currency`` comes from the tariff line, which carries its contract's own currency — NOT
	the site/company default.
	"""
	empty = {"manhour": 0.0, "manhour_rate": 0.0, "item_rate": 0.0, "currency": None}
	if not item_code:
		return empty
	row = tariff_row(item_code, contract) or frappe._dict()
	return {
		# Reported, never priced in here: the hours are charged once on the invoice header.
		"manhour": flt(frappe.db.get_value("Item", item_code, "manhour")),
		"manhour_rate": flt(row.get("manhour_rate")),
		"item_rate": flt(row.get("rate") or 0.0),
		"currency": row.get("currency") or None,
	}


def is_own_rate_card(customer: str | None, contract: str | None) -> bool:
	"""True kalau ``contract`` memang kontrak MILIK ``customer``.

	Pembeda ini yang menentukan mata uang boleh dikunci atau tidak: kontrak sendiri adalah
	isi kesepakatan (harga USD-nya memang USD). Dulu pertanyaannya jauh lebih licin — "apakah
	price list ini miliknya, atau cuma katalog site yang kebetulan terpakai" — dan katalog
	generic itu diam-diam menutupi ``Customer.default_currency``. Kontrak tidak punya versi
	generic: ia selalu milik satu customer.
	"""
	if not (customer and contract):
		return False
	return frappe.db.get_value(CONTRACT_DOCTYPE, contract, "customer") == customer


# Jaring terakhir kalau company pun tidak punya mata uang (site setengah jadi / test).
DEFAULT_CURRENCY = "IDR"


def company_currency() -> str:
	"""Mata uang dasar company — dasar terakhir setiap resolver di modul ini.

	Dipakai menggantikan konstanta IDR yang dulu di-hardcode: mata uang company adalah
	fakta yang sudah di-set operator saat setup, jadi site non-IDR pun ikut benar."""
	from container_depot.invoicing import get_default_company

	company = get_default_company()
	return (
		(frappe.db.get_value("Company", company, "default_currency") if company else None)
		or frappe.defaults.get_global_default("currency")
		or DEFAULT_CURRENCY
	)


def currency_for_customer(customer: str | None = None, contract: str | None = None) -> str:
	"""Mata uang customer, dari yang paling mengikat ke yang paling umum:

	  1. currency kontrak MILIK customer — ini isi kesepakatan;
	  2. ``Customer.default_currency`` — mata uang tagihan yang di-set di master;
	  3. mata uang company.

	Tidak pernah mengembalikan None. Dulu ada satu langkah lagi di antara 2 dan 3 — currency
	price list generic yang kebetulan dipakai — dan itulah yang membuat customer USD tanpa
	kontrak selalu ditagih IDR: katalog site menang sebelum ``default_currency`` sempat
	dibaca. Tidak ada katalog site lagi, jadi tidak ada langkah itu lagi."""
	if is_own_rate_card(customer, contract):
		cur = contract_currency(contract)
		if cur:
			return cur
	if customer:
		cur = frappe.db.get_value("Customer", customer, "default_currency")
		if cur:
			return cur
	return company_currency()


def currency_is_locked(customer: str | None = None, contract: str | None = None) -> bool:
	"""Apakah mata uang sudah punya sumber yang mengikat, sehingga operator tidak boleh
	menggantinya di form.

	Terkunci kalau customer punya kontrak sendiri (harga di dalamnya sudah dalam mata uang
	itu) atau sudah menyatakan ``default_currency`` di master. Terbuka hanya kalau tidak ada
	satu pun — walk-in tanpa kontrak — dan di situ tidak ada rate ter-seed yang bisa
	tertinggal dengan label mata uang keliru, karena tidak ada yang menyeed."""
	if is_own_rate_card(customer, contract):
		return True
	return bool(customer and frappe.db.get_value("Customer", customer, "default_currency"))
