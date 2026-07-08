<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<div class="flex flex-wrap items-center justify-between gap-2">
			<div class="flex items-center gap-2">
				<span class="oak-icon-tile h-9 w-9 bg-brand-50 text-brand-600"><Icon name="grid" :size="20" /></span>
				<div>
					<h1 class="text-lg font-extrabold tracking-tight">{{ labels.monitorTitle }}</h1>
					<p class="text-xs text-gray-500">{{ labels.storageBranch }}: {{ branch }}</p>
				</div>
			</div>
			<div class="flex shrink-0 items-center gap-2">
				<router-link to="/monitor/history" class="oak-btn oak-btn-secondary px-3 py-2">
					<Icon name="clock" :size="16" /> {{ labels.navHistory }}
				</router-link>
			</div>
		</div>

		<!-- Search -->
		<div class="relative">
			<Icon name="search" :size="18" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
			<input
				v-model="search"
				type="search"
				:placeholder="labels.monitorSearch"
				class="oak-input pl-10 uppercase"
				@input="onSearchInput"
			/>
		</div>

		<!-- Status filter chips -->
		<div class="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1">
			<button
				v-for="s in statusChips"
				:key="s.key"
				class="shrink-0 rounded-full border px-3 py-1.5 text-xs font-semibold transition"
				:class="statusFilter === s.key ? 'border-brand-600 bg-brand-600 text-white' : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300'"
				@click="setStatus(s.key)"
			>
				{{ s.label }}
			</button>
		</div>

		<!-- Quick filter: today -->
		<div class="flex gap-1.5">
			<button
				class="flex items-center gap-1 rounded-full border px-3 py-1.5 text-xs font-semibold transition"
				:class="todayOnly ? 'border-brand-600 bg-brand-600 text-white' : 'border-gray-200 bg-white text-gray-600'"
				@click="toggleToday"
			>
				<Icon name="calendar" :size="13" /> {{ labels.monitorToday }}
			</button>
		</div>

		<!-- Depot filter -->
		<div v-if="depots.length > 1" class="flex items-center gap-2">
			<Icon name="map-pin" :size="15" class="shrink-0 text-gray-400" />
			<SearchSelect
				:model-value="depotFilter"
				:options="depots"
				:option-value="(d) => d.code"
				:option-label="(d) => d.name"
				:placeholder="labels.monitorAllDepots"
				:clear-label="labels.monitorAllDepots"
				:search-placeholder="labels.selectSearch"
				class="flex-1"
				@update:model-value="(v) => { depotFilter = v; reload(true) }"
			/>
		</div>

		<!-- Principal filter -->
		<div v-if="principals.length" class="flex items-center gap-2">
			<Icon name="briefcase" :size="15" class="shrink-0 text-gray-400" />
			<SearchSelect
				:model-value="principalFilter"
				:options="principals"
				:option-value="(p) => p.name"
				:option-label="(p) => p.label"
				:placeholder="labels.monitorAllPrincipals"
				:clear-label="labels.monitorAllPrincipals"
				:search-placeholder="labels.selectSearch"
				class="flex-1"
				@update:model-value="(v) => { principalFilter = v; reload(true) }"
			/>
		</div>

		<!-- Loading skeleton -->
		<ul v-if="tankRes.loading && !items.length" class="oak-card divide-y divide-gray-100 overflow-hidden">
			<li v-for="n in 6" :key="n" class="flex items-center gap-3 px-4 py-3.5">
				<div class="oak-skeleton h-9 w-9 rounded-xl"></div>
				<div class="flex-1 space-y-2"><div class="oak-skeleton h-3.5 w-1/2"></div><div class="oak-skeleton h-3 w-3/4"></div></div>
			</li>
		</ul>

		<div v-else-if="!items.length" class="oak-card flex flex-col items-center gap-2 p-8 text-center">
			<span class="oak-icon-tile h-12 w-12 bg-gray-100 text-gray-300"><Icon name="inbox" :size="24" /></span>
			<p class="text-sm text-gray-400">{{ labels.monitorEmpty }}</p>
		</div>

		<ul v-else class="oak-card divide-y divide-gray-100 overflow-hidden">
			<li v-for="c in items" :key="c.name" class="flex items-center">
				<!-- Always a <div> (never a native <button>): buttons render unreliably as flex
				     items/containers on some webviews & Firefox, breaking the row layout. Clickable
				     rows (those with an order) get button semantics via role/tabindex. -->
				<div
					class="min-w-0 flex-1 px-4 py-3 text-left"
					:class="c.order ? 'cursor-pointer transition hover:bg-gray-50' : ''"
					:role="c.order ? 'button' : null"
					:tabindex="c.order ? 0 : null"
					@click="c.order && openOrder(c)"
					@keydown.enter="c.order && openOrder(c)"
					@keydown.space.prevent="c.order && openOrder(c)"
				>
					<div class="flex min-w-0 items-center gap-3">
						<span class="oak-icon-tile h-9 w-9 shrink-0 bg-gray-100 text-gray-500"><Icon name="package" :size="16" /></span>
						<div class="min-w-0 flex-1">
							<div class="flex items-center justify-between gap-2">
								<p class="truncate font-semibold text-gray-900">{{ c.container_no || c.name }}</p>
								<span class="oak-chip shrink-0" :class="statusColors[c.status] || 'bg-gray-100 text-gray-600'">{{ statusLabels[c.status] || c.status }}</span>
							</div>
							<p class="mt-0.5 truncate text-xs text-gray-500">
								<span v-if="c.principal">{{ c.principal }}</span>
								<span v-if="c.pt_due" class="text-red-500"> · {{ labels.monitorPtDue }}</span>
							</p>
							<!-- What put the tank in this bucket (draft/pending/dikerjakan) + link to the order -->
							<p v-if="c.order" class="mt-1 flex items-center gap-1 truncate text-xs font-semibold" :class="orderTint(c.status)">
								<Icon :name="c.order.kind === 'M&R' ? 'tool' : 'droplet'" :size="12" class="shrink-0" />
								{{ statusLabels[c.status] }} · {{ c.order.kind }}
								<span class="font-mono font-normal text-gray-400">· {{ c.order.name }}</span>
							</p>
							<p v-if="c.order_bongkar" class="mt-0.5 flex items-center gap-1 truncate font-mono text-[11px] text-gray-400">
								<Icon name="file-text" :size="11" class="shrink-0" /> {{ c.order_bongkar }}
							</p>
						</div>
					</div>
				</div>
				<button
					v-if="c.raw_status === 'Available'"
					class="oak-btn oak-btn-primary mr-3 shrink-0 px-3 py-1.5 text-xs"
					:disabled="gateOutRes.loading"
					@click.stop="confirmGateOut(c)"
				>
					<Icon name="log-out" :size="14" /> {{ labels.gateOutAction }}
				</button>
				<Icon v-else-if="c.order" name="chevron-right" :size="16" class="mr-4 shrink-0 text-gray-300" />
				<span v-else class="mr-4 shrink-0"></span>
			</li>
		</ul>

		<!-- Infinite-scroll sentinel + count -->
		<div v-if="items.length" class="space-y-2">
			<div ref="sentinel" class="h-px"></div>
			<button
				v-if="items.length < total"
				class="oak-btn oak-btn-secondary w-full"
				:disabled="tankRes.loading"
				@click="loadMore"
			>
				{{ tankRes.loading ? "…" : `${labels.storageLoadMore} (${items.length}/${total})` }}
			</button>
			<p class="text-center text-xs text-gray-400">{{ items.length }} / {{ total }} container</p>
		</div>
	</div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { createResource } from "frappe-ui"
