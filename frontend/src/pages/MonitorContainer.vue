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
			<router-link to="/monitor/history" class="oak-btn oak-btn-secondary min-h-[44px] shrink-0 px-3">
				<Icon name="clock" :size="15" /> {{ labels.navHistory }}
			</router-link>
		</div>

		<ListSearch v-model="search" :placeholder="labels.monitorSearch" @search="reload(true)" />

		<!-- Empat pil: Semua + ketiga kelompok. Angkanya datang bersama daftarnya, jadi ia
		     selalu menghitung dunia yang sama dengan yang ada di bawah. -->
		<StatPills :pills="pills" :model-value="f.status" @update:model-value="setStatus" />

		<FilterBar
			:chips="activeChips"
			:sort-label="SORT_LABELS[f.sort] || labels.monitorSortActivity"
			:show-clear="!!search"
			@open="sheetOpen = true"
			@sort="cycleSort"
			@clear-one="clearOne"
			@clear-all="resetAll"
		/>

		<FilterSheet
			:open="sheetOpen"
			:value="f"
			:options="options"
			:fields="SHEET_FIELDS"
			:counts="facetCounts"
			:preview="facetsRes.data?.total ?? null"
			:preview-unit="labels.monitorTankWord"
			@close="sheetOpen = false"
			@apply="applyFilter"
			@draft="loadFacets"
		/>

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
		<SkeletonList v-if="tankRes.loading && !items.length" :action="false" />

		<!-- Gagal, dan tidak ada apa pun yang bisa ditampilkan -->
		<div v-else-if="failed && !items.length" class="oak-card flex flex-col items-center gap-2 p-8 text-center">
			<span class="oak-icon-tile h-12 w-12 bg-red-50 text-red-500"><Icon name="alert-circle" :size="24" /></span>
			<p class="text-sm font-bold text-gray-900">{{ labels.monitorErrorTitle }}</p>
			<p class="text-xs text-gray-500">
				{{ hasCache ? fill(labels.monitorErrorHint, { t: loadedClock }) : labels.monitorErrorHintNoCache }}
			</p>
			<div class="mt-1 flex gap-2">
				<button class="oak-btn oak-btn-primary min-h-[44px] px-4" @click="reload(true)">{{ labels.monitorRetry }}</button>
				<button v-if="hasCache" class="oak-btn oak-btn-secondary min-h-[44px] px-4" @click="showStale">
					{{ labels.monitorStale }}
				</button>
			</div>
		</div>

		<!-- Tidak ada yang cocok -->
		<div v-else-if="!items.length" class="oak-card flex flex-col items-center gap-2 p-8 text-center">
			<span class="oak-icon-tile h-12 w-12 bg-gray-100 text-gray-300"><Icon name="inbox" :size="24" /></span>
			<p class="text-sm font-bold text-gray-900">{{ labels.monitorEmptyTitle }}</p>
			<p class="text-xs text-gray-500">{{ labels.monitorEmptyHint }}</p>
			<button v-if="anyFilter" class="oak-btn oak-btn-secondary mt-1 min-h-[44px] px-4" @click="resetAll">
				{{ labels.monitorEmptyReset }}
			</button>
		</div>

		<!-- Daftar, dikelompokkan. Kepala kelompok menyebut jumlah SEBENARNYA di bawah filter
		     ini, bukan jumlah yang kebetulan sudah termuat — daftar ini bergulir tanpa batas
		     dan angka yang ikut bertambah sambil digulir tidak menjawab pertanyaan siapa pun. -->
		<div v-else class="space-y-4">
			<section v-for="g in groups" :key="g.key" class="space-y-2">
				<div class="flex items-center justify-between gap-2 px-1">
					<p class="flex min-w-0 items-center gap-1.5 truncate text-xs font-bold text-gray-600">
						<span class="h-2 w-2 shrink-0 rounded-full" :class="GROUP_DOT[g.key]"></span>
						{{ g.label }} · {{ g.total }}
					</p>
					<p v-if="g.first" class="shrink-0 truncate text-[11px] text-gray-400">{{ sortHint }}</p>
				</div>
				<ul class="oak-card divide-y divide-gray-100 overflow-hidden">
					<li v-for="c in g.rows" :key="c.name">
						<router-link
							:to="`/monitor/tank/${encodeURIComponent(c.name)}`"
							class="oak-press flex min-h-[64px] items-center gap-2 px-4 py-3"
						>
							<MonitorTankInfo :c="c" class="flex-1">
								<span class="oak-chip shrink-0" :class="tankChip(c).cls">{{ tankChip(c).label }}</span>
							</MonitorTankInfo>
						</router-link>
					</li>
				</ul>
			</section>

			<div ref="sentinel" class="h-px"></div>
			<button
				v-if="items.length < total"
				class="oak-btn oak-btn-secondary min-h-[48px] w-full"
				:disabled="tankRes.loading"
				@click="loadMore"
			>
				{{ tankRes.loading ? "…" : `${labels.storageLoadMore} (${items.length}/${total})` }}
			</button>
			<p class="text-center text-xs text-gray-400">{{ items.length }} / {{ total }} {{ labels.monitorTankWord }}</p>
		</div>

	</div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from "vue"
import { useRoute } from "vue-router"
import { cachedResource } from "@/data/cache"
import { labels, statusLabels } from "@/utils/labels"
import { userContext, branchLabel } from "@/data/context"
import { fill, useSavedFilters } from "@/utils/listKit"
import { tankChip } from "@/utils/monitorStatus"
import Icon from "@/components/Icon.vue"
import SkeletonList from "@/components/SkeletonList.vue"
import MonitorTankInfo from "@/components/MonitorTankInfo.vue"
import ListSearch from "@/components/list/ListSearch.vue"
import StatPills from "@/components/list/StatPills.vue"
import FilterBar from "@/components/list/FilterBar.vue"
import FilterSheet from "@/components/list/FilterSheet.vue"

