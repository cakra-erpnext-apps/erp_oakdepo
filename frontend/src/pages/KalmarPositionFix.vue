<template>
	<!-- Tata letak = Jadwal Survey (SurveyOrderList): cari, pil, filter + urut, grup per tanggal
	     survey. Satu baris = satu tank di Survey Order booking Tank Out. -->
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<div class="flex items-start justify-between gap-3">
			<div class="min-w-0">
				<h1 class="text-xl font-extrabold tracking-tight text-gray-900">{{ labels.lowTitle }}</h1>
				<p class="mt-0.5 truncate text-xs text-gray-500">{{ labels.lowHint }}</p>
			</div>
			<router-link to="/survey-orders/history" class="oak-btn oak-btn-secondary min-h-[44px] shrink-0 px-3">
				<Icon name="clock" :size="15" /> {{ labels.navHistory }}
			</router-link>
		</div>

		<ListSearch v-model="search" :placeholder="labels.lowSearch" @search="onSearch" />

		<!-- Hasil pencarian menggantikan daftar: yang mengetik nomor sedang mencari satu tank. -->
		<template v-if="search.trim()">
			<ul v-if="searchRows.length" class="oak-card divide-y divide-gray-100 overflow-hidden">
				<TankRow v-for="r in searchRows" :key="r.name" :r="r" />
			</ul>
			<div v-else-if="!searchRes.loading" class="oak-card p-8 text-center text-sm text-gray-400">
				{{ labels.posFixEmpty }}
			</div>
		</template>

		<template v-else>
			<!-- "Mendesak" dipisah dari "Menunggu": antrean yang mengurut apa adanya
			     menyembunyikan tank yang truknya datang besok di tengah dua puluh tank yang
			     truknya bulan depan. -->
			<StatPills :pills="pills" :model-value="f.group" @update:model-value="setGroup" />

			<FilterBar
				:chips="activeChips"
				:sort-label="f.sort === 'far' ? labels.listSortFar : labels.svSortDue"
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

			<SkeletonList v-if="boardRes.loading && !items.length" :action="false" />

			<div v-else-if="failed" class="oak-card flex flex-col items-center gap-2 p-8 text-center">
				<span class="oak-icon-tile h-12 w-12 bg-red-50 text-red-500"><Icon name="alert-circle" :size="24" /></span>
				<p class="text-sm font-bold text-gray-900">{{ labels.monitorErrorTitle }}</p>
				<button class="oak-btn oak-btn-primary mt-1 min-h-[44px] px-4" @click="reload">{{ labels.monitorRetry }}</button>
			</div>

			<div v-else-if="!counts.all" class="oak-card flex flex-col items-center gap-2 p-8 text-center">
				<span class="oak-icon-tile h-12 w-12 bg-gray-100 text-gray-300"><Icon name="arrow-down-circle" :size="24" /></span>
				<p class="text-sm font-bold text-gray-900">{{ labels.lowEmpty }}</p>
				<p class="text-xs text-gray-500">{{ labels.lowEmptyHint }}</p>
				<router-link to="/survey-orders" class="oak-btn oak-btn-secondary mt-1 min-h-[44px] px-4">
					{{ labels.lowEmptyCta }}
				</router-link>
			</div>

			<p v-else-if="!items.length" class="oak-card p-8 text-center text-sm text-gray-400">{{ labels.tankPosEmpty }}</p>

			<div v-else class="space-y-4">
				<section v-for="g in days" :key="g.date" class="space-y-2">
					<div class="flex items-center justify-between gap-2 px-1">
						<p class="flex min-w-0 items-center gap-1.5 truncate text-xs font-bold" :class="g.hot ? 'text-red-600' : 'text-gray-600'">
							<span class="h-2 w-2 shrink-0 rounded-full" :class="g.hot ? 'bg-red-500' : 'bg-gray-400'"></span>
							{{ g.label }}
						</p>
						<p class="shrink-0 text-[11px] text-gray-400">{{ dayCounts[g.date] || g.rows.length }} {{ labels.bulkTankWord }}</p>
					</div>
					<ul class="oak-card divide-y divide-gray-100 overflow-hidden" :class="g.hot && 'border-red-200'">
						<TankRow v-for="r in g.rows" :key="r.name" :r="r" />
					</ul>
				</section>

				<!-- Yang bisa ditandai sekaligus: semua yang masih menunggu DI LAYAR ini. -->
				<button v-if="markable.length > 1" class="oak-btn oak-btn-secondary min-h-[48px] w-full" @click="bulkFrom(markable)">
					{{ fill(labels.lowMarkMany, { n: markable.length }) }}
				</button>

				<button
					v-if="items.length < total"
					class="oak-btn oak-btn-secondary min-h-[48px] w-full"
					:disabled="boardRes.loading"
					@click="loadMore"
				>
					{{ boardRes.loading ? "…" : `${labels.svMore} (${items.length}/${total})` }}
				</button>
			</div>
		</template>
	</div>
