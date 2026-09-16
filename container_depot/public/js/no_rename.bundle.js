// Tombol "Edit" (ikon pensil) di sebelah judul form — dan entri "Rename" di menu ⋯ —
// dimatikan untuk semua doctype.
//
// Frappe memasangnya lewat `Toolbar.setup_editable_title`, yang aktif kalau salah satu dari
// dua predikat ini benar:
//   - `can_rename()`       → doctype punya `allow_rename` dan user punya hak tulis;
//   - `is_title_editable()` → `title_field`-nya bertipe Data yang bisa ditulis.
// Tombol yang sama dipakai `add_rename()` untuk menaruh "Rename" di menu.
//
// Di depot, identitas dokumen datang dari naming series (BKG-OUT-…, RO-…, dst.) dan
// `title_field` cuma cerminan field lain yang sudah punya tempatnya sendiri di form. Jadi
// tombol itu tidak menawarkan apa pun selain cara mengubah nomor dokumen yang sudah
// terlanjur dirujuk EIR, invoice, dan lampiran — sesuatu yang tidak boleh bisa dilakukan
// dari form biasa.
//
// Mematikan kedua predikat menghapus sekaligus: ikon pensilnya, kelas `editable-title` pada
// judul, dan item menu "Rename". Ini murni jalur form Desk — rename lewat API/console tetap
// ada untuk Administrator kalau memang perlu.

(function () {
	const Toolbar = frappe.ui?.form?.Toolbar;
	if (!Toolbar) return;

	Toolbar.prototype.can_rename = () => false;
	Toolbar.prototype.is_title_editable = () => false;
})();
