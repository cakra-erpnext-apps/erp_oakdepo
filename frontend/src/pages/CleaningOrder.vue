<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<!-- Header -->
		<div class="flex items-center justify-between">
			<div class="min-w-0">
				<h1 class="truncate text-xl font-extrabold tracking-tight text-gray-900">
					{{ labels.cleaningTitle }}
				</h1>
				<p v-if="order" class="truncate font-mono text-[11px] text-gray-500">
					{{ order.order_id }} · {{ order.container_no }}
				</p>
				<p v-else class="text-sm text-gray-500">{{ labels.cleaningOrdersHint }}</p>
			</div>
			<div class="flex shrink-0 items-center gap-2">
				<router-link v-if="!order" to="/cleaning/history" class="oak-btn oak-btn-secondary px-3 py-2">
					<Icon name="clock" :size="16" /> {{ labels.navHistory }}
				</router-link>
				<button v-if="order" class="oak-btn oak-btn-secondary px-3 py-2" @click="backToList">
					<Icon name="arrow-left" :size="16" /> {{ labels.cleaningBack }}
				</button>
			</div>
		</div>

		<!-- Submitted confirmation -->
		<section v-if="submitted" class="oak-card border-leaf-200 bg-leaf-50 p-4 space-y-2">
			<p class="font-bold text-leaf-700">
				<Icon name="check-circle" :size="18" /> {{ labels.cleaningSubmitted }}
			</p>
			<p class="font-mono text-sm text-gray-700">{{ submitted.order_id || submitted.name }}</p>
			<a :href="printUrl" target="_blank" rel="noopener" class="oak-btn oak-btn-secondary inline-flex px-3 py-2">
				<Icon name="printer" :size="16" /> {{ labels.cleaningPrint }}
			</a>
		</section>

		<!-- WORKLIST -->
		<section v-if="!order && !submitted" class="space-y-3">
			<div class="flex gap-2">
				<input
					v-model="search"
					class="oak-input uppercase"
					:placeholder="labels.cleaningOrdersSearch"
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
				{{ labels.cleaningOrdersEmpty }}
			</div>
			<div v-for="o in orders" :key="o.name" class="oak-card flex items-center gap-3 p-4">
				<button class="oak-press flex min-w-0 flex-1 items-center gap-3 text-left" @click="openOrder(o)">
					<span class="oak-icon-tile h-11 w-11 shrink-0 bg-brand-50 text-brand-600">
						<Icon name="droplet" :size="20" />
					</span>
					<div class="min-w-0 flex-1">
						<p class="truncate font-bold text-gray-900">{{ o.container_no || o.container }}</p>
						<p class="truncate text-xs text-gray-500">
							{{ o.order_id }}<template v-if="o.service_count"> · {{ o.service_count }} {{ labels.cleaningServicesCount }}</template><template v-else-if="o.cleaning_type"> · {{ o.cleaning_type }}</template>
							<span v-if="o.last_cargo"> · {{ o.last_cargo }}</span>
						</p>
						<p class="truncate text-[11px] text-gray-400">{{ labels.createdOn }} {{ fmtDate(o.order_created) }}</p>
					</div>
				</button>
				<button
					v-if="o.status !== 'In_Progress'"
					class="oak-btn oak-btn-secondary shrink-0 px-3 py-1.5 text-xs"
					:disabled="startRes.loading"
					@click.stop="startOrder(o)"
				>
					{{ labels.cleaningStart }}
				</button>
				<span v-else class="oak-chip shrink-0 bg-amber-50 text-amber-700">{{ labels.cleaningInProgress }}</span>
			</div>
		</section>

		<!-- FORM -->
		<template v-if="order && !submitted">
			<!-- GATE: the order must be started before its detail is accessible. -->
			<section v-if="order.status !== 'In_Progress'" class="oak-card space-y-4 p-5 text-center">
				<span class="oak-icon-tile mx-auto h-14 w-14 bg-brand-50 text-brand-600"><Icon name="droplet" :size="26" /></span>
				<div class="space-y-1">
					<p class="font-bold text-gray-900">{{ order.container_no || order.container }}</p>
					<p class="font-mono text-xs text-gray-400">{{ order.order_id }}</p>
					<p class="text-sm text-gray-500">{{ labels.cleaningStartGate }}</p>
				</div>
				<button
					class="oak-btn oak-btn-primary w-full py-3 text-base"
					:disabled="startRes.loading"
					@click="startCurrent"
				>
					<Icon v-if="startRes.loading" name="loader" :size="18" class="animate-spin" />
					<span v-else>{{ labels.cleaningStartFull }}</span>
				</button>
			</section>

			<!-- Detail — read-only tank/method/cargo info; the operator only signs off. -->
			<template v-else>
			<!-- Cleaning method = the service(s) Admin Ops chose (read-only for the operator). -->
			<section class="oak-card p-4 space-y-3">
				<p class="oak-section-title">{{ labels.cleaningType }}</p>
				<div v-if="order.cleaning_services && order.cleaning_services.length" class="flex flex-wrap gap-1.5">
					<span
						v-for="s in order.cleaning_services"
						:key="s.item_code"
						class="inline-flex items-center rounded-full bg-brand-100 px-2.5 py-1 text-xs font-medium text-brand-700"
					>
						{{ s.item_name || s.item_code }}
					</span>
				</div>
				<p v-else class="text-sm text-gray-400">{{ labels.cleaningNoMethod }}</p>
			</section>

			<!-- Tank header -->
			<section class="oak-card p-4">
				<p class="oak-section-title mb-2">{{ labels.cleaningTankDetails }}</p>
				<dl class="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
					<div v-for="cell in headerCells" :key="cell.label" class="min-w-0">
						<dt class="text-xs text-gray-400">{{ cell.label }}</dt>
						<dd class="truncate font-medium text-gray-800">{{ cell.value || "—" }}</dd>
					</div>
				</dl>
				<p v-if="order.inspection" class="mt-2 font-mono text-[11px] text-gray-400">
					{{ labels.cleaningRefEir }}: {{ order.inspection }}
				</p>
				<p v-if="order.reff_doc" class="font-mono text-[11px] text-gray-400">
					{{ labels.reffDoc }}: {{ order.reff_doc }}
				</p>
			</section>

			<!-- Cargo history -->
			<section class="oak-card p-4">
				<p class="oak-section-title mb-2">{{ labels.cleaningCargoHistory }}</p>
				<ul v-if="order.cargo_history && order.cargo_history.length" class="space-y-1 text-sm">
					<li v-for="(h, i) in order.cargo_history" :key="i" class="flex justify-between gap-2">
						<span class="truncate font-medium text-gray-800">{{ h.cargo }}</span>
						<span class="shrink-0 text-xs text-gray-400">{{ h.date }}</span>
					</li>
				</ul>
				<p v-else class="text-sm text-gray-400">{{ labels.cleaningNoCargoHistory }}</p>
			</section>

			<!-- Catatan -->
			<section class="oak-card p-4 space-y-2">
				<label class="oak-label">{{ labels.eirRemarks }}</label>
				<textarea v-model="remarks" rows="3" class="oak-input"></textarea>
			</section>

			<!-- Tanda Tangan -->
			<section class="oak-card p-4 space-y-2">
				<div class="flex items-center justify-between">
					<p class="oak-section-title">{{ labels.cleaningSignature }}</p>
					<button v-if="signatureUrl" type="button" class="oak-link text-sm" @click="startResign">
						{{ labels.cleaningResign }}
					</button>
				</div>
				<div v-if="signatureUrl && !signing">
					<img :src="signatureUrl" class="h-28 w-full rounded-xl border border-gray-200 bg-white object-contain" />
				</div>
				<div v-else>
					<canvas
						ref="sigCanvas"
						class="h-28 w-full touch-none rounded-xl border border-dashed border-gray-300 bg-white"
						@pointerdown="sigDown"
						@pointermove="sigMove"
						@pointerup="sigUp"
						@pointerleave="sigUp"
					></canvas>
					<div class="mt-1 flex items-center justify-between text-xs text-gray-400">
						<span v-if="sigUploading">{{ labels.cleaningUploading }}</span>
						<span v-else-if="sigErr" class="text-red-600">{{ sigErr }}</span>
						<span v-else>{{ labels.signHint }}</span>
						<button type="button" class="text-gray-600 underline underline-offset-2" @click="clearSignature">
							{{ labels.clear }}
						</button>
					</div>
				</div>
			</section>

			<!-- Auto-save status (Catatan + Tanda Tangan persist on every edit) -->
			<p class="flex items-center gap-1.5 text-xs">
				<span v-if="saveRes.loading" class="text-gray-400">{{ labels.savingDraft }}</span>
				<span v-else-if="savedOk" class="inline-flex items-center gap-1 text-leaf-600">
					<Icon name="check" :size="13" /> {{ labels.draftSaved }}
				</span>
				<span v-else class="text-gray-400">{{ labels.autosaveHint }}</span>
			</p>

			<!-- Finalize — the order is already In_Progress inside this branch. -->
			<button class="oak-btn oak-btn-primary w-full py-3" :disabled="saveRes.loading" @click="confirmComplete">
				<Icon v-if="saveRes.loading" name="loader" :size="18" class="animate-spin" />
				<span v-else>{{ labels.cleaningComplete }}</span>
			</button>
			</template>
		</template>
	</div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { createResource } from "frappe-ui"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
