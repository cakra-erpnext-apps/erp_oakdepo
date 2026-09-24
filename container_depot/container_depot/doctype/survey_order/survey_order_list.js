// Survey Order list — pill status standar (public/js/status_pill.js), plus penanda prioritas.
//
// Pill bawaan Frappe untuk doctype submittable (Draft / Submitted) tidak berarti apa-apa di
// sini: jadwal submit sendiri saat semua tank selesai, jadi "Draft" = Siap Dikerjakan ATAU
// Dikerjakan. `get_indicator` membaca `status` dan memetakannya ke kosakata standar yang sama
// dengan Cleaning / Repair Order. Juga dipakai di kepala form.
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

const STATUS = {
	Scheduled: "ready",
	"In Progress": "doing",
	Completed: "done",
	Cancelled: "cancelled",
};

frappe.listview_settings["Survey Order"] = {
	add_fields: ["status", ...Object.values(PRIORITY)],
	has_indicator_for_draft: 1,
	has_indicator_for_cancelled: 1,

	get_indicator(doc) {
		const s = STATUS[doc.status];
		return s && container_depot.status_pill(s, `status,=,${doc.status}`);
	},

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
