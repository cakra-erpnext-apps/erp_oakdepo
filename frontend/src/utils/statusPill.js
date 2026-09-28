// Kosakata status chip PWA — cermin container_depot/public/js/status_pill.js (Desk).
//
// Tahap yang artinya sama wajib bernama dan berwarna sama di Desk dan di HP. Ubah keduanya
// bersamaan: kata atau warna yang berubah di satu sisi saja membuat satu order terbaca beda
// antara layar kantor dan layar lapangan. Tahap khas satu doctype (Disetujui, Bocor, Siap
// Keluar, …) boleh ditulis di pemanggilnya, asal mengikuti aturan warna yang sama:
//
//   gray   = draf / belum diteruskan          red    = dibatalkan / void / ditolak
//   blue   = tahap akhir (selesai / lunas)    green  = disetujui / siap / aktif
//   orange = menunggu orang lain bergerak     yellow = sedang berjalan
//   purple = menunggu review / diperiksa      pink   = diminta ulang / ditahan
import { labels } from "@/utils/labels"

// Nama warna Desk -> kelas chip. `yellow` memakai `amber` dan `green` memakai `leaf`: hanya
// keluarga yang punya variabel tema (main.css) yang ikut berganti di mode gelap.
const TONE = {
	gray: "bg-gray-100 text-gray-700",
	orange: "bg-orange-100 text-orange-800",
	yellow: "bg-amber-100 text-amber-800",
	purple: "bg-purple-100 text-purple-800",
	pink: "bg-pink-100 text-pink-800",
	blue: "bg-blue-100 text-blue-800",
	red: "bg-red-100 text-red-800",
	green: "bg-leaf-100 text-leaf-800",
}

export const STAGE = {
	draft: { label: labels.stageDraft, colour: "gray" },
	ready: { label: labels.stageReady, colour: "orange" },
	doing: { label: labels.stageDoing, colour: "yellow" },
	review: { label: labels.stageReview, colour: "purple" },
	revision: { label: labels.stageRevision, colour: "pink" },
	done: { label: labels.stageDone, colour: "blue" },
	cancelled: { label: labels.stageCancelled, colour: "red" },
}

/** Kelas chip untuk satu warna Desk; warna tak dikenal jatuh ke abu-abu. */
export const tone = (colour) => TONE[colour] || TONE.gray

/** Chip satu tahap standar: `{ label, cls }`. */
export function pill(key) {
	const s = STAGE[key]
	return { label: s.label, cls: tone(s.colour) }
}

// Container Booking — sama dengan STATUS_LABELS / STATUS_COLOURS di container_booking_list.js.
const BOOKING = {
	Draft: [labels.stageDraft, "gray"],
	Pengajuan: [labels.bkStatusSubmitted, "purple"],
	"Pending Payment": [labels.bkStatusPendingPayment, "orange"],
	"Pending Confirmation": [labels.bkStatusPendingConfirmation, "yellow"],
	Confirmed: [labels.bkStatusConfirmed, "green"],
	Completed: [labels.stageDone, "blue"],
	Cancelled: [labels.stageCancelled, "red"],
	Blocked: [labels.bkStatusBlocked, "pink"],
}

export function bookingPill(status) {
	const [label, colour] = BOOKING[status] || [status || "—", "gray"]
	return { label, cls: tone(colour) }
}
