<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<!-- Header -->
		<div class="flex items-center gap-2">
			<span class="oak-icon-tile h-9 w-9 bg-leaf-50 text-leaf-600"><Icon name="layers" :size="20" /></span>
			<div>
				<h1 class="text-lg font-extrabold leading-tight tracking-tight">{{ labels.storageTitle }}</h1>
				<p class="text-xs text-gray-500">{{ labels.storageDesc }}</p>
			</div>
		</div>

		<!-- Place an isotank -->
		<section class="oak-section space-y-3">
			<p class="oak-section-title">{{ labels.storagePlaceTitle }}</p>
			<p class="text-xs text-gray-500">{{ labels.storagePlaceHint }}</p>
			<div class="flex gap-2">
				<input
					v-model.trim="containerNo"
					type="text"
					autocapitalize="characters"
					:placeholder="labels.storageContainerPlaceholder"
					class="oak-input uppercase"
					@keyup.enter="doRecommend"
				/>
				<button
					class="oak-btn oak-btn-primary shrink-0 px-4"
					:disabled="!containerNo || recommendRes.loading"
					@click="doRecommend"
				>
					<Icon v-if="!recommendRes.loading" name="search" :size="16" />
					{{ recommendRes.loading ? "…" : labels.storageCheck }}
				</button>
			</div>
			<p v-if="recommendError" class="flex items-center gap-1.5 text-sm text-red-600">
				<Icon name="alert-circle" :size="15" /> {{ recommendError }}
			</p>

			<!-- Recommendation -->
			<div v-if="rec" class="space-y-3 border-t border-gray-100 pt-3">
				<div class="flex flex-wrap items-center gap-2 text-xs">
					<span class="oak-chip bg-gray-100 text-gray-700">
						{{ labels.storageStatus }}: <span class="font-semibold">{{ prettyStatus(rec.status) }}</span>
					</span>
					<span v-if="rec.condition" class="oak-chip bg-gray-100 text-gray-700">
						{{ labels.storageCondition }}: <span class="font-semibold">{{ rec.condition }}</span>
					</span>
					<span v-if="rec.target_category" class="oak-chip bg-leaf-100 text-leaf-800">
						{{ labels.storageTargetCategory }}: <span class="font-semibold">{{ categoryLabel(rec.target_category) }}</span>
					</span>
				</div>

				<!-- Recommended zones (target category; scope = own depot then same branch) -->
				<template v-if="rec.zones && rec.zones.length">
					<p class="oak-label">{{ labels.storageSelectZone }}</p>
					<div class="space-y-2">
						<button
							v-for="z in rec.zones"
							:key="z.zone_code"
							class="flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition"
							:class="selectedZone === z.zone_code
								? 'border-brand-500 bg-brand-50 ring-1 ring-brand-500'
								: 'border-gray-200 bg-white hover:border-gray-300'"
							:disabled="z.is_full"
							@click="selectZone(z)"
						>
							<span class="oak-icon-tile h-8 w-8 shrink-0 bg-leaf-50 text-leaf-600"><Icon name="grid" :size="16" /></span>
							<div class="min-w-0 flex-1">
								<p class="truncate text-sm font-semibold text-gray-900">{{ z.zone_name }}</p>
								<p class="text-xs" :class="z.is_full ? 'text-red-600' : 'text-gray-500'">
									{{ z.occupied }}/{{ z.capacity || "∞" }}
									<span v-if="z.is_full"> · {{ labels.storageFull }}</span>
									<span v-else-if="z.free != null"> · {{ z.free }} {{ labels.storageSlotsFree }}</span>
									<span v-if="!z.same_depot" class="text-gray-400"> · {{ z.depot }}</span>
								</p>
							</div>
							<span v-if="z.recommended" class="oak-chip shrink-0 bg-leaf-100 text-leaf-800">
								<Icon name="star" :size="12" /> {{ labels.storageRecommended }}
							</span>
						</button>
					</div>
				</template>
				<p v-else class="flex items-center gap-1.5 text-sm text-amber-600">
					<Icon name="alert-triangle" :size="15" /> {{ labels.storageNoRecommend }}
				</p>

				<!-- Manual picker: every active zone in scope (own depot + same branch) -->
				<div v-if="rec.all_zones && rec.all_zones.length" class="space-y-2">
					<button class="oak-link inline-flex items-center gap-1 text-sm" @click="manualOpen = !manualOpen">
						<Icon :name="manualPickerOpen ? 'chevron-up' : 'chevron-down'" :size="14" />
						{{ labels.storageManualPick }}
					</button>
					<div v-if="manualPickerOpen" class="space-y-3">
						<div v-for="g in manualGroups" :key="g.category" class="space-y-1.5">
							<p class="px-1 text-xs font-semibold uppercase tracking-wide text-gray-400">{{ categoryLabel(g.category) }}</p>
							<button
								v-for="z in g.zones"
								:key="z.zone_code"
								class="flex w-full items-center gap-3 rounded-xl border px-3 py-2 text-left transition"
								:class="selectedZone === z.zone_code
									? 'border-brand-500 bg-brand-50 ring-1 ring-brand-500'
									: 'border-gray-200 bg-white hover:border-gray-300'"
								:disabled="z.is_full"
								@click="selectZone(z)"
							>
								<div class="min-w-0 flex-1">
									<p class="truncate text-sm font-semibold text-gray-900">{{ z.zone_name }}</p>
									<p class="text-xs" :class="z.is_full ? 'text-red-600' : 'text-gray-500'">
										{{ z.occupied }}/{{ z.capacity || "∞" }}
										<span v-if="z.is_full"> · {{ labels.storageFull }}</span>
										<span v-if="!z.same_depot" class="text-gray-400"> · {{ z.depot }}</span>
									</p>
								</div>
								<Icon v-if="selectedZone === z.zone_code" name="check" :size="16" class="shrink-0 text-brand-600" />
							</button>
						</div>
					</div>
				</div>

				<!-- Placement coordinates + confirm (works for ANY selected zone) -->
				<div v-if="selectedZone" class="space-y-2 border-t border-gray-100 pt-3">
					<p class="text-xs text-gray-500">
						{{ labels.storagePlace }} →
						<span class="font-semibold text-gray-800">{{ selectedZoneName }}</span>
					</p>
					<div class="grid grid-cols-3 gap-2">
						<div>
							<label class="oak-label">{{ labels.storageRow }}</label>
							<input v-model.trim="form.row" type="text" inputmode="numeric" class="oak-input" />
						</div>
						<div>
							<label class="oak-label">{{ labels.storageTier }}</label>
							<input v-model.number="form.tier" type="number" min="1" class="oak-input" />
						</div>
						<div>
							<label class="oak-label">{{ labels.storageBay }}</label>
							<input v-model.trim="form.bay" type="text" class="oak-input" />
						</div>
					</div>
					<button
						class="oak-btn oak-btn-primary w-full"
						:disabled="placeRes.loading"
						@click="doPlace"
					>
						<Icon v-if="!placeRes.loading" name="check" :size="18" />
						{{ placeRes.loading ? "…" : labels.storagePlace }}
					</button>
					<p v-if="placeError" class="flex items-center gap-1.5 text-sm text-red-600">
						<Icon name="alert-circle" :size="15" /> {{ placeError }}
					</p>
				</div>

				<div
					v-if="placed"
					class="flex items-center gap-2 rounded-xl border border-leaf-200 bg-leaf-50 px-3 py-2.5 text-sm font-semibold text-leaf-800"
				>
					<Icon name="check-circle" :size="18" /> {{ labels.storagePlaced }}: {{ placed.zone_name }}
				</div>
			</div>
		</section>

		<!-- Zone occupancy overview -->
		<section class="space-y-2">
			<div class="flex items-center justify-between gap-2">
				<p class="oak-section-title">{{ labels.storageOccupancy }}</p>
				<div v-if="depots.length > 1" class="flex rounded-lg bg-gray-100 p-0.5">
					<button
						v-for="d in depots"
						:key="d.code"
						class="rounded-md px-3 py-1 text-xs font-semibold transition"
						:class="activeDepot === d.code ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500'"
						@click="activeDepot = d.code"
					>
						{{ d.name }}
					</button>
				</div>
			</div>

			<p v-if="overviewRes.loading" class="oak-card p-6 text-center text-sm text-gray-400">{{ labels.loading }}</p>
			<p v-else-if="overviewRes.error" class="oak-card p-6 text-center text-sm text-red-500">{{ labels.error }}</p>
			<p v-else-if="!groupedZones.length" class="oak-card p-6 text-center text-sm text-gray-400">{{ labels.storageNoZones }}</p>
			<template v-else>
				<div v-for="g in groupedZones" :key="g.block || 'none'" class="space-y-2">
					<p v-if="g.block" class="px-1 text-xs font-semibold uppercase tracking-wide text-gray-400">{{ g.block }}</p>
					<div class="grid gap-2 sm:grid-cols-2">
						<button
							v-for="z in g.zones"
							:key="z.zone_code"
							class="oak-card oak-press space-y-2 p-3 text-left"
							@click="openZone(z)"
						>
							<div class="flex items-start justify-between gap-2">
								<p class="text-sm font-bold text-gray-900">{{ z.zone_name }}</p>
								<span class="oak-chip shrink-0 bg-gray-100 text-gray-600">{{ categoryLabel(z.category) }}</span>
							</div>
							<div class="h-2 w-full overflow-hidden rounded-full bg-gray-100">
								<div class="h-full rounded-full transition-all" :class="barClass(z)" :style="{ width: barWidth(z) }"></div>
							</div>
							<p class="text-xs font-medium" :class="z.is_full ? 'text-red-600' : 'text-gray-500'">
								{{ z.occupied }}/{{ z.capacity || "∞" }}
								<span v-if="z.utilization != null"> · {{ z.utilization }}%</span>
								<span v-if="z.is_full"> · {{ labels.storageFull }}</span>
							</p>
						</button>
					</div>
				</div>
			</template>
		</section>

		<!-- SOP guide (collapsible) -->
		<section class="oak-card overflow-hidden">
			<button class="flex w-full items-center justify-between px-4 py-3" @click="sopOpen = !sopOpen">
				<span class="flex items-center gap-2 font-semibold text-gray-800">
					<Icon name="book-open" :size="18" /> {{ labels.storageSop }}
				</span>
				<Icon :name="sopOpen ? 'chevron-up' : 'chevron-down'" :size="18" class="text-gray-400" />
			</button>
			<ul v-if="sopOpen" class="space-y-2 border-t border-gray-100 px-4 py-3 text-sm text-gray-600">
				<li v-for="(r, i) in sopRules" :key="i" class="flex gap-2">
					<Icon name="check" :size="15" class="mt-0.5 shrink-0 text-leaf-600" /><span>{{ r }}</span>
				</li>
			</ul>
		</section>

		<!-- Zone tank list (bottom sheet) -->
		<div
			v-if="zoneModal"
			class="fixed inset-0 z-50 flex items-end justify-center bg-black/40 md:items-center md:p-4"
			@click.self="zoneModal = null"
		>
			<div class="flex max-h-[85vh] w-full max-w-lg flex-col overflow-hidden rounded-t-2xl bg-white shadow-soft animate-slide-up md:rounded-2xl">
				<div class="flex items-center justify-between border-b border-gray-100 px-4 py-3">
					<div class="min-w-0">
						<p class="truncate font-bold text-gray-900">{{ zoneModal.zone_name }}</p>
						<p class="text-xs text-gray-500">{{ labels.storageZoneTanks }} · {{ zoneModal.occupied }}/{{ zoneModal.capacity || "∞" }}</p>
					</div>
					<button class="rounded-lg p-1.5 text-gray-400 transition hover:bg-gray-100" @click="zoneModal = null">
						<Icon name="x" :size="18" />
					</button>
				</div>
				<div class="flex-1 overflow-y-auto px-4 py-3">
					<p v-if="zoneTanksRes.loading" class="py-6 text-center text-sm text-gray-400">{{ labels.loading }}</p>
					<p v-else-if="!zoneTanks.length" class="py-6 text-center text-sm text-gray-400">{{ labels.storageNoTanks }}</p>
					<ul v-else class="divide-y divide-gray-100">
						<li v-for="t in zoneTanks" :key="t.name" class="flex items-center gap-3 py-2.5">
							<span class="oak-icon-tile h-8 w-8 shrink-0 bg-gray-100 text-gray-400"><Icon name="package" :size="16" /></span>
							<div class="min-w-0 flex-1">
								<p class="truncate font-semibold text-gray-900">{{ t.container_no }}</p>
								<p v-if="t.principal" class="truncate text-xs text-gray-500">{{ t.principal }}</p>
							</div>
							<span class="oak-chip shrink-0" :class="statusColors[t.status]">{{ statusLabel(t.status) }}</span>
						</li>
					</ul>
				</div>
			</div>
		</div>
	</div>
