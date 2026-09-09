// Penanda MENDESAK di Desk list — dua bentuk, karena satu saja tidak cukup.
//
// Tanggal mendesak (`urgent_date` di Container Booking, `target_urgent_on` di order yang
// memegang tank-nya) adalah alasan sebuah baris ada di puncak worklist orang lain. Di Desk
// alasan itu harus kelihatan tanpa membuka dokumennya, kalau tidak satu-satunya tempat
// urgensi terbaca hanyalah di PWA — dan yang menandainya duduk di Desk.
//
// **Dua bentuk** karena kolom bisa terpotong: Frappe memotong daftar kolom menurut lebar
// layar (4 kolom di layar <=1366px, 6 di layar biasa — lihat list_view.js get_columns), dan
// kolom tanggalnya ada di urutan kelima-keenam. Jadi:
//
//   `urgency_pill`    — formatter untuk KOLOM tanggalnya: pill merah beserta tanggalnya, dan
//                       bisa diklik untuk menyaring daftar jadi "yang mendesak saja"
//                       (`data-filter` + kelas `filterable`, persis cara pill status bekerja).
//   `urgency_subject` — formatter untuk kolom PERTAMA (subject): tidak pernah terpotong di
//                       lebar layar apa pun. Teks polos tanpa markup, karena subject dirender
//                       lewat `textContent` (list_view.js get_link_element) — HTML di situ
//                       akan tampil sebagai tulisan `<span ...>`, bukan sebagai pill.
//
// Merah tidak dipakai untuk status di sini: konvensi warna depot memberi merah pada
// "dibatalkan / void", jadi pill status TIDAK diganggu — urgensi hadir sebagai penanda
// tersendiri di sebelahnya, bukan dengan mengganti warna status.
frappe.provide("container_depot");

container_depot.urgency_pill = function (value, fieldname) {
	if (!value) return "";
	// "is set", bukan tanggal tertentu: yang dicari orang adalah "tunjukkan semua yang
	// mendesak", dan tanggalnya berbeda-beda tiap job.
	return `<span class="indicator-pill red filterable no-indicator-dot ellipsis"
		data-filter="${fieldname},is,set"
		title="${__("Didahulukan di atas semua tanggal survey — klik untuk menyaring yang mendesak saja")}"
		>${__("MENDESAK")} ${frappe.datetime.str_to_user(value)}</span>`;
};

container_depot.urgency_subject = function (value, doc, fieldname) {
	const day = doc && doc[fieldname];
	const subject = value || (doc && doc.name) || "";
	return day ? `${__("MENDESAK")} · ${subject}` : subject;
};
