<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<!-- =================== FORM (In or Out) =================== -->
		<template v-if="activeInspection && activeType">
			<!-- Queue navigator: only when this account is working more than one EIR. Lets the
			     surveyor jump ◀ / ▶ between the EIRs they started without going back to the list;
			     submitting one auto-advances to the next (see onSubmitted / onBack). -->
			<div v-if="navQueue.length > 1 && activeIndex !== -1" class="oak-card space-y-2 p-2">
				<div class="flex items-center justify-between gap-2">
					<button class="oak-btn oak-btn-secondary px-3 py-2" :disabled="activeIndex <= 0" @click="goRel(-1)">
						<Icon name="chevron-left" :size="16" /> {{ labels.eirNavPrev }}
					</button>
					<span class="shrink-0 text-sm font-bold text-gray-700">
						{{ labels.eirBadge }} {{ activeIndex + 1 }} / {{ navQueue.length }}
					</span>
					<button class="oak-btn oak-btn-secondary px-3 py-2" :disabled="activeIndex >= navQueue.length - 1" @click="goRel(1)">
						{{ labels.eirNavNext }} <Icon name="chevron-right" :size="16" />
					</button>
				</div>
				<button class="oak-link mx-auto block text-xs" @click="clearBatch">{{ labels.eirBatchExit }}</button>
			</div>
			<component
				:is="activeType === 'EIR-Out' ? EirOutForm : EirInForm"
				:key="activeInspection + activeType"
				:inspection="activeInspection"
				@back="onBack"
				@submitted="onSubmitted"
			/>
		</template>
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
				<div class="flex items-center justify-between gap-2">
					<div class="flex items-center gap-2">
						<Icon name="clipboard" :size="16" class="text-amber-500" />
						<p class="oak-section-title">{{ labels.eirPendingList }}</p>
					</div>
					<!-- Batch mode: pick several EIRs, then "Mulai" starts them all under this
					     account so the navigator/auto-advance can walk them (started-by-me). -->
					<button
						class="oak-btn px-3 py-1.5 text-xs"
						:class="selectMode ? 'oak-btn-primary' : 'oak-btn-secondary'"
						@click="toggleSelectMode"
					>
						<Icon :name="selectMode ? 'x' : 'check-square'" :size="14" />
						{{ selectMode ? labels.eirSelectCancel : labels.eirSelect }}
					</button>
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
							<button class="flex h-[60px] w-full items-center gap-3 text-left" @click="rowClick(r)">
								<!-- Select-mode tick box (replaces navigation while picking a batch). -->
								<span
									v-if="selectMode"
									class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border"
									:class="selected.has(r.name) ? 'border-brand-500 bg-brand-500 text-white' : 'border-gray-300'"
								>
									<Icon v-if="selected.has(r.name)" name="check" :size="14" />
								</span>
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
				<p v-if="visibleItems.length && !selectMode" class="text-center text-xs text-gray-400">{{ visibleItems.length }} {{ labels.eirPendingCount }}</p>
				<button
					v-if="selectMode"
					class="oak-btn oak-btn-primary w-full py-2.5"
					:disabled="!selected.size"
					@click="openBatch"
				>
					<Icon name="arrow-right" :size="16" /> {{ labels.eirBatchOpen }} <template v-if="selected.size">({{ selected.size }})</template>
				</button>
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
					<li v-for="r in doneItems" :key="r.name">
						<button type="button" class="oak-press flex w-full items-center gap-3 py-2.5 text-left" @click="goCompleted(r)">
							<span class="oak-icon-tile h-9 w-9 shrink-0 bg-leaf-50 text-leaf-600"><Icon name="clipboard" :size="16" /></span>
							<div class="min-w-0 flex-1">
								<p class="truncate font-semibold text-gray-900">{{ r.container_no || r.container }}</p>
								<p class="truncate text-xs text-gray-500">{{ r.inspection_type }}<span v-if="r.tank_status"> · {{ r.tank_status }}</span></p>
								<p class="truncate text-[11px] text-gray-400">{{ r.inspection_id || r.name }}</p>
							</div>
							<span class="oak-chip shrink-0" :class="r.inspection_type === 'EIR-Out' ? 'bg-brand-100 text-brand-700' : 'bg-leaf-100 text-leaf-800'">
								{{ r.inspection_type === 'EIR-Out' ? labels.eirBadgeOut : labels.eirBadgeIn }}
							</span>
							<Icon name="chevron-right" :size="16" class="shrink-0 text-gray-300" />
						</button>
					</li>
				</ul>
			</section>
		</template>
	</div>