import { confirm } from "@/utils/confirm"
import Icon from "@/components/Icon.vue"

const route = useRoute()
const router = useRouter()

const fmtDate = (v) => (v ? String(v).slice(0, 10) : "—")

const search = ref("")
const orders = ref([])
const order = ref(null)
const submitted = ref(null)

// Auto-save (mirrors the EIR flow): debounced draft save on every edit.
let saveTimer = null
const savedOk = ref(false) // last auto-save succeeded
const suppressSave = ref(false) // mute auto-save while a draft is being loaded

// The operator only signs off now: Catatan (remarks) + Tanda Tangan (signature). The cleaning
// method(s) are chosen upstream by Admin Ops and shown read-only.
const remarks = ref("")

const printUrl = computed(() =>
	submitted.value
		? `/api/method/frappe.utils.print_format.download_pdf?doctype=Cleaning%20Order&name=${encodeURIComponent(
				submitted.value.name
		  )}&format=Cleaning%20Order%20Format&no_letterhead=1`
		: "#"
)

const ordersRes = createResource({
	url: "container_depot.ess.cleaning.cleaning_orders",
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
		{ label: labels.cleaningTare, value: h.tare },
		{ label: labels.cleaningMgw, value: h.mgw },
		{ label: labels.cleaningPrevCargo, value: h.previous_cargo },
		{ label: labels.cleaningMfgDate, value: h.date_of_manufacture },
		{ label: labels.cleaningLastTest, value: h.last_test_date },
	]
})

