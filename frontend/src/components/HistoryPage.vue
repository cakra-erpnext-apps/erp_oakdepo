<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<!-- Header -->
		<div class="flex items-center justify-between gap-2">
			<div class="flex min-w-0 items-center gap-2">
				<span class="oak-icon-tile h-9 w-9 bg-gray-100 text-gray-500"><Icon :name="icon" :size="20" /></span>
				<h1 class="truncate text-lg font-extrabold tracking-tight">{{ title }}</h1>
			</div>
			<button v-if="view === 'detail'" class="oak-btn oak-btn-secondary shrink-0 px-3 py-2" @click="closeDetail">
				<Icon name="arrow-left" :size="16" /> {{ labels.cleaningBack }}
			</button>
			<router-link v-else-if="backTo" :to="backTo" class="oak-btn oak-btn-secondary shrink-0 px-3 py-2">
				<Icon name="arrow-left" :size="16" /> {{ backLabel || labels.cleaningBack }}
			</router-link>
		</div>

		<!-- DETAIL -->
		<template v-if="view === 'detail'">
			<div v-if="detailRes.loading" class="oak-card p-8 text-center text-gray-400">
				<Icon name="loader" :size="22" class="animate-spin" />
			</div>
			<p v-else-if="detailRes.error" class="flex items-center gap-2 text-sm text-red-600">
				<Icon name="alert-circle" :size="16" /> {{ labels.error }}
				<button class="oak-link" @click="reloadDetail">{{ labels.retry }}</button>
			</p>
			<slot v-else name="detail" :data="detailData" :item="selectedItem" />
		</template>

		<!-- LIST -->
		<template v-else>
			<div class="relative">
				<Icon
					name="search"
					:size="18"
					class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
				/>
				<input
					v-model="search"
					type="search"
					:placeholder="searchPlaceholder"
					class="oak-input pl-10 uppercase"
					@input="onSearchInput"
				/>
			</div>

			<!-- Loading skeleton -->
			<ul v-if="listRes.loading && !items.length" class="oak-card divide-y divide-gray-100 overflow-hidden">
				<li v-for="n in 6" :key="n" class="flex items-center gap-3 px-4 py-3.5">
					<div class="oak-skeleton h-9 w-9 rounded-xl"></div>
					<div class="flex-1 space-y-2">
						<div class="oak-skeleton h-3.5 w-1/2"></div>
						<div class="oak-skeleton h-3 w-3/4"></div>
					</div>
				</li>
			</ul>

			<p v-else-if="listRes.error" class="flex items-center gap-2 text-sm text-red-600">
				<Icon name="alert-circle" :size="16" /> {{ labels.error }}
				<button class="oak-link" @click="listRes.reload()">{{ labels.retry }}</button>
			</p>

			<div v-else-if="!items.length" class="oak-card flex flex-col items-center gap-2 p-8 text-center">
				<span class="oak-icon-tile h-12 w-12 bg-gray-100 text-gray-300"><Icon name="inbox" :size="24" /></span>
				<p class="text-sm text-gray-400">{{ emptyText || labels.empty }}</p>
			</div>

			<ul v-else class="oak-card divide-y divide-gray-100 overflow-hidden">
				<li v-for="r in items" :key="r[rowKey]">
					<button type="button" class="oak-press flex w-full items-center gap-3 px-4 py-3 text-left" @click="openDetail(r)">
						<slot name="row" :item="r" />
						<Icon name="chevron-right" :size="18" class="shrink-0 text-gray-300" />
					</button>
				</li>
			</ul>

			<!-- Pagination -->
			<div v-if="total > 0" class="space-y-1.5">
				<div class="flex flex-wrap items-center justify-center gap-1.5">
					<button
						class="inline-flex items-center gap-1 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-semibold text-gray-700 transition hover:bg-gray-50 disabled:opacity-40"
						:disabled="page <= 1 || listRes.loading"
						@click="goTo(page - 1)"
					>
						<Icon name="chevron-left" :size="16" /> {{ labels.prev }}
					</button>
					<button
						v-for="p in pageWindow"
						:key="p"
						class="min-w-[2.5rem] rounded-lg border px-3 py-1.5 text-sm font-semibold transition"
						:class="p === page ? 'border-brand-600 bg-brand-600 text-white shadow-sm' : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50'"
						:disabled="listRes.loading"
						@click="goTo(p)"
					>
						{{ p }}
					</button>
					<button
						class="inline-flex items-center gap-1 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-semibold text-gray-700 transition hover:bg-gray-50 disabled:opacity-40"
						:disabled="page >= totalPages || listRes.loading"
						@click="goTo(page + 1)"
					>
						{{ labels.next }} <Icon name="chevron-right" :size="16" />
					</button>
				</div>
				<p class="text-center text-xs text-gray-400">
					{{ page }} / {{ totalPages }} · {{ total }} {{ countLabel }}
				</p>
			</div>
		</template>
	</div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue"
import { useRoute } from "vue-router"
import { createResource } from "frappe-ui"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"

const props = defineProps({
	title: { type: String, required: true },
	icon: { type: String, default: "clock" },
	backTo: { type: String, default: "" },
	backLabel: { type: String, default: "" },
	listUrl: { type: String, required: true },
	listParams: { type: Object, default: () => ({}) },
	searchPlaceholder: { type: String, default: "" },
	emptyText: { type: String, default: "" },
	detailUrl: { type: String, required: true },
	detailParam: { type: String, default: "name" },
	rowKey: { type: String, default: "name" },
	pageLength: { type: Number, default: 10 },
	countLabel: { type: String, default: "" },
})

const search = ref("")
const page = ref(1)
const items = ref([])
const total = ref(0)

const view = ref("list")
const selectedItem = ref(null)
const detailData = ref(null)

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

const listRes = createResource({
	url: props.listUrl,
	method: "GET",
	makeParams: () =>
		cleanParams({
			...props.listParams,
			search: search.value,
			start: (page.value - 1) * props.pageLength,
			page_length: props.pageLength,
		}),
	auto: true,
	onSuccess(data) {
		items.value = data.items || []
		total.value = data.total || 0
	},
})

const detailRes = createResource({
	url: props.detailUrl,
	method: "GET",
	onSuccess(data) {
		detailData.value = data
	},
})

function openDetail(item) {
	selectedItem.value = item
	detailData.value = null
	view.value = "detail"
	detailRes.fetch({ [props.detailParam]: item[props.rowKey] })
}
function reloadDetail() {
	if (selectedItem.value) detailRes.fetch({ [props.detailParam]: selectedItem.value[props.rowKey] })
}
function closeDetail() {
	view.value = "list"
	selectedItem.value = null
	detailData.value = null
}

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / props.pageLength)))

// Deep link: ?open=<rowKey> opens that item's detail straight away (used by the EIR
// landing's "Selesai" list so a tap jumps to the read-only detail + revision button).
const route = useRoute()
onMounted(() => {
	const open = route.query.open
	if (open) openDetail({ [props.rowKey]: String(open) })
})

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
	listRes.reload()
}

let searchTimer = null
function onSearchInput() {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(() => {
		page.value = 1
		listRes.reload()
	}, 300)
}

defineExpose({ closeDetail })
</script>
