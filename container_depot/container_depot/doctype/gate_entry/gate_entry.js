// Gate Entry — Desk form.

frappe.ui.form.on('Gate Entry', {
	refresh(frm) {
		// Revisi Data / Tolak Revisi on a finished gate record (container_depot.revision):
		// truck, driver and guard — the gate times stay, the visit is counted from them.
		container_depot.revision.setup(frm, { locked: GATE_REVISION_LOCKED });
	},
});

// Mirrors gate_entry.REVISION_LOCKED — what a revision may not change.
const GATE_REVISION_LOCKED = [
	'gate_entry_id', 'status', 'booking_code', 'depot', 'order_doctype', 'order_ref',
	'container_no', 'gate_in_timestamp', 'gate_out_timestamp', 'eir_reference',
	'inspection_status', 'in_date', 'out_date', 'order_muat',
];
