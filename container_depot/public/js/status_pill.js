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
	cancelled: ['Dibatalkan', 'red'],
};

// `[label, warna, filter]` siap dikembalikan dari `get_indicator`.
container_depot.status_pill = function (key, filter) {
	const [label, colour] = container_depot.STATUS[key];
	return [__(label), colour, filter];
};
