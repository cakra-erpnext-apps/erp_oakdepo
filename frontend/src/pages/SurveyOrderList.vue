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
			<!-- Tanggal: ketuk chip langsung membuka kalender bawaan HP, tanpa panel. Inputnya
			     ada tapi tak terlihat — showPicker() butuh elemen yang ter-render. -->
			<span
				class="relative flex min-h-[40px] shrink-0 items-center rounded-full border text-xs font-bold transition"
				:class="dateOn ? 'border-brand-500 bg-brand-500/10 text-brand-700' : 'border-gray-200 bg-paper text-gray-600'"
			>
				<button class="oak-press flex h-full items-center gap-1.5 px-3" @click="pickDay">
					<Icon name="calendar" :size="13" /> {{ day ? fmtDate(day) : labels.svChipDate }}
				</button>
				<button
					v-if="dateOn"
					class="oak-press -ml-1.5 flex h-full items-center pr-3"
					:aria-label="labels.monitorFilterReset"
					@click="clearDay"
				>
					<Icon name="x" :size="13" />
				</button>
				<input
					ref="dayInput"
					v-model="day"
					type="date"
					tabindex="-1"
					aria-hidden="true"
					class="pointer-events-none absolute bottom-0 left-0 h-px w-px opacity-0"
					@change="reload"
				/>
			</span>
			<button
				class="oak-press flex min-h-[40px] shrink-0 items-center gap-1.5 rounded-full border px-3 text-xs font-bold transition"
				:class="principal ? 'border-brand-500 bg-brand-500/10 text-brand-700' : 'border-gray-200 bg-paper text-gray-600'"
				@click="panel = panel === 'principal' ? '' : 'principal'"
			>
				<Icon name="briefcase" :size="13" /> {{ principal || labels.svChipPrincipal }}
			</button>
			<button
				v-if="depots.length > 1 || depot"
				class="oak-press flex min-h-[40px] shrink-0 items-center gap-1.5 rounded-full border px-3 text-xs font-bold transition"
				:class="depot ? 'border-brand-500 bg-brand-500/10 text-brand-700' : 'border-gray-200 bg-paper text-gray-600'"
				@click="panel = panel === 'depot' ? '' : 'depot'"
			>
				<Icon name="map-pin" :size="13" /> {{ depot || labels.svChipDepot }}
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
				:class="sort !== 'due' ? 'border-brand-500 bg-brand-500/10 text-brand-700' : 'border-gray-200 bg-paper text-gray-600'"
				@click="toggleSort"
			>
				<Icon name="sliders" :size="13" />
				{{ labels.svChipSort }}: {{ sort === "due" ? labels.svSortDue : labels.svSortNewest }}
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

		<div v-if="panel === 'depot'" class="oak-card flex flex-wrap gap-1.5 p-3">
			<button
				class="oak-press min-h-[38px] rounded-full border px-3 text-xs font-bold"
				:class="!depot ? 'border-brand-500 bg-brand-500/10 text-brand-700' : 'border-gray-200 text-gray-600'"
				@click="setDepot('')"
			>
				{{ labels.monitorAll }}
			</button>
			<button
				v-for="d in depots"
				:key="d"
				class="oak-press min-h-[38px] rounded-full border px-3 text-xs font-bold"
				:class="depot === d ? 'border-brand-500 bg-brand-500/10 text-brand-700' : 'border-gray-200 text-gray-600'"
				@click="setDepot(d)"
			>
				{{ d }}
			</button>
		</div>

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

				<!-- Berjalan: kartu besar. -->
				<router-link
					v-for="o in g.running"
					:key="o.name"
					:to="`/survey-orders/order/${o.name}`"
					class="oak-card oak-press block space-y-2.5 p-4"
				>
					<div class="flex items-start justify-between gap-2">
						<div class="min-w-0">
							<p class="truncate text-base font-extrabold leading-tight text-gray-900">
								{{ o.principal || labels.svNoPrincipal }}
							</p>
							<p v-for="x in parties(o)" :key="x.k" class="truncate text-sm">
								<span class="text-gray-400">{{ x.k }}</span> <span class="font-semibold text-gray-700">{{ x.v }}</span>
							</p>
						</div>
						<span class="oak-chip flex shrink-0 items-center gap-1" :class="chip(o.status)">
							<span class="h-1.5 w-1.5 rounded-full bg-current"></span>{{ statusLabel(o.status) }}
						</span>
					</div>
					<p class="truncate text-xs text-gray-500">
						<span class="font-mono text-sm font-bold text-gray-900">{{ docNo(o) }}</span>
						<template v-for="m in meta(o)" :key="m"> · {{ m }}</template>
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
							<span class="min-w-0 flex-1">
								<span class="block truncate font-mono text-sm font-extrabold text-gray-900">{{ docNo(o) }}</span>
								<span class="block truncate text-xs">
									<span :class="o.principal ? 'font-semibold text-gray-700' : 'text-amber-600'">
										{{ o.principal || labels.svNoPrincipal }}
									</span>
									<span class="text-gray-500"><template v-for="m in meta(o)" :key="m"> · {{ m }}</template></span>
								</span>
								<span v-for="x in parties(o)" :key="x.k" class="block truncate text-xs">
									<span class="text-gray-400">{{ x.k }}</span> <span class="font-semibold text-gray-700">{{ x.v }}</span>
								</span>
							</span>
							<span class="oak-chip shrink-0" :class="chip(o.status)">{{ statusLabel(o.status) }}</span>
							<Icon name="chevron-right" :size="18" class="shrink-0 text-gray-300" />
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
import { computed, onBeforeUnmount, ref } from "vue"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"
import SkeletonList from "@/components/SkeletonList.vue"
import { cachedResource } from "@/data/cache"
import { fmtDate } from "@/utils/surveyStatus"

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

