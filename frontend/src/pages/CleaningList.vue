<template>
	<!-- Tata letak = Jadwal Survey (SurveyOrderList): cari, pil status, filter + urut, grup per
	     tanggal order. Cucian yang sedang jalan = kartu besar dengan tombol lanjut; sisanya
	     baris ringkas; yang batal dilipat di bawah. -->
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<div class="flex items-start justify-between gap-3">
			<div class="min-w-0">
				<h1 class="text-xl font-extrabold tracking-tight text-gray-900">{{ labels.cleaningTitle }}</h1>
				<p class="mt-0.5 truncate text-xs text-gray-500">{{ labels.cleaningOrdersHint }}</p>
			</div>
			<router-link to="/cleaning/history" class="oak-btn oak-btn-secondary min-h-[44px] shrink-0 px-3">
				<Icon name="clock" :size="15" /> {{ labels.navHistory }}
			</router-link>
		</div>

		<ListSearch v-model="search" :placeholder="labels.cleaningListSearch" @search="reload" />

		<StatPills :pills="pills" :model-value="f.status" @update:model-value="setStatus" />

		<FilterBar
			:chips="activeChips"
			:sort-label="SORT_LABELS[f.sort] || SORT_LABELS.priority"
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

		<p v-else-if="!items.length" class="oak-card p-8 text-center text-sm text-gray-400">{{ labels.cleaningListEmpty }}</p>

		<div v-else class="space-y-4">
			<section v-for="g in days" :key="g.date" class="space-y-2">
				<div class="flex items-center justify-between gap-2 px-1">
					<p class="flex min-w-0 items-center gap-1.5 truncate text-xs font-bold" :class="g.hot ? 'text-red-600' : 'text-gray-600'">
						<span class="h-2 w-2 shrink-0 rounded-full" :class="g.hot ? 'bg-red-500' : 'bg-gray-400'"></span>
						{{ g.label }}
					</p>
					<p class="shrink-0 text-[11px] text-gray-400">{{ fill(labels.svOrderCount, { n: dayCounts[g.date] || g.rows.length }) }}</p>
				</div>

				<!-- Dikerjakan: kartu besar. -->
				<router-link
					v-for="o in g.running"
					:key="o.name"
					:to="detailLink(o)"
					class="oak-card oak-press block space-y-2.5 p-4"
				>
					<CleaningOrderInfo :o="o">
						<span class="oak-chip flex shrink-0 items-center gap-1" :class="cleaningChip(o).cls">
							<span class="h-1.5 w-1.5 rounded-full bg-current"></span>{{ cleaningChip(o).label }}
						</span>
					</CleaningOrderInfo>
					<LiftOnBadge :survey="o.target_survey_on" :target="o.target_lift_on" :urgent="o.target_urgent_on" />
					<p v-if="o.cleaning_start" class="text-[11px] text-gray-500">
						{{ labels.cleaningStartAt }} {{ fmtDateTime(o.cleaning_start) }}
					</p>
					<span class="oak-btn oak-btn-primary min-h-[48px] w-full">
						<Icon name="sparkles" :size="16" /> {{ labels.cleaningContinue }}
					</span>
				</router-link>

				<!-- Sisanya: baris ringkas. -->
				<ul v-if="g.rest.length" class="oak-card divide-y divide-gray-100 overflow-hidden">
					<li v-for="o in g.rest" :key="o.name">
						<router-link :to="detailLink(o)" class="oak-press flex min-h-[64px] items-center gap-2 px-4 py-3">
							<span class="min-w-0 flex-1 space-y-1">
								<CleaningOrderInfo :o="o">
									<span class="oak-chip shrink-0" :class="cleaningChip(o).cls">{{ cleaningChip(o).label }}</span>
								</CleaningOrderInfo>
								<span v-if="isOpen(o) || o.revision_requested" class="flex flex-wrap items-center gap-1.5">
									<LiftOnBadge v-if="isOpen(o)" :survey="o.target_survey_on" :target="o.target_lift_on" :urgent="o.target_urgent_on" />
									<span v-if="o.revision_requested" class="oak-chip bg-orange-100 text-orange-800">{{ labels.cleaningStatusRevision }}</span>
								</span>
							</span>
						</router-link>
					</li>
				</ul>
			</section>

			<section v-if="cancelled.length">
				<button
					class="oak-press flex min-h-[48px] w-full items-center justify-between rounded-xl border border-dashed border-gray-300 px-4 text-xs font-semibold text-gray-500"
					:aria-expanded="showCancelled"
					@click="showCancelled = !showCancelled"
				>
					{{ labels.svCancelledGroup }} · {{ fill(labels.svOrderCount, { n: cancelled.length }) }}
					<Icon :name="showCancelled ? 'chevron-up' : 'chevron-down'" :size="16" />
				</button>
				<ul v-if="showCancelled" class="oak-card mt-2 divide-y divide-gray-100 overflow-hidden">
					<li v-for="o in cancelled" :key="o.name">
						<router-link :to="detailLink(o)" class="oak-press flex min-h-[56px] items-center gap-2 px-4 py-2.5">
							<span class="min-w-0 flex-1">
								<span class="block truncate font-mono text-sm font-bold text-gray-500 line-through">{{ o.reff_doc || o.name }}</span>
								<span class="block truncate text-xs text-gray-400">
									{{ [o.container_no, o.container_principal, fmtDate(o.order_created)].filter(Boolean).join(" · ") }}
								</span>
							</span>
							<Icon name="chevron-right" :size="18" class="shrink-0 text-gray-300" />
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
import { useRoute } from "vue-router"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"
import SkeletonList from "@/components/SkeletonList.vue"
import LiftOnBadge from "@/components/LiftOnBadge.vue"
import CleaningOrderInfo from "@/components/CleaningOrderInfo.vue"
import ListSearch from "@/components/list/ListSearch.vue"
import StatPills from "@/components/list/StatPills.vue"
import FilterBar from "@/components/list/FilterBar.vue"
import FilterSheet from "@/components/list/FilterSheet.vue"
import { cachedResource } from "@/data/cache"
import { fmtDate, fmtDateTime } from "@/utils/surveyStatus"
import { daysFrom, fill, groupByDay, useSavedFilters } from "@/utils/listKit"
import { cleaningChip } from "@/utils/cleaningStatus"