</template>

<script setup>
import { computed, ref } from "vue"
import { createResource } from "frappe-ui"
import {
	labels,
	categoryLabel,
	storageSopRules as sopRules,
	statusLabel,
	statusColors,
} from "@/utils/labels"
import Icon from "@/components/Icon.vue"

const BLOCK_ORDER = ["Blok Kiri", "Blok Kanan", ""]
const CATEGORY_ORDER = [
	"Empty Dirty Queue", "Cleaning Bay", "Ready", "Empty Clean", "Workshop", "Survey", "Gate",
]

const containerNo = ref("")
const rec = ref(null)
const selectedZone = ref(null)
const form = ref({ row: "", tier: null, bay: "" })
const placed = ref(null)
const activeDepot = ref(null)
const sopOpen = ref(false)
const manualOpen = ref(false)
const zoneModal = ref(null)

// --- Resources ---
const overviewRes = createResource({
	url: "container_depot.ess.yard.yard_overview",
	method: "GET",
	auto: true,
	onSuccess(data) {
		if (!activeDepot.value && data?.depots?.length) activeDepot.value = data.depots[0].code
	},
})

const recommendRes = createResource({
	url: "container_depot.ess.yard.yard_recommend",
	method: "GET",
	onSuccess(data) {
		rec.value = data
		selectedZone.value = null
		placed.value = null
		manualOpen.value = false
		// Auto-select the recommended zone for a one-tap happy path.
		const pick = (data.zones || []).find((z) => z.recommended)
		if (pick) selectedZone.value = pick.zone_code
	},
})