</template>

<script setup>
import { computed, h, onMounted, ref } from "vue"
import { useRoute, useRouter, RouterLink } from "vue-router"
import { labels } from "@/utils/labels"
import { since, fmtDate } from "@/utils/surveyStatus"
import { setLoweringPreselect } from "@/utils/positionPick"
import { lowerTank } from "@/utils/lowering"
import { fill, groupByDay, useSavedFilters } from "@/utils/listKit"
import Icon from "@/components/Icon.vue"
import SkeletonList from "@/components/SkeletonList.vue"
import PositionJob from "@/components/PositionJob.vue"
import OrderInfo from "@/components/list/OrderInfo.vue"
import ListSearch from "@/components/list/ListSearch.vue"
import StatPills from "@/components/list/StatPills.vue"
import FilterBar from "@/components/list/FilterBar.vue"
import FilterSheet from "@/components/list/FilterSheet.vue"
import { cachedResource } from "@/data/cache"


const route = useRoute()
const router = useRouter()
const WAITING = "Waiting Lowering"
const PAGE = 20

// ---- daftar ----
// Pil dan filter dikirim ke server, bukan disaring di klien: yang dijanjikan pil adalah angka
// penuh, dan menyaring satu halaman yang terlanjur diambil tidak akan sampai ke sana.
const SHEET_DEFAULTS = { day: "", depot: "", principal: "" }
const SHEET_FIELDS = [
	{ key: "day", type: "date", label: labels.svChipDate },
	{ key: "depot", type: "chips", list: "depots", label: labels.svChipDepot },
	{ key: "principal", type: "select", list: "principals", label: labels.svChipPrincipal },
]
const f = useSavedFilters("lowering", { ...SHEET_DEFAULTS, group: "", sort: "due" })
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
	Object.assign(f, SHEET_DEFAULTS, { group: "", sort: "due" })
	reload()
}

const items = ref([])
const total = ref(0)
const counts = ref({})
const options = ref({ depots: [], principals: [] })
const dayCounts = ref({})
const failed = ref(false)
const start = ref(0)

