// Kerangka layar daftar + detail — patokan: Jadwal Survey (SurveyOrderList / SurveyOrderDetail).
// Komponennya di components/list/; di sini logika kecil yang dipakai bersama.

import { reactive, watch } from "vue"
import { labels } from "@/utils/labels"
import { session } from "@/data/session"

export function fill(tpl, vars) {
	return Object.entries(vars).reduce((s, [k, v]) => s.replace(`{${k}}`, v), tpl)
}

/**
 * Filter satu layar, disimpan di perangkat ini per user (handset berpindah tangan antar shift —
 * lihat utils/userPicks.js). Pencarian sengaja tidak ikut: itu pertanyaan sekali jalan.
 */
export function useSavedFilters(name, defaults) {
	const key = `oak-${name}-filters:${session.user || ""}`
	let saved = {}
	try {
		const v = JSON.parse(localStorage.getItem(key) || "null")
		if (v && typeof v === "object") saved = v
	} catch {
		/* rusak / mode privat: mulai dari bawaan */
	}
	const state = reactive({ ...defaults })
	for (const k of Object.keys(defaults)) if (k in saved) state[k] = saved[k]
	watch(
		() => ({ ...state }),
		(v) => {
			try {
				localStorage.setItem(key, JSON.stringify(v))
			} catch {
				/* mode privat: filter tetap berlaku sampai halaman ditutup */
			}
		}
	)
	return state
}

export function daysFrom(iso) {
	const t = new Date()
	t.setHours(0, 0, 0, 0)
	return Math.round((new Date(`${iso}T00:00:00`) - t) / 86400000)
}

// "Hari ini · Rab, 23 Sep", "Kam, 2 Okt · 9 hari lagi", "Sen, 21 Sep · lewat 2 hari".
export function dayLabel(iso) {
	if (!iso) return "—"
	const name = new Date(`${iso}T00:00:00`).toLocaleDateString("id-ID", { weekday: "short", day: "numeric", month: "short" })
	const d = daysFrom(iso)
	if (d === 0) return `${labels.homeToday} · ${name}`
	if (d === 1) return `${labels.svTomorrow} · ${name}`
	return `${name} · ${d > 0 ? fill(labels.svDaysAhead, { n: d }) : fill(labels.svDaysAgo, { n: -d })}`
}

/**
 * Satu grup per tanggal, mengikuti urutan dari server (baris bertanggal sama harus berurutan).
 * `running(o)` = jadi kartu besar; `hot(o)` = judul grup merah.
 */
export function groupByDay(items, dateOf, { running = () => false, hot = () => false } = {}) {
	const out = []
	for (const o of items) {
		const key = dateOf(o) || ""
		let g = out[out.length - 1]
		if (!g || g.date !== key) {
			g = { date: key, label: dayLabel(key), hot: false, rows: [], running: [], rest: [] }
			out.push(g)
		}
		g.rows.push(o)
		;(running(o) ? g.running : g.rest).push(o)
		if (hot(o)) g.hot = true
	}
	return out
}
