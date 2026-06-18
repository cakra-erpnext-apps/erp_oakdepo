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
			<button v-if="order" class="oak-btn oak-btn-secondary px-3 py-2" @click="backToList">
				<Icon name="arrow-left" :size="16" /> {{ labels.mrBack }}
			</button>
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
					</div>
				</button>
				<button
					v-if="o.status !== 'In Progress'"
					class="oak-btn oak-btn-secondary shrink-0 px-3 py-1.5 text-xs"
					:disabled="startRes.loading"
					@click.stop="startOrder(o)"
				>
					{{ labels.mrStart }}
				</button>
				<span v-else class="oak-chip shrink-0 bg-amber-50 text-amber-700">{{ labels.mrInProgress }}</span>
			</div>
		</section>

		<!-- FORM -->
		<template v-if="order && !completed">
			<!-- Source warehouse (top) -->
			<section class="oak-card p-4 space-y-1">
				<label class="oak-label">{{ labels.mrWarehouse }}</label>
				<select v-model="warehouse" class="oak-input">
					<option value="">— {{ labels.mrWarehousePick }} —</option>
					<option v-for="w in order.warehouses" :key="w.name" :value="w.name">
						{{ w.warehouse_name }}<span v-if="w.branch"> · {{ w.branch }}</span>
					</option>
				</select>
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
						<a v-for="(ph, pi) in d.photos" :key="pi" :href="ph" target="_blank" rel="noopener">
							<img :src="ph" class="h-20 w-20 rounded-lg border border-gray-200 object-cover" />
						</a>
					</div>
				</div>
			</section>

			<!-- SECTION 2: services & parts used (owner Item Price) -->
			<section class="oak-card p-4 space-y-3">
				<div class="flex items-center justify-between">
					<p class="oak-section-title">{{ labels.mrUsedTitle }}</p>
					<button class="oak-link text-sm" @click="addUsed">+ {{ labels.mrAddUsed }}</button>
				</div>
				<p class="text-xs text-gray-400">{{ labels.mrUsedHint }}</p>

				<p v-if="!used.length" class="py-2 text-center text-sm text-gray-400">{{ labels.mrNoUsed }}</p>
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
								<a :href="ph" target="_blank" rel="noopener">
									<img :src="ph" class="h-16 w-16 rounded-lg border border-gray-200 object-cover" />
								</a>
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
			</section>

			<!-- General remarks -->
			<section class="oak-card p-4 space-y-2">
				<label class="oak-label">{{ labels.mrRemarks }}</label>
				<textarea v-model="remarks" rows="2" class="oak-input"></textarea>
			</section>

			<!-- Actions -->
			<p v-if="order.status !== 'In Progress'" class="text-center text-xs text-amber-600">{{ labels.mrStartFirst }}</p>
			<div class="flex gap-2">
				<button class="oak-btn oak-btn-secondary flex-1 py-3" :disabled="saveRes.loading" @click="save(false)">
					{{ labels.mrSave }}
				</button>
				<button
					v-if="order.status !== 'In Progress'"
					class="oak-btn oak-btn-primary flex-1 py-3"
					:disabled="startRes.loading"
					@click="startCurrent"
				>
					<Icon v-if="startRes.loading" name="loader" :size="18" class="animate-spin" />
					<span v-else>{{ labels.mrStartFull }}</span>
				</button>
				<button v-else class="oak-btn oak-btn-primary flex-1 py-3" :disabled="saveRes.loading" @click="save(true)">
					<Icon v-if="saveRes.loading" name="loader" :size="18" class="animate-spin" />
					<span v-else>{{ labels.mrComplete }}</span>
				</button>
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
import { computed, reactive, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { createResource } from "frappe-ui"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
import Icon from "@/components/Icon.vue"

const route = useRoute()
const router = useRouter()

const search = ref("")
const orders = ref([])
const order = ref(null)
const completed = ref(null)

const warehouse = ref("")
const used = ref([])
const remarks = ref("")

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
		order.value = data
		warehouse.value = data.warehouse || ""
		remarks.value = data.remarks || ""
		used.value = (data.used_items || []).map((u) =>
			reactive({ ...u, photos: [...(u.photos || [])], uploading: false, photoErr: "" })
		)
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

// --- start ------------------------------------------------------------------
const startRes = createResource({
	url: "container_depot.ess.repairs.mr_start",
	method: "POST",
	onSuccess: () => toast.success(labels.mrStarted),
	onError: (err) => toast.error(err?.messages?.[0] || err?.message || labels.error),
})

function startOrder(o) {
	startRes.fetch({ repair_order: o.name }).then(reloadOrders)
}
function startCurrent() {
	if (!order.value) return
	startRes.fetch({ repair_order: order.value.name }).then(() => detailRes.fetch({ repair_order: order.value.name }))
}

// --- save / complete --------------------------------------------------------
const saveRes = createResource({
	url: "container_depot.ess.repairs.mr_order_save",
	method: "POST",
	onSuccess(data) {
		if (data.status === "Completed") {
			completed.value = data
			order.value = null
			if (route.query.o) router.replace({ query: {} })
			toast.success(labels.mrCompleted, { title: data.repair_order_id || data.name })
			reloadOrders()
		} else {
			toast.success(labels.mrSaved)
		}
	},
	onError: (err) => toast.error(err?.messages?.[0] || err?.message || labels.error),
})

function save(submit) {
	if (!order.value) return
	const items = used.value
		.filter((u) => u.item)
		.map((u) => ({
			item: u.item,
			quantity: u.quantity !== "" ? u.quantity : undefined,
			remark: u.remark || undefined,
			photos: u.photos || [],
		}))
	saveRes.fetch({
		repair_order: order.value.name,
		used_items: JSON.stringify(items),
		warehouse: warehouse.value || undefined,
		remarks: remarks.value || undefined,
		submit: submit ? 1 : 0,
	})
}

function backToList() {
	completed.value = null
	used.value = []
	warehouse.value = ""
	remarks.value = ""
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
