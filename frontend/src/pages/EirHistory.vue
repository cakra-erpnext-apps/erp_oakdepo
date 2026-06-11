<template>
	<div class="mx-auto w-full max-w-lg space-y-4">
		<div class="flex items-center justify-between gap-2">
			<h1 class="text-lg font-semibold">{{ labels.eirHistoryTitle }}</h1>
			<router-link to="/eir" class="shrink-0 text-sm text-blue-600 underline">
				{{ labels.eirTitle }}
			</router-link>
		</div>

		<input
			v-model="search"
			type="search"
			:placeholder="labels.eirHistorySearch"
			class="w-full rounded-md border px-3 py-2 text-sm uppercase"
			@input="onSearchInput"
		/>

		<p v-if="history.loading && !items.length" class="text-sm text-gray-500">{{ labels.loading }}</p>
		<p v-else-if="history.error" class="text-sm text-red-600">
			{{ labels.error }}
			<button class="underline" @click="history.reload()">{{ labels.retry }}</button>
		</p>
		<p
			v-else-if="!items.length"
			class="rounded-lg border bg-white p-6 text-center text-sm text-gray-400"
		>
			{{ labels.empty }}
		</p>
		<ul v-else class="divide-y rounded-lg border bg-white">
			<li v-for="r in items" :key="r.name" class="px-3 py-3">
				<div class="flex items-center justify-between gap-2">
					<p class="truncate font-medium">{{ r.container_no || r.container }}</p>
					<span
						class="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium"
						:class="statusClass(r)"
					>
						{{ statusText(r) }}
					</span>
				</div>
				<div class="mt-0.5 flex items-center justify-between text-xs text-gray-500">
					<span>{{ r.inspection_type }}<span v-if="r.tank_status"> · {{ r.tank_status }}</span></span>
					<span>{{ fmtDate(r.eir_date || r.creation) }}</span>
				</div>
				<p class="text-[11px] text-gray-400">{{ r.inspection_id || r.name }}</p>
			</li>
		</ul>

		<div v-if="total > 0" class="space-y-1">
			<div class="flex flex-wrap items-center justify-center gap-1">
				<button
					class="rounded-md border bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-40"
					:disabled="page <= 1 || history.loading"
					@click="goTo(page - 1)"
				>
					‹ {{ labels.prev }}
				</button>
				<button
					v-for="p in pageWindow"
					:key="p"
					class="min-w-[2.25rem] rounded-md border px-3 py-1.5 text-sm font-medium"
					:class="p === page ? 'border-blue-600 bg-blue-600 text-white' : 'bg-white text-gray-700 hover:bg-gray-50'"
					:disabled="history.loading"
					@click="goTo(p)"
				>
					{{ p }}
				</button>
				<button
					class="rounded-md border bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-40"
					:disabled="page >= totalPages || history.loading"
					@click="goTo(page + 1)"
				>
					{{ labels.next }} ›
				</button>
			</div>
			<p class="text-center text-xs text-gray-400">{{ page }} / {{ totalPages }} · {{ total }} EIR</p>
		</div>
	</div>
</template>

<script setup>
import { computed, ref } from "vue"
import { createResource } from "frappe-ui"
import { labels } from "@/utils/labels"

const PAGE = 10
const search = ref("")
const page = ref(1)
const items = ref([])
const total = ref(0)

// frappe-ui serializes GET params via URLSearchParams, turning `undefined` into the
// string "undefined" — only include keys that actually have a value.
function cleanParams(obj) {
	const out = {}
	for (const k in obj) {
		const v = obj[k]
		if (v !== undefined && v !== null && v !== "") out[k] = v
	}
	return out
}

const history = createResource({
	url: "container_depot.ess.inspections.eir_history",
	method: "GET",
	makeParams: () => cleanParams({ search: search.value, start: (page.value - 1) * PAGE, page_length: PAGE }),
	auto: true,
	onSuccess(data) {
		items.value = data.items || []
		total.value = data.total || 0
	},
})

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE)))

// A window of up to 5 page numbers centred on the current page.
const pageWindow = computed(() => {
	const tp = totalPages.value
	const max = 5
	let startP = Math.max(1, page.value - Math.floor(max / 2))
	const endP = Math.min(tp, startP + max - 1)
	startP = Math.max(1, endP - max + 1)
	const out = []
	for (let p = startP; p <= endP; p++) out.push(p)
	return out
})

function goTo(p) {
	page.value = Math.min(Math.max(1, p), totalPages.value)
	history.reload()
}

let searchTimer = null
function onSearchInput() {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(() => {
		page.value = 1
		history.reload()
	}, 300)
}

function statusText(r) {
	if (r.docstatus === 1) return labels.eirStatusSubmitted
	if (r.docstatus === 2) return labels.eirStatusCancelled
	return labels.eirStatusDraft
}
function statusClass(r) {
	if (r.docstatus === 1) return "bg-green-100 text-green-800"
	if (r.docstatus === 2) return "bg-gray-200 text-gray-600"
	return "bg-amber-100 text-amber-800"
}
function fmtDate(v) {
	return v ? String(v).slice(0, 10) : "—"
}
</script>
