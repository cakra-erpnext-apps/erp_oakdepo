// Form User: rapikan form pembuatan user, dan guard handler Role Profiles bawaan Frappe.
//
// Skrip ini dimuat lewat hook `doctype_js` untuk "User", jadi berjalan SETELAH user.js core —
// baik saat mendaftarkan handler maupun saat handler `refresh` dijalankan.

// ---------------------------------------------------------------------------------------
// 0. Menyembunyikan TAB tidak bisa lewat `set_df_property`
//
// `frm.set_df_property` menulis ke salinan docfield PER DOKUMEN
// (`frappe.meta.docfield_copy[doctype][docname]`), sementara objek Tab memegang docfield
// GLOBAL dari `frappe.get_meta` — dibuktikan di browser pada frappe 16.18.3:
// `tab.df === frappe.get_meta("User").fields[...]` true, `=== frappe.meta.get_docfield(...)`
// false. Jadi Section Break ikut sembunyi (control-nya membaca salinan per dokumen), tapi
// Tab Break tidak pernah. Satu-satunya pegangan adalah objek Tab-nya sendiri.
//
// Karena docfield-nya global, nilainya bertahan untuk semua dokumen User di sesi itu —
// jadi pemanggilnya WAJIB menyetel kedua arah (sembunyi/tampil), bukan cuma menyembunyikan.
function set_tabs_hidden(frm, fieldnames, hidden) {
	for (const tab of frm.layout?.tabs || []) {
		if (!fieldnames.includes(tab.df?.fieldname)) continue;
		tab.df.hidden = hidden ? 1 : 0;
		tab.refresh();
	}
}

// ---------------------------------------------------------------------------------------
// 1. Tata letak form "New User"
//
// Form pembuatan user bawaan menampilkan seluruh isi doctype User sekaligus, termasuk yang
// baru ada artinya SETELAH user tersimpan: API Access, Third Party Authentication, Email,
// Document Follow, dan preferensi Desk yang sebenarnya milik user itu sendiri (tema, sidebar,
// tombol navigasi). Sebaliknya, satu-satunya hal yang benar-benar menentukan user baru —
// Role Profiles — justru tidak kelihatan: user.js core menyembunyikan section "Roles" (sb1)
// di setiap refresh dan hanya membukanya kembali untuk dokumen yang sudah tersimpan. Jadi
// form pembuatan penuh oleh hal yang belum bisa diisi, dan kehilangan hal yang harus diisi.
//
// Yang tersisa di sini tinggal tiga hal: identitas (tab User Details), peran (tab Roles &
// Permissions), dan halaman awal (section App). Change Password tetap dibiarkan apa adanya —
// `depends_on` bawaannya sudah memunculkannya persis saat dibutuhkan, yaitu ketika "Send
// Welcome Email" dimatikan sehingga password harus diisi manual.
//
// Semua yang disembunyikan muncul lagi begitu user disimpan: `set_df_property` bekerja pada
// salinan docfield PER DOKUMEN, dan nama dokumen berubah dari `new-user-xxxx` menjadi email
// user setelah insert. Form user yang sudah tersimpan tidak pernah ikut terpengaruh.
const HIDE_UNTIL_SAVED = [
	// Diisi server saat simpan.
	"full_name",
	// Role editor & module editor hanya dibuat core untuk dokumen tersimpan; di dokumen baru
	// keduanya cuma menyisakan blok kosong.
	"roles_html",
	"sb_allow_modules",
	// Preferensi tampilan milik user yang bersangkutan, bukan urusan yang membuatkan akun.
	"desk_settings_section",
	"navigation_settings_section",
	"list_settings_section",
	"form_settings_section",
	"document_follow_notifications_section",
	"email_settings",
	"workspace_section",
	// Baru bisa dipakai setelah ada user-nya.
	"third_party_authentication",
	"api_access",
];

frappe.ui.form.on("User", {
	refresh(frm) {
		// Tab, bukan field — lihat bagian 0. Disetel dua arah: docfield-nya global, jadi
		// tanpa `false` di dokumen tersimpan tab ini ikut hilang di form user lain.
		set_tabs_hidden(frm, ["connections_tab"], frm.is_new());
		if (!frm.is_new()) return;

		// Core menyembunyikan sb1 di setiap refresh (`toggle_display(["sb1", ...], false)`),
		// dan handler ini berjalan sesudahnya — jadi cukup dibuka kembali di sini.
		frm.set_df_property("sb1", "hidden", 0);

		for (const fieldname of HIDE_UNTIL_SAVED) {
			frm.set_df_property(fieldname, "hidden", 1);
		}
	},
});