const placeRes = createResource({
	url: "container_depot.ess.yard.yard_place",
	method: "POST",
})

const zoneTanksRes = createResource({
	url: "container_depot.ess.yard.yard_zone_tanks",
	method: "GET",
})

// --- Derived ---
const depots = computed(() => overviewRes.data?.depots || [])

const groupedZones = computed(() => {
	const zones = (overviewRes.data?.zones || []).filter((z) => !activeDepot.value || z.depot === activeDepot.value)
	const byBlock = new Map()
	for (const z of zones) {
		const key = z.block || ""
		if (!byBlock.has(key)) byBlock.set(key, [])
		byBlock.get(key).push(z)
	}
	return [...byBlock.keys()]
		.sort((a, b) => {
			const ia = BLOCK_ORDER.indexOf(a), ib = BLOCK_ORDER.indexOf(b)
			return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib)
		})
		.map((block) => ({ block, zones: byBlock.get(block) }))
})

// When there is no recommendation, the manual picker opens automatically so the
// operator is never blocked from placing a tank.
const manualPickerOpen = computed(() => manualOpen.value || !(rec.value?.zones || []).length)

const manualGroups = computed(() => {
	const all = rec.value?.all_zones || []
	const byCat = new Map()
	for (const z of all) {
		if (!byCat.has(z.category)) byCat.set(z.category, [])
		byCat.get(z.category).push(z)
	}
	return [...byCat.keys()]
		.sort((a, b) => {
			const ia = CATEGORY_ORDER.indexOf(a), ib = CATEGORY_ORDER.indexOf(b)
			return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib)
		})
		.map((category) => ({ category, zones: byCat.get(category) }))
})

