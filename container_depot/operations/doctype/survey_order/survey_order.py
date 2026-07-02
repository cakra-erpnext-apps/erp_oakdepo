"""Survey Order — third-party survey charges billed to a customer (Paid To).

Draft → (submit) → Payment Pending (Cash) / Submitted (TOP). Each row in the
``charges`` table is one survey charge for one container (container optional).
On submit, **Cash** raises a DRAFT Sales Invoice (one line per charge) for the
Paid To — left as draft so the user can review / add tax before submitting &
collecting payment. **TOP** raises no invoice (billed later via the per-customer
invoice run). Cancelling the Survey Order rolls its invoice back: a draft is
deleted, a submitted one is cancelled (blocked if it already has a payment).
"""

import frappe
from frappe.model.document import Document
from frappe.utils import flt

from container_depot import invoicing, pricing_model


class SurveyOrder(Document):
    def validate(self):
        self._resolve_pricing()
        self.total = sum(flt(c.price) for c in self.charges)
        if self.docstatus == 0 and not self.status:
            self.status = "Draft"

    def _resolve_pricing(self):
        """Fill price list / currency from Paid To, and auto-price blank charge rows."""
        if self.paid_to and not self.price_list:
            self.price_list = pricing_model.price_list_for_customer(self.paid_to)
        if not self.currency:
            self.currency = (
                frappe.db.get_value("Price List", self.price_list, "currency")
                if self.price_list
                else None
            ) or frappe.defaults.get_global_default("currency") or "IDR"
        # Auto-price any row that has an item + price list but no manual price yet.
        for c in self.charges:
            if c.item and self.price_list and not flt(c.price):
                c.price = flt(pricing_model.resolve_price(c.item, self.price_list))

    def before_submit(self):
        if not self.paid_to:
            frappe.throw("Paid To wajib diisi.")
        if not any(c.item for c in self.charges):
            frappe.throw("Minimal satu Charge dengan Item wajib diisi.")
        if flt(self.total) <= 0:
            frappe.throw("Total harus lebih dari 0.")

    def on_submit(self):
        if self.payment_type == "Cash":
            # Cash: raise a submitted (Unpaid) Sales Invoice now — just awaiting payment.
            self._create_invoice()
            self.db_set("status", "Payment Pending")
        else:
            # TOP: no invoice yet — billed later via the per-customer invoice run.
            self.db_set("status", "Submitted")

    def _create_invoice(self):
        if self.sales_invoice:
            return
        # Cash bills due today (only Cash reaches this path).
        due_days = 0
        lines = []
        for c in self.charges:
            if not c.item:
                continue
            ref = c.container_no or c.container or ""
            desc = f"Survey {c.survey_date or ''} — {ref}".strip(" —")
            if self.notes:
                desc = f"{desc} · {self.notes}" if desc else self.notes
            lines.append({
                "item_code": c.item,
                "description": desc or c.item,
                "qty": 1,
                "rate": flt(c.price),
            })
        if not lines:
            frappe.throw("Tidak ada Charge yang bisa ditagih.")
        inv = invoicing.create_draft_sales_invoice(
            customer=self.paid_to,
            lines=lines,
            due_days=due_days,
            remarks=f"Survey Order {self.name}",
            currency=self.currency,
            selling_price_list=self.price_list or None,
        )
        if not inv:
            frappe.throw(
                "Gagal membuat Sales Invoice — site belum invoice-ready "
                "(cek default Company & Customer). Survey Order tidak jadi disubmit."
            )
        # Leave the invoice as a DRAFT so the user can review / add tax before
        # submitting & collecting payment.
        self.db_set("sales_invoice", inv)

    def on_cancel(self):
        self._rollback_invoice()
        self.db_set("status", "Cancelled")

    def _rollback_invoice(self):
        """Roll back the linked Sales Invoice on cancel; block if it's been paid."""
        if not self.sales_invoice or not frappe.db.exists("Sales Invoice", self.sales_invoice):
            return
        si = frappe.get_doc("Sales Invoice", self.sales_invoice)
        if si.docstatus == 2:  # already cancelled — nothing to roll back
            return
        if si.docstatus == 0:  # still a draft — unlink then delete it
            name = si.name
            self.db_set("sales_invoice", None)  # clear the link so delete isn't blocked
            frappe.delete_doc("Sales Invoice", name, ignore_permissions=True)
            return
        paid = flt(si.grand_total) - flt(si.outstanding_amount)
        if paid > 0:
            frappe.throw(
                f"Sales Invoice {si.name} sudah menerima pembayaran ({paid:.2f}). "
                "Batalkan / refund Payment Entry-nya dulu sebelum cancel Survey Order."
            )
        si.flags.ignore_permissions = True
        si.cancel()


# ── Whitelisted helpers used by the client form ───────────────────────────────
@frappe.whitelist()
def get_pricing_context(customer):
    """Price list + currency for a Paid To (customer)."""
    pl = pricing_model.price_list_for_customer(customer)
    cur = frappe.db.get_value("Price List", pl, "currency") if pl else None
    return {"price_list": pl, "currency": cur}


@frappe.whitelist()
def get_item_price(item, price_list):
    """Resolved selling rate for an item in a price list."""
    if not price_list:
        return 0
    return pricing_model.resolve_price(item, price_list)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def item_price_query(doctype, txt, searchfield, start, page_len, filters):
    """Link-field query: items that have a selling Item Price in the given price list."""
    price_list = (filters or {}).get("price_list")
    if not price_list:
        return []
    like = f"%{txt}%"
    return frappe.db.sql(
        """
        select distinct ip.item_code, i.item_name
        from `tabItem Price` ip
        join `tabItem` i on i.name = ip.item_code
        where ip.price_list = %(pl)s and ip.selling = 1
          and (ip.item_code like %(txt)s or i.item_name like %(txt)s)
        order by ip.item_code
        limit %(start)s, %(page_len)s
        """,
        {"pl": price_list, "txt": like, "start": start, "page_len": page_len},
    )
