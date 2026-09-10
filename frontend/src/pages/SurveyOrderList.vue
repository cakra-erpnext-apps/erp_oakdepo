<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<div class="flex items-start justify-between gap-3">
			<div class="min-w-0">
				<h1 class="text-xl font-extrabold tracking-tight text-gray-900">{{ labels.svListTitle }}</h1>
				<p class="mt-0.5 truncate text-xs text-gray-500">{{ labels.svListHint }}</p>
			</div>
			<router-link to="/survey-orders/history" class="oak-btn oak-btn-secondary min-h-[44px] shrink-0 px-3">
				<Icon name="clock" :size="15" /> {{ labels.navHistory }}
			</router-link>
		</div>

		<!-- Mencari nomor jadwal, prinsipal, DAN nomor tank (server menyisir tabel anaknya):
		     yang dipegang orang yang bertanya "hari apa tank itu" adalah nomor tanknya. -->
		<div class="relative">
			<Icon name="search" :size="18" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
			<input
				v-model="search"
				type="search"
				class="oak-input pl-10 pr-10"
				:placeholder="labels.svListSearch"
				autocorrect="off"
				spellcheck="false"
				@input="onSearchInput"
			/>
			<button
				v-if="search"
				class="oak-press absolute right-2 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full text-gray-400"
				:aria-label="labels.tplCancel"
				@click="search = ''; reload()"
			>
				<Icon name="x" :size="16" />
			</button>
		</div>

		<!-- Empat angka yang bisa dipencet. Angkanya dihitung TANPA filter yang sedang berlaku,
		     supaya pil tetap bisa dipakai berpindah justru saat pencarian sedang mempersempit —
		     pil yang semuanya berbunyi 0 begitu diketik adalah pil yang tidak bisa dinavigasi. -->
		<div class="grid grid-cols-4 gap-1.5">
			<button
				v-for="p in pills"
				:key="p.key || 'all'"
				class="oak-press flex min-h-[68px] flex-col items-center justify-center rounded-xl border px-1 py-2 transition"
				:class="status === p.key ? 'border-brand-500 bg-brand-500/10' : 'border-gray-200 bg-paper'"
				:aria-pressed="status === p.key"
				@click="setStatus(status === p.key ? '' : p.key)"
			>
				<span class="text-lg font-extrabold leading-none" :class="status === p.key ? 'text-brand-700' : p.tone">
					{{ p.count }}
				</span>
				<span class="mt-1 truncate text-[11px] font-semibold" :class="status === p.key ? 'text-brand-700' : 'text-gray-500'">
					{{ p.label }}
				</span>
			</button>
		</div>

		<!-- Chip filter. Tiap chip membuka barisnya sendiri di bawah, bukan sheet: yang diatur
		     di sini cuma satu nilai per chip, dan sheet untuk satu pilihan adalah dua ketukan
		     untuk pekerjaan satu ketukan. -->
		<div class="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1">
			<button
				class="oak-press flex min-h-[40px] shrink-0 items-center gap-1.5 rounded-full border px-3 text-xs font-bold transition"
				:class="dateOn ? 'border-brand-500 bg-brand-500/10 text-brand-700' : 'border-gray-200 bg-paper text-gray-600'"
				@click="panel = panel === 'date' ? '' : 'date'"
			>
				<Icon name="calendar" :size="13" /> {{ labels.svChipDate }}
			</button>
			<button
				class="oak-press flex min-h-[40px] shrink-0 items-center gap-1.5 rounded-full border px-3 text-xs font-bold transition"
				:class="principal ? 'border-brand-500 bg-brand-500/10 text-brand-700' : 'border-gray-200 bg-paper text-gray-600'"
				@click="panel = panel === 'principal' ? '' : 'principal'"
			>
				<Icon name="briefcase" :size="13" /> {{ principal || labels.svChipPrincipal }}
			</button>
			<button
				class="oak-press flex min-h-[40px] shrink-0 items-center gap-1.5 rounded-full border px-3 text-xs font-bold transition"
				:class="activeOnly ? 'border-brand-500 bg-brand-500/10 text-brand-700' : 'border-gray-200 bg-paper text-gray-600'"
				:aria-pressed="activeOnly"
				@click="toggleActive"
			>
				<Icon name="filter" :size="13" /> {{ labels.svChipActive }}
			</button>
			<button
				class="oak-press flex min-h-[40px] shrink-0 items-center gap-1.5 rounded-full border px-3 text-xs font-bold transition"
				:class="sort === 'due' ? 'border-brand-500 bg-brand-500/10 text-brand-700' : 'border-gray-200 bg-paper text-gray-600'"
				@click="toggleSort"
			>
				<Icon name="sliders" :size="13" />
				{{ labels.svChipSort }}: {{ sort === "due" ? labels.svSortDue : labels.svSortNewest }}
			</button>
		</div>

		<div v-if="panel === 'date'" class="oak-card space-y-2 p-3">
			<div class="flex items-center gap-2">
				<input v-model="fromDate" type="date" class="oak-input min-h-[44px] flex-1" @change="reload" />
				<span class="shrink-0 text-xs text-gray-400">—</span>
				<input v-model="toDate" type="date" class="oak-input min-h-[44px] flex-1" @change="reload" />
			</div>
			<button v-if="dateOn" class="oak-press text-xs font-bold text-brand-600" @click="resetFilters">
				{{ labels.monitorFilterReset }}
			</button>
		</div>

		<div v-if="panel === 'principal'" class="oak-card flex flex-wrap gap-1.5 p-3">
			<button
				class="oak-press min-h-[38px] rounded-full border px-3 text-xs font-bold"
				:class="!principal ? 'border-brand-500 bg-brand-500/10 text-brand-700' : 'border-gray-200 text-gray-600'"
				@click="setPrincipal('')"
			>
				{{ labels.monitorAll }}
			</button>
			<button
				v-for="p in principals"
				:key="p"
				class="oak-press min-h-[38px] rounded-full border px-3 text-xs font-bold"
				:class="principal === p ? 'border-brand-500 bg-brand-500/10 text-brand-700' : 'border-gray-200 text-gray-600'"
				@click="setPrincipal(p)"
			>
				{{ p }}
			</button>
		</div>

		<SkeletonList v-if="listRes.loading && !items.length" :action="false" />

		<div v-else-if="failed" class="oak-card flex flex-col items-center gap-2 p-8 text-center">
			<span class="oak-icon-tile h-12 w-12 bg-red-50 text-red-500"><Icon name="alert-circle" :size="24" /></span>
			<p class="text-sm font-bold text-gray-900">{{ labels.monitorErrorTitle }}</p>
			<button class="oak-btn oak-btn-primary mt-1 min-h-[44px] px-4" @click="reload">{{ labels.monitorRetry }}</button>
		</div>

		<p v-else-if="!items.length" class="oak-card p-8 text-center text-sm text-gray-400">{{ labels.svEmpty }}</p>

		<!-- Dikelompokkan: mendesak dulu, lalu yang sedang berjalan, lalu sisanya. Urutan ini
		     urutan perhatian, bukan urutan abjad — dan "Mendesak" menyilang status, karena
		     tenggat yang mepet tidak peduli jadwalnya sudah dimulai atau belum. -->
		<div v-else class="space-y-3">
			<section v-for="g in groups" :key="g.key" class="space-y-1.5">
				<div class="flex items-baseline justify-between gap-2 px-1">
					<p class="text-xs font-bold" :class="g.key === 'urgent' ? 'text-red-600' : 'text-gray-500'">
						{{ g.label }} · {{ g.count }}
					</p>
					<p v-if="g.hint" class="truncate text-[11px] text-gray-400">{{ g.hint }}</p>
				</div>
				<ul class="oak-card divide-y divide-gray-100 overflow-hidden" :class="g.key === 'urgent' ? 'border-red-200' : ''">
					<li v-for="o in g.rows" :key="o.name">
						<router-link
							:to="`/survey-orders/order/${o.name}`"
							class="oak-press flex min-h-[64px] items-center gap-3 px-4 py-3"
						>
							<span class="oak-icon-tile h-10 w-10 shrink-0" :class="tile(o.status)">
								<Icon :name="statusIcon(o.status)" :size="17" />
							</span>
							<span class="min-w-0 flex-1">
								<span class="flex items-center gap-2">
									<span class="min-w-0 truncate font-mono text-sm font-extrabold text-gray-900">
										{{ o.booking || o.name }}
									</span>
									<span class="shrink-0 font-mono text-[11px] text-gray-400">{{ o.name }}</span>
								</span>
								<span class="block truncate text-[11px] text-gray-500">{{ orderLine(o) }}</span>
								<span class="mt-1 flex flex-wrap items-center gap-1.5">
									<LiftOnBadge :survey="o.survey_date" :target="o.plan_date" :urgent="o.target_urgent_on" />
									<span class="oak-chip shrink-0" :class="chip(o.status)">{{ statusLabel(o.status) }}</span>
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
import { computed, onBeforeUnmount, ref } from "vue"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"
import LiftOnBadge from "@/components/LiftOnBadge.vue"
import SkeletonList from "@/components/SkeletonList.vue"
import { cachedResource } from "@/data/cache"
import { fmtDate } from "@/utils/surveyStatus"

