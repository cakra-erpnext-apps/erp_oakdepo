<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<!-- Header -->
		<div class="flex items-center justify-between">
			<div class="min-w-0">
				<h1 class="truncate text-xl font-extrabold tracking-tight text-gray-900">
					{{ labels.ptTitleFull }}
				</h1>
				<p v-if="order" class="truncate font-mono text-[11px] text-gray-500">
					{{ order.name }} · {{ order.container_no }}
				</p>
				<p v-else class="text-sm text-gray-500">{{ labels.ptExecOrdersHint }}</p>
			</div>
			<div class="flex shrink-0 items-center gap-2">
				<router-link v-if="!order" to="/periodic-test/history" class="oak-btn oak-btn-secondary px-3 py-2">
					<Icon name="clock" :size="16" /> {{ labels.navHistory }}
				</router-link>
				<button v-if="order" class="oak-btn oak-btn-secondary px-3 py-2" @click="backToList">
					<Icon name="arrow-left" :size="16" /> {{ labels.ptBack }}
				</button>
			</div>
		</div>

		<!-- Completed confirmation -->
		<section v-if="completed" class="oak-card border-leaf-200 bg-leaf-50 p-4 space-y-2">
			<p class="font-bold text-leaf-700">
				<Icon name="check-circle" :size="18" /> {{ labels.ptCompleted }}
			</p>
			<p class="font-mono text-sm text-gray-700">{{ completed.name }}</p>
			<p v-if="completed.stock_entry" class="font-mono text-[11px] text-gray-500">
				Stock Entry: {{ completed.stock_entry }}
			</p>
		</section>

		<!-- WORKLIST (Approved / In Progress only) -->
		<section v-if="!order && !completed" class="space-y-3">
			<div class="flex gap-2">
				<input
					v-model="search"
					class="oak-input uppercase"
					:placeholder="labels.ptSearch"
					@keyup.enter="reloadOrders"
				/>
				<button class="oak-btn oak-btn-secondary shrink-0 px-3" @click="reloadOrders">
					<Icon name="search" :size="16" />
				</button>
			</div>

			<div v-if="ordersRes.loading" class="oak-card p-6 text-center text-gray-400">
				<Icon name="loader" :size="20" class="animate-spin" />
			</div>
			<div v-else-if="!orders.length" class="oak-card p-6 text-center text-gray-400">
				{{ labels.ptExecEmpty }}
			</div>
			<div v-for="o in orders" :key="o.name" class="oak-card flex items-center gap-3 p-4">
				<button class="oak-press flex min-w-0 flex-1 items-center gap-3 text-left" @click="openOrder(o)">
					<span class="oak-icon-tile h-11 w-11 shrink-0 bg-brand-50 text-brand-600">
						<Icon name="activity" :size="20" />
					</span>
					<div class="min-w-0 flex-1">
						<p class="truncate font-bold text-gray-900">{{ o.container_no || o.container }}</p>
						<p class="truncate text-xs text-gray-500">{{ o.name }} · {{ o.principal || "—" }}</p>
						<p class="truncate text-[11px] text-gray-400">
							<span v-if="o.test_type" class="font-semibold text-brand-600">{{ o.test_type }}</span>
							· {{ labels.createdOn }} {{ fmtDate(o.creation) }}
						</p>
					</div>
				</button>
				<span class="oak-chip shrink-0" :class="statusChipClass(o.status)">{{ repairStatusLabel(o.status) }}</span>
			</div>
		</section>

		<!-- DETAIL (execution) -->
		<template v-if="order && !completed">
			<!-- GATE: an Approved (not-yet-started) order must be started first. -->
			<section v-if="isApproved" class="oak-card space-y-4 p-5 text-center">
				<span class="oak-icon-tile mx-auto h-14 w-14 bg-brand-50 text-brand-600"><Icon name="activity" :size="26" /></span>
				<div class="space-y-1">
					<p class="font-bold text-gray-900">{{ order.container_no || order.container }}</p>
					<p class="font-mono text-xs text-gray-400">{{ order.name }}</p>
					<p class="text-sm text-gray-500">{{ labels.ptExecStartGate }}</p>
				</div>
				<button class="oak-btn oak-btn-primary w-full py-3 text-base" @click="startCurrent">
					{{ labels.ptStartFull }}
				</button>
			</section>

			<!-- Non-execution order opened via deep-link — managed in ERP. -->
			<section v-else-if="!isInProgress" class="oak-card border-amber-200 bg-amber-50 p-3">
				<p class="text-sm font-semibold text-amber-800">{{ labels.ptExecErpBanner }}</p>
			</section>

			<!-- WORK DETAIL — only once the order is In Progress (started). -->
			<template v-else>
				<section class="oak-card border-indigo-200 bg-indigo-50 p-3">
					<p class="text-sm font-semibold text-indigo-700">{{ labels.ptExecInProgress }}</p>
				</section>

				<!-- Tank header -->
				<section class="oak-card p-4">
					<p class="oak-section-title mb-2">{{ labels.mrTankDetails }}</p>
					<dl class="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
						<div v-for="cell in headerCells" :key="cell.label" class="min-w-0">
							<dt class="text-xs text-gray-400">{{ cell.label }}</dt>
							<dd class="truncate font-medium text-gray-800">{{ cell.value || "—" }}</dd>
						</div>
					</dl>
				</section>

				<!-- Test info + test-date input (drives the next due-date) -->
				<section class="oak-card p-4 space-y-3">
					<p class="oak-section-title">{{ labels.ptTestInfoTitle }}</p>
					<dl class="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
						<div class="min-w-0">
							<dt class="text-xs text-gray-400">{{ labels.ptTestType }}</dt>
							<dd class="font-semibold text-brand-600">{{ order.test_type || "—" }}</dd>
						</div>
						<div class="min-w-0">
							<dt class="text-xs text-gray-400">{{ labels.ptLastTest }}</dt>
							<dd class="truncate font-medium text-gray-800">
								{{ order.last_pt_type || "" }} {{ order.last_pt_date ? fmtDate(order.last_pt_date) : (order.last_test_date ? fmtDate(order.last_test_date) : "—") }}
							</dd>
						</div>
					</dl>
					<div>
						<label class="text-xs font-medium text-gray-500">{{ labels.ptPeriodicDate }}</label>
						<input v-model="periodicDate" type="date" class="oak-input mt-1" />
						<p class="mt-1 text-[11px] text-gray-400">{{ labels.ptPeriodicDateHint }}</p>
					</div>
				</section>

				<!-- Approved services/parts (read-only — the estimate is owned by ERP) -->
				<section class="oak-card p-4 space-y-3">
					<p class="oak-section-title">{{ labels.ptPartsTitle }}</p>
					<p v-if="!testLines.length" class="py-2 text-center text-sm text-gray-400">{{ labels.mrNoUsed }}</p>
					<div
						v-for="(u, i) in testLines"
						:key="i"
						class="rounded-xl border p-3 space-y-2"
						:class="u.decision === 'Rejected' ? 'border-red-100 bg-red-50/40' : 'border-gray-100'"
					>
						<div class="flex items-start justify-between gap-2">
							<div class="min-w-0">
								<p class="truncate font-semibold text-gray-900">{{ u.item_name || u.item }}</p>
								<p class="text-xs text-gray-500">
									<span v-if="u.line_type" class="text-gray-400">{{ u.line_type }} · </span>{{ labels.mrQty }} {{ u.quantity }}<span v-if="u.on_hand != null"> · {{ labels.mrOnHand }} {{ u.on_hand }}</span>
								</p>
								<p v-if="u.warehouse" class="text-xs text-gray-500">{{ labels.mrWarehouse }}: {{ u.warehouse }}</p>
								<p v-if="u.remark" class="text-xs text-gray-400">{{ u.remark }}</p>
							</div>
							<span class="oak-chip shrink-0" :class="decChipClass(u.decision)">{{ repairStatusLabel(u.decision) }}</span>
						</div>
						<div v-if="u.photos && u.photos.length" class="flex flex-wrap gap-2">
							<button v-for="(ph, pi) in u.photos" :key="pi" type="button" class="oak-press" @click="openLightbox(u.photos, pi)">
								<img :src="ph" class="h-16 w-16 rounded-lg border border-gray-200 object-cover" />
							</button>
						</div>
					</div>
				</section>

				<!-- Remarks (read-only) -->
				<section v-if="order.remarks" class="oak-card p-4">
					<p class="oak-section-title mb-1">{{ labels.mrRemarks }}</p>
					<p class="whitespace-pre-line text-sm text-gray-700">{{ order.remarks }}</p>
				</section>

				<!-- Complete -->
				<button class="oak-btn oak-btn-primary w-full py-3" :disabled="completing" @click="confirmComplete">
					<Icon v-if="completing" name="loader" :size="18" class="animate-spin" />
					<span v-else>{{ labels.ptComplete }}</span>
				</button>
			</template>
		</template>
	</div>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { labels, repairStatusLabel } from "@/utils/labels"
