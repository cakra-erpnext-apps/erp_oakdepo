// container_depot.close_order — "Tutup Order" on the Desk form, Administrator only.
//
// The server half is container_depot/container_depot/closing.py: the order is finished through
// its own Submit road (billed when its charges are filled, revisable later through Revisi
// Data), dated by its own date, and marked "Ditutup". This half offers the button and asks for
// the reason — and, on a Survey Order, which tanks.
//
// Registered here for every order doctype instead of in each form script, so the doctypes'
// own scripts (and their cache keys) stay untouched. The open-rules mirror closing.is_open;
// the server is the rule.
frappe.provide('container_depot');

container_depot.close_order = {
	OPEN: {
		'Cleaning Order': (d) => d.docstatus === 0 && d.status !== 'Cancelled',
		'Repair Order': (d) => !['Completed', 'Cancelled', 'Rejected'].includes(d.status),
		Inspection: (d) => d.docstatus === 0 && d.status !== 'Cancelled',
		'Leak Check': (d) => d.docstatus === 0 && d.status !== 'Cancelled',
		'Order Bongkar': (d) => d.docstatus === 1 && d.order_status !== 'Completed',
		'Order Muat': (d) => d.docstatus === 1 && d.order_status !== 'Completed',
		'Survey Order': (d) => d.docstatus < 2 && container_depot.close_order.open_rows(d).length > 0,
	},

	open_rows(doc) {
		return (doc.tanks || []).filter((r) => !['Survey Done', 'Cancelled'].includes(r.status));
	},

	setup(frm) {
		if (frappe.session.user !== 'Administrator' || frm.is_new()) return;
		if (!this.OPEN[frm.doctype](frm.doc)) return;
		frm.add_custom_button(__('Tutup Order'), () => this.ask(frm));
	},

	ask(frm) {
		const survey = frm.doctype === 'Survey Order';
		const fields = [];
		if (survey) {
			fields.push({
				fieldname: 'rows',
				fieldtype: 'MultiCheck',
				label: __('Tank yang sudah selesai'),
				reqd: 1,
				options: this.open_rows(frm.doc).map((r) => ({
					label: `${r.container_no || r.container} — ${__(r.status)}`,
					value: r.name,
					checked: 0,
				})),
			});
		}
		fields.push({ fieldname: 'reason', fieldtype: 'Small Text', label: __('Alasan'), reqd: 1 });
		const d = new frappe.ui.Dialog({
			title: __('Tutup Order'),
			fields: [
				{
					fieldtype: 'HTML',
					options: `<p class="text-muted small">${__(
						'Order diselesaikan langsung dengan tanggalnya sendiri, seperti Submit: ditagih kalau charges terisi, part keluar dari gudang, dan bisa direvisi nanti lewat Revisi Data.'
					)}</p>`,
				},
				...fields,
			],
			primary_action_label: __('Tutup Order'),
			primary_action(v) {
				if (survey && !(v.rows || []).length) {
					frappe.msgprint(__('Pilih minimal satu tank.'));
					return;
				}
				frappe.call({
					method: 'container_depot.container_depot.closing.close_order',
					args: { doctype: frm.doctype, name: frm.doc.name, reason: v.reason, rows: v.rows },
					freeze: true,
					callback() {
						d.hide();
						frappe.show_alert({ message: __('Order ditutup'), indicator: 'blue' });
						frm.reload_doc();
					},
				});
			},
		});
		d.show();
	},
};

Object.keys(container_depot.close_order.OPEN).forEach((doctype) => {
	frappe.ui.form.on(doctype, 'refresh', (frm) => container_depot.close_order.setup(frm));
});