import { labels, statusLabels, statusColors } from "@/utils/labels"
import { userContext, branchLabel } from "@/data/context"
import { toast } from "@/utils/toast"
import { confirm } from "@/utils/confirm"
import Icon from "@/components/Icon.vue"
import SearchSelect from "@/components/SearchSelect.vue"

const PAGE = 50
const route = useRoute()
const router = useRouter()
const search = ref("")
const statusFilter = ref("") // default to "Semua" — the field observer sees every container
const principalFilter = ref("")
const depotFilter = ref("")
const todayOnly = ref(false)
const items = ref([])
const total = ref(0)
const start = ref(0)
const sentinel = ref(null)

const branch = computed(() => branchLabel())

// Order-state buckets: "" = all, then Available / Draft / Pending / Dikerjakan / Keluar.
const statusChips = [
	{ key: "", label: labels.monitorAll },
	{ key: "available", label: statusLabels.available },
	{ key: "draft", label: statusLabels.draft },
	{ key: "pending", label: statusLabels.pending },
	{ key: "in_progress", label: statusLabels.in_progress },
	{ key: "gate_out", label: statusLabels.gate_out },
]

const principalsRes = createResource({
	url: "container_depot.ess.inventory.list_container_principals",
	method: "GET",
	auto: true,
})
const principals = computed(() => principalsRes.data?.principals || [])