const detailRes = createResource({
	url: "container_depot.ess.cleaning.cleaning_order_detail",
	method: "GET",
	onSuccess(data) {
		// Mute auto-save while we populate the form from the loaded order.
		suppressSave.value = true
		savedOk.value = false
		order.value = data
		remarks.value = data.remarks || data.default_remarks || ""
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
				submitted.value = null
				detailRes.fetch({ cleaning_order: o })
			}
		} else {
			order.value = null
		}
	},
	{ immediate: true }
)

// Mulai Cleaning (worklist or in-form)
const startRes = createResource({
	url: "container_depot.ess.cleaning.cleaning_start",
	method: "POST",
	onSuccess() {
		toast.success(labels.cleaningStarted)
	},
	onError: (err) => toast.error(err?.messages?.[0] || err?.message || labels.error),
})

function startOrder(o) {
	startRes.fetch({ cleaning_order: o.name }).then(reloadOrders)
}
function startCurrent() {
	if (!order.value) return
	startRes.fetch({ cleaning_order: order.value.name }).then(() => detailRes.fetch({ cleaning_order: order.value.name }))
}

const saveRes = createResource({
	url: "container_depot.ess.cleaning.cleaning_order_save",
	method: "POST",
	onSuccess(data) {
		if (data.docstatus === 1) {
			// Finalized → drop back to the worklist with a toast (print stays in Riwayat).
			submitted.value = null
			order.value = null
			if (route.query.o) router.replace({ query: {} })
			toast.success(labels.cleaningSubmitted, { title: data.order_id || data.name })
			reloadOrders()
		} else {
			savedOk.value = true // auto-save / manual save succeeded (no toast)
		}
	},
	onError: (err) => toast.error(err?.messages?.[0] || err?.message || labels.error),
})

