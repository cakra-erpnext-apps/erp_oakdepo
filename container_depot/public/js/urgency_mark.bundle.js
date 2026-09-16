// Prioritas satu baris di Desk list — kosakata yang sama persis dengan PWA.
//
// Sebelum ini Desk cuma menjawab SATU pertanyaan: mendesak atau tidak. Baris yang tidak
// ditandai mendesak tampil dengan kolom tanggal kosong, jadi dari daftar Desk tidak
// kelihatan mana yang tinggal dua hari lagi dan mana yang masih dua minggu — padahal yang
// duduk di Desk-lah yang menentukan urutan kerja lapangan. Di PWA jawabannya sudah ada dan
// sudah dihafal operator ("H-3", "Hari-H", "Lewat 2 hr"); yang kurang cuma menyalakannya di
// sini, dengan bunyi dan warna yang sama supaya satu kosakata dipakai kedua layar.
//
// **Tanggalnya harus tanggal yang sama dengan yang dipakai server mengurutkan.** Definisi
// tunggalnya ada di `container_depot/worklist.py` (`urgent_date` → `priority_date`):
//
//     mendesak  →  tanggal survey  →  rencana pickup
//
// Mendesak MENGGANTIKAN tenggat di bawahnya, bukan menambah pill kedua: begitu tanggal
// mendesak terisi, dialah yang menaruh baris ini di puncak semua worklist, jadi memajang
// tanggal survey di sebelahnya berarti memajang tanggal yang bukan lagi penentu urutannya.
// Nama field-nya berbeda tiap doctype (Container Booking memakai `urgent_date`, order yang
// memegang tank memakai `target_urgent_on`), jadi tiap list menyebutkan triplet-nya sendiri.
//
// **Dua bentuk penanda** karena kolom bisa terpotong: Frappe memotong daftar kolom menurut
// lebar layar (4 kolom di layar <=1366px, 6 di layar biasa — lihat list_view.js
// get_columns), dan kolom prioritasnya ada di urutan kelima-keenam. Jadi:
//
//   `priority_pill`    — formatter untuk kolomnya: pill lengkap "MENDESAK · H-2 · 9 Sep",
//                        dan kalau mendesak bisa diklik untuk menyaring daftar jadi yang
//                        mendesak saja (`data-filter` + kelas `filterable`, persis cara
//                        pill status bekerja).
//   `urgency_subject`  — formatter untuk kolom PERTAMA (subject): tidak pernah terpotong di
//                        lebar layar apa pun. Teks polos tanpa markup, karena subject
//                        dirender lewat `textContent` (list_view.js get_link_element) —
//                        HTML di situ akan tampil sebagai tulisan `<span ...>`, bukan pill.
//                        Sengaja HANYA menandai yang mendesak: awalan "H-3 · " di depan tiap
//                        nomor tank akan memakan kolom yang paling sering dibaca demi
//                        keterangan yang pill di sebelahnya sudah berikan.
//
// Merah tidak dipakai untuk status di sini: konvensi warna depot memberi merah pada
// "dibatalkan / void", jadi pill status TIDAK diganggu — prioritas hadir sebagai penanda
// tersendiri di sebelahnya, bukan dengan mengganti warna status.
frappe.provide("container_depot");

const MONTHS = [
	"Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
	"Jul", "Agu", "Sep", "Okt", "Nov", "Des",
];

// Tanggal polos, dibandingkan tanggal-ke-tanggal di waktu lokal: mem-parse-nya sebagai
// "YYYY-MM-DDT00:00:00" (bukan membiarkan Date memperlakukan tanggal telanjang sebagai UTC)
// menjaga Hari-H tetap jatuh di hari pelanggannya benar-benar datang, di Jakarta dan bukan
// di London. Sama persis dengan frontend/src/utils/liftOn.js.
container_depot.priority_days = function (value) {
	if (!value) return null;
	const target = new Date(String(value).slice(0, 10) + "T00:00:00");
	const today = new Date(new Date().toDateString());
	return Math.round((target - today) / 86400000);
};

container_depot.h_minus = function (value) {
	const d = container_depot.priority_days(value);
	if (d === null) return "";
	if (d < 0) return __("Lewat {0} hr", [-d]);
	if (d === 0) return __("Hari-H");
	return `H-${d}`;
};

