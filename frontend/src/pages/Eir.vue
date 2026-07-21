<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<!-- =================== FORM (In or Out) =================== -->
		<component
			:is="activeType === 'EIR-Out' ? EirOutForm : EirInForm"
			v-if="activeInspection && activeType"
			:key="activeInspection + activeType"
			:inspection="activeInspection"
			@back="closeForm"
			@submitted="onSubmitted"
		/>
		<!-- ?e= without ?t= (hand-typed / shared link): the worklist is still resolving
		     which direction this EIR is. Rendering the wrong form would call the wrong
		     endpoint, so wait rather than guess. -->
		<div v-else-if="activeInspection" class="oak-section space-y-2">
			<div class="oak-skeleton h-6 w-1/2 rounded-md"></div>
			<div class="oak-skeleton h-24 rounded-xl"></div>
		</div>

		<!-- =================== WORKLIST + LANDING =================== -->
		<template v-else>
			<div class="flex flex-wrap items-center justify-between gap-2">
				<div class="flex items-center gap-2">
					<span class="oak-icon-tile h-9 w-9 bg-leaf-50 text-leaf-600"><Icon name="clipboard" :size="20" /></span>
					<div class="min-w-0">
						<h1 class="text-lg font-extrabold leading-tight tracking-tight">{{ labels.eirTitle }}</h1>
						<p class="truncate text-xs text-gray-500">{{ labels.eirCombinedSubtitle }}</p>
					</div>
				</div>
				<div class="flex items-center gap-2">
					<router-link to="/eir/sort" class="oak-btn oak-btn-secondary px-3 py-2">
						<Icon name="layers" :size="16" /> {{ labels.eirSortOpen }}
					</router-link>
					<router-link to="/eir/history" class="oak-btn oak-btn-secondary px-3 py-2">
						<Icon name="clock" :size="16" /> {{ labels.eirHistory }}
					</router-link>
				</div>
			</div>

			<!-- Pending worklist (In + Out combined, badge per row). Capped to ~5 rows tall,
			     scrolls internally so a long queue never runs far down the page. -->
			<section class="oak-section space-y-3">
				<div class="flex items-center gap-2">
					<Icon name="clipboard" :size="16" class="text-amber-500" />
					<p class="oak-section-title">{{ labels.eirPendingList }}</p>
				</div>
				<div class="flex gap-2">
					<input
						v-model.trim="search"
						type="text"
						:placeholder="labels.eirPendingSearch"
						class="oak-input uppercase"
						@input="onSearchInput"
					/>
					<button class="oak-btn oak-btn-secondary shrink-0 px-4" :disabled="loadingPending" @click="reloadPending">
						<Icon name="search" :size="16" />
					</button>
				</div>

				<!-- Belum / Dikerjakan split. A draft EIR is "belum" until Mulai stamps
				     work_started_on; submitted ones move to the Selesai section below. -->
				<div class="grid grid-cols-3 gap-2">
					<button
						v-for="f in FILTERS"
						:key="f.key"
						class="oak-toggle flex items-center justify-center gap-1.5"
						:class="filter === f.key ? 'oak-toggle-on' : 'oak-toggle-off'"
						@click="filter = f.key"
					>
						{{ f.label }}
						<span class="oak-chip" :class="filter === f.key ? 'bg-brand-100 text-brand-700' : 'bg-gray-100 text-gray-500'">{{ f.count }}</span>
					</button>
				</div>

				<ul v-if="loadingPending && !pendingItems.length" class="space-y-2">
					<li v-for="n in 4" :key="n" class="oak-skeleton h-14 rounded-xl"></li>
				</ul>
				<p v-else-if="!visibleItems.length" class="py-4 text-center text-sm text-gray-400">{{ emptyText }}</p>
				<!-- Every draft is listed; the scroller reveals exactly 5 rows (fixed 60px each)
			     and the rest scroll. -->
				<div v-else class="max-h-[300px] overflow-y-auto overscroll-contain">
					<ul class="divide-y divide-gray-100">
						<li v-for="r in visibleItems" :key="r.name">
							<button class="flex h-[60px] w-full items-center gap-3 text-left" @click="openItem(r)">
								<span class="oak-icon-tile h-9 w-9 shrink-0" :class="r._type === 'EIR-Out' ? 'bg-brand-50 text-brand-600' : 'bg-amber-50 text-amber-600'">
									<Icon :name="r._type === 'EIR-Out' ? 'log-out' : 'clipboard'" :size="16" />
								</span>
								<div class="min-w-0 flex-1">
									<p class="truncate font-semibold text-gray-900">{{ r.container_no || r.container }}</p>
									<!-- The in-progress badge shares the subtitle line so the row keeps a
									     single right-hand chip and stays readable on a narrow phone. -->
									<p class="flex items-center gap-1.5 text-[11px]">
										<span v-if="r.work_started_on" class="oak-chip shrink-0 bg-amber-100 text-amber-800">
											<Icon name="clock" :size="11" /> {{ labels.eirChipStarted }}
										</span>
										<span v-if="r.referred_voucher" class="truncate font-mono text-gray-500">{{ r.referred_voucher }}</span>
										<span v-else-if="r.tank_status" class="truncate text-gray-400">{{ r.tank_status }}</span>
									</p>
								</div>
								<span
									class="oak-chip shrink-0"
									:class="r._type === 'EIR-Out' ? 'bg-brand-100 text-brand-700' : 'bg-leaf-100 text-leaf-800'"
								>
									{{ r._type === 'EIR-Out' ? labels.eirBadgeOut : labels.eirBadgeIn }}
								</span>
							</button>
						</li>
					</ul>
				</div>
				<p v-if="visibleItems.length" class="text-center text-xs text-gray-400">{{ visibleItems.length }} {{ labels.eirPendingCount }}</p>
				<p v-if="fetchError" class="flex items-center gap-1.5 text-sm text-red-600">
					<Icon name="alert-circle" :size="15" /> {{ fetchError }}
				</p>
			</section>

			<!-- Completed (submitted) EIRs — In & Out -->
			<section class="oak-section space-y-3">
				<div class="flex items-center justify-between gap-2">
					<div class="flex items-center gap-2">
						<Icon name="check-circle" :size="16" class="text-leaf-600" />
						<p class="oak-section-title">{{ labels.eirCompleteList }}</p>
					</div>
					<router-link to="/eir/history" class="oak-link text-sm">{{ labels.eirListMore }}</router-link>
				</div>
				<ul v-if="doneRes.loading && !doneItems.length" class="space-y-2">
					<li v-for="n in 3" :key="n" class="oak-skeleton h-12 rounded-xl"></li>
				</ul>
				<p v-else-if="!doneItems.length" class="py-2 text-center text-sm text-gray-400">{{ labels.eirCompleteEmpty }}</p>
				<ul v-else class="divide-y divide-gray-100">
					<li v-for="r in doneItems" :key="r.name" class="flex items-center gap-3 py-2.5">
						<span class="oak-icon-tile h-9 w-9 shrink-0 bg-leaf-50 text-leaf-600"><Icon name="clipboard" :size="16" /></span>
						<div class="min-w-0 flex-1">
							<p class="truncate font-semibold text-gray-900">{{ r.container_no || r.container }}</p>
							<p class="truncate text-xs text-gray-500">{{ r.inspection_type }}<span v-if="r.tank_status"> · {{ r.tank_status }}</span></p>
							<p class="truncate text-[11px] text-gray-400">{{ r.inspection_id || r.name }}</p>
						</div>
						<span class="oak-chip shrink-0" :class="r.inspection_type === 'EIR-Out' ? 'bg-brand-100 text-brand-700' : 'bg-leaf-100 text-leaf-800'">
							{{ r.inspection_type === 'EIR-Out' ? labels.eirBadgeOut : labels.eirBadgeIn }}
						</span>
					</li>
				</ul>
			</section>
		</template>
	</div>
