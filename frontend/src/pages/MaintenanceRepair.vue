<template>
	<!-- Satu akar: <transition> di App.vue butuh satu elemen. -->
	<div>
	<!-- Satu order terbuka (?o=<name>) — dari daftar ini, dari notifikasi, atau dari Riwayat
	     setelah "Tarik & Perbaiki". Daftarnya tetap terpasang di belakang (v-show) supaya
	     halaman yang sudah dimuat dan posisi gulir tidak hilang saat kembali. -->
	<RepairDetail v-if="route.query.o" :key="String(route.query.o)" />

	<!-- Tata letak = Jadwal Survey (SurveyOrderList): cari, pil status, filter + urut, grup
	     per tanggal rencana. Yang sedang dikerjakan jadi kartu besar dengan tombol lanjut;
	     sisanya baris ringkas; ditolak/dibatalkan dilipat di bawah. -->
	<div v-show="!route.query.o" class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<div class="flex items-start justify-between gap-3">
			<div class="min-w-0">
				<h1 class="text-xl font-extrabold tracking-tight text-gray-900">{{ kind.title }}</h1>
				<p class="mt-0.5 truncate text-xs text-gray-500">{{ kind.hint }}</p>
			</div>
			<router-link :to="`${kind.base}/history`" class="oak-btn oak-btn-secondary min-h-[44px] shrink-0 px-3">
				<Icon name="clock" :size="15" /> {{ labels.navHistory }}
			</router-link>
		</div>

		<ListSearch v-model="search" :placeholder="labels.mrListSearch" @search="reload" />

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

		<p v-else-if="!items.length" class="oak-card p-8 text-center text-sm text-gray-400">{{ labels.mrListEmpty }}</p>

		<div v-else class="space-y-4">
			<section v-for="g in days" :key="g.date" class="space-y-2">
				<div class="flex items-center justify-between gap-2 px-1">
					<p class="flex min-w-0 items-center gap-1.5 truncate text-xs font-bold" :class="g.hot ? 'text-red-600' : 'text-gray-600'">
						<span class="h-2 w-2 shrink-0 rounded-full" :class="g.hot ? 'bg-red-500' : 'bg-gray-400'"></span>
						{{ g.label }}
					</p>
					<p class="shrink-0 text-[11px] text-gray-400">{{ fill(labels.svOrderCount, { n: dayCounts[g.date] || g.rows.length }) }}</p>
				</div>

				<!-- Dikerjakan: kartu besar — siapa yang memegang, berapa bukti yang sudah masuk. -->
				<router-link
					v-for="o in g.running"
					:key="o.name"
					:to="linkTo(o)"
					class="oak-card oak-press block space-y-2.5 p-4"
				>
					<RepairOrderInfo :o="o">
						<span class="oak-chip flex shrink-0 items-center gap-1" :class="mrChip(o.status).tone">
							<span class="h-1.5 w-1.5 rounded-full bg-current"></span>{{ mrChip(o.status).label }}
						</span>
					</RepairOrderInfo>
					<LiftOnBadge :survey="o.target_survey_on" :target="o.target_lift_on" :urgent="o.target_urgent_on" />
					<p v-if="o.started_by_name" class="flex items-center gap-1.5 text-xs">
						<Icon name="user" :size="13" class="shrink-0 text-gray-400" />
						<span class="text-gray-400">{{ labels.svWorkedBy }}</span>
						<span class="min-w-0 truncate font-semibold text-gray-700">{{ o.started_by_name }}</span>
					</p>
					<div class="h-1.5 overflow-hidden rounded-full bg-gray-100">
						<div class="h-full rounded-full bg-brand-500" :style="{ width: `${progressPct(o)}%` }"></div>
					</div>
					<p class="text-[11px] text-gray-500">
						{{ labels.mrProgressChip.replace("{done}", o.photo_done || 0).replace("{total}", o.item_count || 0) }}
					</p>
					<span class="oak-btn oak-btn-primary min-h-[48px] w-full">
						<Icon name="camera" :size="16" /> {{ labels.mrContinue }}
					</span>
				</router-link>

				<!-- Sisanya: baris ringkas. -->
				<ul v-if="g.rest.length" class="oak-card divide-y divide-gray-100 overflow-hidden">
					<li v-for="o in g.rest" :key="o.name">
						<router-link :to="linkTo(o)" class="oak-press flex min-h-[64px] items-center gap-2 px-4 py-3">
							<span class="block min-w-0 flex-1 space-y-1">
								<RepairOrderInfo :o="o">
									<span class="oak-chip shrink-0" :class="mrChip(o.status).tone">{{ mrChip(o.status).label }}</span>
								</RepairOrderInfo>
								<LiftOnBadge
									v-if="ACTIVE.includes(o.status)"
									:survey="o.target_survey_on"
									:target="o.target_lift_on"
									:urgent="o.target_urgent_on"
								/>
							</span>
						</router-link>
					</li>
				</ul>
			</section>

			<section v-if="folded.length">
				<button
					class="oak-press flex min-h-[48px] w-full items-center justify-between rounded-xl border border-dashed border-gray-300 px-4 text-xs font-semibold text-gray-500"
					:aria-expanded="showFolded"
					@click="showFolded = !showFolded"
				>
					{{ labels.mrFoldedGroup }} · {{ fill(labels.svOrderCount, { n: folded.length }) }}
					<Icon :name="showFolded ? 'chevron-up' : 'chevron-down'" :size="16" />
				</button>
				<ul v-if="showFolded" class="oak-card mt-2 divide-y divide-gray-100 overflow-hidden">
					<li v-for="o in folded" :key="o.name">
						<router-link :to="linkTo(o)" class="oak-press flex min-h-[56px] items-center gap-2 px-4 py-2.5">
							<span class="min-w-0 flex-1">
								<span class="block truncate font-mono text-sm font-bold text-gray-500 line-through">{{ o.reff_doc || o.name }}</span>
								<span class="block truncate text-xs text-gray-400">
									{{ [mrChip(o.status).label, o.container_no, o.principal, fmtDate(o.day)].filter(Boolean).join(" · ") }}
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
	</div>
