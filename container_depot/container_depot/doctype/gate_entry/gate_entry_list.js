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
//
// WHY onload CLEARS THE ADD BUTTON: Riwayat Gate is an audit log. Every row is written by a
// hook — the arrival by `Order Bongkar._record_gate_in`, the departure by `gate.mark_gate_out`,
// the SST lane by `api.register_gate_entry` — and `install.NO_MANUAL_CREATE` strips the create
// permission for every role to match. Administrator bypasses permissions entirely, though, so
// the button survives there; this removes it. `can_create = false` is set as well because
// `toggle_actions_menu_button` re-runs `set_primary_action` whenever a row checkbox is cleared.
frappe.listview_settings['Gate Entry'] = {
	add_fields: ['status', 'gate_out_timestamp'],
	has_indicator_for_draft: true,

	onload(listview) {
		listview.can_create = false;
		listview.page.clear_primary_action();
	},

	// Colour convention, shared by every Container Depot list: grey = draft / status
	// belum terisi, red = batal, blue = the terminal state, any other colour = a stage
	// in between. The gate log ends at Gate_Out_Completed, so "Keluar" is the blue one.
	get_indicator(doc) {
		const map = {
			// Still in the yard — the tank has arrived but has not left.
			Active: [__('Di Depo'), 'orange', 'status,=,Active'],
			Gate_In_Completed: [__('Masuk'), 'green', 'status,=,Gate_In_Completed'],
			EIR_Completed: [__('EIR Selesai'), 'purple', 'status,=,EIR_Completed'],
			// The terminal, and the only state that occurs today.
			Gate_Out_Completed: [__('Keluar'), 'blue', 'status,=,Gate_Out_Completed'],
			Cancelled: [__('Batal'), 'red', 'status,=,Cancelled'],
		};
		return map[doc.status] || [doc.status || __('Draf'), 'gray', 'status,=,' + (doc.status || '')];
	},
};
