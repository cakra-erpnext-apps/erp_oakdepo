// One vocabulary for the three Container Position Survey statuses, shared by the calendar,
// the schedule detail, the tank screen, the Kalmar queue and the Riwayat.
//
// WHY THIS FILE EXISTS: five screens show the same three statuses, and before the Tank Out
// rework each of them carried its own copy of the mapping. They drifted — the same status
// read "Sudah Disurvei" on one screen and "Disurvei" on another, in different colours — and
// an operator who cannot tell whether two screens are talking about the same thing stops
// trusting both. The mapping is data, so it lives in one place.
//
// The colour convention is the app's own, and it is about WHO IS BLOCKED, not about
// progress: amber = somebody still has to do something, blue/green = nobody does.

import { labels } from "@/utils/labels"

export const WAITING = "Waiting Lowering"
export const LOWERED = "Lowered"
export const DONE = "Survey Done"
export const CANCELLED = "Cancelled"

export function statusLabel(status) {
	return (
		{
			[WAITING]: labels.surveyPosStatusWaiting,
			[LOWERED]: labels.surveyPosStatusLowered,
			[DONE]: labels.surveyPosStatusDone,
			[CANCELLED]: labels.surveyPosStatusCancelled,
		}[status] || status || "—"
	)
}

/** Chip background + text, for a status shown beside a tank number. */
export function chipClass(status) {
	return (
		{
			[WAITING]: "bg-amber-100 text-amber-800",
			[LOWERED]: "bg-leaf-100 text-leaf-700",
			[DONE]: "bg-brand-100 text-brand-700",
			[CANCELLED]: "bg-red-100 text-red-700",
		}[status] || "bg-gray-100 text-gray-600"
	)
}

/** The round icon tile in front of a tank row. */
export function tileClass(status) {
	return (
		{
			[WAITING]: "bg-amber-50 text-amber-600",
			[LOWERED]: "bg-leaf-50 text-leaf-600",
			[DONE]: "bg-brand-50 text-brand-600",
			[CANCELLED]: "bg-red-50 text-red-500",
		}[status] || "bg-gray-100 text-gray-400"
	)
}

/**
 * The feather icon for a status. Chosen to read as the STATE, not as a decoration:
 * a tank still up gets the "bring it down" arrow, a tank on the ground gets a tick, a
 * closed survey gets the seal.
 */
export function statusIcon(status) {
	return (
		{
			[WAITING]: "arrow-down-circle",
			[LOWERED]: "check-circle",
			[DONE]: "clipboard",
			[CANCELLED]: "x-circle",
		}[status] || "package"
	)
}

const MONTHS = [
	"Januari", "Februari", "Maret", "April", "Mei", "Juni",
	"Juli", "Agustus", "September", "Oktober", "November", "Desember",
]

/** `2026-09-04` -> `4 September 2026`. Parsed by hand, never through `new Date(string)`,
 *  which reads a bare date as UTC and so shows the day before west of Greenwich. */
export function fmtDate(v) {
	if (!v) return "—"
	const [y, m, d] = String(v).slice(0, 10).split("-").map(Number)
	if (!y || !m) return String(v)
	return `${d} ${MONTHS[m - 1]} ${y}`
}

/**
 * "2 jam lalu" / "Sejak 08:35" — how OLD a reading is, in the words an operator thinks in.
 *
 * Freshness is half of what a position means: "blok kanan, 20 menit lalu" is an instruction,
 * "blok kanan, 3 bulan lalu" is a guess. Every screen that shows a location shows this beside
 * it, so the phrasing lives here once.
 */
export function since(v) {
	if (!v) return "—"
	const then = parseServerDateTime(v)
	if (!then) return String(v)
	const mins = Math.round((Date.now() - then.getTime()) / 60000)
	if (mins < 1) return "Baru saja"
	if (mins < 60) return `${mins} menit lalu`
	const hours = Math.round(mins / 60)
	if (hours < 24) return `${hours} jam lalu`
	const days = Math.round(hours / 24)
	if (days < 30) return `${days} hari lalu`
	return fmtDate(v)
}

/**
 * Frappe hands back `2026-09-04 08:35:12` — no timezone, already in the site's own zone.
 * `new Date(...)` on that string is implementation-defined (Safari refuses it outright), so
 * the parts are pulled apart by hand and fed to the local-time constructor.
 */
function parseServerDateTime(v) {
	const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?/.exec(String(v))
	if (!m) return null
	return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0))
}

/**
 * `4 Sep 2026 · 08:35 — 2 jam lalu`: when it happened AND how long ago, in one string.
 *
 * The two answer different questions and the screens need both. The clock time is what gets
 * compared against a truck's ETA or written on a bon; the age is what tells the surveyor
 * whether the lowering he is reading about happened this shift or last week. Showing only one
 * makes the reader do arithmetic on a handset, in the yard.
 */
export function stamp(v) {
	if (!v) return "—"
	return `${fmtDateTime(v)} — ${since(v)}`
}

/** `2026-09-04 08:35:12` -> `4 Sep 2026 · 08:35`. Datetimes arrive as plain strings. */
export function fmtDateTime(v) {
	if (!v) return "—"
	const s = String(v)
	const [y, m, d] = s.slice(0, 10).split("-").map(Number)
	if (!y || !m) return s
	const time = s.slice(11, 16)
	return `${d} ${MONTHS[m - 1]?.slice(0, 3)} ${y}${time ? ` · ${time}` : ""}`
}
