// Consolidated ("generate") Sales Invoice UX.
//
// A generated invoice carries a rollback manifest (custom field depot_billed_sources)
// listing the depot orders it swept. Its line items are frozen server-side
// (consolidated_billing.protect_consolidated_items). Here we surface a prominent,
// visible button to discard/cancel the invoice — which rolls every order back to
// un-invoiced (consolidated_billing.rollback_billed_sources). We do NOT hide any of
// the standard Delete/Cancel actions in the ⋮ menu; this only adds a clearer button.
frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		if (!frm.doc.depot_billed_sources) return; // only generated invoices

		frm.set_intro(
			__(
				"Faktur ini dibuat lewat Generate — item terkunci (tidak bisa diubah/dihapus). " +
					"Untuk membatalkan, pakai tombol Batalkan & Kembalikan Order: semua order kembali " +
					"ke status belum di-invoice dan bisa di-generate ulang."
			),
			"blue"
		);

		if (frm.doc.docstatus === 0) {
			// Draft → discard (delete). on_trash rolls the orders back and unblocks the delete.
			frm.add_custom_button(__("Batalkan & Kembalikan Order"), () => frm.savetrash())
				.removeClass("btn-default")
				.addClass("btn-danger");
		} else if (frm.doc.docstatus === 1) {
			// Submitted → cancel. on_cancel rolls the orders back.
			frm.add_custom_button(__("Cancel & Kembalikan Order"), () => frm.savecancel())
				.removeClass("btn-default")
				.addClass("btn-danger");
		}
	},
});
