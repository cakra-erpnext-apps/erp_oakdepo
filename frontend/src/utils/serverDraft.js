// Autosave ke server untuk formulir PWA yang tidak punya dokumen draft sendiri (Letak Tank,
// langkah lowering, foto interior survey). Isian — termasuk foto yang sudah terunggah —
// disimpan di `PWA Draft` (ess/drafts.py) tiap kali berubah, dimuat lagi saat formulir dibuka,
// dan dihapus saat formulirnya dikirim. Satu kiriman sekali jalan: kiriman lama yang tiba
// belakangan tidak boleh menimpa yang lebih baru.
import { ref } from "vue"
import { isLocalRef, post } from "@/data/send"

// Foto yang masih terparkir di HP (`local:`) belum ada di server; `send` mengunggahnya saat
// formulir dikirim. Dibuang dari salinan server supaya draft tidak menunjuk ke file yang tidak ada.
export function serverSide(v) {
	if (Array.isArray(v)) return v.filter((x) => !(isLocalRef(x) || isLocalRef(x?.photo))).map(serverSide)
	if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, serverSide(x)]))
	return v
}

async function get(url, args) {
	const res = await fetch(`/api/method/${url}?${new URLSearchParams(args)}`, {
		headers: { Accept: "application/json" },
	})
	if (!res.ok) throw new Error(String(res.status))
	return (await res.json()).message
}

/** `key()` → kunci draft (mis. `position:ABCU1234567`), atau null kalau belum ada yang dibuka. */
export function useServerDraft(key) {
	const saved = ref(true)
	let timer = null
	let busy = false
	let again = null
	let gen = 0

	async function load() {
		const k = key()
		if (!k) return null
		try {
			return await get("container_depot.ess.drafts.draft_get", { key: k })
		} catch {
			return null
		}
	}

	function save(data) {
		const k = key()
		if (!k) return
		saved.value = false
		clearTimeout(timer)
		const snapshot = JSON.parse(JSON.stringify(data))
		timer = setTimeout(() => flush(k, snapshot), 800)
	}

	async function flush(k, data) {
		if (busy) {
			again = [k, data]
			return
		}
		busy = true
		const mine = gen
		try {
			await post("container_depot.ess.drafts.draft_save", { key: k, data: serverSide(data) })
			saved.value = !again
		} catch {
			// Sinyal putus: kiriman berikutnya membawa isian yang sama lagi.
		} finally {
			busy = false
			// Formulir sudah dikirim selagi kiriman ini terbang — draft yang baru dibuatnya dibuang.
			if (mine !== gen) post("container_depot.ess.drafts.draft_clear", { key: k }).catch(() => {})
			else if (again) {
				const [a, b] = again
				again = null
				flush(a, b)
			}
		}
	}

	function clear() {
		const k = key()
		clearTimeout(timer)
		again = null
		gen += 1
		saved.value = true
		if (k) post("container_depot.ess.drafts.draft_clear", { key: k }).catch(() => {})
	}

	return { load, save, clear, saved }
}