// ---------------------------------------------------------------------------------------
// 2. Handler Role Profiles bawaan error di dokumen baru
//
// core/doctype/user/user.js membuat `frm.roles_editor` HANYA untuk dokumen yang sudah
// tersimpan (`!frm.is_new()`), tapi handler `role_profiles_add` / `role_profiles_remove`
// memakainya tanpa pemeriksaan. Jadi di form (atau quick entry) User baru, setiap
// penambahan/penghapusan Role Profile melempar TypeError dan membatalkan rantai promise yang
// menyetel nilai field itu.
//
// Saat editor belum ada, yang dilewati hanya urusan tampilan: `populate_role_profile_roles`
// cuma mengisi tabel Roles supaya terlihat di editor tersebut, dan server tetap
// menjalankannya sendiri lewat `User.validate` waktu user disimpan. Jadi melewati handler
// pada dokumen baru tidak menghilangkan role apa pun.
//
// Masih ada juga di upstream v16.27, jadi guard ini tidak dibatasi versi.

(function () {
	const handlers = frappe.ui.form.handlers["User Role Profile"];
	if (!handlers) return;

	for (const event of ["role_profiles_add", "role_profiles_remove"]) {
		const handler_list = handlers[event] || [];
		handler_list.forEach((handler, i) => {
			if (handler.__depot_guarded) return;

			const guarded = function (frm, ...rest) {
				if (!frm?.roles_editor) return;
				if (event === "role_profiles_remove" && frm.doc.role_profiles?.length > 0) {
					frm.roles_editor.disable = 1;
					frm.call("populate_role_profile_roles").then(() => {
						frm.roles_editor.show();
					});
					$(".deselect-all, .select-all").prop("disabled", true);
					return;
				}
				return handler(frm, ...rest);
			};
			guarded.__depot_guarded = true;
			handler_list[i] = guarded;
		});
	}
})();

// ---------------------------------------------------------------------------------------
// 3. Form User milik user sendiri (non System Manager)
//
// Frappe membagikan tiap dokumen User ke user-nya sendiri lewat DocShare read+write
// (lihat `tabDocShare`, share_doctype = "User"), jadi SETIAP akun bisa membuka
// /app/user/<email>-nya sendiri walaupun role `Desk User` cuma punya `select`. Yang terbuka
// di sana bukan cuma profilnya: preferensi Desk, Email, Document Follow, Workspace/App
// default, Security Settings, Third Party Authentication, sampai tab Sessions — belasan
// setelan yang bukan urusan pemakai dan cuma jadi jalan merusak akunnya sendiri.
//
// Yang disisakan persis tiga: tab User Details, tab More Information, dan tab Settings
// dengan SATU section — Change Password. Selebihnya disembunyikan.
//
// Gate-nya role System Manager, bukan nama dokumen: akun non-SM tidak punya `read` pada
// doctype User sama sekali, jadi satu-satunya dokumen User yang bisa ia buka memang
// dokumennya sendiri. Administrator memegang semua role, jadi ikut lolos.
//
// Batasnya: ini lapisan tampilan. Field permlevel 1 (Roles, Allow Modules, Defaults) memang
// sudah tertutup izin, dan `generate_keys` sudah `frappe.only_for("System Manager")` — tapi
// field permlevel 0 yang disembunyikan di sini (mis. `simultaneous_sessions`,
// `bypass_restrict_ip_check_if_2fa_enabled`) masih bisa ditulis lewat API oleh pemilik
// akunnya. Kalau itu perlu ditutup juga, tempatnya guard di `User.before_save`.
const SELF_VIEW_HIDDEN_TABS = ["roles_permissions_tab", "connections_tab", "sessions_tab"];

const SELF_VIEW_HIDDEN = [
	// Isi tab Settings, semuanya kecuali `change_password`.
	"desk_settings_section",
	"navigation_settings_section",
	"list_settings_section",
	"form_settings_section",
	"document_follow_notifications_section",
	"email_settings",
	"workspace_section",
	"app_section",
	"sb3",
	"third_party_authentication",
	"api_access",
];

frappe.ui.form.on("User", {
	refresh(frm) {
		if (frm.is_new() || frappe.user.has_role("System Manager")) return;

		for (const fieldname of SELF_VIEW_HIDDEN) {
			frm.set_df_property(fieldname, "hidden", 1);
		}
		set_tabs_hidden(frm, SELF_VIEW_HIDDEN_TABS, true);
	},
});
