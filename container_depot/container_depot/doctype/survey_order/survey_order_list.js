// Survey Order list — penanda prioritas, dan itu saja.
//
// Sengaja tidak ada `get_indicator` di sini: Survey Order submittable, jadi pill bawaan
// Frappe (Draft / Submitted) masih yang dipakai, dan `status`-nya sendiri sudah jadi kolom
// lewat in_list_view. Yang belum terjawab hanya satu: mana jadwal yang harus didahulukan.
//
// Urgensinya dipasang di booking dan turun ke BARIS tank, jadi headernya meringkas tanggal
// mendesak paling dekat di antara tank-nya (`survey_order.refresh_urgency`) — satu tank
// mendesak sudah cukup membuat harinya mendesak. Jadwal yang tidak ditandai mendesak pun
// tetap punya jawabannya: hitung mundur ke hari survey-nya sendiri. Dua bentuk penanda
// karena kolom bisa terpotong di layar sempit; lihat public/js/urgency_mark.js.
//
// Doctype ini tidak punya `title_field`, jadi kolom subject-nya adalah `name` (nomor SO) —
// di situlah awalannya dipasang.
// Tenggat jadwal ini. Hari survey-nya ada di doctype ini sendiri, jadi tidak ada `target_*`
// yang perlu diturunkan dari booking — rencana pickup cuma cadangan kalau tanggalnya kosong.
const PRIORITY = { urgent: "target_urgent_on", survey: "survey_date", due: "plan_date" };

frappe.listview_settings["Survey Order"] = {
	add_fields: [...Object.values(PRIORITY)],

	formatters: {
		name(value, df, doc) {
			return container_depot.urgency_subject(value, doc, PRIORITY.urgent);
		},
		target_urgent_on(value, df, doc) {
			return container_depot.priority_pill(doc, PRIORITY);
		},
	},

	onload(listview) {
		container_depot.priority_column(listview, PRIORITY.urgent);
	},
};
