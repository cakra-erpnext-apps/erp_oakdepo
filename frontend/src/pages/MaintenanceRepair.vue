<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<!-- Header -->
		<div class="flex items-center justify-between">
			<div class="min-w-0">
				<h1 class="truncate text-xl font-extrabold tracking-tight text-gray-900">
					{{ labels.mrTitleFull }}
				</h1>
				<p v-if="order" class="truncate font-mono text-[11px] text-gray-500">
					{{ order.repair_order_id }} · {{ order.container_no }}
				</p>
				<p v-else class="text-sm text-gray-500">{{ labels.mrOrdersHint }}</p>
			</div>
			<div class="flex shrink-0 items-center gap-2">
				<router-link v-if="!order" to="/mr/history" class="oak-btn oak-btn-secondary px-3 py-2">
					<Icon name="clock" :size="16" /> {{ labels.navHistory }}
				</router-link>
				<button v-if="order" class="oak-btn oak-btn-secondary px-3 py-2" @click="backToList">
					<Icon name="arrow-left" :size="16" /> {{ labels.mrBack }}
				</button>
			</div>
		</div>

		<!-- Completed confirmation -->
		<section v-if="completed" class="oak-card border-leaf-200 bg-leaf-50 p-4 space-y-2">
			<p class="font-bold text-leaf-700">
				<Icon name="check-circle" :size="18" /> {{ labels.mrCompleted }}
			</p>
			<p class="font-mono text-sm text-gray-700">{{ completed.repair_order_id || completed.name }}</p>
			<p v-if="completed.stock_entry" class="font-mono text-[11px] text-gray-500">
				Stock Entry: {{ completed.stock_entry }}
			</p>
		</section>

		<!-- WORKLIST -->
		<section v-if="!order && !completed" class="space-y-3">
			<div class="flex gap-2">
				<input
					v-model="search"
					class="oak-input uppercase"
					:placeholder="labels.mrOrdersSearch"
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
				{{ labels.mrOrdersEmpty }}
			</div>
			<div v-for="o in orders" :key="o.name" class="oak-card flex items-center gap-3 p-4">
				<button class="oak-press flex min-w-0 flex-1 items-center gap-3 text-left" @click="openOrder(o)">
					<span class="oak-icon-tile h-11 w-11 shrink-0 bg-brand-50 text-brand-600">
						<Icon name="tool" :size="20" />
					</span>
					<div class="min-w-0 flex-1">
						<p class="truncate font-bold text-gray-900">{{ o.container_no || o.container }}</p>
						<p class="truncate text-xs text-gray-500">{{ o.repair_order_id }} · {{ o.principal || "—" }}</p>
						<p class="truncate text-[11px] text-gray-400">{{ labels.createdOn }} {{ fmtDate(o.creation) }}</p>
					</div>
				</button>
				<div class="flex shrink-0 flex-col items-end gap-1">
					<span class="oak-chip" :class="statusChipClass(o.status)">{{ repairStatusLabel(o.status) }}</span>
				</div>
			</div>
		</section>

		<!-- FORM -->
		<template v-if="order && !completed">
			<!-- Status + revision / rejected banners -->
			<section
				v-if="order.status === 'Revision Requested'"
				class="oak-card border-amber-200 bg-amber-50 p-3"
			>
				<p class="text-sm font-semibold text-amber-800">{{ labels.mrRevisionBanner }}</p>
				<p v-if="order.owner_note" class="mt-1 text-sm text-amber-700">"{{ order.owner_note }}"</p>
			</section>
			<section
				v-else-if="order.status === 'Rejected'"
				class="oak-card border-red-200 bg-red-50 p-3"
			>
				<p class="text-sm font-semibold text-red-800">{{ labels.mrRejectedBanner }}</p>
				<p v-if="order.owner_note" class="mt-1 text-sm text-red-700">"{{ order.owner_note }}"</p>
			</section>
			<section
				v-else-if="order.status === 'Approved'"
				class="oak-card border-leaf-200 bg-leaf-50 p-3"
			>
				<p class="text-sm font-semibold text-leaf-700">{{ labels.mrApprovedReadonly }}</p>
			</section>

			<!-- Source warehouse (top) -->
			<section class="oak-card p-4 space-y-1">
				<label class="oak-label">{{ labels.mrWarehouse }}</label>
				<SearchSelect
					v-if="canEditWarehouse"
					v-model="warehouse"
					:options="order.warehouses"
					:option-value="(w) => w.name"
					:option-label="(w) => (w.branch ? `${w.warehouse_name} · ${w.branch}` : w.warehouse_name)"
					:placeholder="labels.mrWarehousePick"
					:search-placeholder="labels.selectSearch"
				/>
				<p v-else class="text-sm font-medium text-gray-800">{{ warehouseName(warehouse) || "—" }}</p>
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
				<p v-if="order.inspection" class="mt-2 font-mono text-[11px] text-gray-400">
					{{ labels.mrRefEir }}: {{ order.inspection }}
				</p>
			</section>

			<!-- SECTION 1: EIR damage entries (read-only, copied) -->
			<section class="oak-card p-4 space-y-3">
				<p class="oak-section-title">{{ labels.mrDamagesTitle }}</p>
				<p v-if="!order.damages || !order.damages.length" class="py-2 text-center text-sm text-gray-400">
					{{ labels.mrNoDamages }}
				</p>
				<div v-for="(d, i) in order.damages" :key="i" class="rounded-xl border border-gray-100 p-3 space-y-2">
					<p class="font-semibold text-gray-900">{{ d.component || d.area || "—" }}</p>
					<div class="flex flex-wrap gap-1.5 text-xs">
						<span v-if="d.damage_code" class="oak-chip bg-red-50 text-red-700">
							{{ labels.mrCodeDamage }}: {{ d.damage_code }}<span v-if="d.damage_desc"> — {{ d.damage_desc }}</span>
						</span>
						<span v-if="d.repair_code" class="oak-chip bg-blue-50 text-blue-700">
							{{ labels.mrCodeRepair }}: {{ d.repair_code }}<span v-if="d.repair_desc"> — {{ d.repair_desc }}</span>
						</span>
					</div>
					<p v-if="d.damage_description" class="text-sm text-gray-600">{{ d.damage_description }}</p>
					<div v-if="d.photos && d.photos.length" class="flex flex-wrap gap-2">
						<button v-for="(ph, pi) in d.photos" :key="pi" type="button" class="oak-press" @click="openLightbox(d.photos, pi)">
							<img :src="ph" class="h-20 w-20 rounded-lg border border-gray-200 object-cover" />
						</button>
					</div>
				</div>
			</section>

			<!-- SECTION 2: services & parts used / owner approval -->
			<section class="oak-card p-4 space-y-3">
				<div class="flex items-center justify-between">
					<p class="oak-section-title">{{ isEditable ? labels.mrUsedTitle : labels.mrApprovalTitle }}</p>
					<button v-if="isEditable" class="oak-link text-sm" @click="addUsed">+ {{ labels.mrAddUsed }}</button>
				</div>
				<p v-if="isEditable" class="text-xs text-gray-400">{{ labels.mrUsedHint }}</p>
				<p v-else-if="isPending" class="text-xs text-gray-400">{{ labels.mrApprovalHint }}</p>

				<p v-if="!used.length" class="py-2 text-center text-sm text-gray-400">{{ labels.mrNoUsed }}</p>

				<!-- EDITABLE builder (Draft / Revision Requested) -->
				<template v-if="isEditable">
					<div v-for="(u, i) in used" :key="i" class="rounded-xl border border-gray-100 p-3 space-y-2">
						<div class="flex items-center gap-2">
							<button class="oak-input flex flex-1 items-center justify-between text-left text-sm" @click="openPicker(i)">
								<span :class="u.item ? 'text-gray-800' : 'text-gray-400'">
									{{ u.item ? u.item_name || u.item : labels.mrPickItem }}
								</span>
								<span v-if="u.item && u.on_hand != null" class="shrink-0 text-xs text-gray-400">
									{{ labels.mrOnHand }}: {{ u.on_hand }}
								</span>
							</button>
							<button class="shrink-0 text-gray-400 hover:text-red-500" @click="used.splice(i, 1)">
								<Icon name="trash-2" :size="16" />
							</button>
						</div>

						<div class="flex items-end gap-2">
							<div class="w-24">
								<label class="oak-label">{{ labels.mrQty }}</label>
								<input v-model="u.quantity" type="number" step="1" min="0" class="oak-input" inputmode="decimal" />
							</div>
							<input v-model="u.remark" class="oak-input flex-1 text-sm" :placeholder="labels.mrRemark" />
						</div>

						<!-- Multiple evidence photos (like EIR) -->
						<div>
							<div class="mb-1 flex items-center justify-between">
								<span class="oak-label">{{ labels.mrPhotos }}</span>
								<span v-if="u.uploading" class="text-xs text-gray-400">{{ labels.mrPhotoUploading }}</span>
							</div>
							<div class="flex flex-wrap gap-2">
								<div v-for="(ph, pi) in u.photos" :key="pi" class="relative">
									<button type="button" class="oak-press block" @click="openLightbox(u.photos, pi)">
										<img :src="ph" class="h-16 w-16 rounded-lg border border-gray-200 object-cover" />
									</button>
									<button
										class="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-white text-gray-500 shadow"
										@click="u.photos.splice(pi, 1)"
									>
										<Icon name="x" :size="12" />
									</button>
								</div>
								<label class="flex h-16 w-16 cursor-pointer items-center justify-center rounded-lg border border-dashed border-gray-300 text-gray-400 hover:bg-gray-50">
									<Icon name="camera" :size="20" />
									<input type="file" accept="image/*" capture="environment" class="hidden" @change="onPhotos($event, u)" />
								</label>
							</div>
							<p v-if="u.photoErr" class="mt-1 text-xs text-red-600">{{ u.photoErr }}</p>
						</div>
					</div>
				</template>

				<!-- READ-ONLY / APPROVAL list (Pending Approval, Approved, In Progress) -->
				<template v-else>
					<div
						v-for="(u, i) in used"
						:key="i"
						class="rounded-xl border p-3 space-y-2"
						:class="u.decision === 'Rejected' ? 'border-red-100 bg-red-50/40' : 'border-gray-100'"
					>
						<div class="flex items-start justify-between gap-2">
							<div class="min-w-0">
								<p class="truncate font-semibold text-gray-900">{{ u.item_name || u.item }}</p>
								<p class="text-xs text-gray-500">{{ labels.mrQty }} {{ u.quantity }}</p>
								<p v-if="u.remark" class="text-xs text-gray-400">{{ u.remark }}</p>
							</div>
							<div v-if="isPending" class="flex shrink-0 gap-1">
								<button
									class="oak-chip"
									:class="u.decision === 'Approved' ? 'bg-leaf-100 text-leaf-700' : 'bg-gray-100 text-gray-500'"
									@click="u.decision = 'Approved'"
								>
									{{ labels.mrLineApprove }}
								</button>
								<button
									class="oak-chip"
									:class="u.decision === 'Rejected' ? 'bg-red-100 text-red-700' : 'bg-gray-100 text-gray-500'"
									@click="u.decision = 'Rejected'"
								>
									{{ labels.mrLineReject }}
								</button>
							</div>
							<span v-else class="oak-chip shrink-0" :class="decChipClass(u.decision)">{{ repairStatusLabel(u.decision) }}</span>
						</div>
						<input
							v-if="isPending"
							v-model="u.owner_remark"
							class="oak-input text-sm"
							:placeholder="labels.mrOwnerNotePlaceholder"
						/>
						<div v-if="u.photos && u.photos.length" class="flex flex-wrap gap-2">
							<button v-for="(ph, pi) in u.photos" :key="pi" type="button" class="oak-press" @click="openLightbox(u.photos, pi)">
								<img :src="ph" class="h-16 w-16 rounded-lg border border-gray-200 object-cover" />
							</button>
						</div>
					</div>
				</template>
			</section>

			<!-- Owner note (Pending Approval) -->
			<section v-if="isPending" class="oak-card p-4 space-y-2">
				<label class="oak-label">{{ labels.mrOwnerNote }}</label>
				<textarea v-model="ownerNote" rows="2" class="oak-input" :placeholder="labels.mrOwnerNotePlaceholder"></textarea>
			</section>

			<!-- General remarks (editable while building) -->
			<section v-if="isEditable" class="oak-card p-4 space-y-2">
				<label class="oak-label">{{ labels.reffDoc }}</label>
				<input v-model.trim="reffDoc" type="text" class="oak-input" :placeholder="labels.reffDocAutoHint" />
				<label class="oak-label">{{ labels.mrRemarks }}</label>
				<textarea v-model="remarks" rows="2" class="oak-input"></textarea>
			</section>

			<!-- Auto-save status (while building the estimate) -->
			<p v-if="isEditable" class="flex items-center gap-1.5 text-xs">
				<span v-if="saveRes.loading" class="text-gray-400">{{ labels.savingDraft }}</span>
				<span v-else-if="savedOk" class="inline-flex items-center gap-1 text-leaf-600">
					<Icon name="check" :size="13" /> {{ labels.draftSaved }}
				</span>
				<span v-else class="text-gray-400">{{ labels.autosaveHint }}</span>
			</p>

			<!-- Actions by status -->
			<div class="flex gap-2">
				<template v-if="isEditable">
					<button
						class="oak-btn oak-btn-primary flex-1 py-3"
						:disabled="submitRes.loading || saveRes.loading || !used.length"
						@click="confirmSubmitApproval"
					>
						<Icon v-if="submitRes.loading" name="loader" :size="18" class="animate-spin" />
						<span v-else>{{ labels.mrSubmitApproval }}</span>
					</button>
				</template>
				<template v-else-if="isPending">
					<button class="oak-btn oak-btn-secondary flex-1 py-2.5 text-sm" :disabled="decisionRes.loading" @click="decide('Rejected')">
						{{ labels.mrReject }}
					</button>
					<button class="oak-btn oak-btn-secondary flex-1 py-2.5 text-sm" :disabled="decisionRes.loading" @click="decide('Revision Requested')">
						{{ labels.mrRequestRevision }}
					</button>
					<button class="oak-btn oak-btn-primary flex-1 py-2.5 text-sm" :disabled="decisionRes.loading" @click="decide('Approved')">
						<Icon v-if="decisionRes.loading" name="loader" :size="16" class="animate-spin" />
						<span v-else>{{ labels.mrApprove }}</span>
					</button>
				</template>
				<template v-else-if="isApproved">
					<button class="oak-btn oak-btn-primary flex-1 py-3" :disabled="startRes.loading" @click="startCurrent">
						<Icon v-if="startRes.loading" name="loader" :size="18" class="animate-spin" />
						<span v-else>{{ labels.mrStartFull }}</span>
					</button>
				</template>
				<template v-else-if="isInProgress">
					<button class="oak-btn oak-btn-primary flex-1 py-3" :disabled="saveRes.loading" @click="confirmComplete">
						<Icon v-if="saveRes.loading" name="loader" :size="18" class="animate-spin" />
						<span v-else>{{ labels.mrComplete }}</span>
					</button>
				</template>
			</div>
		</template>

		<!-- Item picker overlay -->
		<div
			v-if="pickerOpen"
			class="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-4"
			@click.self="closePicker"
		>
			<div class="w-full max-w-lg rounded-t-2xl bg-white p-4 shadow-xl sm:rounded-2xl">
				<div class="mb-3 flex items-center gap-2">
					<input v-model="itemSearch" class="oak-input flex-1" :placeholder="labels.mrSearchItem" @keyup.enter="searchItems" />
					<button class="oak-btn oak-btn-secondary shrink-0 px-3" @click="searchItems">
						<Icon name="search" :size="16" />
					</button>
					<button class="shrink-0 text-gray-400" @click="closePicker">
						<Icon name="x" :size="20" />
					</button>
				</div>
				<div class="max-h-80 space-y-1 overflow-y-auto">
					<div v-if="itemsRes.loading" class="p-6 text-center text-gray-400">
						<Icon name="loader" :size="20" class="animate-spin" />
					</div>
					<div v-else-if="!itemList.length" class="p-6 text-center text-gray-400">{{ labels.mrItemsEmpty }}</div>
					<button
						v-for="it in itemList"
						:key="it.item_code"
						class="flex w-full items-center justify-between gap-2 rounded-lg border border-gray-100 p-2.5 text-left hover:bg-gray-50"
						@click="pickItem(it)"
					>
						<div class="min-w-0">
							<p class="truncate text-sm font-medium text-gray-800">{{ it.item_name || it.item_code }}</p>
							<p class="truncate font-mono text-[11px] text-gray-400">
								{{ it.item_code }}<span v-if="it.is_stock_item"> · stok</span>
							</p>
						</div>
						<span v-if="it.on_hand != null" class="shrink-0 text-xs text-gray-500">{{ labels.mrOnHand }}: {{ it.on_hand }}</span>
					</button>
				</div>
			</div>
		</div>
	</div>
