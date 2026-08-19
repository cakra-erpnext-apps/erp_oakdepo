<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<!-- Header -->
		<div class="flex flex-wrap items-center justify-between gap-2">
			<div class="flex items-center gap-2">
				<span class="oak-icon-tile h-9 w-9 bg-amber-50 text-amber-600"><Icon name="log-out" :size="20" /></span>
				<div>
					<h1 class="text-lg font-extrabold tracking-tight">{{ labels.readyOutTitle }}</h1>
					<p class="text-xs text-gray-500">{{ labels.storageBranch }}: {{ branch }}</p>
				</div>
			</div>
			<router-link to="/gate/history" class="oak-btn oak-btn-secondary shrink-0 px-3 py-2">
				<Icon name="clock" :size="16" /> {{ labels.navHistory }}
			</router-link>
		</div>

		<!-- What this queue is, and the one rule for pressing ACC -->
		<p class="rounded-xl bg-amber-50 p-3 text-xs leading-relaxed text-amber-800">{{ labels.readyOutHint }}</p>

		<!-- Search -->
		<div class="relative">
			<Icon name="search" :size="18" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
			<input
				v-model="search"
				type="search"
				:placeholder="labels.readyOutSearch"
				class="oak-input pl-10 uppercase"
				@input="onSearchInput"
			/>
		</div>

		<!-- Loading skeleton (first load only) -->
		<div v-if="readyRes.loading && !items.length" class="space-y-2">
			<div v-for="n in 3" :key="n" class="oak-skeleton h-24 rounded-2xl"></div>
		</div>

		<!-- Empty -->
		<div v-else-if="!items.length" class="oak-card p-8 text-center">
			<span class="oak-icon-tile mx-auto h-12 w-12 bg-leaf-50 text-leaf-600"><Icon name="check-circle" :size="24" /></span>
			<p class="mt-3 text-sm text-gray-500">{{ labels.readyOutEmpty }}</p>
		</div>

		<!-- Queue — longest wait first -->
		<ul v-else class="space-y-2">
			<li v-for="c in items" :key="c.container" class="oak-card overflow-hidden">
				<div class="flex items-start gap-3 p-4">
					<span class="oak-icon-tile h-10 w-10 shrink-0 bg-leaf-50 text-leaf-600"><Icon name="check-circle" :size="20" /></span>
					<div class="min-w-0 flex-1">
						<div class="flex items-start justify-between gap-2">
							<p class="truncate font-extrabold text-gray-900">{{ c.container_no || c.container }}</p>
							<span class="oak-chip shrink-0" :class="waitClass(c)">{{ waitText(c) }}</span>
						</div>
						<p class="mt-0.5 truncate font-mono text-[11px] text-gray-400">
							{{ c.order_muat || labels.readyOutNoBon }}
							<span v-if="c.principal" class="font-sans"> · {{ c.principal }}</span>
						</p>
						<dl class="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
							<div v-for="f in fields(c)" :key="f.label" class="min-w-0">
								<dt class="text-[11px] text-gray-400">{{ f.label }}</dt>
								<dd class="truncate font-medium text-gray-700">{{ f.value || "—" }}</dd>
							</div>
						</dl>
					</div>
				</div>
				<button
					class="oak-btn oak-btn-primary w-full rounded-none py-3"
					:disabled="accing"
					@click="confirmAcc(c)"
				>
					<Icon name="log-out" :size="16" /> {{ labels.readyOutAcc }}
				</button>
			</li>
		</ul>

		<!-- Paging -->
		<div v-if="items.length" class="space-y-2">
			<button
				v-if="items.length < total"
				class="oak-btn oak-btn-secondary w-full"
				:disabled="readyRes.loading"
				@click="loadMore"
			>
				{{ readyRes.loading ? "…" : `${labels.storageLoadMore} (${items.length}/${total})` }}
			</button>
			<p class="text-center text-xs text-gray-400">{{ total }} {{ labels.readyOutCount }}</p>
		</div>
	</div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue"
import { labels } from "@/utils/labels"
import { send } from "@/data/send"
import { userContext, branchLabel } from "@/data/context"
import { toast } from "@/utils/toast"
import { confirm } from "@/utils/confirm"
import Icon from "@/components/Icon.vue"
import { cachedResource } from "@/data/cache"