const PAGE = 20

// The four schedule statuses, plus an "everything" chip. These are the SCHEDULE's statuses
// (Survey Order), not a tank's — `utils/surveyStatus.js` owns those three and they are a
// different vocabulary on purpose.
const FILTERS = [
	{ key: "", label: labels.surveyListFilterAll, on: "bg-brand-600 text-white" },
	{ key: "Scheduled", label: labels.surveyOrderStatusScheduled, on: "bg-gray-700 text-white" },
	{ key: "In Progress", label: labels.surveyOrderStatusProgress, on: "bg-amber-500 text-white" },
	{ key: "Completed", label: labels.surveyOrderStatusCompleted, on: "bg-leaf-600 text-white" },
	{ key: "Cancelled", label: labels.surveyOrderStatusCancelled, on: "bg-red-600 text-white" },
]

// Warna DAN bentuk: sebuah chip yang hanya berbeda warna tidak terbaca di bawah matahari,
// dan itu kondisi normal buat layar yang dipakai di yard.
const STATUS_STYLE = {
	Scheduled: { chip: "bg-gray-100 text-gray-600", tile: "bg-gray-100 text-gray-500", icon: "calendar" },
	"In Progress": { chip: "bg-amber-100 text-amber-800", tile: "bg-amber-50 text-amber-600", icon: "loader" },
	Completed: { chip: "bg-leaf-100 text-leaf-700", tile: "bg-leaf-50 text-leaf-600", icon: "check-circle" },
	Cancelled: { chip: "bg-red-100 text-red-700", tile: "bg-red-50 text-red-500", icon: "x-circle" },
}
const chip = (s) => STATUS_STYLE[s]?.chip || "bg-gray-100 text-gray-600"
const tile = (s) => STATUS_STYLE[s]?.tile || "bg-gray-100 text-gray-400"
const statusIcon = (s) => STATUS_STYLE[s]?.icon || "clipboard"
const statusLabel = (s) =>
	FILTERS.find((f) => f.key === s)?.label || s || "—"