</template>

<script setup>
import { computed, ref, watch } from "vue"
import { useRoute } from "vue-router"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"
import LiftOnBadge from "@/components/LiftOnBadge.vue"
import SkeletonList from "@/components/SkeletonList.vue"
import RepairOrderInfo from "@/components/RepairOrderInfo.vue"
import ListSearch from "@/components/list/ListSearch.vue"
import StatPills from "@/components/list/StatPills.vue"
import FilterBar from "@/components/list/FilterBar.vue"
import FilterSheet from "@/components/list/FilterSheet.vue"
import RepairDetail from "@/pages/RepairDetail.vue"
import { cachedResource } from "@/data/cache"
import { mrChip } from "@/utils/mrStatus"
import { fmtDate } from "@/utils/surveyStatus"
import { daysFrom, fill, groupByDay, useSavedFilters } from "@/utils/listKit"


const route = useRoute()

// Menu M&R atau Periodic Test — satu halaman, dua menu (router.js meta; server:
// container_depot/mr_scope.py). Tidak reaktif: App.vue me-remount halaman saat menunya berganti.
const kind = route.meta.jobType === "Periodic Test"
	? { jobType: "Periodic Test", base: "/periodic", key: "periodic", title: labels.navPeriodic, hint: labels.ptExecOrdersHint }
	: { jobType: "Repair", base: "/mr", key: "mr", title: labels.mrTitle, hint: labels.mrExecOrdersHint }

const PAGE = 20
const ACTIVE = ["Pending", "In Progress", "Pending Review"]
const FOLDED = ["Rejected", "Cancelled"]
const SHEET_DEFAULTS = { day: "", depot: "", principal: "", activeOnly: false }
const SHEET_FIELDS = [
	{ key: "activeOnly", type: "scope", empty: false, choices: [{ key: false, label: labels.monitorAll }, { key: true, label: labels.svChipActive }] },
	{ key: "day", type: "date", label: labels.svChipDate },
	{ key: "depot", type: "chips", list: "depots", label: labels.svChipDepot },
	{ key: "principal", type: "select", list: "principals", label: labels.svChipPrincipal },
]
// Disimpan per menu: tim Repair dan tim Periodic bisa berbagi HP.
// Prioritas = urutan worklist yang lama (mendesak, lalu tanggal survey/muat terdekat).
const SORT_LABELS = { priority: labels.listSortPriority, newest: labels.svSortNewest, oldest: labels.leakSortOldest }
const f = useSavedFilters(kind.key, { ...SHEET_DEFAULTS, status: "", sort: "priority" })
if (!SORT_LABELS[f.sort]) f.sort = "priority"
const search = ref("")
const sheetOpen = ref(false)