container_depot.day_month = function (value) {
	if (!value) return "";
	const [, m, d] = String(value).slice(0, 10).split("-").map(Number);
	return m ? `${d} ${MONTHS[m - 1]}` : String(value);
};

// Tanjakan warnanya, ambang persis seperti di PWA (`liftOn.liftChipClass`) supaya yang sudah
// dihafal operator tidak bergeser di layar sebelah: diam → kuning → merah → merah penuh.
// Frappe hanya punya pill berlatar muda, jadi ujung merah penuhnya dari CSS app sendiri
// (`.oak-pri-alarm` di public/css/container_depot.css) — lewat tenggat dan mendesak memang
// bukan "satu tingkat lagi", keduanya kategori lain.
function ramp(days, urgent) {
	if (urgent || days < 0) return "oak-pri-alarm";
	if (days <= 1) return "red";
	if (days <= 3) return "orange";
	return "gray";
}

/**
 * Pill prioritas satu baris.
 *
 * `fields` menyebutkan triplet doctype-nya: `{ urgent, survey, due }` — nama field, bukan
 * nilainya, karena formatter Frappe hanya dapat `doc` mentah.
 */
container_depot.priority_pill = function (doc, fields) {
	if (!doc) return "";
	const urgent = fields.urgent ? doc[fields.urgent] : "";
	const day = urgent || (fields.survey && doc[fields.survey]) || (fields.due && doc[fields.due]);
	if (!day) return "";

	const days = container_depot.priority_days(day);
	const text = [
		urgent ? __("MENDESAK") : "",
		container_depot.h_minus(day),
		container_depot.day_month(day),
	]
		.filter(Boolean)
		.join(" · ");

	// Hanya yang mendesak yang bisa diklik, dan filternya "is set" bukan tanggal tertentu:
	// yang dicari orang adalah "tunjukkan semua yang mendesak", dan tanggalnya berbeda tiap
	// job. Baris tak-mendesak tidak diberi filter sama sekali — menyaring "tenggatnya persis
	// 9 Sep" bukan pertanyaan yang pernah ditanyakan siapa pun.
	const filter = urgent ? `data-filter="${fields.urgent},is,set"` : "";
	const classes = [
		"indicator-pill",
		ramp(days, urgent),
		"no-indicator-dot",
		"ellipsis",
		urgent ? "filterable" : "",
	]
		.filter(Boolean)
		.join(" ");
	const title = urgent
		? __("Didahulukan di atas semua tanggal survey — klik untuk menyaring yang mendesak saja")
		: __("Tenggat pekerjaan ini: tanggal survey, atau rencana pickup kalau surveinya belum dijadwalkan");

	return `<span class="${classes}" ${filter} title="${title}">${text}</span>`;
};

container_depot.urgency_subject = function (value, doc, fieldname) {
	const day = doc && doc[fieldname];
	const subject = value || (doc && doc.name) || "";
	return day ? `${__("MENDESAK")} · ${subject}` : subject;
};

/**
 * Beri judul kolomnya nama yang sesuai dengan isinya.
 *
 * Pill-nya menumpang kolom `target_urgent_on` / `urgent_date` yang sudah ada — kolom itu
 * memang selalu ada di keenam daftar ini, dan memakainya kembali berarti tidak ada kolom
 * baru yang merebut lebar dari kolom lain. Tapi judul "Tanggal Mendesak" jadi berbohong
 * begitu barisnya menampilkan "H-3" untuk order yang tidak ditandai mendesak, jadi
 * headernya ditulis ulang jadi "Prioritas".
 *
 * `col.df` disalin dangkal, TIDAK diubah di tempat: `df` itu docfield milik meta bersama
 * (frappe.get_meta), dan menimpanya juga akan mengganti label field ini di form-nya.
 */
container_depot.priority_column = function (listview, fieldname) {
	if (listview._priority_column_labelled) return;
	listview._priority_column_labelled = true;

	const build_columns = listview.setup_columns.bind(listview);
	listview.setup_columns = function () {
		build_columns();
		this.columns = this.columns.map((col) =>
			col.df && col.df.fieldname === fieldname
				? { ...col, df: { ...col.df, label: __("Prioritas") } }
				: col
		);
	};
	// setup_view() sudah menjalankan keduanya sebelum memanggil onload — ulangi supaya baris
	// header ikut memakai judul barunya (true = buang header yang barusan dirender).
	listview.setup_columns();
	listview.render_header(true);
};
