// Survey Order list — penanda MENDESAK, dan itu saja.
//
// Sengaja tidak ada `get_indicator` di sini: Survey Order submittable, jadi pill bawaan
// Frappe (Draft / Submitted) masih yang dipakai, dan `status`-nya sendiri sudah jadi kolom
// lewat in_list_view. Yang belum terjawab hanya satu: mana jadwal yang harus didahulukan.
//
// Urgensinya dipasang di booking dan turun ke BARIS tank, jadi headernya meringkas tanggal
// mendesak paling dekat di antara tank-nya (`survey_order.refresh_urgency`) — satu tank
// mendesak sudah cukup membuat harinya mendesak. Dua bentuk penanda karena kolom bisa
// terpotong di layar sempit; lihat public/js/urgency_mark.js.
//
// Doctype ini tidak punya `title_field`, jadi kolom subject-nya adalah `name` (nomor SO) —
// di situlah awalannya dipasang.
frappe.listview_settings["Survey Order"] = {
	add_fields: ["target_urgent_on"],

	formatters: {
		name(value, df, doc) {
			return container_depot.urgency_subject(value, doc, "target_urgent_on");
		},
		target_urgent_on(value) {
			return container_depot.urgency_pill(value, "target_urgent_on");
		},
	},
};
