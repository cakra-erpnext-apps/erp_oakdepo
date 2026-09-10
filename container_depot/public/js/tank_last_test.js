// Tgl. Tes Terakhir tank, dibaca dan dibetulkan dari form order mana pun di Desk.
//
// Nilainya milik TANK (`Container.last_test_date`), bukan milik order — tidak ada salinan
// yang disimpan di Cleaning Order / Repair Order, karena salinan berarti satu tank punya dua
// jawaban dan yang tercetak di EIR berikutnya adalah lemparan koin. Jadi: dibaca hidup dari
// master tiap kali form dibuka, dan tombolnya menulis kembali ke master, bukan ke order.
//
// Yang mengisi otomatis adalah uji berkala yang selesai DI SINI (M&R ber-job_type Periodic
// Test — lihat RepairOrder._stamp_last_test_date). Tombol ini separuh yang lain: uji di
// vendor atau di depo lain, yang tidak akan pernah punya dokumennya di sistem ini, tapi tetap
// menentukan kapan tank ini jatuh tempo lagi.
frappe.provide('container_depot');

container_depot.tank_last_test = {
	// Panggil dari `refresh`: baca ulang nilai master, lalu gambar ulang panel fakta sidebar.
	// Async — Desk tidak menahan form untuk satu tanggal — jadi nilainya diparkir di `frm`
	// dan `_render_system_facts` dipicu ulang begitu ia sampai.
	load(frm) {
		frm.__last_test = undefined;
		if (frm.is_new() || !frm.doc.container) return;
		frappe.db.get_value('Container', frm.doc.container, 'last_test_date').then((r) => {
			frm.__last_test = (r.message || {}).last_test_date || null;
			frm.trigger('_render_system_facts');
		});
	},

	// Baris untuk container_depot.render_system_facts. Kosong = baris tidak muncul sama
	// sekali (aturan panel itu), dan tombolnya yang menjadi satu-satunya penunjuk — itu
	// benar: tank yang belum pernah tercatat diuji tidak punya fakta untuk ditampilkan.
	fact(frm) {
		return frm.__last_test ? frappe.datetime.str_to_user(frm.__last_test) : null;
	},

	// Tombol di grup "Tank". Sengaja bukan field di order: field berarti tersimpan di order,
	// dan order yang menyimpan tanggal uji akan menampilkan tanggal basi selamanya.
	button(frm) {
		if (frm.is_new() || !frm.doc.container) return;
		frm.add_custom_button(
			__('Tgl. Tes Terakhir'),
			() => container_depot.tank_last_test.edit(frm),
			__('Tank')
		);
	},

	edit(frm) {
		frappe.prompt(
			[
				{
					fieldname: 'last_test_date',
					fieldtype: 'Date',
					label: __('Tgl. Tes Terakhir'),
					default: frm.__last_test || null,
					reqd: 1,
					description: __(
						'Tanggal uji berkala terakhir tank ini — dari depo kita maupun vendor/depo lain. Tersimpan di master tank, bukan di order ini.'
					),
				},
			],
			(values) => {
				frappe.call({
					method: 'container_depot.container_depot.doctype.container.container.set_last_test_date',
					args: { container: frm.doc.container, last_test_date: values.last_test_date },
					freeze: true,
					freeze_message: __('Menyimpan…'),
				}).then((r) => {
					if (!r.message) return;
					frm.__last_test = r.message.last_test_date;
					frm.trigger('_render_system_facts');
					frappe.show_alert({
						message: __('Tgl. Tes Terakhir {0} tersimpan di {1}', [
							frappe.datetime.str_to_user(r.message.last_test_date),
							frm.doc.container,
						]),
						indicator: 'green',
					});
				});
			},
			__('Tgl. Tes Terakhir'),
			__('Simpan')
		);
	},
};
