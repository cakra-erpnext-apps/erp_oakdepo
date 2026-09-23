<template>
	<!-- Tata letak = Jadwal Survey (SurveyOrderList): cari, pil status, filter + urut, grup
	     per tanggal. Satu Leak Check lahir per container di bon Bongkar. -->
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<div class="flex items-start justify-between gap-3">
			<div class="min-w-0">
				<h1 class="text-xl font-extrabold tracking-tight text-gray-900">{{ labels.navLeak }}</h1>
				<p class="mt-0.5 truncate text-xs text-gray-500">{{ labels.leakHint }}</p>
			</div>
			<router-link to="/leak-check/new" class="oak-btn oak-btn-secondary min-h-[44px] shrink-0 px-3">
				<Icon name="plus" :size="15" /> {{ labels.leakManual }}
			</router-link>
		</div>

		<ListSearch v-model="search" :placeholder="labels.leakSearch" @search="reload" />

		<StatPills :pills="pills" :model-value="f.status" @update:model-value="setStatus" />

		<FilterBar
			:chips="activeChips"
			:sort-label="f.sort === 'oldest' ? labels.leakSortOldest : labels.svSortNewest"
			:show-clear="!!search"
			@open="sheetOpen = true"
			@sort="toggleSort"
			@clear-one="clearOne"
			@clear-all="clearAll"
		/>

		<FilterSheet
			:open="sheetOpen"
			:value="f"
			:options="options"
			:fields="SHEET_FIELDS"
			@close="sheetOpen = false"
			@apply="applyFilter"
		/>

		<SkeletonList v-if="listRes.loading && !items.length" :action="false" />

		<div v-else-if="failed" class="oak-card flex flex-col items-center gap-2 p-8 text-center">
			<span class="oak-icon-tile h-12 w-12 bg-red-50 text-red-500"><Icon name="alert-circle" :size="24" /></span>
			<p class="text-sm font-bold text-gray-900">{{ labels.monitorErrorTitle }}</p>
			<button class="oak-btn oak-btn-primary mt-1 min-h-[44px] px-4" @click="reload">{{ labels.monitorRetry }}</button>
		</div>

		<p v-else-if="!items.length" class="oak-card p-8 text-center text-sm text-gray-400">{{ labels.leakEmpty }}</p>

		<div v-else class="space-y-4">
			<section v-for="g in days" :key="g.date" class="space-y-2">
				<div class="flex items-center justify-between gap-2 px-1">
					<p class="flex min-w-0 items-center gap-1.5 truncate text-xs font-bold" :class="g.hot ? 'text-red-600' : 'text-gray-600'">
						<span class="h-2 w-2 shrink-0 rounded-full" :class="g.hot ? 'bg-red-500' : 'bg-gray-400'"></span>
						{{ g.label }}
					</p>
					<p class="shrink-0 text-[11px] text-gray-400">{{ fill(labels.svOrderCount, { n: dayCounts[g.date] || g.rows.length }) }}</p>
				</div>
				<ul class="oak-card divide-y divide-gray-100 overflow-hidden">
					<li v-for="o in g.rows" :key="o.name">
						<router-link :to="`/leak-check/${o.name}`" class="oak-press flex min-h-[64px] items-center gap-2 px-4 py-3">
							<LeakCheckInfo :o="o" class="flex-1">
								<span class="oak-chip shrink-0" :class="leakChip(o).cls">{{ leakChip(o).label }}</span>
							</LeakCheckInfo>
						</router-link>
					</li>
				</ul>
			</section>

			<button
				v-if="items.length < total"
				class="oak-btn oak-btn-secondary min-h-[48px] w-full"
				:disabled="listRes.loading"
				@click="loadMore"
			>
				{{ listRes.loading ? "…" : `${labels.svMore} (${items.length}/${total})` }}
			</button>
		</div>
	</div>
</template>

