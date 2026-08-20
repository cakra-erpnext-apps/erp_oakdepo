// Copyright (c) 2026, Oak Depot Team and contributors
// For license information, please see license.txt

// Inspection (EIR) list view — colour each row by the EIR's real state so the
// worklist reads at a glance, including the "Revisi Diminta" flag the PWA raises
// (container_depot.container_depot.eir.request_revision) which otherwise left no mark.
frappe.listview_settings['Inspection'] = {
	add_fields: ['revision_requested', 'docstatus', 'status'],

	// Direction as a colour, not a word to read: green In / orange Out, matching the gate
	// PWA's GATE IN / GATE OUT so one habit covers both screens. The stored value stays
	// "EIR-In"/"EIR-Out" — the "EIR-" half is noise in a column headed "Tipe EIR".
	formatters: {
		inspection_type(value) {
			const pill = (colour, text) =>
				`<span class="indicator-pill no-indicator-dot ${colour}">${__(text)}</span>`;
			if (value === 'EIR-In') return pill('green', 'In');
			if (value === 'EIR-Out') return pill('orange', 'Out');
			return frappe.utils.escape_html(value || '');
		},
	},

	// Frappe's get_indicator (model/indicator.js) short-circuits to a default "Draft"/
	// "Cancelled" pill for submittable docs at docstatus 0/2 BEFORE it ever calls our
	// get_indicator — unless these flags are set. Without them a Pending-Review EIR (still
	// docstatus 0) shows the stock red "Draft" and "Menunggu Review" never renders.
	has_indicator_for_draft: 1,
	has_indicator_for_cancelled: 1,

	// Single status vocabulary, identical to the PWA (Eir.vue / EirHistory.vue) so the two
	// surfaces never read differently: Batal / Revisi Diminta / Selesai / Menunggu Review / Draf.
	//
	// Colour convention, shared by every Container Depot list: grey = draft, red = batal,
	// blue = the terminal submitted state, any other colour = a stage in between. So a
	// draft EIR is no longer alarming red, and a cancelled one no longer quiet grey.
	get_indicator(doc) {
		if (doc.docstatus === 2) return [__('Batal'), 'red', 'docstatus,=,2'];
		// A submitted EIR with a pending revision request stands out (needs Admin Ops).
		if (doc.docstatus === 1 && doc.revision_requested) {
			return [__('Revisi Diminta'), 'orange', 'revision_requested,=,1'];
		}
		if (doc.docstatus === 1) return [__('Selesai'), 'blue', 'docstatus,=,1'];
		// Field operator submitted → awaiting Admin Ops review + final submit.
		if (doc.status === 'Pending Review') {
			return [__('Menunggu Review'), 'purple', 'status,=,Pending Review'];
		}
		return [__('Draf'), 'gray', 'docstatus,=,0'];
	},
};
