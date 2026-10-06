// "Delete" dan "Duplicate" dimatikan untuk dokumen operasional depo; daftar juga kehilangan
// tombol Actions (aksi massal) di semua modul (lihat bawah).
//
// Keduanya bawaan Frappe dan keduanya salah di sini, masing-masing karena alasan sendiri:
//
//   Delete    — dokumen-dokumen ini adalah CATATAN apa yang terjadi di lapangan, dan
//               cara membatalkannya sudah ada: Cancel / Void, yang menyimpan jejaknya
//               beserta invoice, bon dan tank yang terlanjur dirujuk. Menghapus barisnya
//               bukan versi lebih bersih dari itu — ia meninggalkan EIR yang menunjuk
//               booking yang tidak ada, invoice tanpa order, dan bon tanpa asal.
//               `on_trash` di beberapa doctype memang sudah menolak, tapi penolakan itu
//               baru terbaca SETELAH orang menekan Delete dan mengetik konfirmasinya.
//
//   Duplicate — nomor dokumen datang dari naming series dan isinya terikat pada satu tank,
//               satu kunjungan, satu kesepakatan. Salinan mentahnya selalu salah: tank yang
//               sama dibooking dua kali, EIR kedua untuk kunjungan yang sama. Order baru
//               dibuat dari menunya sendiri, yang mengisi konteksnya dengan benar.
//
//               Kecuali Container Booking (lihat DUPLICATE_OK di bawah): satu customer
//               memesan pekerjaan yang sama berulang kali, dan yang berulang justru bagian
//               atas formnya. Di sana Duplicate dibiarkan hidup, dan yang TIDAK boleh ikut
//               tersalin dijaga dengan `no_copy: 1` di doctype-nya — container, biaya,
//               pembayaran, DO, catatan dan seluruh kolom sistem lahir kosong; yang terbawa
//               hanya section "Booking" dan "Pihak".
//
// Ditegakkan di prototype toolbar/list, bukan per-doctype, supaya berlaku sama di semua
// form dan daftar — termasuk lewat pintasan keyboard, yang ikut mati karena ia didaftarkan
// bersama item menunya (`add_menu_item` di toolbar.js). Sebagian doctype sudah memakai
// `allow_copy: 1` (yang di Frappe artinya "Hide Copy" — lihat catatan di doctype-nya);
// guard ini yang membuat aturannya berlaku untuk semuanya, juga yang belum menyalakan flag
// itu.
//
// Ini murni permukaan Desk. Hak `delete` sendiri tetap seperti seeder RBAC mengaturnya
// (hanya System Manager), dan penghapusan lewat API / console tetap ada untuk perbaikan
// data yang memang harus dilakukan Administrator secara sadar.

(function () {
	// Tiga kelompok, satu aturan — semuanya dokumen yang dirujuk dokumen lain:
	const GUARDED = new Set([
		// Order & bon: yang dipesan pelanggan dan yang dikerjakan depo.
		'Container Booking',
		'Booking Code',
		'Order Muat',
		'Order Bongkar',
		'Inspection',
		'Cleaning Order',
		'Repair Order',
		'Survey Order',
		// Jejak: apa yang benar-benar lewat gerbang dan berpindah di yard.
		'Gate Entry',
		'Container Movement',
		'Container Activity',
		// Penagihan: angka yang sudah (atau akan) masuk invoice.
		'Storage Charge',
		'OAK Monthly Invoice',
	]);

	// Dijaga dari Delete, TAPI Duplicate tetap boleh — lihat catatan Duplicate di atas.
	const DUPLICATE_OK = new Set(['Container Booking']);

	const Toolbar = frappe.ui?.form?.Toolbar;
	if (Toolbar) {
		['add_delete', 'add_duplicate'].forEach((method) => {
			const original = Toolbar.prototype[method];
			if (!original) return;
			Toolbar.prototype[method] = function () {
				const doctype = this.frm?.doctype;
				const allowed = method === 'add_duplicate' && DUPLICATE_OK.has(doctype);
				if (GUARDED.has(doctype) && !allowed) return;
				return original.apply(this, arguments);
			};
		});
	}

	// Daftar: TANPA aksi massal (user, 2026-10-06), di semua daftar semua modul — List view dan
	// Report view; form tidak tersentuh. Banyak aturan "tidak boleh" hanya hidup di tombol form
	// (Cancel merah, Kembalikan ke Draft dulu), dan aksi massal melewatinya: bon Completed bisa
	// ter-Cancel, puluhan invoice batal sekali klik, state Booking Code diganti massal — plus
	// aksi massal yang ditambahkan ERPNext / app sendiri (Payment dari Sales Invoice, Close
	// Purchase Order, Void Pending Cash …). Menyembunyikan tombol Actions menutup semuanya
	// sekaligus; centang barisnya ikut disembunyikan (container_depot.css). Print dan Export
	// tetap: menu ⋯ di Report view, untuk semua baris yang lolos filter.
	const ListView = frappe.views?.ListView;
	if (ListView?.prototype?.toggle_actions_menu_button) {
		const toggle = ListView.prototype.toggle_actions_menu_button;
		ListView.prototype.toggle_actions_menu_button = function () {
			return toggle.call(this, false);
		};
	}
})();
