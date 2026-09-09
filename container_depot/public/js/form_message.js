// Satu spanduk per pesan — bukan setumpuk salinan.
//
// Frappe v16 mengubah `layout.show_message()` dari "ganti" menjadi "tambah": setiap panggilan
// meng-APPEND satu blok baru ke area pesan (frappe/public/js/frappe/form/layout.js). Yang
// menghapusnya cuma `render_form()`, sekali per render. Jadi begitu sebuah form men-trigger
// `refresh` lebih dari sekali dalam satu render — hal biasa setelah Save, atau saat jawaban
// asinkron (mis. rate_card_notice) mendarat belakangan — spanduk yang sama tergambar dua kali.
// `frm.set_intro()` dan `frm.dashboard.add_comment()` keduanya bermuara ke fungsi itu, jadi
// keduanya menumpuk.
//
// Helper ini memberi setiap spanduk sebuah KUNCI: cat ulang dengan kunci yang sama menimpa
// miliknya sendiri dan tidak menyentuh spanduk lain. Aman dipanggil sesering apa pun.
frappe.provide('container_depot');

// `html` kosong/null = hapus spanduk berkunci itu (mis. kontraknya sudah dibuat).
// `permanent` false memberi tombol silang seperti `frm.set_intro()`.
container_depot.form_message = function (frm, key, html, color, permanent = true) {
	const box = frm.layout && frm.layout.message;
	if (!box) return;
	const cls = `oak-msg-${key}`;
	box.find(`.${cls}`).remove();
	if (!html) {
		// Area pesan disembunyikan lagi kalau yang barusan dibuang adalah isi terakhirnya —
		// tanpa ini ia menyisakan celah kosong di atas form.
		if (!box.children().length) box.addClass('hidden');
		return;
	}
	frm.layout.show_message(html, color, permanent);
	box.children().last().addClass(cls);
};
