"""Jinja helpers for Print Formats (registered in hooks.jinja.methods).

Kept tiny and defensive: a print must never 500 because a barcode failed.
"""

import base64
from io import BytesIO

import frappe
from frappe.utils import flt


def _png_via_qrcode(text: str) -> bytes | None:
    """`qrcode` (Pillow-backed) — the nicer renderer when it is installed."""
    try:
        import qrcode
    except ImportError:
        return None
    buf = BytesIO()
    qrcode.make(text).save(buf, format="PNG")
    return buf.getvalue()


def _png_via_pyqrcode(text: str) -> bytes | None:
    """`pyqrcode` + `pypng` — ships with the bench, so this is what actually runs
    on a stock Frappe image. Without it the gate-pass band on every OAK print
    format renders as empty boxes."""
    try:
        import pyqrcode
    except ImportError:
        return None
    buf = BytesIO()
    # scale 4 ≈ 200px for a 12-char payload: sharp at the ~84px the prints draw it.
    pyqrcode.create(text, error="M").png(buf, scale=4, quiet_zone=2)
    return buf.getvalue()


def qr_data_uri(code, prefix=""):
    """PNG data-URI QR encoding ``{prefix}{code}`` — defaults to the bare code
    (no ``OAK|`` prefix) since prints are scanned by the PWA, and
    container_depot.api.validate_qr accepts a bare Booking Code too. Returns ""
    if code is empty or no QR library is available, so a print never breaks.
    """
    if not code:
        return ""
    try:
        payload = f"{prefix}{code}"
        png = _png_via_qrcode(payload) or _png_via_pyqrcode(payload)
        if not png:
            return ""
        return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    except Exception:
        frappe.log_error(frappe.get_traceback(), "qr_data_uri failed")
        return ""


# --- OAK Invoice ----------------------------------------------------------------------------
# The pick list's sections, in its order, as the invoice prints them (user, 2026-09-30).
_INVOICE_GROUPS = {
	"Booking": "Lift On / Lift Off",
	"Storage": "Storage",
	"Cleaning": "Cleaning",
	"M&R": "Maintenance & Repair",
	"Periodic Test": "Periodic Test",
	"": "Others",  # hand-typed lines
}
_TANK = {"Container Booking": "container_summary", "Storage Charge": "container"}


def _source_facts(source):
	"""(group, Ref OAK, Ref Cust, tank) of the order a line's ``depot_source`` names."""
	from container_depot.consolidated_billing import _source_category, cust_ref

	dt, _sep, name = (source or "").partition("|")
	if not name:
		return "", "", "", ""
	if dt == "Storage":  # pre-ledger storage: named by the tank
		return "Storage", "", "", name
	if not (frappe.db.exists("DocType", dt) and frappe.db.exists(dt, name)):
		return "", name, "", ""
	group = "Storage" if dt == "Storage Charge" else _source_category({"dt": dt, "name": name})
	tank = frappe.db.get_value(dt, name, _TANK.get(dt, "container"))
	return group, name, cust_ref(dt, name), tank or ""


def invoice_groups(doc):
	"""An invoice's lines as OAK Invoice prints them: grouped like the pick list, each line with
	the order it bills (Ref OAK), the customer's reference on that order and its tank.

	    {"groups": [{"key", "label", "rows": [{"row", "ref", "cust_ref", "tank", "text"}], "total"}],
	     "kurs": {"USD": [17922.0, ...]}}

	``cust_ref`` is the line's own Reff Doc (frozen at submit), else its order's today.

	``kurs`` is every line currency but the ledger's own, with the kurs its lines were billed at.
	"""
	base = frappe.get_cached_value("Company", doc.company, "default_currency")
	facts, groups, kurs = {}, {}, {}
	for r in doc.items:
		src = r.get("depot_source") or ""
		if src not in facts:
			facts[src] = _source_facts(src)
		key, ref, cust_ref, tank = facts[src]
		g = groups.setdefault(key, {"key": key, "label": _INVOICE_GROUPS.get(key, key), "rows": [], "total": 0})
		# An order's line reads "Cleaning CO-0001 · Standard Clean": the order has its own column.
		text = (r.description or r.item_name or "").split(" · ", 1)[-1] if ref else (r.description or r.item_name or "")
		g["rows"].append({"row": r, "ref": ref, "cust_ref": r.get("depot_reff_doc") or cust_ref, "tank": tank, "text": text})
		g["total"] += flt(r.amount)
		ccy = r.get("depot_currency")
		if ccy and ccy != base and flt(r.get("depot_kurs")) not in kurs.setdefault(ccy, []):
			kurs[ccy].append(flt(r.depot_kurs))
	order = list(_INVOICE_GROUPS)
	return {
		"groups": sorted(groups.values(), key=lambda g: order.index(g["key"]) if g["key"] in order else len(order)),
		"kurs": {c: sorted(k) for c, k in kurs.items()},
	}


_CURRENCY_WORDS = {"IDR": "rupiah", "USD": "dolar Amerika Serikat", "SGD": "dolar Singapura", "EUR": "euro"}


def terbilang(amount, currency="IDR"):
	"""An amount in words in the print's language: Indonesian as the invoice states it
	("Sembilan belas juta ... rupiah"), else ERPNext's own words."""
	from num2words import num2words

	if not (frappe.local.lang or "").startswith("id"):
		return frappe.utils.money_in_words(amount, currency)

	amount = round(flt(amount), 2)
	whole, cents = divmod(round(abs(amount) * 100), 100)
	words = f"{num2words(whole, lang='id')} {_CURRENCY_WORDS.get(currency, currency)}"
	if cents:
		words += f" {num2words(cents, lang='id')} sen"
	words = ("minus " if amount < 0 else "") + words
	return words[:1].upper() + words[1:]
