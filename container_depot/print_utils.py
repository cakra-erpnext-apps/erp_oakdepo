"""Jinja helpers for Print Formats (registered in hooks.jinja.methods).

Kept tiny and defensive: a print must never 500 because a barcode failed.
"""

import base64
from io import BytesIO

import frappe


def qr_data_uri(code, prefix=""):
    """PNG data-URI QR encoding ``{prefix}{code}`` — defaults to the bare code
    (no ``OAK|`` prefix) since prints are scanned by the PWA, and
    container_depot.api.validate_qr accepts a bare Booking Code too. Returns ""
    if code is empty or the qrcode lib is unavailable, so a print never breaks.
    """
    if not code:
        return ""
    try:
        import qrcode

        img = qrcode.make(f"{prefix}{code}")
        buf = BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        frappe.log_error(frappe.get_traceback(), "qr_data_uri failed")
        return ""