// Debounced auto-save on every edit (mirrors EIR): only while an unfinished order is open.
function scheduleSave() {
	if (!order.value || order.value.docstatus === 1 || suppressSave.value) return
	savedOk.value = false
	if (saveTimer) clearTimeout(saveTimer)
	saveTimer = setTimeout(() => save(false), 700)
}

// Finalize (Selesaikan) asks for an explicit confirmation first.
async function confirmComplete() {
	const ok = await confirm({
		title: labels.confirmSubmitTitle,
		message: labels.confirmSubmitMessage,
		confirmLabel: labels.confirmSubmitYes,
		cancelLabel: labels.confirmCancel,
	})
	if (ok) save(true)
}

function save(submit) {
	if (!order.value) return
	if (saveTimer) {
		clearTimeout(saveTimer)
		saveTimer = null
	}
	saveRes.fetch({
		cleaning_order: order.value.name,
		remarks: remarks.value || undefined,
		signature: signatureUrl.value || undefined,
		submit: submit ? 1 : 0,
	})
}

function backToList() {
	submitted.value = null
	resetForm()
	if (route.query.o) router.push({ query: {} })
	else order.value = null
	reloadOrders()
}

function resetForm() {
	// Clearing the form must never trigger an auto-save of the emptied fields.
	if (saveTimer) {
		clearTimeout(saveTimer)
		saveTimer = null
	}
	suppressSave.value = true
	savedOk.value = false
	remarks.value = ""
	signatureUrl.value = ""
	signing.value = false
}

// --- file upload + virtual signature pad ------------------------------------
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

const sigCanvas = ref(null)
const signatureUrl = ref("")
const signing = ref(false)
const sigUploading = ref(false)
const sigErr = ref("")
let sigCtx = null
let sigDrawing = false
let sigHasInk = false
let sigTimer = null

function sigCtxInit() {
	const c = sigCanvas.value
	if (!c) return null
	if (sigCtx && sigCtx.canvas === c) return sigCtx
	const ratio = window.devicePixelRatio || 1
	c.width = c.clientWidth * ratio
	c.height = c.clientHeight * ratio
	const ctx = c.getContext("2d")
	ctx.scale(ratio, ratio)
	ctx.lineWidth = 2
	ctx.lineCap = "round"
	ctx.lineJoin = "round"
	ctx.strokeStyle = "#111827"
	sigCtx = ctx
	return ctx
}

function sigPos(e) {
	const r = sigCanvas.value.getBoundingClientRect()
	return { x: e.clientX - r.left, y: e.clientY - r.top }
}

function sigDown(e) {
	const ctx = sigCtxInit()
	if (!ctx) return
	sigDrawing = true
	const p = sigPos(e)
	ctx.beginPath()
	ctx.moveTo(p.x, p.y)
	sigCanvas.value.setPointerCapture?.(e.pointerId)
}

function sigMove(e) {
	if (!sigDrawing || !sigCtx) return
	const p = sigPos(e)
	sigCtx.lineTo(p.x, p.y)
	sigCtx.stroke()
	sigHasInk = true
}

function sigUp() {
	if (!sigDrawing) return
	sigDrawing = false
	if (!sigHasInk) return
	if (sigTimer) clearTimeout(sigTimer)
	sigTimer = setTimeout(uploadSignature, 600)
}

async function uploadSignature() {
	const c = sigCanvas.value
	if (!c || !sigHasInk) return
	sigErr.value = ""
	sigUploading.value = true
	try {
		const blob = await new Promise((res) => c.toBlob(res, "image/png"))
		signatureUrl.value = await uploadFile(new File([blob], "cleaning-signature.png", { type: "image/png" }))
		signing.value = false
	} catch (e) {
		sigErr.value = labels.signatureError
	} finally {
		sigUploading.value = false
	}
}

function clearSignature() {
	if (sigTimer) clearTimeout(sigTimer)
	const ctx = sigCtxInit()
	if (ctx && sigCanvas.value) ctx.clearRect(0, 0, sigCanvas.value.width, sigCanvas.value.height)
	sigHasInk = false
	signatureUrl.value = ""
}

function startResign() {
	signatureUrl.value = ""
	signing.value = true
	sigHasInk = false
	sigCtx = null
	nextTick(sigCtxInit)
}

// Auto-save on every edit: Catatan (remarks) + Tanda Tangan (signature).
watch([remarks, signatureUrl], scheduleSave)
</script>
