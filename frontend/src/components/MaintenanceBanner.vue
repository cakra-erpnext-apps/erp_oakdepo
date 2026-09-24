<template>
	<!-- Countdown before maintenance (container_depot.maintenance). Two ways in: the service
	     worker forwards the push, and the app asks the server itself — on load, on return
	     to the foreground and every few seconds, since a phone without push hears nothing. -->
	<p
		v-if="left !== null"
		role="alert"
		style="padding-top: max(0.5rem, env(safe-area-inset-top))"
		class="fixed inset-x-0 top-0 z-50 bg-red-600 px-4 pb-2 text-center text-[13px] font-bold leading-snug text-white"
	>
		{{ left > 0 ? labels.maintenanceSoon(left) : labels.maintenanceNow }}
	</p>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from "vue"
import { labels } from "@/utils/labels"

// ponytail: 10 s poll — a 30 s warning still shows with >= 20 s left; one cache read each.
const POLL_MS = 10_000
const left = ref(null)
let countdown = null
let poll = null
let end = 0

function start(seconds) {
	const next = Date.now() + (Number(seconds) || 30) * 1000
	// The poll and the push report the same countdown; keep the one already running.
	if (countdown && Math.abs(next - end) < 3000) return
	end = next
	clearInterval(countdown)
	const tick = () => {
		left.value = Math.max(0, Math.ceil((end - Date.now()) / 1000))
		if (!left.value) clearInterval(countdown)
	}
	tick()
	countdown = setInterval(tick, 1000)
}

async function check() {
	try {
		const res = await fetch("/api/method/container_depot.maintenance.status", { credentials: "same-origin" })
		const seconds = (await res.json()).message?.seconds
		if (seconds) start(seconds)
	} catch (e) {
		// Offline or the server is already down — nothing to announce from here.
	}
}

function onMessage(event) {
	if (event.data?.type === "oak-maintenance") start(event.data.seconds)
}

function onVisibility() {
	clearInterval(poll)
	poll = null
	if (document.hidden) return
	check()
	poll = setInterval(check, POLL_MS)
}

onMounted(() => {
	navigator.serviceWorker?.addEventListener("message", onMessage)
	document.addEventListener("visibilitychange", onVisibility)
	onVisibility()
})
onBeforeUnmount(() => {
	navigator.serviceWorker?.removeEventListener("message", onMessage)
	document.removeEventListener("visibilitychange", onVisibility)
	clearInterval(countdown)
	clearInterval(poll)
})
</script>