</template>

<script setup>
import { computed, nextTick, reactive, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { createResource } from "frappe-ui"
import { labels, repairStatusLabel } from "@/utils/labels"
import { toast } from "@/utils/toast"
import { openLightbox } from "@/utils/lightbox"
import { confirm } from "@/utils/confirm"
import Icon from "@/components/Icon.vue"
import SearchSelect from "@/components/SearchSelect.vue"

const route = useRoute()
const router = useRouter()

const fmtDate = (v) => (v ? String(v).slice(0, 10) : "—")

const search = ref("")
const orders = ref([])
const order = ref(null)
const completed = ref(null)

const warehouse = ref("")
const reffDoc = ref("")
const used = ref([])
const remarks = ref("")
const ownerNote = ref("")

// Auto-save (mirrors the EIR flow): debounced draft save while building the estimate.
let saveTimer = null
const savedOk = ref(false) // last auto-save succeeded
const suppressSave = ref(false) // mute auto-save while a draft is being loaded

// --- status-driven view flags ----------------------------------------------
const isEditable = computed(() => ["Draft", "Revision Requested"].includes(order.value?.status))
const isPending = computed(() => order.value?.status === "Pending Approval")
const isApproved = computed(() => order.value?.status === "Approved")
const isInProgress = computed(() => order.value?.status === "In Progress")
const canEditWarehouse = computed(() => isEditable.value || isInProgress.value)

function warehouseName(name) {
	const w = (order.value?.warehouses || []).find((x) => x.name === name)
	return w ? w.warehouse_name : name
}
function decChipClass(d) {
	if (d === "Approved") return "bg-leaf-100 text-leaf-700"
	if (d === "Rejected") return "bg-red-100 text-red-700"
	return "bg-gray-100 text-gray-500"
}
function statusChipClass(s) {
	if (s === "Pending Approval" || s === "Revision Requested") return "bg-amber-50 text-amber-700"
	if (s === "Approved") return "bg-leaf-50 text-leaf-700"
	if (s === "In Progress") return "bg-indigo-50 text-indigo-700"
	if (s === "Rejected") return "bg-red-50 text-red-700"
	return "bg-gray-100 text-gray-600"
}

const ordersRes = createResource({
	url: "container_depot.ess.repairs.mr_orders",
	method: "GET",
	auto: true,
	onSuccess: (data) => (orders.value = data.items || []),
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

const detailRes = createResource({
	url: "container_depot.ess.repairs.mr_order_detail",
	method: "GET",
	onSuccess(data) {
		// Mute auto-save while we populate the form from the loaded order.
		suppressSave.value = true
		savedOk.value = false
		order.value = data
		warehouse.value = data.warehouse || ""
		reffDoc.value = data.reff_doc || ""
		remarks.value = data.remarks || ""
		ownerNote.value = ""
		used.value = (data.used_items || []).map((u) =>
			reactive({ ...u, decision: u.decision || "Pending", photos: [...(u.photos || [])], uploading: false, photoErr: "" })
		)
		nextTick(() => {
			suppressSave.value = false
		})
	},
	onError: (err) => toast.error(err?.messages?.[0] || err?.message || labels.error),
})

// The open order lives in the URL (?o=<name>) so a refresh restores the detail view
// instead of dropping back to the worklist.
function openOrder(o) {
	router.push({ query: { o: o.name } })
}

watch(
	() => route.query.o,
	(o) => {
		if (o) {
			if (order.value?.name !== o) {
				completed.value = null
				detailRes.fetch({ repair_order: o })
			}
		} else {
			order.value = null
		}
	},
	{ immediate: true }
)

function addUsed() {
	used.value.push(reactive({ item: null, item_name: "", quantity: 1, remark: "", on_hand: null, photos: [], uploading: false, photoErr: "" }))
}

// --- start (Approved -> In Progress) ----------------------------------------
const startRes = createResource({
	url: "container_depot.ess.repairs.mr_start",
	method: "POST",
	onSuccess: () => toast.success(labels.mrStarted),
	onError: (err) => toast.error(err?.messages?.[0] || err?.message || labels.error),
})

function startCurrent() {
	if (!order.value) return
	startRes.fetch({ repair_order: order.value.name }).then(() => detailRes.fetch({ repair_order: order.value.name }))
}

// --- submit for approval (Draft/Revision -> Pending Approval) ---------------
const submitRes = createResource({
	url: "container_depot.ess.repairs.mr_submit_approval",
	method: "POST",
	onSuccess() {
		// Submitted to the owner → drop back to the worklist with a toast.
		toast.success(labels.mrSubmittedToast)
		if (route.query.o) router.replace({ query: {} })
		order.value = null
		reloadOrders()
	},
	onError: (err) => toast.error(err?.messages?.[0] || err?.message || labels.error),
})

function submitForApproval() {
	if (!order.value || !used.value.length) return
	// Persist the estimate first, then submit it to the owner.
	saveDraft().then(() => submitRes.fetch({ repair_order: order.value.name }))
}

// Both irreversible submits ask for an explicit confirmation first.
async function confirmSubmitApproval() {
	if (!order.value || !used.value.length) return
	const ok = await confirm({
		title: labels.confirmSubmitTitle,
		message: labels.confirmSubmitMessage,
		confirmLabel: labels.confirmSubmitYes,
		cancelLabel: labels.confirmCancel,
	})
	if (ok) submitForApproval()
}
async function confirmComplete() {
	const ok = await confirm({
		title: labels.confirmSubmitTitle,
		message: labels.confirmSubmitMessage,
		confirmLabel: labels.confirmSubmitYes,
		cancelLabel: labels.confirmCancel,
	})
	if (ok) complete()
}

// --- owner decision (Pending Approval -> Approved/Rejected/Revision) ---------
const decisionRes = createResource({
	url: "container_depot.ess.repairs.mr_decision",
	method: "POST",
	onSuccess() {
		toast.success(labels.mrDecisionToast)
		detailRes.fetch({ repair_order: order.value.name })
		reloadOrders()
	},
	onError: (err) => toast.error(err?.messages?.[0] || err?.message || labels.error),
})

function decide(decision) {
	if (!order.value) return
	const lineDecisions = used.value.map((u) => ({ decision: u.decision || "Pending", owner_remark: u.owner_remark || "" }))
	decisionRes.fetch({
		repair_order: order.value.name,
		decision,
		line_decisions: JSON.stringify(lineDecisions),
		note: ownerNote.value || undefined,
	})
}

// --- save draft / complete --------------------------------------------------
const saveRes = createResource({
	url: "container_depot.ess.repairs.mr_order_save",
	method: "POST",
	onSuccess(data) {
		if (data.status === "Completed") {
			// Finalized → drop back to the worklist with a toast.
			completed.value = null
			order.value = null
			if (route.query.o) router.replace({ query: {} })
			toast.success(labels.mrCompleted, { title: data.repair_order_id || data.name })
			reloadOrders()
		} else {
			savedOk.value = true // auto-save / manual save succeeded (no toast)
		}
	},
	onError: (err) => toast.error(err?.messages?.[0] || err?.message || labels.error),
})

// Debounced auto-save while building the estimate (Draft / Revision Requested only).
function scheduleSave() {
	if (!order.value || !isEditable.value || suppressSave.value) return
	savedOk.value = false
	if (saveTimer) clearTimeout(saveTimer)
	saveTimer = setTimeout(() => saveDraft(), 700)
}

function saveDraft() {
	if (!order.value) return Promise.resolve()
	if (saveTimer) {
		clearTimeout(saveTimer)
		saveTimer = null
	}
	const items = used.value
		.filter((u) => u.item)
		.map((u) => ({
			item: u.item,
			quantity: u.quantity !== "" ? u.quantity : undefined,
			remark: u.remark || undefined,
			photos: u.photos || [],
		}))
	return saveRes.fetch({
		repair_order: order.value.name,
		used_items: JSON.stringify(items),
		warehouse: warehouse.value || undefined,
		reff_doc: reffDoc.value,
		remarks: remarks.value || undefined,
		submit: 0,
	})
}

// Complete from In Progress — issues approved parts. Used items aren't editable here,
// so only the source warehouse is sent alongside the submit flag.
function complete() {
	if (!order.value) return
	saveRes.fetch({ repair_order: order.value.name, warehouse: warehouse.value || undefined, submit: 1 })
}

// Auto-save while building: the used items (qty / remark / photos), the source warehouse
// and the general remarks each trigger a debounced draft save.
watch([warehouse, reffDoc, remarks], scheduleSave)
watch(used, scheduleSave, { deep: true })

function backToList() {
	// Clearing the form must never trigger an auto-save of the emptied fields.
	if (saveTimer) {
		clearTimeout(saveTimer)
		saveTimer = null
	}
	suppressSave.value = true
	savedOk.value = false
	completed.value = null
	used.value = []
	warehouse.value = ""
	reffDoc.value = ""
	remarks.value = ""
	ownerNote.value = ""
	if (route.query.o) router.push({ query: {} })
	else order.value = null
	reloadOrders()
}

// --- evidence photo upload (multiple per used item) -------------------------
async function uploadFile(file) {
	const fd = new FormData()
	fd.append("file", file, file.name)
	fd.append("is_private", 1)
	fd.append("folder", "Home")
	const res = await fetch("/api/method/upload_file", {
		method: "POST",
		headers: { "X-Frappe-CSRF-Token": window.csrf_token || "" },
		body: fd,
	})
	if (!res.ok) throw new Error("upload failed")
	const data = await res.json()
	return data.message.file_url
}

async function onPhotos(e, row) {
	const files = Array.from(e.target.files || [])
	e.target.value = ""
	if (!files.length) return
	row.photoErr = ""
	row.uploading = true
	try {
		for (const f of files) {
			const url = await uploadFile(f)
			row.photos.push(url)
		}
	} catch (err) {
		row.photoErr = labels.mrPhotoError
	} finally {
		row.uploading = false
	}
}

// --- item picker (service or part, owner-priced) ----------------------------
const pickerOpen = ref(false)
const pickerRow = ref(-1)
const itemSearch = ref("")
const itemList = ref([])

const itemsRes = createResource({
	url: "container_depot.ess.repairs.mr_items",
	method: "GET",
	onSuccess: (data) => (itemList.value = data.items || []),
	onError: (err) => toast.error(err?.messages?.[0] || err?.message || labels.error),
})

function pickerParams() {
	const p = { repair_order: order.value?.name }
	const s = itemSearch.value.trim()
	if (s) p.search = s
	return p
}
function openPicker(i) {
	pickerRow.value = i
	pickerOpen.value = true
	itemSearch.value = ""
	itemList.value = []
	itemsRes.fetch(pickerParams())
}
function closePicker() {
	pickerOpen.value = false
	pickerRow.value = -1
}
function searchItems() {
	itemsRes.fetch(pickerParams())
}
function pickItem(it) {
	const row = used.value[pickerRow.value]
	if (row) {
		row.item = it.item_code
		row.item_name = it.item_name || it.item_code
		row.on_hand = it.on_hand
	}
	closePicker()
}
</script>
