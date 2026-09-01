// Riwayat satu tank, dibuka dari baris register (Steam Wash / PP Wash / Methanol Rinse /
// Periodic Test). Sebuah baris register menjawab "order ini bagaimana"; yang ditanyakan
// berikutnya hampir selalu "tank ini SEBELUMNYA bagaimana" — dan di sheet, jawabannya
// adalah menggulung ratusan baris mencari nomor tank yang sama.
//
// Isinya diambil dari report registernya sendiri lewat container_depot.register_history,
// jadi dialog ini tidak pernah menyatakan sesuatu yang berbeda dari tabel di belakangnya.
frappe.provide('container_depot');

// Sel Tank No yang bisa diklik. Dipakai di formatter tiap report register.
container_depot.tank_history_cell = function (register, tank) {
	if (!tank) return '';
	const safe = frappe.utils.escape_html(tank);
	return `<a href="#" onclick="container_depot.show_tank_history('${encodeURIComponent(
		register
	)}', '${encodeURIComponent(tank)}'); return false;">${safe}</a>`;
};

container_depot.show_tank_history = function (register, tank) {
	register = decodeURIComponent(register);
	tank = decodeURIComponent(tank);
	frappe.call({
		method: 'container_depot.container_depot.register_history.tank_history',
		args: { container: tank, register: register },
		freeze: true,
		callback: function (r) {
			if (!r.message) return;
			const dialog = new frappe.ui.Dialog({
				title: __('Riwayat {0} — {1}', [tank, register]),
				size: 'large',
				fields: [{ fieldtype: 'HTML', fieldname: 'history' }],
			});
			dialog.fields_dict.history.$wrapper.html(container_depot._history_table(r.message));
			dialog.show();
		},
	});
};

container_depot._history_table = function (data) {
	if (!data.rows || !data.rows.length) {
		// Tank yang belum pernah masuk register ini bukan error — dikatakan apa adanya.
		return `<p class="text-muted">${__('Belum ada riwayat untuk tank ini.')}</p>`;
	}
	const head = data.columns.map((c) => `<th>${frappe.utils.escape_html(c.label)}</th>`).join('');
	const body = data.rows
		.map((row) => {
			const cells = data.columns
				.map((c) => `<td>${container_depot._history_cell(row[c.fieldname], c)}</td>`)
				.join('');
			return `<tr>${cells}</tr>`;
		})
		.join('');
	return `<div class="table-responsive"><table class="table table-bordered table-sm">
		<thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
};

container_depot._history_cell = function (value, column) {
	if (value === null || value === undefined || value === '') return '';
	if (column.fieldtype === 'Link' && column.options) {
		// Setiap dokumen yang disebut baris riwayat bisa dibuka langsung — termasuk
		// invoicenya, yang justru sering jadi alasan orang membuka riwayat ini.
		return container_depot.doc_link(column.options, value) || frappe.utils.escape_html(value);
	}
	if (column.fieldtype === 'Date') return frappe.datetime.str_to_user(value);
	return frappe.utils.escape_html(String(value));
};