</template>

<script setup>
import { computed, reactive, ref } from "vue"
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

// --- queue navigator + batch selection --------------------------------------
// "Pilih" (select mode) lets the surveyor tick several pending EIRs, then "Buka" opens
// them as a batch. The navigator walks that picked set — no need to press Mulai and no
// need to submit to move on; every edit already auto-saves. The batch persists (as names)
// until it's cleared or every EIR in it leaves the pending list.
const selectMode = ref(false)
const selected = reactive(new Set())
const autoAdvanceTo = ref(null) // next EIR to open after a submit (consumed by onBack)

// The batch = the picked EIRs that are still pending, in worklist order.
const navQueue = computed(() => pendingItems.value.filter((r) => selected.has(r.name)))
const activeIndex = computed(() => navQueue.value.findIndex((r) => r.name === activeInspection.value))

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

// Landing "recently submitted" — the caller's own latest completed EIRs (In & Out),
// newest first (no date filter). Tapping one opens its read-only detail (+ revision).
const LANDING_LIMIT = 5
const doneItems = ref([])
const doneRes = createResource({
	url: "container_depot.ess.inspections.eir_history",
	method: "GET",
	makeParams: () => ({ docstatus: 1, page_length: LANDING_LIMIT }),
	auto: true,
	onSuccess: (data) => (doneItems.value = data.items || []),
})

function goItem(r) {
	router.push({ query: { e: r.name, t: r._type === "EIR-Out" ? "out" : "in" } })
}
// Completed EIRs are read-only: open the History detail (which carries the revision button).
function goCompleted(r) {
	router.push({ path: "/eir/history", query: { open: r.name } })
}
// Prev/next within the current account's queue.
function goRel(delta) {
	const target = navQueue.value[activeIndex.value + delta]
	if (target) goItem(target)
}

// Worklist tap: select in batch mode, otherwise open the EIR.
function rowClick(r) {
	if (selectMode.value) {
		if (selected.has(r.name)) selected.delete(r.name)
		else selected.add(r.name)
		return
	}
	goItem(r)
}
function toggleSelectMode() {
	selectMode.value = !selectMode.value
	selected.clear()
}

// Open the picked EIRs as a batch: just navigate to the first — no Mulai, no submit. The
// selection stays as the batch so the ◀ / ▶ navigator can walk it. Each EIR still has its
// own Mulai gate for editing; moving between them needs neither Mulai nor submit.
function openBatch() {
	const first = pendingItems.value.find((r) => selected.has(r.name)) // worklist order
	if (!first) return
	selectMode.value = false // keep `selected` — it IS the batch now
	goItem(first)
}
// Leave the batch (clears the picked set) and drop back to the worklist.
function clearBatch() {
	selected.clear()
	if (route.query.e) router.push({ query: {} })
}

function onBack() {
	// After a submit the child emits `submitted` (which queued the next EIR) then `back`.
	const next = autoAdvanceTo.value
	autoAdvanceTo.value = null
	if (next) {
		goItem(next) // auto-advance to the next EIR in this account's queue
		reloadPending()
		doneRes.reload()
		return
	}
	if (route.query.e) router.push({ query: {} })
	reloadPending()
	doneRes.reload()
}
function onSubmitted(name) {
	// Capture the next EIR to jump to BEFORE the lists refresh (the just-submitted one is
	// still in navQueue here). Prefer the following item, else the previous, else stop.
	const q = navQueue.value
	const i = q.findIndex((r) => r.name === name)
	const next = i === -1 ? null : q[i + 1] || q[i - 1] || null
	autoAdvanceTo.value = next && next.name !== name ? next : null
	selected.delete(name) // the submitted EIR leaves the batch
}
</script>