import { toast } from "@/utils/toast"
import { openLightbox } from "@/utils/lightbox"
import { confirm } from "@/utils/confirm"
import Icon from "@/components/Icon.vue"
import { cachedResource } from "@/data/cache"
import { enqueue, isQueued, outbox } from "@/data/outbox"

const route = useRoute()
const router = useRouter()

const fmtDate = (v) =>
	v
		? new Date(String(v).slice(0, 10) + "T00:00:00").toLocaleDateString("id-ID", {
				day: "numeric",
				month: "short",
				year: "numeric",
		  })
		: "—"

const todayStr = () => {
	const d = new Date()
	return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

const search = ref("")
const allOrders = ref([]) // what the server (or the offline cache) last said
const order = ref(null)
const completed = ref(null)
const used = ref([])

// An order whose completion is queued is done as far as the technician is concerned; the
// server just has not heard yet. Leaving it listed invites them to redo the whole test.
const orders = computed(() => allOrders.value.filter((o) => !isQueued(o.name)))
// The date the test was actually performed — drives the next due-date on completion.
const periodicDate = ref(todayStr())

// --- status-driven view flags (execution phase only) -----------------------
const isApproved = computed(() => order.value?.status === "Approved")
const isInProgress = computed(() => order.value?.status === "In Progress")
// Only approved lines are relevant to the field crew (rejected ones aren't done).
const testLines = computed(() => used.value.filter((u) => u.decision !== "Rejected"))

function decChipClass(d) {
	if (d === "Approved") return "bg-leaf-100 text-leaf-700"
	if (d === "Rejected") return "bg-red-100 text-red-700"
	return "bg-gray-100 text-gray-500"
}
function statusChipClass(s) {
	if (s === "Approved") return "bg-leaf-50 text-leaf-700"
	if (s === "In Progress") return "bg-indigo-50 text-indigo-700"
	return "bg-gray-100 text-gray-600"
}

const ordersRes = cachedResource({
	url: "container_depot.ess.periodic.pt_execution",
	method: "GET",
	auto: true,
	onSuccess: (data) => (allOrders.value = data.items || []),
})

function reloadOrders() {
	const s = search.value.trim()
	ordersRes.fetch(s ? { search: s } : {})
}

const headerCells = computed(() => {
	const h = order.value || {}
	return [
		{ label: labels.cleaningTankType, value: h.tank_type },
		{ label: labels.cleaningClient, value: h.client },
		{ label: labels.cleaningCapacity, value: h.capacity },
		{ label: labels.cleaningPrevCargo, value: h.previous_cargo },
		{ label: labels.cleaningTare, value: h.tare },
		{ label: labels.cleaningMgw, value: h.mgw },
	]
})

const detailRes = cachedResource({
	url: "container_depot.ess.periodic.pt_order_detail",
	method: "GET",
	onSuccess(data) {
		order.value = data
		used.value = (data.used_items || []).map((u) =>
			reactive({ ...u, decision: u.decision || "Pending", photos: [...(u.photos || [])] })
		)
		periodicDate.value = data.periodic_date || todayStr()
	},
	onError: (err) => toast.error(err?.messages?.[0] || err?.message || labels.error),
})

// The open order lives in the URL (?o=<name>) so a refresh restores the detail view.
function openOrder(o) {
	router.push({ query: { o: o.name } })
}

watch(
	() => route.query.o,
	(o) => {
		if (o) {
			if (order.value?.name !== o) {
				completed.value = null
				detailRes.fetch({ periodic_test_order: o })
			}
		} else {
			order.value = null
		}
	},
	{ immediate: true }
)

// --- start (Approved -> In Progress) ----------------------------------------
//
// Queued, and the status flipped locally rather than re-fetched. The response carried nothing
// the screen needed except the new status, and waiting for it is what made "Mulai" impossible
// in a dead spot — which locked the technician out of the rest of the form.
//
// No `ref` on this row: starting is not finishing, so the order must stay in the worklist.
async function startCurrent() {
	if (!order.value) return
	try {
		await enqueue({
			kind: "pt-start",
			title: `${labels.navPt} · Mulai`,
			url: "container_depot.ess.periodic.pt_start",
			payload: { periodic_test_order: order.value.name },
		})
		order.value = { ...order.value, status: "In Progress" }
		toast.success(labels.ptStarted)
	} catch (e) {
		toast.error(e?.message || labels.error)
	}
}

// --- complete (In Progress -> Completed; issues parts + advances the due date) ---
//
// Through the outbox, online and off. Completing pushes the container's next test due-date
// forward, which is precisely why it carries a request_id: replaying it would advance the
// date a second interval into the future (see ess/idempotency.py).
const completing = ref(false)

async function confirmComplete() {
	const ok = await confirm({
		title: labels.confirmSubmitTitle,
		message: labels.confirmSubmitMessage,
		confirmLabel: labels.confirmSubmitYes,
		cancelLabel: labels.confirmCancel,
	})
	if (ok) complete()
}

async function complete() {
	if (!order.value || completing.value) return
	completing.value = true
	const o = order.value
	try {
		await enqueue({
			kind: "pt-complete",
			title: `${labels.navPt} · ${o.container_no || o.container}`,
			ref: o.name,
			url: "container_depot.ess.periodic.pt_order_save",
			payload: {
				periodic_test_order: o.name,
				periodic_date: periodicDate.value || undefined,
				submit: 1,
			},
		})
		toast.success(outbox.online ? labels.ptCompleted : labels.queuedOffline, { title: o.name })
		order.value = null
		if (route.query.o) router.replace({ query: {} })
		reloadOrders()
	} catch (e) {
		toast.error(e?.message || labels.error)
	} finally {
		completing.value = false
	}
}

function backToList() {
	completed.value = null
	used.value = []
	if (route.query.o) router.push({ query: {} })
	else order.value = null
	reloadOrders()
}
</script>
