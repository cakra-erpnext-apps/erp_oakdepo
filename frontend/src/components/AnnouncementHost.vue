<template>
	<transition name="an">
		<div
			v-if="current"
			class="fixed inset-0 z-[65] flex items-end justify-center bg-black/50 p-4 backdrop-blur-sm sm:items-center"
			role="dialog"
			aria-modal="true"
		>
			<div class="oak-card w-full max-w-sm space-y-4 p-5">
				<div class="space-y-1.5">
					<p class="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide text-brand-600">
						<Icon name="bell" :size="12" />{{ labels.announceTitle }}
					</p>
					<p class="text-base font-extrabold tracking-tight text-gray-900">{{ current.title }}</p>
				</div>
				<!-- Frappe sanitizes Note content on save (note.py validate), so v-html is safe here. -->
				<div class="an-body max-h-[55vh] overflow-y-auto text-sm leading-snug text-gray-700" v-html="current.content" />
				<button class="oak-btn oak-btn-primary w-full py-2.5" @click="dismiss">
					{{ queue.length > 1 ? fill(labels.announceNext, { n: queue.length - 1 }) : labels.announceOk }}
				</button>
			</div>
		</div>
	</transition>
</template>

<script setup>
// Pengumuman manual dari admin — Frappe Note (Public + Notify On Login), lihat
// container_depot/ess/announcements.py. Diambil saat app dibuka dan tiap kali kembali ke
// depan, ditampilkan satu per satu; "Mengerti" menandainya terbaca (Desk ikut).
import { computed, onMounted, onUnmounted, ref } from "vue"
import { labels } from "@/utils/labels"
import { fill } from "@/utils/listKit"
import { useDismissOnBack } from "@/utils/backstack"
import Icon from "@/components/Icon.vue"

const API = "/api/method/container_depot.ess.announcements"
const queue = ref([])
const current = computed(() => queue.value[0] || null)
// "Notify On Every Login" is never marked seen server-side: once per app launch is enough.
const shownThisLaunch = new Set()

async function load() {
	try {
		const res = await fetch(`${API}.unseen`, { headers: { Accept: "application/json" } })
		if (!res.ok) return
		const fresh = ((await res.json()).message || []).filter(
			(n) => !shownThisLaunch.has(n.name) && !queue.value.some((q) => q.name === n.name)
		)
		queue.value.push(...fresh)
	} catch {
		/* offline: try again next time the app comes to the front */
	}
}

function dismiss() {
	const n = queue.value.shift()
	if (!n) return
	shownThisLaunch.add(n.name)
	fetch(`${API}.mark_seen`, {
		method: "POST",
		headers: { "Content-Type": "application/json", "X-Frappe-CSRF-Token": window.csrf_token || "" },
		body: JSON.stringify({ note: n.name }),
	}).catch(() => {})
}

useDismissOnBack(() => !!current.value, dismiss)

const onVisible = () => document.visibilityState === "visible" && load()
onMounted(() => {
	load()
	document.addEventListener("visibilitychange", onVisible)
})
onUnmounted(() => document.removeEventListener("visibilitychange", onVisible))
</script>

<style scoped>
.an-body :deep(p) {
	margin: 0 0 0.5rem;
}
.an-body :deep(ul),
.an-body :deep(ol) {
	margin: 0 0 0.5rem 1.1rem;
	list-style: revert;
}
.an-body :deep(a) {
	text-decoration: underline;
}
.an-body :deep(img) {
	max-width: 100%;
	border-radius: 0.5rem;
}
.an-enter-active,
.an-leave-active {
	transition: opacity 0.18s ease;
}
.an-enter-from,
.an-leave-to {
	opacity: 0;
}
</style>
