// Menu profil di halaman /desk (avatar pojok kanan atas): buang tiga item bawaan.
//
// `desk/page/desktop/desktop.js` `setup_avatar()` menulis daftar menunya SEBAGAI KONSTANTA di
// dalam fungsi — tidak ada hook, tidak ada Navbar Settings (doctype itu cuma mengisi dropdown
// navbar lama). Yang bisa dipegang dari luar tinggal `frappe.ui.create_menu`, pintu yang
// dilewati SETIAP menu Desk sebelum digambar, jadi filternya dipasang di situ.
//
// Yang dibuang dan alasannya:
//   About                 — daftar versi frappe/erpnext/app; informasi vendor, bukan urusan
//                           pemakai depot, dan satu-satunya isi dialognya.
//   Frappe Support        — membuka https://support.frappe.io; support OAK bukan di sana.
//   Reset Desktop Layout  — menghapus tata letak ikon desktop tanpa konfirmasi apa pun.
//
// Dicocokkan dengan label ASLI (bahasa Inggris, sebelum `__()`), karena itu yang ditulis
// desktop.js. Kalau frappe suatu saat mengganti labelnya, item itu muncul lagi — bukan error
// diam: yang hilang hanya penyaringannya.
(function () {
	const DROPPED_LABELS = ["About", "Frappe Support", "Reset Desktop Layout"];
	const create_menu = frappe.ui.create_menu;
	if (!create_menu) return;

	frappe.ui.create_menu = function (opts) {
		if (opts && Array.isArray(opts.menu_items)) {
			opts.menu_items = opts.menu_items.filter(
				(item) => !DROPPED_LABELS.includes(item?.label)
			);
		}
		return create_menu.call(this, opts);
	};
})();
