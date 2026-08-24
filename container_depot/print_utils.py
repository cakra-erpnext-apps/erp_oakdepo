"""Jinja helpers for Print Formats (registered in hooks.jinja.methods).

Kept tiny and defensive: a print must never 500 because a barcode failed.
"""

import base64
from io import BytesIO

import frappe


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
