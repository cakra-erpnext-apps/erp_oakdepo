// "Minta Cek Letak" — satu tombol di form order yang sedang memegang sebuah tank.
//
// Yang paling butuh tahu di mana tank berdiri adalah orang yang harus mengambilnya, dan
// pertanyaan itu muncul saat order cuci / M&R-nya dibuka — bukan saat booking keluarnya
// ditulis berhari-hari sebelumnya. Sebelum ini satu-satunya yang bisa memasukkan tank ke
// antrean "cek letak" adalah jadwal survey booking Tank Out, jadi tank yang belum punya
// booking tidak punya jalan sama sekali.
//
// TIDAK ADA DOKUMEN ORDER DI BELAKANGNYA, sama seperti antrean terjadwalnya (lihat
// container_position.request_position_check): yang diminta cuma satu jawaban — sebuah
// catatan Container Position — dan catatan yang lebih baru dari permintaannya adalah
// penutupnya. Tidak ada yang perlu dibatalkan kalau tank keluar duluan.
frappe.provide('container_depot');

container_depot.tank_position = {
	// Panggil dari `refresh` form mana pun yang punya field `container`.
	button(frm) {
		if (frm.is_new() || !frm.doc.container) return;
		// can_create, bukan perm.has_perm: has_perm atas doctype yang meta-nya belum dimuat
		// klien menjawab `false` diam-diam untuk semua hak selain read (lihat container.js).
		// CREATE atas Container Position adalah hak yang sama dengan mencatat letak — yang
		// boleh menjawab pertanyaan ini boleh mengajukannya.
		if (!frappe.model.can_create('Container Position')) return;
		frm.add_custom_button(
			__('Minta Cek Letak'),
			() => container_depot.tank_position.request(frm),
			__('Tank')
		);
	},

	request(frm) {
		frappe.call({
			method: 'container_depot.ess.container_position.position_request',
			args: { container: frm.doc.container },
			freeze: true,
			freeze_message: __('Meminta cek letak…'),
		}).then((r) => {
			const res = r.message;
			if (!res) return;
			// Letak terakhir ikut di pesannya: sering kali jawabannya sudah ada dan cukup
			// segar, dan yang menekan tombol ini lebih butuh membacanya daripada menunggu
			// orang berjalan ke sana lagi.
			const last = res.location_note
				? __('Letak terakhir: {0}', [res.location_note]) +
					(res.hours === null || res.hours === undefined
						? ''
						: ' · ' + __('{0} jam lalu', [Math.round(res.hours)]))
				: __('Belum pernah dicatat.');
			frappe.show_alert(
				{
					message: __('Cek letak diminta untuk {0}. {1}', [res.container_no || frm.doc.container, last]),
					indicator: 'green',
				},
				10
			);
		});
	},
};