</template>

<script setup>
import { computed, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import { createResource } from "frappe-ui"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"
import EirInForm from "@/pages/EirInForm.vue"
import EirOutForm from "@/pages/EirOutForm.vue"

const route = useRoute()
const router = useRouter()

// One EIR menu for both directions. The worklist below merges pending EIR-In and EIR-Out
// (each row badged by type); tapping opens the matching form component.
//
// The open EIR lives in the URL (?e=<name>&t=in|out) — same contract as CleaningOrder's
// ?o= — so a refresh restores the form instead of dropping back to the worklist. The
// direction rides along because the two forms hit different endpoints, so it must
// survive the reload too.
const activeInspection = computed(() => route.query.e || null)
const activeType = computed(() => {
	if (route.query.t === "out") return "EIR-Out"
	if (route.query.t === "in") return "EIR-In"
	// No ?t (hand-typed / shared link): recover the direction from the worklist rather
	// than guessing. Null until it loads — the template shows a skeleton meanwhile.
	return pendingItems.value.find((r) => r.name === route.query.e)?._type || null
})

const search = ref("")
const inItems = ref([])
const outItems = ref([])

// Pending EIR-In (auto-created per container when an Order Bongkar is submitted).
const inRes = createResource({
	url: "container_depot.ess.inspections.eir_pending",
	method: "GET",
	makeParams: () => ({ search: search.value || undefined, page_length: 50 }),
	auto: true,
	onSuccess: (data) => (inItems.value = (data.items || []).map((x) => ({ ...x, _type: "EIR-In" }))),
})
// Pending EIR-Out (auto-created per container when an Order Muat is submitted).
const outRes = createResource({
	url: "container_depot.ess.inspections.eir_out_pending",
	method: "GET",
	makeParams: () => ({ search: search.value || undefined, page_length: 50 }),
	auto: true,
	onSuccess: (data) => (outItems.value = (data.items || []).map((x) => ({ ...x, _type: "EIR-Out" }))),
})

const loadingPending = computed(() => inRes.loading || outRes.loading)
const fetchError = computed(() => {
	const e = inRes.error || outRes.error
	return e ? e.messages?.[0] || e.message : null
})

// Merge both queues. In-progress first — resuming an inspection someone already opened
// matters more than picking up a fresh one — then newest by creation.
const pendingItems = computed(() => {
	const all = [...inItems.value, ...outItems.value]
	all.sort((a, b) => {
		const started = Number(!!b.work_started_on) - Number(!!a.work_started_on)
		return started || String(b.creation || "").localeCompare(String(a.creation || ""))
	})
	return all
})

// Worklist status filter. "Selesai" is not a choice here: a submitted EIR leaves the
// pending queue entirely and shows in its own section below.
const filter = ref("all")
const startedItems = computed(() => pendingItems.value.filter((r) => r.work_started_on))
const notStartedItems = computed(() => pendingItems.value.filter((r) => !r.work_started_on))
const visibleItems = computed(() => {
	if (filter.value === "started") return startedItems.value
	if (filter.value === "todo") return notStartedItems.value
	return pendingItems.value
})
const FILTERS = computed(() => [
	{ key: "all", label: labels.eirFilterAll, count: pendingItems.value.length },
	{ key: "todo", label: labels.eirFilterNotStarted, count: notStartedItems.value.length },
	{ key: "started", label: labels.eirFilterStarted, count: startedItems.value.length },
])
const emptyText = computed(() => {
	if (!pendingItems.value.length) return labels.eirPendingEmpty
	if (filter.value === "started") return labels.eirFilterEmptyStarted
	if (filter.value === "todo") return labels.eirFilterEmptyNotStarted
	return labels.eirPendingEmpty
})

let searchTimer = null
function onSearchInput() {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(reloadPending, 300)
}
function reloadPending() {
	inRes.reload()
	outRes.reload()
}

// Landing "recently submitted" — the caller's own latest completed EIRs (In & Out).
const LANDING_LIMIT = 3
const doneItems = ref([])
const doneRes = createResource({
	url: "container_depot.ess.inspections.eir_history",
	method: "GET",
	makeParams: () => ({ docstatus: 1, page_length: LANDING_LIMIT }),
	auto: true,
	onSuccess: (data) => (doneItems.value = data.items || []),
})

function openItem(r) {
	router.push({ query: { e: r.name, t: r._type === "EIR-Out" ? "out" : "in" } })
}
function closeForm() {
	if (route.query.e) router.push({ query: {} })
	reloadPending()
	doneRes.reload()
}
function onSubmitted() {
	// The child also emits `back`; just make sure the lists are fresh.
	reloadPending()
	doneRes.reload()
}
</script>