const route = useRoute()
const PAGE = 20
const SHEET_DEFAULTS = { day: "", depot: "", principal: "", cleaningType: "" }
const SHEET_FIELDS = [
	{ key: "day", type: "date", label: labels.svChipDate },
	{ key: "depot", type: "chips", list: "depots", label: labels.svChipDepot },
	{ key: "principal", type: "select", list: "principals", label: labels.svChipPrincipal },
	{ key: "cleaningType", type: "chips", list: "cleaningTypes", label: labels.cleaningType },
]
// Prioritas = urutan worklist yang lama (mendesak, lalu tanggal survey/muat terdekat).
const SORT_LABELS = { priority: labels.listSortPriority, newest: labels.svSortNewest, oldest: labels.leakSortOldest }
const f = useSavedFilters("cleaning", { ...SHEET_DEFAULTS, status: "", sort: "priority" })
if (!SORT_LABELS[f.sort]) f.sort = "priority"
// ?s=doing|todo|review|done — dikirim kartu & antrean Beranda: angka yang ditekan mendarat di
// pil yang menghitungnya.
const FROM_HOME = { doing: "In_Progress", todo: "todo", review: "Pending Review", done: "Completed" }
if (FROM_HOME[route.query.s]) f.status = FROM_HOME[route.query.s]
const search = ref("")
const sheetOpen = ref(false)

const activeChips = computed(() =>
	[
		f.day && { key: "day", label: labels.svChipDate, value: fmtDate(f.day) },
		f.depot && { key: "depot", label: labels.svChipDepot, value: f.depot },
		f.principal && { key: "principal", label: labels.svChipPrincipal, value: f.principal },
		f.cleaningType && { key: "cleaningType", label: labels.cleaningType, value: f.cleaningType },
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
	Object.assign(f, SHEET_DEFAULTS, { status: "", sort: "priority" })
	reload()
}

const items = ref([])
const total = ref(0)
const counts = ref({})
const options = ref({ depots: [], principals: [], cleaningTypes: [] })
const dayCounts = ref({})
const failed = ref(false)
const start = ref(0)

// Angkanya dari hitungan TANPA filter (server), supaya pil tetap bisa dipakai berpindah.
const pills = computed(() => [
	{ key: "", label: labels.svStatAll, count: counts.value.all || 0, tone: "text-gray-900" },
	{ key: "todo", label: labels.cleaningFilterTodo, count: counts.value.todo || 0, tone: "text-gray-600" },
	{ key: "In_Progress", label: labels.cleaningInProgress, count: counts.value.In_Progress || 0, tone: "text-amber-600" },
	{ key: "Pending Review", label: labels.listStatReview, count: counts.value["Pending Review"] || 0, tone: "text-sky-600" },
	{ key: "Completed", label: labels.cleaningStatusCompleted, count: counts.value.Completed || 0, tone: "text-leaf-600" },
])

// Masih di tangan tim cuci (belum diajukan review / selesai).
const isOpen = (o) => !["Pending Review", "Completed", "Cancelled"].includes(o.status)
const dueOf = (o) => o.target_urgent_on || o.target_survey_on || o.target_lift_on

const showCancelled = ref(false)
const cancelled = computed(() => items.value.filter((o) => o.status === "Cancelled"))
// Urutan dari server: tanggal, lalu dalam satu hari dikerjakan → belum → review → selesai.
// Merah = ada tank yang tenggat keluarnya sudah hari ini / lewat tapi cuciannya belum lepas.
const days = computed(() =>
	groupByDay(
		items.value.filter((o) => o.status !== "Cancelled"),
		(o) => o.group ?? o.day,
		{
			running: (o) => o.status === "In_Progress",
			hot: (o) => (o.group === "urgent" && isOpen(o)) || isOpen(o) && (!!o.target_urgent_on || (dueOf(o) && daysFrom(String(dueOf(o)).slice(0, 10)) <= 0)),
		}
	)
)

// Detail = /cleaning?o=<name> — alamat yang sama yang dipakai notifikasi sejak dulu.
const detailLink = (o) => ({ path: "/cleaning", query: { o: o.name } })

const listRes = cachedResource({
	url: "container_depot.ess.cleaning.cleaning_list",
	method: "GET",
	makeParams: () => ({
		status: f.status || undefined,
		search: search.value || undefined,
		day: f.day || undefined,
		depot: f.depot || undefined,
		principal: f.principal || undefined,
		cleaning_type: f.cleaningType || undefined,
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
		options.value = {
			depots: data?.depots || [],
			principals: data?.principals || [],
			cleaningTypes: data?.cleaning_types || [],
		}
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
	const keys = Object.keys(SORT_LABELS)
	f.sort = keys[(keys.indexOf(f.sort) + 1) % keys.length]
	reload()
}
</script>