// ?s=doing|todo|review|done — dikirim kartu & antrean Beranda, supaya angka yang ditekan
// mendarat di status yang menghitungnya.
const FROM_HOME = { doing: "In Progress", todo: "Pending", review: "Pending Review", done: "Completed" }
if (FROM_HOME[route.query.s]) f.status = FROM_HOME[route.query.s]

const activeChips = computed(() =>
	[
		f.day && { key: "day", label: labels.svChipDate, value: fmtDate(f.day) },
		f.depot && { key: "depot", label: labels.svChipDepot, value: f.depot },
		f.principal && { key: "principal", label: labels.svChipPrincipal, value: f.principal },
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
	Object.assign(f, SHEET_DEFAULTS, { status: "", sort: "priority" })
	reload()
}

const items = ref([])
const total = ref(0)
const counts = ref({})
const options = ref({ depots: [], principals: [] })
const dayCounts = ref({})
const failed = ref(false)
const start = ref(0)

// Angkanya dari hitungan TANPA filter (server), supaya pil tetap bisa dipakai berpindah.
const pills = computed(() => [
	{ key: "", label: labels.svStatAll, count: counts.value.all || 0, tone: "text-gray-900" },
	{ key: "Pending", label: labels.mrStatusNotStarted, count: counts.value.Pending || 0, tone: "text-gray-600" },
	{ key: "In Progress", label: labels.sectionDoing, count: counts.value["In Progress"] || 0, tone: "text-brand-600" },
	{ key: "Pending Review", label: labels.listStatReview, count: counts.value["Pending Review"] || 0, tone: "text-sky-600" },
	{ key: "Completed", label: labels.svStatDone, count: counts.value.Completed || 0, tone: "text-leaf-600" },
])

const showFolded = ref(false)
const folded = computed(() => items.value.filter((o) => FOLDED.includes(o.status)))

// Grup per tanggal rencana (server: plan_date, jatuh ke tanggal dibuat). Merah kalau masih ada
// pekerjaan terbuka yang tenggat lift-on-nya sudah tiba.
const days = computed(() =>
	groupByDay(
		items.value.filter((o) => !FOLDED.includes(o.status)),
		(o) => o.group ?? o.day,
		{
			running: (o) => o.status === "In Progress",
			hot: (o) => {
				const due = o.target_urgent_on || o.target_survey_on || o.target_lift_on
				return ACTIVE.includes(o.status) && !!due && (!!o.target_urgent_on || daysFrom(String(due).slice(0, 10)) <= 0)
			},
		}
	)
)

function progressPct(o) {
	return o.item_count ? Math.round(((o.photo_done || 0) / o.item_count) * 100) : 0
}

// Order yang sudah tutup tidak punya form kerja — Riwayat membawa catatan lengkapnya (album,
// linimasa, "Ajukan Revisi"). Yang masih di tangan tim dibuka di detail di halaman ini.
function linkTo(o) {
	return ACTIVE.includes(o.status)
		? { path: kind.base, query: { o: o.name } }
		: { path: `${kind.base}/history`, query: { open: o.name } }
}

const listRes = cachedResource({
	url: "container_depot.ess.repairs.mr_list",
	method: "GET",
	makeParams: () => ({
		job_type: kind.jobType,
		status: f.status || undefined,
		search: search.value || undefined,
		day: f.day || undefined,
		depot: f.depot || undefined,
		principal: f.principal || undefined,
		active_only: f.activeOnly ? 1 : 0,
		sort: f.sort,
		start: start.value,
		page_length: PAGE,
	}),
	auto: true,
	onSuccess(data) {
		failed.value = false
		// `start > 0` = "muat lagi", bukan kueri baru.
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
	const keys = Object.keys(SORT_LABELS)
	f.sort = keys[(keys.indexOf(f.sort) + 1) % keys.length]
	reload()
}

// Kembali dari detail: statusnya mungkin sudah berubah (Mulai, Kirim Review, Tarik).
watch(
	() => route.query.o,
	(o, prev) => {
		if (!o && prev) reload()
	}
)
</script>
