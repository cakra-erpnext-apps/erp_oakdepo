// Kosakata status standar untuk pill list/form Container Depot.
//
// Tahap yang artinya sama wajib bernama dan berwarna sama di semua menu. Sebelum ini
// "menunggu dikerjakan" tertulis Menunggu Operator / Siap Dikerjakan / Terjadwal / Open, dan
// "batal" tertulis Batal / Dibatalkan / Cancelled. Pakai `container_depot.status_pill` untuk
// tahap di bawah; tahap khas satu doctype (Lunas, Siap Muat, Di Depo, …) boleh ditulis di
// list-nya sendiri, asal mengikuti aturan warna:
//
//   gray   = draf / belum diteruskan          red    = dibatalkan / void / ditolak
//   blue   = tahap akhir (selesai / lunas)    green  = disetujui / siap / aktif
//   orange = menunggu orang lain bergerak     yellow = sedang berjalan
//   purple = menunggu review / diperiksa      pink   = diminta ulang / ditahan
frappe.provide('container_depot');

container_depot.STATUS = {
	draft: ['Draf', 'gray'],
	ready: ['Siap Dikerjakan', 'orange'],
	doing: ['Dikerjakan', 'yellow'],
	review: ['Menunggu Review', 'purple'],
	revision: ['Revisi Diminta', 'pink'],
	done: ['Selesai', 'blue'],
	// Tutup Order (closing.py): selesai lewat Administrator, dikerjakan di luar aplikasi.
	closed: ['Ditutup', 'blue'],
	cancelled: ['Dibatalkan', 'red'],
};

// `[label, warna, filter]` siap dikembalikan dari `get_indicator`.
container_depot.status_pill = function (key, filter) {
	const [label, colour] = container_depot.STATUS[key];
	return [__(label), colour, filter];
};

// Status Cleaning Order & Repair Order — SATU peta untuk list, sidebar form, panel Dokumen
// Terkait di booking, dan register. Satu tahap = satu nama di semua menu: status awal kedua
// order sama-sama "Draf". Opsi Select mentahnya (filter Status, dll.) diterjemahkan ke label
// yang sama lewat translations/en-US.csv, ber-context doctype — ubah keduanya bersamaan.
// Nilai = kunci `container_depot.STATUS`, atau `[label, warna]` untuk tahap khas doctype itu.
container_depot.ORDER_STATUS = {
	'Cleaning Order': {
		// Admin Ops belum memilih metode — draf-nya order cuci.
		'Service Setup': 'draft',
		Pending: 'ready',
		In_Progress: 'doing',
		'Pending Review': 'review',
		Completed: 'done',
		Cancelled: 'cancelled',
	},
	'Repair Order': {
		Draft: 'draft',
		'Pending Approval': ['Menunggu Persetujuan', 'orange'],
		// Persetujuan owner baru MEMULAI pekerjaan — hijau, bukan biru selesai.
		Approved: ['Disetujui', 'green'],
		Rejected: ['Ditolak', 'red'],
		'Revision Requested': 'revision',
		Pending: 'ready',
		'In Progress': 'doing',
		'Pending Review': 'review',
		Completed: 'done',
		Cancelled: 'cancelled',
	},
};

// `[label, warna, filter]` untuk status order di atas; null kalau tidak dipetakan.
container_depot.order_status_pill = function (doctype, status, filter) {
	const hit = (container_depot.ORDER_STATUS[doctype] || {})[status];
	if (!hit) return null;
	const [label, colour] = typeof hit === 'string' ? container_depot.STATUS[hit] : hit;
	return [__(label), colour, filter];
};

// Pill HTML-nya, untuk panel dan report yang menggambar sendiri. Status di luar peta tampil
// apa adanya dengan `fallback_colour`.
container_depot.order_status_html = function (doctype, status, fallback_colour) {
	const [label, colour] = container_depot.order_status_pill(doctype, status) || [status || '—', fallback_colour || 'gray'];
	return `<span class="indicator-pill ${colour}">${frappe.utils.escape_html(label)}</span>`;
};