const PAGE = 20
const search = ref("")
const loaded = ref([]) // what the server (or the offline cache) last said
const total = ref(0)
const start = ref(0)

// A tank whose ACC is queued has left, or is leaving. It stays in the server's answer until
// the queue drains, so filter it out here — a released tank sitting in the "waiting" list is
// how the same truck gets released twice.
const items = computed(() => loaded.value)

const branch = computed(() => branchLabel())

// The queue is derived server-side from the EIRs themselves (no stored list), so a plain
// re-fetch after an ACC is enough to make the released tank disappear.
const readyRes = cachedResource({
	url: "container_depot.ess.gate.gate_ready",
	method: "GET",
	makeParams: () => ({ search: search.value || "", start: start.value, page_length: PAGE }),
	onSuccess(data) {
		loaded.value = start.value === 0 ? data.items || [] : loaded.value.concat(data.items || [])
		total.value = data.total || 0
		start.value += (data.items || []).length
	},
})

function reload(reset) {
	if (reset) {
		start.value = 0
		loaded.value = []
	}
	readyRes.reload()
}
function loadMore() {
	if (readyRes.loading || loaded.value.length >= total.value) return
	readyRes.reload()
}

let searchTimer = null
function onSearchInput() {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(() => reload(true), 300)
}

function fields(c) {
	return [
		{ label: labels.gateTruck, value: c.truck_no },
		{ label: labels.gateDriver, value: c.driver },
		{ label: labels.readyOutDest, value: c.destination },
		{ label: labels.readyOutSince, value: (c.ready_since || "").slice(0, 16) },
	]
}

// How long the tank has been standing ready — the reason this screen exists. A tank waiting
// days is tinted red so it stands out without the operator reading timestamps.
function waitHours(c) {
	if (!c.ready_since) return 0
	const t = Date.parse(String(c.ready_since).replace(" ", "T"))
	return Number.isNaN(t) ? 0 : (Date.now() - t) / 3600000
}
function waitText(c) {
	const h = waitHours(c)
	if (h < 1) return `${Math.max(0, Math.round(h * 60))} ${labels.readyOutWaitingMin}`
	if (h < 24) return `${Math.floor(h)} ${labels.readyOutWaitingHour}`
	return `${Math.floor(h / 24)} ${labels.readyOutWaitingDay}`
}
function waitClass(c) {
	const h = waitHours(c)
	if (h >= 24) return "bg-red-100 text-red-700"
	if (h >= 4) return "bg-amber-100 text-amber-800"
	return "bg-leaf-100 text-leaf-800"
}

// ACC — the same endpoint (and therefore the same server-side guards) as the Desk report's
// button, but queued rather than posted.
//
// This is the deliberate call on this screen. The gate is where the signal is worst and where
// waiting is most expensive: a truck held at the barrier because the handset cannot reach the
// server blocks every truck behind it. So with a link this waits for the server — one fast
// round trip, and the server's guards (open work still holding the tank, branch scope) answer
// at the barrier where they can still be acted on.
//
// Without a link the tank is released now and the record catches up. The honest cost is only
// paid on that path: a release the server would have refused surfaces afterwards as a failed
// row in the queue panel, a discrepancy someone has to reconcile — visible, and rarer than
// the jam.
const accing = ref(false)
async function confirmAcc(c) {
	if (accing.value) return
	const ok = await confirm({
		message: `${c.container_no || c.container} — ${labels.readyOutAccMessage}`,
		confirmLabel: labels.readyOutAcc,
		cancelLabel: labels.confirmCancel,
	})
	if (!ok) return
	accing.value = true
	try {
		await send({
			url: "container_depot.ess.gate.gate_out",
			payload: { container: c.container },
		})
		toast.success(labels.gateOutDone, {
			title: c.container_no || c.container,
		})
	} catch (e) {
		toast.error(e?.message || labels.error)
	} finally {
		accing.value = false
	}
}

onMounted(() => {
	if (!userContext.data) userContext.reload()
	reload(true)
})
</script>
