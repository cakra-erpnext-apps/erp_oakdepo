// Filter bersama report depot — pasangan container_depot/report_kit.py.
//
//   frappe.query_reports["X"] = {
//     filters: [
//       ...container_depot.report_kit.filters([["order_date", "Order Date"], ["wash_date", "Wash Date"]]),
//       { fieldname: "principal", ... },
//     ],
//     onload: container_depot.report_kit.onload,
//   };
//
// "Cari" mencari di semua kolom teks baris (nomor tank, dokumen, customer, catatan), jadi
// user tidak perlu tahu filter mana yang memegang yang dicari. "Tanggal" memilih kolom
// tanggal mana yang disaring Dari/Sampai — kolom pertama = bawaan report.
frappe.provide('container_depot');

container_depot.report_kit = {
	filters(dates) {
		const out = [
			{
				fieldname: 'search',
				label: __('Cari'),
				fieldtype: 'Data',
				description: __('No. tank, dokumen, customer, cargo, catatan…'),
			},
		];
		if (dates && dates.length) {
			if (dates.length > 1) {
				out.push({
					fieldname: 'date_based_on',
					label: __('Tanggal'),
					fieldtype: 'Select',
					options: dates.map(([value, label]) => ({ value, label: __(label) })),
					default: dates[0][0],
				});
			}
			out.push(
				{ fieldname: 'from_date', label: __('Dari Tanggal'), fieldtype: 'Date' },
				{ fieldname: 'to_date', label: __('Sampai Tanggal'), fieldtype: 'Date' }
			);
		}
		return out;
	},

	// Header kolom seperti sheet Excel yang sudah dipakai user (tebal, rata tengah, bergaris)
	// — dipasang per report lewat kelas, tidak mengubah report Frappe/ERPNext lain. Warna
	// lewat variabel tema Frappe, bukan hex, supaya ikut dark mode.
	onload(report) {
		report.page.wrapper.addClass('oak-excel-report');
		if (document.getElementById('oak-excel-report-css')) return;
		const css = document.createElement('style');
		css.id = 'oak-excel-report-css';
		css.textContent = `
			.oak-excel-report .dt-cell--header {
				background: var(--subtle-fg); border-right: 1px solid var(--dark-border-color);
			}
			.oak-excel-report .dt-cell--header .dt-cell__content {
				font-weight: 700; color: var(--heading-color); text-align: center; white-space: nowrap;
			}
			.oak-excel-report .dt-row:not(.dt-row-filter) .dt-cell { border-right: 1px solid var(--border-color); }
		`;
		document.head.appendChild(css);
	},
};