const search = ref("")
const status = ref("")
const day = ref("")
const principal = ref("")
const depot = ref("")
const activeOnly = ref(false)
const sort = ref("due")
// Chip mana yang barisnya sedang terbuka — satu saja, karena dua baris filter terbuka
// bersamaan mendorong daftarnya ke bawah lipatan di HP.
const panel = ref("")
const items = ref([])
const total = ref(0)
const counts = ref({})
const principals = ref([])
const depots = ref([])
const dayCounts = ref({})
const failed = ref(false)
const start = ref(0)

const dateOn = computed(() => Boolean(day.value))

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
const days = computed(() => {
	const out = []
	for (const o of items.value) {
		if (o.status === "Cancelled") continue
		const key = o.survey_date || ""
		let g = out[out.length - 1]
		if (!g || g.date !== key) {
			g = { date: key, label: dayLabel(key), hot: false, rows: [], running: [], rest: [] }
			out.push(g)
		}
		g.rows.push(o)
		;(o.status === "In Progress" ? g.running : g.rest).push(o)
		if (o.urgent || (key && daysFrom(key) <= 0 && o.status !== "Completed")) g.hot = true
	}
	return out
})

function daysFrom(iso) {
	const t = new Date()
	t.setHours(0, 0, 0, 0)
	return Math.round((new Date(`${iso}T00:00:00`) - t) / 86400000)
}
// "Hari ini · Rab, 23 Sep", "Kam, 2 Okt · 9 hari lagi".
function dayLabel(iso) {
	if (!iso) return "—"
	const name = new Date(`${iso}T00:00:00`).toLocaleDateString("id-ID", { weekday: "short", day: "numeric", month: "short" })
	const d = daysFrom(iso)
	if (d === 0) return `${labels.homeToday} · ${name}`
	if (d === 1) return `${labels.svTomorrow} · ${name}`
	return `${name} · ${d > 0 ? fill(labels.svDaysAhead, { n: d }) : fill(labels.svDaysAgo, { n: -d })}`
}

// Nomor yang dicocokkan dengan kertas: Reff Doc kalau ada, booking kalau belum.
const docNo = (o) => o.reff_doc || o.booking || o.name
const parties = (o) =>
	[
		{ k: labels.shipper, v: o.shipper },
		{ k: labels.svEmkl, v: o.emkl },
	].filter((x) => x.v)
const meta = (o) => [o.depot, fill(labels.svTankCount, { n: o.tank_count || 0 })].filter(Boolean)

function fill(tpl, vars) {
	return Object.entries(vars).reduce((s, [k, v]) => s.replace(`{${k}}`, v), tpl)
}
const listRes = cachedResource({
	url: "container_depot.ess.tank_survey.survey_order_list",
	method: "GET",
	makeParams: () => ({
		status: status.value || undefined,
		from_date: day.value || undefined,
		to_date: day.value || undefined,
		search: search.value || undefined,
		principal: principal.value || undefined,
		depot: depot.value || undefined,
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
		depots.value = data?.depots || []
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
	status.value = key
	reload()
}

const dayInput = ref(null)
function pickDay() {
	const el = dayInput.value
	try {
		el.showPicker()
	} catch {
		el.focus()
		el.click()
	}
}
function clearDay() {
	day.value = ""
	reload()
}

function setPrincipal(p) {
	principal.value = p
	panel.value = ""
	reload()
}
function setDepot(d) {
	depot.value = d
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