const search = ref("")
const status = ref("")
const fromDate = ref("")
const toDate = ref("")
const principal = ref("")
const activeOnly = ref(false)
const sort = ref("newest")
// Chip mana yang barisnya sedang terbuka — satu saja, karena dua baris filter terbuka
// bersamaan mendorong daftarnya ke bawah lipatan di HP.
const panel = ref("")
const items = ref([])
const total = ref(0)
const counts = ref({})
const principals = ref([])
const failed = ref(false)
const start = ref(0)

const dateOn = computed(() => Boolean(fromDate.value || toDate.value))

// Empat pil. Angkanya datang dari hitungan TANPA filter (lihat _status_counts di server).
const pills = computed(() => [
	{ key: "", label: labels.svStatAll, count: counts.value.all || 0, tone: "text-gray-900" },
	{ key: "Scheduled", label: labels.svStatScheduled, count: counts.value.Scheduled || 0, tone: "text-gray-600" },
	{ key: "In Progress", label: labels.svStatRunning, count: counts.value["In Progress"] || 0, tone: "text-amber-600" },
	{ key: "Completed", label: labels.svStatDone, count: counts.value.Completed || 0, tone: "text-leaf-600" },
])

// Kelompok tampil. "Mendesak" menyilang status karena tenggat yang mepet tidak peduli
// jadwalnya sudah dimulai atau belum; sisanya jatuh ke statusnya masing-masing.
const GROUPS = [
	{ key: "In Progress", label: labels.svStatRunning },
	{ key: "Scheduled", label: labels.svStatScheduled },
	{ key: "Completed", label: labels.svStatDone },
	{ key: "Cancelled", label: labels.surveyOrderStatusCancelled },
]
const groups = computed(() => {
	const urgent = items.value.filter((o) => o.urgent)
	const out = []
	if (urgent.length) {
		out.push({
			key: "urgent",
			label: labels.svSecUrgent,
			count: counts.value.urgent ?? urgent.length,
			hint: fill(labels.svSecUrgentHint, { n: 8 }),
			rows: urgent,
		})
	}
	for (const g of GROUPS) {
		const rows = items.value.filter((o) => o.status === g.key && !o.urgent)
		if (rows.length) out.push({ key: g.key, label: g.label, count: counts.value[g.key] || rows.length, rows })
	}
	return out
})

function fill(tpl, vars) {
	return Object.entries(vars).reduce((s, [k, v]) => s.replace(`{${k}}`, v), tpl)
}
function orderLine(o) {
	return [o.principal, fmtDate(o.survey_date), fill(labels.svTankCount, { n: o.tank_count || 0 })]
		.filter(Boolean)
		.join(" · ")
}

const listRes = cachedResource({
	url: "container_depot.ess.tank_survey.survey_order_list",
	method: "GET",
	makeParams: () => ({
		status: status.value || undefined,
		from_date: fromDate.value || undefined,
		to_date: toDate.value || undefined,
		search: search.value || undefined,
		principal: principal.value || undefined,
		active_only: activeOnly.value ? 1 : 0,
		sort: sort.value,
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
		principals.value = data?.principals || []
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
	status.value = key
	reload()
}

function resetFilters() {
	fromDate.value = ""
	toDate.value = ""
	reload()
}

function setPrincipal(p) {
	principal.value = p
	panel.value = ""
	reload()
}
function toggleActive() {
	activeOnly.value = !activeOnly.value
	reload()
}
function toggleSort() {
	sort.value = sort.value === "due" ? "newest" : "due"
	reload()
}

// Debounced so a tank number typed a character at a time is one query, not twelve.
let searchTimer = null
function onSearchInput() {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(reload, 300)
}
onBeforeUnmount(() => clearTimeout(searchTimer))
</script>