<script setup>
import { computed, ref } from "vue"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"
import SkeletonList from "@/components/SkeletonList.vue"
import LeakCheckInfo from "@/components/LeakCheckInfo.vue"
import ListSearch from "@/components/list/ListSearch.vue"
import StatPills from "@/components/list/StatPills.vue"
import FilterBar from "@/components/list/FilterBar.vue"
import FilterSheet from "@/components/list/FilterSheet.vue"
import { cachedResource } from "@/data/cache"
import { fmtDate } from "@/utils/surveyStatus"
import { fill, groupByDay, useSavedFilters } from "@/utils/listKit"
import { leakChip } from "@/utils/leakStatus"

const PAGE = 20
const SHEET_DEFAULTS = { day: "", depot: "", principal: "" }
const SHEET_FIELDS = [
	{ key: "day", type: "date", label: labels.svChipDate },
	{ key: "depot", type: "chips", list: "depots", label: labels.svChipDepot },
	{ key: "principal", type: "select", list: "principals", label: labels.svChipPrincipal },
]
const f = useSavedFilters("leak", { ...SHEET_DEFAULTS, status: "", sort: "newest" })
const search = ref("")
const sheetOpen = ref(false)

const activeChips = computed(() =>
	[
		f.day && { key: "day", label: labels.svChipDate, value: fmtDate(f.day) },
		f.depot && { key: "depot", label: labels.svChipDepot, value: f.depot },
		f.principal && { key: "principal", label: labels.svChipPrincipal, value: f.principal },
	].filter(Boolean)
)
function clearOne(key) {
	f[key] = SHEET_DEFAULTS[key]
	reload()
}
function applyFilter(draft) {
	Object.assign(f, draft)
	reload()
}
function clearAll() {
	search.value = ""
	Object.assign(f, SHEET_DEFAULTS, { status: "", sort: "newest" })
	reload()
}

const items = ref([])
const total = ref(0)
const counts = ref({})
const options = ref({ depots: [], principals: [] })
const dayCounts = ref({})
const failed = ref(false)
const start = ref(0)

const pills = computed(() => [
	{ key: "", label: labels.svStatAll, count: counts.value.all || 0, tone: "text-gray-900" },
	{ key: "Open", label: labels.leakStatOpen, count: counts.value.Open || 0, tone: "text-amber-600" },
	{ key: "Completed", label: labels.svStatDone, count: counts.value.Completed || 0, tone: "text-leaf-600" },
	{ key: "leak", label: labels.leakFlag, count: counts.value.leak || 0, tone: "text-red-600" },
])

// Grup per tanggal order dibuat (= tanggal bon masuk). Merah kalau masih ada yang belum dicek.
const days = computed(() => groupByDay(items.value, (o) => o.day, { hot: (o) => o.status === "Open" }))

const listRes = cachedResource({
	url: "container_depot.ess.leak_check.leak_list",
	method: "GET",
	makeParams: () => ({
		status: f.status || undefined,
		search: search.value || undefined,
		day: f.day || undefined,
		depot: f.depot || undefined,
		principal: f.principal || undefined,
		sort: f.sort,
		start: start.value,
		page_length: PAGE,
	}),
	auto: true,
	onSuccess(data) {
		failed.value = false
		items.value = start.value ? [...items.value, ...(data?.items || [])] : data?.items || []
		total.value = data?.total || 0
		counts.value = data?.counts || {}
		options.value = { depots: data?.depots || [], principals: data?.principals || [] }
		dayCounts.value = data?.day_counts || {}
	},
	onError() {
		failed.value = true
	},
})

function reload() {
	start.value = 0
	listRes.reload()
}
function loadMore() {
	start.value = items.value.length
	listRes.reload()
}
function setStatus(key) {
	f.status = key
	reload()
}
function toggleSort() {
	f.sort = f.sort === "oldest" ? "newest" : "oldest"
	reload()
}
</script>
