// Bahasa visual satu M&R: statusnya sebagai chip, dan jam kerjanya sebagai satu baris.
//
// Empat layar membacanya — worklist, kartu order, form kerja, dan Riwayat — dan yang membuat
// chip status berguna justru karena bunyinya dan warnanya sama persis di keempatnya. Salinan
// terpisah di tiap halaman (yang memang sempat ada: tiga peta warna berbeda untuk status yang
// sama) pada akhirnya berselisih, dan operator jadi menghafal warna per layar.
import { labels, repairStatusLabels } from "@/utils/labels"
import { LOCALE } from "@/utils/lang"
import { tone } from "@/utils/statusPill"

// Warna per status, sama dengan repair_order_list.js di Desk (aturan warnanya di statusPill.js).
const COLOUR = {
	Draft: "gray",
	"Pending Approval": "orange",
	Approved: "green",
	Rejected: "red",
	"Revision Requested": "pink",
	Pending: "orange",
	"In Progress": "yellow",
	"Pending Review": "purple",
	Completed: "blue",
	Cancelled: "red",
}

/** Chip status satu order: `{ label, tone }`. */
export function mrChip(status) {
	return {
		label: repairStatusLabels[status] || status || "—",
		tone: tone(COLOUR[status]),
	}
}

/** Jam saja dari sebuah Datetime Frappe ("2026-09-08 15:33:12" -> "15:33"). */
export function clockOf(dt) {
	return dt ? String(dt).slice(11, 16) : ""
}

/** Tanggal + jam pendek: "8 Sep 15:29". Dipakai timeline dan chip persetujuan. */
export function fmtStamp(dt) {
	if (!dt) return ""
	const d = parseDt(dt)
	if (!d || Number.isNaN(d.getTime())) return String(dt).slice(0, 16).replace("T", " ")
	return (
		d.toLocaleDateString(LOCALE, { day: "numeric", month: "short" }) + " " + clockOf(dt)
	)
}

// Selalu bentuk "T", tidak pernah `new Date("YYYY-MM-DD HH:MM")` — Safari menolaknya mentah,
// dan durasinya akan jadi NaN di persis separuh HP di lapangan.
function parseDt(v) {
	return v ? new Date(String(v).slice(0, 19).replace(" ", "T")) : null
}

// Selisih menit dua Datetime, atau null kalau salah satunya tidak ada / tidak masuk akal.
// Tidak diekspor: satu-satunya pembacanya adalah `workWindow` di bawah.
function durationMin(start, end) {
	if (!start || !end) return null
	const mins = Math.round((parseDt(end) - parseDt(start)) / 60000)
	return Number.isFinite(mins) && mins >= 0 ? mins : null
}

/**
 * Rentang kerja satu baris: `15:33 – 16:20 · 47 mnt`, atau hanya jam mulai selama pekerjaan
 * masih berjalan. String kosong kalau belum pernah dimulai — pemanggilnya `v-if` di atasnya.
 */
export function workWindow(start, end) {
	if (!start) return ""
	if (!end) return clockOf(start)
	const line = labels.mrWorkWindow.replace("{start}", clockOf(start)).replace("{end}", clockOf(end))
	const mins = durationMin(start, end)
	return mins == null ? line : `${line} · ${labels.mrDurationMin.replace("{n}", mins)}`
}
