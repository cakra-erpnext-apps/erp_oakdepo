<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<!-- =================== FORM (In or Out) =================== -->
		<component
			:is="activeType === 'EIR-Out' ? EirOutForm : EirInForm"
			v-if="activeInspection"
			:key="activeInspection"
			:inspection="activeInspection"
			@back="closeForm"
			@submitted="onSubmitted"
		/>

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

				<ul v-if="loadingPending && !pendingItems.length" class="space-y-2">
					<li v-for="n in 4" :key="n" class="oak-skeleton h-14 rounded-xl"></li>
				</ul>
				<p v-else-if="!pendingItems.length" class="py-4 text-center text-sm text-gray-400">{{ labels.eirPendingEmpty }}</p>
				<!-- Every draft is listed; the scroller reveals exactly 5 rows (fixed 60px each)
			     and the rest scroll. -->
				<div v-else class="max-h-[300px] overflow-y-auto overscroll-contain">
					<ul class="divide-y divide-gray-100">
						<li v-for="r in pendingItems" :key="r.name">
							<button class="flex h-[60px] w-full items-center gap-3 text-left" @click="openItem(r)">
								<span class="oak-icon-tile h-9 w-9 shrink-0" :class="r._type === 'EIR-Out' ? 'bg-brand-50 text-brand-600' : 'bg-amber-50 text-amber-600'">
									<Icon :name="r._type === 'EIR-Out' ? 'log-out' : 'clipboard'" :size="16" />
								</span>
								<div class="min-w-0 flex-1">
									<p class="truncate font-semibold text-gray-900">{{ r.container_no || r.container }}</p>
									<p v-if="r.referred_voucher" class="truncate font-mono text-[11px] text-gray-500">{{ r.referred_voucher }}</p>
									<p v-else-if="r.tank_status" class="truncate text-xs text-gray-400">{{ r.tank_status }}</p>
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
				<p v-if="pendingItems.length" class="text-center text-xs text-gray-400">{{ pendingItems.length }} {{ labels.eirPendingCount }}</p>
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
import { createResource } from "frappe-ui"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"
import EirInForm from "@/pages/EirInForm.vue"
import EirOutForm from "@/pages/EirOutForm.vue"

// One EIR menu for both directions. The worklist below merges pending EIR-In and EIR-Out
// (each row badged by type); tapping opens the matching form component.
const activeInspection = ref(null)
const activeType = ref("EIR-In")

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

// Merge both queues, newest first (by creation).
const pendingItems = computed(() => {
	const all = [...inItems.value, ...outItems.value]
	all.sort((a, b) => String(b.creation || "").localeCompare(String(a.creation || "")))
	return all
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
	activeType.value = r._type === "EIR-Out" ? "EIR-Out" : "EIR-In"
	activeInspection.value = r.name
}
function closeForm() {
	activeInspection.value = null
	reloadPending()
	doneRes.reload()
}
function onSubmitted() {
	// The child also emits `back`; just make sure the lists are fresh.
	reloadPending()
	doneRes.reload()
}
</script>