const PAGE = 50
const route = useRoute()

// Saringan di sheet + pil status + urutan, disimpan per user di perangkat ini (listKit).
const SHEET_DEFAULTS = { depot: "", principal: "", period: "all", sort: "activity" }
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
const toChoices = (m) => Object.entries(m).map(([key, label]) => ({ key, label }))
const SHEET_FIELDS = [
	{ key: "depot", type: "chips", list: "depots", label: labels.monitorFilterDepot },
	{ key: "principal", type: "select", list: "principals", label: labels.monitorFilterPrincipal },
	{ key: "period", type: "scope", label: labels.monitorFilterPeriod, choices: toChoices(PERIOD_LABELS), empty: "all" },
	{ key: "sort", type: "scope", label: labels.monitorFilterSort, choices: toChoices(SORT_LABELS), empty: "activity" },
]

const f = useSavedFilters("monitor", { ...SHEET_DEFAULTS, status: "" })
const search = ref("")
const sheetOpen = ref(false)

// Angka di balik tiap pilihan sheet + total untuk tombol Terapkan, dihitung untuk DRAFT yang
// sedang disusun (tiap faset mengabaikan pilihannya sendiri — lihat ess.inventory.get_tank_facets).
const facetsRes = cachedResource({ url: "container_depot.ess.inventory.get_tank_facets", method: "GET" })
function loadFacets(draft) {
	facetsRes.submit({
		search: search.value || "",
		status: f.status || "",
		principal: draft.principal || "",
		depot: draft.depot || "",
		period: draft.period || "all",
	})
}
const facetCounts = computed(() => {
	const d = facetsRes.data
	if (!d) return {}
	return {
		depot: { "": d.all, ...Object.fromEntries((d.depots || []).map((r) => [r.code, r.count])) },
		principal: Object.fromEntries((d.principals || []).map((r) => [r.name, r.count])),
	}
})
watch(sheetOpen, (open) => open && loadFacets(f))

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

const scopeLine = computed(() => {
	const where = f.depot || branchLabel() || labels.monitorAllBranch
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
const options = computed(() => ({
	depots: (depotsRes.data?.depots || []).map((d) => d.code),
	principals: principals.value.map((p) => ({ value: p.name, label: p.label })),
}))

const tankRes = cachedResource({
	url: "container_depot.ess.inventory.get_tank_list",
	method: "GET",
	makeParams: () => ({
		search: search.value || "",
		status: f.status || "",
		principal: f.principal || "",
		depot: f.depot || "",
		period: f.period || "all",
		sort: f.sort || "activity",
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

// --- Pil, chip, kelompok ------------------------------------------------------------
// Kelompok memakai kalimat bucket yang paling mewakilinya, tapi kuncinya sendiri berbeda —
// "working" berisi draft, pending, DAN yang sedang dikerjakan (lihat GROUPS di inventory.py).
const GROUP_LABEL = {
	working: statusLabels.in_progress,
	available: statusLabels.available,
	gate_out: statusLabels.gate_out,
}
const GROUP_DOT = { working: "bg-blue-500", available: "bg-leaf-500", gate_out: "bg-gray-400" }

const pills = computed(() => [
	{ key: "", label: labels.monitorAll, count: allCount.value, tone: "text-gray-900" },
	{ key: "available", label: statusLabels.available, count: groupCounts.value.available, tone: "text-leaf-600" },
	{ key: "working", label: GROUP_LABEL.working, count: groupCounts.value.working, tone: "text-blue-600" },
	{ key: "gate_out", label: statusLabels.gate_out, count: groupCounts.value.gate_out, tone: "text-gray-500" },
])

const principalLabel = computed(
	() => principals.value.find((p) => p.name === f.principal)?.label || f.principal
)
// Urutan tidak jadi chip: sudah tertulis di tombol urut FilterBar.
const activeChips = computed(() =>
	[
		f.depot && { key: "depot", label: labels.monitorFilterDepot, value: f.depot },
		f.principal && { key: "principal", label: labels.monitorChipPrincipal, value: principalLabel.value },
		f.period !== "all" && { key: "period", label: labels.monitorFilterPeriod, value: PERIOD_LABELS[f.period] || f.period },
	].filter(Boolean)
)

const sortHint = computed(
	() =>
		({
			activity: labels.monitorSortHintActivity,
			number: labels.monitorSortHintNumber,
			idle: labels.monitorSortHintIdle,
		})[f.sort] || ""
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
	() => Boolean(search.value) || Boolean(f.status) || Boolean(f.depot) || Boolean(f.principal) || f.period !== "all"
)

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
	f.status = key
	reload(true)
}
function applyFilter(d) {
	Object.assign(f, d)
	reload(true)
}
function clearOne(key) {
	f[key] = SHEET_DEFAULTS[key]
	reload(true)
}
function cycleSort() {
	const keys = Object.keys(SORT_LABELS)
	f.sort = keys[(keys.indexOf(f.sort) + 1) % keys.length]
	reload(true)
}
function resetAll() {
	search.value = ""
	Object.assign(f, SHEET_DEFAULTS, { status: "" })
	reload(true)
}

let observer = null
onMounted(() => {
	if (!userContext.data) userContext.reload()
	// Deep-link bucket dari KPI dashboard (?status=<bucket>) — bucket lama maupun kelompok baru.
	const q = route.query.status
	if (typeof q === "string" && q) f.status = q
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
onBeforeUnmount(() => observer?.disconnect())
</script>
