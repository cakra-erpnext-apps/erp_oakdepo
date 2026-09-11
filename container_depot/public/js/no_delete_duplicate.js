// "Delete" dan "Duplicate" dimatikan untuk dokumen operasional depo.
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

	const Toolbar = frappe.ui?.form?.Toolbar;
	if (Toolbar) {
		['add_delete', 'add_duplicate'].forEach((method) => {
			const original = Toolbar.prototype[method];
			if (!original) return;
			Toolbar.prototype[method] = function () {
				if (GUARDED.has(this.frm?.doctype)) return;
				return original.apply(this, arguments);
			};
		});
	}

	// Daftar: Actions ▸ Delete (hapus massal). Disaring dari daftar item yang sudah dibangun
	// Frappe, bukan dengan mencabut elemennya dari DOM setelah tergambar — menu itu dibangun
	// ulang tiap kali daftar dimuat, dan yang berkedip sesaat lalu hilang lebih buruk
	// daripada yang tidak pernah ada.
	const ListView = frappe.views?.ListView;
	if (ListView?.prototype?.get_actions_menu_items) {
		const original = ListView.prototype.get_actions_menu_items;
		ListView.prototype.get_actions_menu_items = function () {
			const items = original.apply(this, arguments);
			if (!GUARDED.has(this.doctype)) return items;
			// Label yang sama persis dengan yang dipasang Frappe, KONTEKS terjemahannya ikut:
			// `__('Delete')` polos bisa menghasilkan string lain di Desk berbahasa Indonesia.
			const label = __('Delete', null, 'Button in list view actions menu');
			return items.filter((item) => item.label !== label);
		};
	}
})();
