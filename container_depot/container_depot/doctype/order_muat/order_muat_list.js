// Copyright (c) 2026, Oak Depot Team and contributors
// For license information, please see license.txt

// Order Muat list view — the bon for muat (tank keluar / loading).
//
// WHY THIS FILE EXISTS: the doctype is submittable and carries its own `order_status`, but
// Frappe never looked at it. A draft bon got the stock red "Draft", a voided one
// (order_generation.void_order → docstatus 2) got a red "Cancelled" that read exactly like
// a draft, and once submitted every row said the same "Submitted" whether the bon was just
// issued or long finished.
//
// Colour convention, shared by every Container Depot list:
//   grey   — Draf: docstatus 0, belum diterbitkan
//   red    — Void: docstatus 2 (soft-delete; the record is kept for audit)
//   blue   — Selesai: the terminal state
//   others — the stages in between; Hold is a pause, not a cancellation, so it stays out of red
frappe.listview_settings["Order Muat"] = {
	add_fields: ["order_status"],
	// Without these two, frappe.get_indicator returns its blanket "Draft"/"Cancelled" pill
	// for docstatus 0/2 and bails out before get_indicator below is ever called.
	has_indicator_for_draft: 1,
	has_indicator_for_cancelled: 1,

	get_indicator(doc) {
		if (doc.docstatus === 0) return [__("Draf"), "gray", "docstatus,=,0"];
		if (doc.docstatus === 2) return [__("Void"), "red", "docstatus,=,2"];
		const map = {
			// Bon sudah terbit, EIR belum jalan.
			Issued: [__("Diterbitkan"), "orange", "order_status,=,Issued"],
			"EIR In Progress": [__("EIR Berjalan"), "yellow", "order_status,=,EIR In Progress"],
			"Ready To Load": [__("Siap Muat"), "green", "order_status,=,Ready To Load"],
			Completed: [__("Selesai"), "blue", "order_status,=,Completed"],
			// Ditahan — EIR menemukan masalah; bukan batal, hanya berhenti sementara.
			Hold: [__("Ditahan"), "purple", "order_status,=,Hold"],
		};
		return map[doc.order_status] || [__(doc.order_status || "-"), "gray", `order_status,=,${doc.order_status || ""}`];
	},
};
