<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<!-- Judul + berapa tank yang sedang dilihat. Cakupannya disebut lebih dulu ("Semua
		     branch") karena angka di sebelahnya tidak berarti apa-apa tanpa tahu ia menghitung
		     depo yang mana. -->
		<div class="flex items-start justify-between gap-3">
			<div class="min-w-0">
				<h1 class="text-xl font-extrabold tracking-tight text-gray-900">{{ labels.monitorTitle }}</h1>
				<p class="mt-0.5 truncate text-xs text-gray-500">
					{{ scopeLine }}
				</p>
			</div>
			<router-link to="/monitor/history" class="oak-btn oak-btn-secondary shrink-0 px-3 py-2">
				<Icon name="clock" :size="15" /> {{ labels.navHistory }}
			</router-link>
		</div>

		<!-- Cari -->
		<div class="relative">
			<Icon name="search" :size="18" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
			<input
				v-model="search"
				type="search"
				:placeholder="labels.monitorSearch"
				class="oak-input pl-10 pr-10 uppercase"
				@input="onSearchInput"
			/>
			<button
				v-if="search"
				class="oak-press absolute right-2 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full text-gray-400"
				:aria-label="labels.monitorFilterReset"
				@click="clearSearch"
			>
				<Icon name="x" :size="16" />
			</button>
		</div>

		<!-- Empat pil: Semua + ketiga kelompok. Angkanya datang bersama daftarnya, jadi ia
		     selalu menghitung dunia yang sama dengan yang ada di bawah. -->
		<div class="grid grid-cols-4 gap-1.5">
			<button
				v-for="p in pills"
				:key="p.key"
				class="oak-press flex min-h-[62px] flex-col items-center justify-center rounded-xl border px-1 py-2 transition"
				:class="statusFilter === p.key ? 'border-brand-500 bg-brand-500/10' : 'border-gray-200 bg-paper'"
				@click="setStatus(p.key)"
			>
				<span class="text-lg font-extrabold leading-none" :class="statusFilter === p.key ? 'text-brand-700' : p.tone">
					{{ p.count }}
				</span>
				<span class="mt-1 truncate text-[11px] font-semibold text-gray-500">{{ p.label }}</span>
			</button>
		</div>

		<!-- Chip filter. Semuanya membuka sheet yang sama: di HP, empat kontrol terpisah di
		     baris ini berarti empat target sentuh sempit yang saling bersebelahan. -->
		<div class="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1">
			<button
				v-for="c in chips"
				:key="c.key"
				class="oak-press flex min-h-[40px] shrink-0 items-center gap-1.5 rounded-full border px-3 text-xs font-bold transition"
				:class="c.on ? 'border-brand-500 bg-brand-500/10 text-brand-700' : 'border-gray-200 bg-paper text-gray-600'"
				@click="sheetOpen = true"
			>
				<Icon v-if="c.icon" :name="c.icon" :size="13" />
				{{ c.label }}
				<span
					v-if="c.badge"
					class="rounded-full px-1.5 py-0.5 text-[10px] font-extrabold"
					:class="c.on ? 'bg-brand-500/20 text-brand-700' : 'bg-gray-100 text-gray-500'"
					>{{ c.badge }}</span
				>
			</button>
		</div>

		<!-- Spanduk data lama: muncul HANYA setelah pemuatan gagal dan yang tampil di bawah
		     berasal dari cache. Tanpa ini daftar basi terlihat persis seperti daftar segar. -->
		<div
			v-if="showingStale"
			class="flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-800"
		>
			<Icon name="wifi-off" :size="14" class="shrink-0" />
			{{ fill(labels.monitorStaleBanner, { t: loadedClock }) }}
		</div>

		<!-- Memuat pertama kali -->
		<ul v-if="tankRes.loading && !items.length" class="oak-card divide-y divide-gray-100 overflow-hidden">
			<li v-for="n in 6" :key="n" class="flex items-center gap-3 px-4 py-3.5">
				<div class="oak-skeleton h-10 w-10 rounded-xl"></div>
				<div class="flex-1 space-y-2">
					<div class="oak-skeleton h-3.5 w-1/2"></div>
					<div class="oak-skeleton h-3 w-3/4"></div>
				</div>
			</li>
		</ul>

		<!-- Gagal, dan tidak ada apa pun yang bisa ditampilkan -->
		<div v-else-if="failed && !items.length" class="oak-card flex flex-col items-center gap-2 p-8 text-center">
			<span class="oak-icon-tile h-12 w-12 bg-red-50 text-red-500"><Icon name="alert-circle" :size="24" /></span>
			<p class="text-sm font-bold text-gray-900">{{ labels.monitorErrorTitle }}</p>
			<p class="text-xs text-gray-500">
				{{ hasCache ? fill(labels.monitorErrorHint, { t: loadedClock }) : labels.monitorErrorHintNoCache }}
			</p>
			<div class="mt-1 flex gap-2">
				<button class="oak-btn oak-btn-primary px-4 py-2" @click="reload(true)">{{ labels.monitorRetry }}</button>
				<button v-if="hasCache" class="oak-btn oak-btn-secondary px-4 py-2" @click="showStale">
					{{ labels.monitorStale }}
				</button>
			</div>
		</div>

		<!-- Tidak ada yang cocok -->
		<div v-else-if="!items.length" class="oak-card flex flex-col items-center gap-2 p-8 text-center">
			<span class="oak-icon-tile h-12 w-12 bg-gray-100 text-gray-300"><Icon name="inbox" :size="24" /></span>
			<p class="text-sm font-bold text-gray-900">{{ labels.monitorEmptyTitle }}</p>
			<p class="text-xs text-gray-500">{{ labels.monitorEmptyHint }}</p>
			<button v-if="anyFilter" class="oak-btn oak-btn-secondary mt-1 px-4 py-2" @click="resetAll">
				{{ labels.monitorEmptyReset }}
			</button>
		</div>

		<!-- Daftar, dikelompokkan. Kepala kelompok menyebut jumlah SEBENARNYA di bawah filter
		     ini, bukan jumlah yang kebetulan sudah termuat — daftar ini bergulir tanpa batas
		     dan angka yang ikut bertambah sambil digulir tidak menjawab pertanyaan siapa pun. -->
		<div v-else class="space-y-3">
			<section v-for="g in groups" :key="g.key" class="space-y-1.5">
				<div class="flex items-baseline justify-between gap-2 px-1">
					<p class="text-xs font-bold text-gray-500">{{ g.label }} · {{ g.total }}</p>
					<p v-if="g.first" class="truncate text-[11px] text-gray-400">{{ sortHint }}</p>
				</div>
				<ul class="oak-card divide-y divide-gray-100 overflow-hidden">
					<li v-for="c in g.rows" :key="c.name">
						<!-- Selalu <div>, tidak pernah <button>: tombol native tidak bisa
						     diandalkan sebagai flex container di sebagian webview. -->
						<div
							class="flex cursor-pointer items-start gap-3 px-4 py-3 transition active:bg-gray-50"
							role="button"
							tabindex="0"
							@click="openTank(c)"
							@keydown.enter="openTank(c)"
							@keydown.space.prevent="openTank(c)"
						>
							<span class="oak-icon-tile mt-0.5 h-10 w-10 shrink-0" :class="tileTone(c)">
								<Icon name="package" :size="17" />
							</span>
							<div class="min-w-0 flex-1">
								<div class="flex items-start justify-between gap-2">
									<p class="min-w-0 truncate font-mono text-sm font-extrabold text-gray-900">
										<template v-if="c.container_no">
											<span v-for="(part, i) in mark(c.container_no)" :key="i" :class="part.hit ? 'rounded bg-brand-500/25 px-0.5 text-brand-700' : ''">{{ part.text }}</span>
										</template>
										<span v-else class="text-gray-400">{{ labels.monitorNoNumber }}</span>
									</p>
									<span class="oak-chip shrink-0" :class="badge(c).tone">{{ badge(c).label }}</span>
								</div>
								<p class="mt-0.5 truncate text-xs text-gray-500">{{ subline(c) }}</p>
								<div v-if="c.order || c.order_bongkar" class="mt-1 flex flex-wrap items-center gap-1">
									<span
										v-if="c.order"
										class="inline-flex items-center gap-1 rounded-md bg-blue-50 px-1.5 py-0.5 text-[11px] font-bold text-blue-700"
									>
										<Icon :name="orderIcon(c.order.kind)" :size="11" />
										{{ c.order.kind }} · <span class="font-mono font-semibold">{{ c.order.name }}</span>
									</span>
									<span
										v-if="c.order_bongkar"
										class="rounded-md bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-gray-600"
										>{{ c.order_bongkar }}</span
									>
								</div>
								<p v-if="c.last_activity" class="mt-1 truncate text-[11px] text-gray-400">
									{{ activityLine(c.last_activity) }}
								</p>
							</div>
							<Icon name="chevron-right" :size="16" class="mt-3 shrink-0 text-gray-300" />
						</div>
					</li>
				</ul>
			</section>

			<div ref="sentinel" class="h-px"></div>
			<button
				v-if="items.length < total"
				class="oak-btn oak-btn-secondary w-full"
				:disabled="tankRes.loading"
				@click="loadMore"
			>
				{{ tankRes.loading ? "…" : `${labels.storageLoadMore} (${items.length}/${total})` }}
			</button>
			<p class="text-center text-xs text-gray-400">{{ items.length }} / {{ total }} {{ labels.monitorTankWord }}</p>
		</div>

		<MonitorFilterSheet
			:open="sheetOpen"
			:value="filter"
			:depots="depots"
			:principals="principals"
			:facets="facets"
			:loading="facetRes.loading"
			@close="sheetOpen = false"
			@draft="onDraft"
			@apply="applyFilter"
		/>
	</div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, reactive, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { cachedResource } from "@/data/cache"
import { labels, statusLabels } from "@/utils/labels"
import { since } from "@/utils/surveyStatus"
import { userContext, branchLabel } from "@/data/context"
import { STEP_COUNT, hasStep, getStep } from "@/utils/eirBatch"
import Icon from "@/components/Icon.vue"
import MonitorFilterSheet from "@/components/MonitorFilterSheet.vue"

const PAGE = 50
const route = useRoute()
const router = useRouter()

const search = ref("")
const statusFilter = ref("") // "" = Semua
const filter = reactive({ depot: "", principal: "", period: "all", sort: "activity" })
const sheetOpen = ref(false)

const loaded = ref([])
const items = computed(() => loaded.value)
const total = ref(0)
const allCount = ref(0)
const groupCounts = ref({ working: 0, available: 0, gate_out: 0 })
const start = ref(0)
const sentinel = ref(null)
const failed = ref(false)
const showingStale = ref(false)
const loadedAt = ref(null)

function fill(tpl, vars) {
	return Object.entries(vars).reduce((s, [k, v]) => s.replace(`{${k}}`, v), tpl)
}

const scopeLine = computed(() => {
	const where = filter.depot || branchLabel() || labels.monitorAllBranch
	return `${where} · ${allCount.value} ${labels.monitorTankWord}`
})

const principalsRes = cachedResource({
	url: "container_depot.ess.inventory.list_container_principals",
	method: "GET",
	auto: true,
})
const principals = computed(() => principalsRes.data?.principals || [])

const depotsRes = cachedResource({
	url: "container_depot.ess.inventory.list_user_depots",
	method: "GET",
	auto: true,
})
const depots = computed(() => depotsRes.data?.depots || [])

const tankRes = cachedResource({
	url: "container_depot.ess.inventory.get_tank_list",
	method: "GET",
	makeParams: () => ({
		search: search.value || "",
		status: statusFilter.value || "",
		principal: filter.principal || "",
		depot: filter.depot || "",
		period: filter.period || "all",
		sort: filter.sort || "activity",
		start: start.value,
		page_length: PAGE,
	}),
	onSuccess(data) {
		failed.value = false
		showingStale.value = false
		loadedAt.value = new Date()
		take(data)
	},
	onError() {
		// Halaman ini boleh dibuka di yard tanpa sinyal. Kegagalan tidak mengosongkan apa yang
		// sudah terlihat — ia hanya menawarkan data lama secara terbuka (lihat spanduk di atas).
		failed.value = true
	},
})

function take(data) {
	loaded.value = start.value === 0 ? data.items || [] : loaded.value.concat(data.items || [])
	total.value = data.total || 0
	allCount.value = data.all ?? data.total ?? 0
	groupCounts.value = data.groups || { working: 0, available: 0, gate_out: 0 }
	start.value += (data.items || []).length
}

const hasCache = computed(() => Boolean(tankRes.data?.items?.length))
const loadedClock = computed(() => {
	const d = loadedAt.value
	if (!d) return "—"
	return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`
})
function showStale() {
	if (!tankRes.data) return
	start.value = 0
	take(tankRes.data)
	showingStale.value = true
}

// --- Faset untuk sheet filter -------------------------------------------------------
// Draft-nya sendiri, bukan `filter`: sheet menghitung "kalau ini yang dipilih", dan halaman
// di belakangnya belum berubah sampai Terapkan ditekan.
const draft = ref({ ...filter })
const facetRes = cachedResource({
	url: "container_depot.ess.inventory.get_tank_facets",
	method: "GET",
	makeParams: () => ({
		search: search.value || "",
		status: statusFilter.value || "",
		principal: draft.value.principal || "",
		depot: draft.value.depot || "",
		period: draft.value.period || "all",
	}),
})
const facets = computed(() => facetRes.data || null)

let facetTimer = null
function onDraft(d) {
	draft.value = d
	// Di-debounce: mengetuk empat chip berturut-turut tidak perlu empat perjalanan ke server.
	clearTimeout(facetTimer)
	facetTimer = setTimeout(() => facetRes.reload(), 200)
}
watch(sheetOpen, (v) => {
	if (!v) return
	draft.value = { ...filter }
	facetRes.reload()
})

// --- Pil, chip, kelompok ------------------------------------------------------------
// Kelompok memakai kalimat bucket yang paling mewakilinya, tapi kuncinya sendiri berbeda —
// "working" berisi draft, pending, DAN yang sedang dikerjakan (lihat GROUPS di inventory.py).
const GROUP_LABEL = {
	working: statusLabels.in_progress,
	available: statusLabels.available,
	gate_out: statusLabels.gate_out,
}

const pills = computed(() => [
	{ key: "", label: labels.monitorAll, count: allCount.value, tone: "text-gray-900" },
	{ key: "available", label: statusLabels.available, count: groupCounts.value.available, tone: "text-leaf-600" },
	{ key: "working", label: GROUP_LABEL.working, count: groupCounts.value.working, tone: "text-blue-600" },
	{ key: "gate_out", label: statusLabels.gate_out, count: groupCounts.value.gate_out, tone: "text-gray-500" },
])

const PERIOD_LABELS = {
	today: labels.monitorPeriodToday,
	"7d": labels.monitorPeriod7,
	all: labels.monitorPeriodAll,
}
const SORT_LABELS = {
	activity: labels.monitorSortActivity,
	number: labels.monitorSortNumber,
	idle: labels.monitorSortIdle,
}
const chips = computed(() => [
	{
		key: "depot",
		icon: "map-pin",
		label: filter.depot || labels.monitorChipDepot,
		on: Boolean(filter.depot),
		badge: filter.depot ? null : depots.value.length || null,
	},
	{
		key: "principal",
		icon: "briefcase",
		label: principalLabel.value || labels.monitorChipPrincipal,
		on: Boolean(filter.principal),
	},
	{
		key: "period",
		icon: "calendar",
		label: PERIOD_LABELS[filter.period] || labels.monitorPeriodAll,
		on: filter.period !== "all",
	},
	{
		key: "sort",
		icon: "sliders",
		label: `${labels.monitorChipSort}: ${SORT_LABELS[filter.sort] || ""}`,
		on: filter.sort !== "activity",
	},
])
const principalLabel = computed(
	() => principals.value.find((p) => p.name === filter.principal)?.label || filter.principal
)

const sortHint = computed(
	() =>
		({
			activity: labels.monitorSortHintActivity,
			number: labels.monitorSortHintNumber,
			idle: labels.monitorSortHintIdle,
		})[filter.sort] || ""
)

// Urutan kelompok tetap: yang sedang dikerjakan lebih dulu, yang sudah keluar terakhir.
// Bukan urutan abjad dan bukan urutan jumlah — ini urutan perhatian.
const GROUP_ORDER = ["working", "available", "gate_out"]
const groups = computed(() => {
	const out = []
	for (const key of GROUP_ORDER) {
		const rows = items.value.filter((c) => c.group === key)
		if (!rows.length) continue
		out.push({
			key,
			label: GROUP_LABEL[key],
			total: groupCounts.value[key] ?? rows.length,
			rows,
			first: out.length === 0,
		})
	}
	return out
})

const anyFilter = computed(
	() =>
		Boolean(search.value) ||
		Boolean(statusFilter.value) ||
		Boolean(filter.depot) ||
		Boolean(filter.principal) ||
		filter.period !== "all"
)

// --- Isi baris ----------------------------------------------------------------------
const TILE_TONE = {
	working: "bg-blue-50 text-blue-600",
	available: "bg-leaf-50 text-leaf-600",
	gate_out: "bg-gray-100 text-gray-500",
}
function tileTone(c) {
	return TILE_TONE[c.group] || "bg-gray-100 text-gray-500"
}

const BADGE_TONE = {
	available: "bg-leaf-100 text-leaf-800",
	draft: "bg-gray-100 text-gray-700",
	pending: "bg-amber-100 text-amber-800",
	in_progress: "bg-blue-100 text-blue-800",
	gate_out: "bg-gray-200 text-gray-700",
}
function badge(c) {
	// EIR yang sedang dikerjakan diberi kalimatnya sendiri: "Draft" saja akan dibaca sebagai
	// M&R draft, dan kedua pekerjaan itu dipegang orang yang berbeda.
	if (c.order?.kind === "EIR") {
		const step = hasStep(c.order.name) ? ` ${getStep(c.order.name) + 1}/${STEP_COUNT}` : ""
		return { label: `${labels.monitorDraftEir}${step}`, tone: "bg-brand-100 text-brand-700" }
	}
	return { label: statusLabels[c.status] || c.status, tone: BADGE_TONE[c.status] || "bg-gray-100 text-gray-600" }
}

function orderIcon(kind) {
	return { "M&R": "tool", Cleaning: "droplet", EIR: "clipboard" }[kind] || "file-text"
}

function subline(c) {
	return [c.principal, c.container_type, c.depot, c.location].filter(Boolean).join(" · ")
}

function activityLine(a) {
	return [a.summary || a.type, since(a.time), a.by].filter(Boolean).join(" · ")
}

// Potong nomor container pada bagian yang cocok dengan pencarian, supaya mata langsung
// menemukan kenapa baris ini muncul — pada layar hasil cari itulah satu-satunya pertanyaan.
function mark(text) {
	const q = search.value.trim().toUpperCase()
	const s = String(text)
	if (!q) return [{ text: s, hit: false }]
	const i = s.toUpperCase().indexOf(q)
	if (i < 0) return [{ text: s, hit: false }]
	return [
		{ text: s.slice(0, i), hit: false },
		{ text: s.slice(i, i + q.length), hit: true },
		{ text: s.slice(i + q.length), hit: false },
	].filter((p) => p.text)
}

// --- Aksi ----------------------------------------------------------------------------
function reload(reset) {
	if (reset) {
		start.value = 0
		loaded.value = []
	}
	tankRes.reload()
}
function loadMore() {
	if (tankRes.loading || loaded.value.length >= total.value) return
	tankRes.reload()
}
function setStatus(key) {
	statusFilter.value = statusFilter.value === key ? "" : key
	reload(true)
}
function applyFilter(d) {
	Object.assign(filter, d)
	reload(true)
}
function resetAll() {
	search.value = ""
	statusFilter.value = ""
	Object.assign(filter, { depot: "", principal: "", period: "all", sort: "activity" })
	reload(true)
}
let searchTimer = null
function onSearchInput() {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(() => reload(true), 300)
}
function clearSearch() {
	search.value = ""
	reload(true)
}
function openTank(c) {
	router.push({ path: `/monitor/tank/${encodeURIComponent(c.name)}` })
}

let observer = null
onMounted(() => {
	if (!userContext.data) userContext.reload()
	// Deep-link bucket dari KPI dashboard (?status=<bucket>) — bucket lama maupun kelompok baru.
	const q = route.query.status
	if (typeof q === "string" && q) statusFilter.value = q
	reload(true)

	observer = new IntersectionObserver(
		(entries) => {
			if (entries.some((e) => e.isIntersecting)) loadMore()
		},
		{ rootMargin: "300px" }
	)
	if (sentinel.value) observer.observe(sentinel.value)
})
watch(sentinel, (el, old) => {
	if (!observer) return
	if (old) observer.unobserve(old)
	if (el) observer.observe(el)
})
onBeforeUnmount(() => {
	observer?.disconnect()
	clearTimeout(searchTimer)
	clearTimeout(facetTimer)
})
</script>