const depotsRes = createResource({
	url: "container_depot.ess.inventory.list_user_depots",
	method: "GET",
	auto: true,
})
const depots = computed(() => depotsRes.data?.depots || [])

const tankRes = createResource({
	url: "container_depot.ess.inventory.get_tank_list",
	method: "GET",
	makeParams: () => ({
		search: search.value || "",
		status: statusFilter.value || "",
		principal: principalFilter.value || "",
		depot: depotFilter.value || "",
		today: todayOnly.value ? 1 : 0,
		start: start.value,
		page_length: PAGE,
	}),
	onSuccess(data) {
		items.value = start.value === 0 ? data.items || [] : items.value.concat(data.items || [])
		total.value = data.total || 0
		start.value += (data.items || []).length
	},
})

function reload(reset) {
	if (reset) {
		start.value = 0
		items.value = []
	}
	tankRes.reload()
}
function loadMore() {
	if (tankRes.loading || items.value.length >= total.value) return
	tankRes.reload()
}
function setStatus(key) {
	statusFilter.value = key
	reload(true)
}
function toggleToday() {
	todayOnly.value = !todayOnly.value
	reload(true)
}
let searchTimer = null
function onSearchInput() {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(() => reload(true), 300)
}

// Tap a draft/pending/dikerjakan row -> open the order that drives the bucket.
function openOrder(c) {
	if (!c.order) return
	const path = c.order.kind === "M&R" ? "/mr" : "/cleaning"
	router.push({ path, query: { o: c.order.name } })
}
// Text tint matching the status chip (leaf/amber/blue/gray) for the order descriptor.
function orderTint(status) {
	return { draft: "text-gray-600", pending: "text-amber-700", in_progress: "text-blue-700" }[status] || "text-gray-600"
}

// TANK OUT — confirm + complete gate-out for a pickup-pending tank, then refresh so it
// drops out of the live-inventory buckets.
const gateOutRes = createResource({
	url: "container_depot.ess.gate.gate_out",
	method: "POST",
	onSuccess(data) {
		toast.success(labels.gateOutDone, { title: data?.container })
		reload(true)
	},
	onError: (err) => toast.error(err?.messages?.[0] || err?.message || labels.error),
})
async function confirmGateOut(c) {
	const ok = await confirm({
		title: labels.gateOutConfirmTitle,
		message: labels.gateOutConfirmMessage,
		confirmLabel: labels.gateOutAction,
		cancelLabel: labels.confirmCancel,
	})
	if (ok) gateOutRes.fetch({ container: c.name })
}

// Infinite-scroll: auto-load the next page when the sentinel scrolls into view.
let observer = null
onMounted(() => {
	if (!userContext.data) userContext.reload()
	// Honor a deep-link bucket from the dashboard status KPIs (?status=<bucket>).
	const q = route.query.status
	if (typeof q === "string" && statusChips.some((c) => c.key === q)) statusFilter.value = q
	reload(true)

	observer = new IntersectionObserver(
		(entries) => {
			if (entries.some((e) => e.isIntersecting)) loadMore()
		},
		{ rootMargin: "300px" },
	)
	if (sentinel.value) observer.observe(sentinel.value)
})
// The sentinel only exists once the list has rows — (re)observe it whenever it mounts.
watch(sentinel, (el, old) => {
	if (!observer) return
	if (old) observer.unobserve(old)
	if (el) observer.observe(el)
})
onBeforeUnmount(() => observer?.disconnect())
</script>
