// Daftar User tertutup untuk akun yang tidak punya izin `read` pada doctype User.
//
// Frappe memberi role `Desk User` izin `select` supaya picker orang (Assign To, Share,
// mention) bisa mencari nama, dan `db_query` menerima `select` SEBAGAI PENGGANTI `read` —
// jadi rute /app/user/view/list terbuka untuk semua akun, termasuk akun customer, lengkap
// dengan email seluruh staf. Penolakannya ada di server
// (`container_depot.user_directory.user_query`); yang dikerjakan di sini cuma
// menggambarkannya, karena list view menjawab 403 dengan kerangka halaman yang menggantung
// di "Refreshing…".
//
// Flagnya dari boot (`container_depot.boot.expose_user_list_block`), bukan
// `frappe.boot.user.can_read`: daftar can_read ikut memuat doctype yang izinnya cuma
// `select`, jadi "User" selalu ada di sana dan tidak bisa dipakai membedakan.
(function () {
	const settings = (frappe.listview_settings["User"] = frappe.listview_settings["User"] || {});
	const core_onload = settings.onload;

	settings.onload = function (listview) {
		if (frappe.boot.depot_block_user_list) {
			// Halaman yang sama dengan yang dipakai router saat PermissionError.
			frappe.show_not_permitted(__("User"));
			return;
		}
		return core_onload && core_onload.call(this, listview);
	};
})();
