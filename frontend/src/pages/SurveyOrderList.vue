<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<div class="flex items-start justify-between gap-3">
			<div class="min-w-0">
				<h1 class="text-xl font-extrabold tracking-tight text-gray-900">{{ labels.svListTitle }}</h1>
				<p class="mt-0.5 truncate text-xs text-gray-500">{{ labels.svListHint }}</p>
			</div>
			<router-link to="/survey-orders/riwayat" class="oak-btn oak-btn-secondary min-h-[44px] shrink-0 px-3">
				<Icon name="clock" :size="15" /> {{ labels.navHistory }}
			</router-link>
		</div>

		<!-- Mencari nomor jadwal, prinsipal, DAN nomor tank (server menyisir tabel anaknya):
		     yang dipegang orang yang bertanya "hari apa tank itu" adalah nomor tanknya. -->
		<ListSearch v-model="search" :placeholder="labels.svListSearch" @search="reload" />

		<StatPills :pills="pills" :model-value="f.status" @update:model-value="setStatus" />

		<FilterBar
			:chips="activeChips"
			:sort-label="f.sort === 'due' ? labels.svSortDue : labels.svSortNewest"
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

		<p v-else-if="!items.length" class="oak-card p-8 text-center text-sm text-gray-400">{{ labels.svEmpty }}</p>

		<!-- Dikelompokkan per tanggal survey: yang dicari orang di yard adalah "hari ini ada
		     apa", bukan status. Yang sedang berjalan jadi kartu besar dengan tombol lanjut;
		     sisanya baris ringkas. Yang dibatalkan dilipat di bawah — riwayat, bukan kerjaan. -->
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
					:to="`/survey-orders/order/${o.name}`"
					class="oak-card oak-press block space-y-2.5 p-4"
				>
					<SurveyOrderInfo :o="o">
						<span class="oak-chip flex shrink-0 items-center gap-1" :class="chip(o.status)">
							<span class="h-1.5 w-1.5 rounded-full bg-current"></span>{{ statusLabel(o.status) }}
						</span>
					</SurveyOrderInfo>
					<p v-if="o.worked_by?.length" class="flex items-center gap-1.5 text-xs">
						<Icon name="user" :size="13" class="shrink-0 text-gray-400" />
						<span class="text-gray-400">{{ labels.svWorkedBy }}</span>
						<span class="min-w-0 truncate font-semibold text-gray-700">{{ o.worked_by.join(", ") }}</span>
					</p>
					<div class="h-1.5 overflow-hidden rounded-full bg-gray-100">
						<div class="h-full rounded-full bg-brand-500" :style="{ width: `${o.per_surveyed || 0}%` }"></div>
					</div>
					<p class="text-[11px] text-gray-500">
						{{ fill(labels.svProgressLine, { d: o.survey_done_count || 0, n: o.tank_count || 0 }) }}
					</p>
					<span class="oak-btn oak-btn-primary min-h-[48px] w-full">
						<Icon name="camera" :size="16" /> {{ labels.svContinue }}
					</span>
				</router-link>

				<!-- Sisanya: baris ringkas. -->
				<ul v-if="g.rest.length" class="oak-card divide-y divide-gray-100 overflow-hidden">
					<li v-for="o in g.rest" :key="o.name">
						<router-link :to="`/survey-orders/order/${o.name}`" class="oak-press flex min-h-[64px] items-center gap-2 px-4 py-3">
							<SurveyOrderInfo :o="o" class="flex-1">
								<span class="oak-chip shrink-0" :class="chip(o.status)">{{ statusLabel(o.status) }}</span>
							</SurveyOrderInfo>
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
						<router-link :to="`/survey-orders/order/${o.name}`" class="oak-press flex min-h-[56px] items-center gap-2 px-4 py-2.5">
							<span class="min-w-0 flex-1">
								<span class="block truncate font-mono text-sm font-bold text-gray-500 line-through">{{ docNo(o) }}</span>
								<span class="block truncate text-xs text-gray-400">
									{{ [o.principal, fmtDate(o.survey_date)].filter(Boolean).join(" · ") }}
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
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"
import SkeletonList from "@/components/SkeletonList.vue"
import SurveyOrderInfo from "@/components/SurveyOrderInfo.vue"
import ListSearch from "@/components/list/ListSearch.vue"
import StatPills from "@/components/list/StatPills.vue"
import FilterBar from "@/components/list/FilterBar.vue"
import FilterSheet from "@/components/list/FilterSheet.vue"
import { cachedResource } from "@/data/cache"
import { fmtDate } from "@/utils/surveyStatus"
import { daysFrom, fill, groupByDay, useSavedFilters } from "@/utils/listKit"

const PAGE = 20

// Chip status membawa teksnya sendiri, jadi tetap terbaca walau warnanya pudar di bawah matahari.
const STATUS_STYLE = {
	Scheduled: { chip: "bg-blue-100 text-blue-700" },
	"In Progress": { chip: "bg-amber-100 text-amber-800" },
	Completed: { chip: "bg-leaf-100 text-leaf-700" },
	Cancelled: { chip: "bg-red-100 text-red-700" },
}
const chip = (s) => STATUS_STYLE[s]?.chip || "bg-gray-100 text-gray-600"
const STATUS_LABEL = {
	Scheduled: labels.svStatScheduled,
	"In Progress": labels.svStatRunning,
	Completed: labels.svStatDone,
	Cancelled: labels.svCancelledGroup,
}
const statusLabel = (s) => STATUS_LABEL[s] || s || "—"

