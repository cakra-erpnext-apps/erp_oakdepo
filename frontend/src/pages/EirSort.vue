<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<!-- Header -->
		<div class="flex flex-wrap items-center justify-between gap-2">
			<div class="flex items-center gap-2">
				<button v-if="mode !== 'list'" class="oak-btn oak-btn-secondary px-2 py-2" @click="backToList">
					<Icon name="arrow-left" :size="18" />
				</button>
				<span class="oak-icon-tile h-9 w-9 bg-brand-50 text-brand-600"><Icon name="layers" :size="20" /></span>
				<div class="min-w-0">
					<h1 class="text-lg font-extrabold tracking-tight">{{ labels.eirSortTitle }}</h1>
					<p class="truncate text-xs text-gray-500">{{ mode === 'detail' ? (current?.container_no || '') : labels.eirSortDesc }}</p>
				</div>
			</div>
			<router-link v-if="mode === 'list'" to="/eir" class="oak-btn oak-btn-secondary px-3 py-2">
				<Icon name="clipboard" :size="16" /> {{ labels.eirTitle }}
			</router-link>
		</div>

		<!-- =================== WORKLIST: EIRs needing sorting =================== -->
		<template v-if="mode === 'list'">
			<div class="relative">
				<Icon name="search" :size="18" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
				<input v-model="search" type="search" :placeholder="labels.eirHistorySearch" class="oak-input pl-10 uppercase" @input="onSearchInput" />
			</div>

			<ul v-if="listRes.loading && !items.length" class="oak-card divide-y divide-gray-100 overflow-hidden">
				<li v-for="n in 5" :key="n" class="flex items-center gap-3 px-4 py-3.5">
					<div class="oak-skeleton h-9 w-9 rounded-xl"></div>
					<div class="flex-1 space-y-2"><div class="oak-skeleton h-3.5 w-1/2"></div><div class="oak-skeleton h-3 w-3/4"></div></div>
				</li>
			</ul>

			<div v-else-if="!items.length" class="oak-card flex flex-col items-center gap-2 p-8 text-center">
				<span class="oak-icon-tile h-12 w-12 bg-leaf-50 text-leaf-500"><Icon name="check-circle" :size="24" /></span>
				<p class="text-sm text-gray-400">{{ labels.eirSortEmpty }}</p>
			</div>

			<ul v-else class="oak-card divide-y divide-gray-100 overflow-hidden">
				<li v-for="r in items" :key="r.name">
					<button class="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-gray-50" @click="openEir(r)">
						<span class="oak-icon-tile h-9 w-9 shrink-0 bg-brand-50 text-brand-500"><Icon name="image" :size="16" /></span>
						<div class="min-w-0 flex-1">
							<p class="truncate font-semibold text-gray-900">{{ r.container_no || r.container }}</p>
							<p class="mt-0.5 truncate text-xs text-gray-500">
								<span class="font-mono">{{ r.inspection_id || r.name }}</span> · {{ r.inspection_type }}
							</p>
						</div>
						<Icon name="chevron-right" :size="16" class="shrink-0 text-gray-300" />
					</button>
				</li>
			</ul>
			<p v-if="items.length" class="text-center text-xs text-gray-400">{{ total }} EIR</p>
		</template>

		<!-- =================== DETAIL: sort one EIR's photos =================== -->
		<template v-else-if="mode === 'detail'">
			<p v-if="photosRes.loading && !photos.length" class="oak-card p-6 text-center text-sm text-gray-400">…</p>

			<div v-else-if="!photos.length" class="oak-card flex flex-col items-center gap-2 p-8 text-center">
				<span class="oak-icon-tile h-12 w-12 bg-leaf-50 text-leaf-500"><Icon name="check-circle" :size="24" /></span>
				<p class="text-sm text-gray-500">{{ labels.eirSortPhotosEmpty }}</p>
				<button class="oak-link mt-1 inline-flex items-center gap-1 text-sm" @click="backToList">
					<Icon name="list" :size="14" /> {{ labels.eirBackToList }}
				</button>
			</div>

			<template v-else>
				<p class="text-xs text-gray-500">{{ photos.length }} {{ labels.eirSortUnsortedCount }}</p>
				<div class="space-y-3">
					<div v-for="p in photos" :key="p.row" class="oak-card space-y-3 p-3">
						<button type="button" class="oak-press block w-full" @click="openLightbox(photos.map((x) => x.photo), photos.indexOf(p))">
							<img :src="p.photo" class="h-48 w-full rounded-xl border border-gray-200 object-cover" />
						</button>
						<label class="oak-label">{{ labels.eirSortPick }}</label>
						<SearchSelect
							:model-value="p.chosen"
							:options="checklistItems"
							:option-value="(o) => o.item_code"
							:option-label="(o) => `${o.printed_no}. ${o.item_name}`"
							:group-by="(o) => o.area"
							:placeholder="labels.eirSortPick"
							:search-placeholder="labels.selectSearch"
							:disabled="p.pending"
							@update:model-value="(v) => { p.chosen = v; assign(p) }"
						/>
						<p v-if="p.pending" class="text-xs text-gray-400">…</p>
					</div>
				</div>
			</template>
		</template>
	</div>
</template>

<script setup>
import { computed, ref } from "vue"
import { createResource } from "frappe-ui"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
import { openLightbox } from "@/utils/lightbox"
import Icon from "@/components/Icon.vue"
import SearchSelect from "@/components/SearchSelect.vue"

const mode = ref("list") // list | detail

// ---- worklist: EIRs that still carry unsorted bulk photos ----
const items = ref([])
const total = ref(0)
const search = ref("")
const listRes = createResource({
	url: "container_depot.ess.inspections.eir_unsorted",
	method: "GET",
	makeParams: () => ({ search: search.value || "", page_length: 50 }),
	auto: true,
	onSuccess(data) {
		items.value = data.items || []
		total.value = data.total || 0
	},
})
let searchTimer = null
function onSearchInput() {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(() => listRes.reload(), 300)
}

// ---- section options (flat checklist, ordered by sequence → grouped by area), loaded once ----
const checklistItems = ref([])
createResource({
	url: "container_depot.ess.inspections.eir_masters",
	method: "GET",
	auto: true,
	onSuccess(data) {
		checklistItems.value = data.checklist || []
	},
})

// ---- detail: one EIR's unsorted photos ----
const current = ref(null)
const photos = ref([])
const photosRes = createResource({
	url: "container_depot.ess.inspections.eir_unsorted_photos",
	method: "GET",
	onSuccess(data) {
		current.value = data
		photos.value = (data.photos || []).map((p) => ({ ...p, chosen: "", pending: false }))
		mode.value = "detail"
	},
	onError(err) {
		toast.error(err?.messages?.[0] || err?.message || labels.error)
	},
})

function openEir(r) {
	photosRes.submit({ inspection: r.name })
}

const assignRes = createResource({
	url: "container_depot.ess.inspections.eir_assign_photo_section",
	method: "POST",
})

async function assign(p) {
	if (!p.chosen || p.pending) return
	p.pending = true
	try {
		await assignRes.submit({ inspection: current.value.inspection, row: p.row, item_code: p.chosen })
		// Drop the freshly-sorted photo from the list.
		photos.value = photos.value.filter((x) => x.row !== p.row)
		toast.success(labels.eirSortAssigned)
	} catch (err) {
		toast.error(err?.messages?.[0] || err?.message || labels.error)
		p.chosen = ""
	} finally {
		p.pending = false
	}
}

function backToList() {
	mode.value = "list"
	current.value = null
	photos.value = []
	listRes.reload()
}
</script>