const selectedZoneName = computed(() => {
	const z = (rec.value?.all_zones || []).find((x) => x.zone_code === selectedZone.value)
	return z ? z.zone_name : selectedZone.value
})

const zoneTanks = computed(() => zoneTanksRes.data?.items || [])

const recommendError = computed(
	() => recommendRes.error?.messages?.[0] || recommendRes.error?.message || null,
)
const placeError = computed(
	() => placeRes.error?.messages?.[0] || placeRes.error?.message || null,
)

// --- Helpers ---
function prettyStatus(s) {
	return (s || "").replace(/_/g, " ")
}

function barWidth(z) {
	if (!z.capacity) return z.occupied ? "100%" : "0%"
	return Math.min(100, Math.round((z.occupied / z.capacity) * 100)) + "%"
}

function barClass(z) {
	const u = z.utilization
	if (u == null) return "bg-gray-300"
	if (u >= 90) return "bg-red-500"
	if (u >= 70) return "bg-amber-500"
	return "bg-leaf-500"
}

// --- Actions ---
function doRecommend() {
	if (!containerNo.value) return
	rec.value = null
	placed.value = null
	recommendRes.submit({ container_no: containerNo.value })
}

function selectZone(z) {
	if (z.is_full) return
	selectedZone.value = z.zone_code
}

function doPlace() {
	if (!selectedZone.value) return
	placed.value = null
	placeRes
		.submit({
			container_no: rec.value.container_no,
			zone: selectedZone.value,
			row: form.value.row || "",
			tier: form.value.tier ?? "",
			bay: form.value.bay || "",
		})
		.then((data) => {
			placed.value = data
			form.value = { row: "", tier: null, bay: "" }
			rec.value = null
			selectedZone.value = null
			containerNo.value = ""
			overviewRes.reload()
		})
}

function openZone(z) {
	zoneModal.value = z
	zoneTanksRes.submit({ zone: z.zone_code })
}
</script>