// Semua saringan di sheet (SHEET_FIELDS) + pil status + urutan, disimpan per user di perangkat
// ini (utils/listKit). Pencarian sengaja tidak ikut: itu pertanyaan sekali jalan.
const SHEET_DEFAULTS = { day: "", depot: "", principal: "", surveyor: "", shipper: "", emkl: "", mine: false, activeOnly: false }
const SHEET_FIELDS = [
	{ key: "activeOnly", type: "scope", empty: false, choices: [{ key: false, label: labels.monitorAll }, { key: true, label: labels.svChipActive }] },
	// Kerjaan saya: jadwal yang tank-nya pernah saya turunkan atau survey.
	{ key: "mine", type: "toggle", icon: "user", label: labels.svMine },
	{ key: "day", type: "date", label: labels.svChipDate },
	{ key: "depot", type: "chips", list: "depots", label: labels.svChipDepot },
	{ key: "principal", type: "select", list: "principals", label: labels.svChipPrincipal },
	{ key: "surveyor", type: "select", list: "surveyors", label: labels.svSurveyor },
	{ key: "shipper", type: "select", list: "shippers", label: labels.shipper },
	{ key: "emkl", type: "select", list: "emkls", label: labels.svEmkl },
]
const f = useSavedFilters("survey", { ...SHEET_DEFAULTS, status: "", sort: "due" })
if (f.sort !== "newest") f.sort = "due"
const search = ref("")
const sheetOpen = ref(false)

// Chip filter aktif, dalam urutan sheet. Label pendek di depan supaya "OAK1" atau nama PT
// tetap jelas milik saringan yang mana.
const activeChips = computed(() =>
	[
		f.day && { key: "day", label: labels.svChipDate, value: fmtDate(f.day) },
		f.depot && { key: "depot", label: labels.svChipDepot, value: f.depot },
		f.principal && { key: "principal", label: labels.svChipPrincipal, value: f.principal },
		f.surveyor && { key: "surveyor", label: labels.svSurveyor, value: f.surveyor },
		f.shipper && { key: "shipper", label: labels.shipper, value: f.shipper },
		f.emkl && { key: "emkl", label: labels.svEmkl, value: f.emkl },
		f.mine && { key: "mine", label: "", value: labels.svMine },
		f.activeOnly && { key: "activeOnly", label: "", value: labels.svChipActive },
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
	Object.assign(f, SHEET_DEFAULTS, { status: "", sort: "due" })
	reload()
}

const items = ref([])
const total = ref(0)
const counts = ref({})
const options = ref({ depots: [], principals: [], surveyors: [], shippers: [], emkls: [] })
const dayCounts = ref({})
const failed = ref(false)
const start = ref(0)

// Empat pil. Angkanya datang dari hitungan TANPA filter (lihat _status_counts di server).
const pills = computed(() => [
	{ key: "", label: labels.svStatAll, count: counts.value.all || 0, tone: "text-gray-900" },
	{ key: "Scheduled", label: labels.svStatScheduled, count: counts.value.Scheduled || 0, tone: "text-gray-600" },
	{ key: "In Progress", label: labels.svStatRunning, count: counts.value["In Progress"] || 0, tone: "text-amber-600" },
	{ key: "Completed", label: labels.svStatDone, count: counts.value.Completed || 0, tone: "text-leaf-600" },
])

const showCancelled = ref(false)
const cancelled = computed(() => items.value.filter((o) => o.status === "Cancelled"))

// Satu grup per tanggal survey. Urutan sepenuhnya dari server: tanggal, lalu dalam satu hari
// dikerjakan → terjadwal → selesai.
const days = computed(() =>
	groupByDay(
		items.value.filter((o) => o.status !== "Cancelled"),
		(o) => o.survey_date,
		{
			running: (o) => o.status === "In Progress",
			hot: (o) => o.urgent || (o.survey_date && daysFrom(o.survey_date) <= 0 && o.status !== "Completed"),
		}
	)
)

// Nomor yang dicocokkan dengan kertas: Reff Doc kalau ada, booking kalau belum.
const docNo = (o) => o.reff_doc || o.booking || o.name

const listRes = cachedResource({
	url: "container_depot.ess.tank_survey.survey_order_list",
	method: "GET",
	makeParams: () => ({
		status: f.status || undefined,
		from_date: f.day || undefined,
		to_date: f.day || undefined,
		search: search.value || undefined,
		principal: f.principal || undefined,
		depot: f.depot || undefined,
		surveyor: f.surveyor || undefined,
		shipper: f.shipper || undefined,
		emkl: f.emkl || undefined,
		mine: f.mine ? 1 : 0,
		active_only: f.activeOnly ? 1 : 0,
		sort: f.sort,
		start: start.value,
		page_length: PAGE,
	}),
	auto: true,
	onSuccess(data) {
		failed.value = false
		// `start > 0` is the only signal that this was a "load more" rather than a fresh
		// query — the resource itself does not distinguish them.
		items.value = start.value ? [...items.value, ...(data?.items || [])] : data?.items || []
		total.value = data?.total || 0
		counts.value = data?.counts || {}
		options.value = {
			depots: data?.depots || [],
			principals: data?.principals || [],
			surveyors: data?.surveyors || [],
			shippers: data?.shippers || [],
			emkls: data?.emkls || [],
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
	f.sort = f.sort === "due" ? "newest" : "due"
	reload()
}
</script>
