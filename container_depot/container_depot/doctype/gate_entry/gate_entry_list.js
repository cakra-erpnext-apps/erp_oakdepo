// Gate Entry list — a read-only log of tanks leaving the yard ("Riwayat Gate").
//
// WHY THIS FILE EXISTS: every row was showing a red "Draft".
//
// Gate Entry is submittable, and frappe.get_indicator checks docstatus BEFORE it looks at
// the document's own `status` — so a submittable doc on docstatus 0 is labelled Draft, full
// stop. Every Gate Entry here IS docstatus 0, deliberately: `mark_gate_out` leaves the new
// record unsubmitted because submitting runs on_submit, which forces the container back to
// Gate_In. So the whole list read "Draft · Draft · Draft" for records that are, in fact,
// completed gate-outs. That is the ambiguity, more than the missing columns were.
//
// `has_indicator_for_draft` tells that check to stand down so the real status shows. The
// doctype carries no Document States rows, so the colours are mapped here.
frappe.listview_settings['Gate Entry'] = {
	add_fields: ['status', 'gate_out_timestamp'],
	has_indicator_for_draft: true,

	get_indicator(doc) {
		const map = {
			// Still in the yard — the tank has arrived but has not left.
			Active: ['Di Depo', 'orange', 'status,=,Active'],
			Gate_In_Completed: ['Masuk', 'blue', 'status,=,Gate_In_Completed'],
			EIR_Completed: ['EIR Selesai', 'light-blue', 'status,=,EIR_Completed'],
			// The terminal, and the only state that occurs today.
			Gate_Out_Completed: ['Keluar', 'green', 'status,=,Gate_Out_Completed'],
			Cancelled: ['Batal', 'red', 'status,=,Cancelled'],
		};
		return map[doc.status] || [doc.status || '—', 'gray', 'status,=,' + (doc.status || '')];
	},
};
