// Copyright (c) 2026, Oak Depot Team and contributors
// For license information, please see license.txt

// Inspection (EIR) list view — colour each row by the EIR's real state so the
// worklist reads at a glance, including the "Revisi Diminta" flag the PWA raises
// (container_depot.container_depot.eir.request_revision) which otherwise left no mark.
frappe.listview_settings['Inspection'] = {
	add_fields: ['revision_requested', 'docstatus', 'status', 'work_started_on'],

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
	// surfaces never read differently: Batal / Revisi Diminta / Selesai / Menunggu Review /
	// Dikerjakan / Draf.
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
		// "Mulai" pressed in the PWA (start_eir stamps work_started_on) but not yet sent for
		// review — the same belum / dikerjakan split the PWA worklist shows, so a draft that
		// somebody is actually standing at the tank filling in no longer reads as untouched.
		if (doc.work_started_on) return [__('Dikerjakan'), 'yellow', 'work_started_on,is,set'];
		return [__('Draf'), 'gray', 'docstatus,=,0'];
	},

	// "Dibuat" as a column. Mulai Pengerjaan / Dimulai Oleh are ordinary docfields and get
	// their columns from in_list_view in inspection.json, but `creation` is a standard
	// column, not a docfield — setup_columns() only ever walks meta.fields, so there is no
	// declarative way to ask for it. Wrapping setup_columns is the one seam: it re-runs on
	// every rebuild (incl. after the user saves List View Settings), so the column sticks.
	onload(listview) {
		if (listview._creation_column_added) return;
		listview._creation_column_added = true;
		const build_columns = listview.setup_columns.bind(listview);
		listview.setup_columns = function () {
			build_columns();
			// `creation` rides along in every list fetch (frappe.model.std_fields_list), so
			// this needs no add_fields entry — only a df for the formatter and the header,
			// whose data-sort-by makes the column click-to-sort like any other.
			this.columns.push({
				type: 'Field',
				df: { label: __('Dibuat'), fieldname: 'creation', fieldtype: 'Datetime' },
			});
		};
		// setup_view() already ran both of these before calling onload — redo them so the
		// header row picks the new column up (true = drop the header it just rendered).
		listview.setup_columns();
		listview.render_header(true);
	},
};