const boardRes = cachedResource({
	url: "container_depot.ess.tank_survey.lowering_board",
	method: "GET",
	makeParams: () => ({
		group: f.group || "",
		day: f.day || undefined,
		depot: f.depot || undefined,
		principal: f.principal || undefined,
		sort: f.sort,
		start: start.value,
		page_length: PAGE,
		limit: 1, // daftar pendek papan lama tidak dibaca layar ini
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

const pills = computed(() => [
	{ key: "", label: labels.lowStatAll, count: counts.value.all || 0, tone: "text-gray-900" },
	{ key: "urgent", label: labels.lowStatUrgent, count: counts.value.urgent || 0, tone: "text-red-600" },
	{ key: "waiting", label: labels.lowStatWaiting, count: counts.value.waiting || 0, tone: "text-amber-600" },
	{ key: "lowered", label: labels.lowStatLowered, count: counts.value.lowered || 0, tone: "text-leaf-600" },
])

// Grup per tanggal survey (server: `day_key`). Yang dinyatakan mendesak berdiri di grupnya
// sendiri di atas semua tanggal; grup merah = masih ada yang menunggu dan tenggatnya ≤ H-2.
const days = computed(() =>
	groupByDay(items.value, (r) => r.day_key, { hot: (r) => r.status === WAITING && r.urgent }).map((g) =>
		g.date === "urgent" ? { ...g, label: labels.lowSecUrgent, hot: true } : g.date ? g : { ...g, label: labels.listNoSurveyDate }
	)
)

function reload() {
	start.value = 0
	boardRes.reload()
}
function loadMore() {
	start.value = items.value.length
	boardRes.reload()
}
function setGroup(key) {
	f.group = key
	reload()
}
function toggleSort() {
	f.sort = f.sort === "far" ? "due" : "far"
	reload()
}

// Satu centang = lowered. Baris yang sedang dikirim dikunci supaya ketukan ganda tidak
// mengirim dua kali.
const busy = ref(new Set())
async function tick(r) {
	if (busy.value.has(r.name)) return
	busy.value = new Set(busy.value).add(r.name)
	const ok = await lowerTank(r)
	const next = new Set(busy.value)
	next.delete(r.name)
	busy.value = next
	if (ok) {
		reload()
		if (search.value.trim()) searchRes.reload()
	}
}

const markable = computed(() => items.value.filter((r) => r.status === WAITING))
function bulkFrom(rows) {
	setLoweringPreselect(rows)
	router.push("/position-fix/bulk")
}

// ---- pencarian ----
const search = ref("")
const searchRes = cachedResource({
	url: "container_depot.ess.tank_survey.survey_waiting",
	method: "GET",
	makeParams: () => ({ search: search.value || "", page_length: 30 }),
})
const searchRows = computed(() => (search.value.trim() ? searchRes.data?.items || [] : []))
function onSearch() {
	if (search.value.trim()) searchRes.reload()
}

// Satu baris tank: nomor + letak + job (OrderInfo + PositionJob), centang lowered di kanan.
// Render function di file yang sama karena ia tidak punya arti di luar layar ini.
const TankRow = ({ r }) => {
	const waiting = r.status === WAITING
	const chips = [
		r.reopen_note ? h("span", { class: "oak-chip shrink-0 bg-orange-100 text-orange-800" }, labels.posReopenNote) : null,
		waiting && r.urgent ? h("span", { class: "oak-chip shrink-0 bg-red-100 text-red-700" }, labels.lowStatUrgent) : null,
		waiting ? null : h("span", { class: "oak-chip shrink-0 bg-leaf-100 text-leaf-700" }, labels.lowStatLowered),
	]
	return h("li", { class: "flex items-center" }, [
		h(
			RouterLink,
			{ to: `/survey-orders/tank/${r.name}`, class: "oak-press flex min-h-[64px] min-w-0 flex-1 items-center py-3 pl-4 pr-2" },
			() => [
				h("span", { class: "block min-w-0 flex-1" }, [
					// Nomor tank = judul: itu yang dicocokkan Kalmar dengan cat di badan tank.
					h(
						OrderInfo,
						{
							title: r.container_no || r.container || labels.monitorNoNumber,
							principal: r.principal,
							meta: [r.located ? r.location_note : labels.tankPosUnlocated, !waiting && r.lowered_on ? since(r.lowered_on) : null],
						},
						() => h("span", { class: "flex shrink-0 gap-1" }, chips)
					),
					h(PositionJob, { row: { ...r, survey_order: r.survey_order || r.parent } }),
				]),
			]
		),
		// Centang = selesai lowering. Di luar link supaya ketukannya tidak membuka detail.
		!waiting
			? h(Icon, { name: "chevron-right", size: 18, class: "mr-4 shrink-0 text-gray-300" })
			: h(
					"button",
					{
						class: "oak-press mr-3 flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border-2 border-leaf-500 text-leaf-600 disabled:opacity-40",
						"aria-label": `${labels.tankMarkLowered} ${r.container_no || ""}`,
						disabled: busy.value.has(r.name),
						onClick: () => tick(r),
					},
					[h(Icon, { name: busy.value.has(r.name) ? "loader" : "check", size: 22, class: busy.value.has(r.name) ? "animate-spin" : "" })]
				),
	])
}
TankRow.props = ["r"]

// Deep link dari lonceng: `/position-fix?s=CPS-0001` langsung ke tank itu
// (ess/notification_routes._survey).
onMounted(() => {
	const s = route.query.s
	if (s) router.replace(`/survey-orders/tank/${String(s)}`)
})
</script>
