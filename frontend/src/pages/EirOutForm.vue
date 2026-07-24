<template>
	<div class="space-y-4">
		<!-- Compact form header (the page header + worklist live in Eir.vue) -->
		<div class="flex items-center gap-2">
			<button class="oak-btn oak-btn-secondary px-2 py-2" @click="emit('back')">
				<Icon name="arrow-left" :size="18" />
			</button>
			<span class="oak-icon-tile h-9 w-9 bg-brand-50 text-brand-600"><Icon name="log-out" :size="20" /></span>
			<div class="min-w-0 flex-1">
				<h2 class="text-base font-extrabold leading-tight tracking-tight">{{ labels.eirBadgeOut }} · {{ header?.container_no || "" }}</h2>
				<p v-if="eirCode" class="truncate font-mono text-[11px] text-gray-500">{{ eirCode }}</p>
				<p v-if="bookingCode" class="truncate font-mono text-[11px] font-semibold text-brand-600">{{ labels.bookingCode }}: {{ bookingCode }}</p>
			</div>
		</div>

		<p v-if="fetchError" class="oak-card border-red-200 bg-red-50 p-3 text-sm text-red-700">{{ fetchError }}</p>

		<template v-if="header">
			<!-- Work-timing gate: the checklist stays locked until the operator presses Mulai,
			     so Mulai → Submit measures how long the inspection actually took. -->
			<section v-if="!workStartedOn" class="oak-card space-y-3 p-5 text-center">
				<span class="oak-icon-tile mx-auto h-12 w-12 bg-brand-50 text-brand-600"><Icon name="play" :size="24" /></span>
				<div>
					<p class="text-base font-extrabold text-gray-900">{{ labels.eirStartTitle }}</p>
					<p class="mt-1 text-sm text-gray-500">{{ labels.eirStartHint }}</p>
				</div>
				<button class="oak-btn oak-btn-primary w-full py-3" :disabled="startRes.loading" @click="startWork">
					<Icon v-if="!startRes.loading" name="play" :size="18" />
					{{ startRes.loading ? "…" : labels.eirStartBtn }}
				</button>
			</section>

			<template v-else>
			<p class="flex items-center gap-1.5 text-[11px] text-gray-400">
				<Icon name="clock" :size="12" /> {{ labels.eirStartedAt }}: {{ workStartedOn }}
			</p>
			<!-- Tank header -->
			<section class="oak-card grid grid-cols-2 gap-x-3 gap-y-2 p-4 sm:grid-cols-3">
				<div v-for="cell in headerCells" :key="cell.label">
					<p class="text-[11px] uppercase tracking-wide text-gray-400">{{ cell.label }}</p>
					<p class="truncate text-sm font-semibold text-gray-800">{{ cell.value || "—" }}</p>
				</div>
			</section>

			<!-- Comparison vs last EIR-In -->
			<section class="oak-card overflow-hidden">
				<div class="flex items-center gap-2 border-b border-gray-100 px-4 py-3">
					<Icon name="git-compare" :size="16" class="text-gray-400" />
					<p class="oak-section-title">{{ labels.eirOutCompare }}</p>
				</div>
				<div class="p-4">
					<template v-if="refEirIn">
						<p class="text-xs text-gray-500">
							<span class="font-mono">{{ refEirIn.inspection_id || refEirIn.name }}</span>
							<span v-if="refEirIn.eir_date"> · {{ refEirIn.eir_date }}</span>
							<span v-if="refEirIn.tank_status"> · {{ refEirIn.tank_status }}</span>
						</p>
						<p v-if="refEirIn.remarks" class="mt-1 text-sm text-gray-600">{{ refEirIn.remarks }}</p>

						<div v-if="refEirIn.damages && refEirIn.damages.length" class="mt-3 space-y-2">
							<p class="text-xs font-bold uppercase tracking-wide text-gray-400">{{ labels.eirOutPrevDamage }}</p>
							<div v-for="(d, i) in refEirIn.damages" :key="i" class="rounded-lg border border-amber-100 bg-amber-50 px-3 py-2">
								<p class="text-sm font-semibold text-gray-800">{{ d.component || d.item_name }}</p>
								<p class="text-xs text-gray-600">{{ d.damage_description }}<span v-if="d.damage_type"> · {{ d.damage_type }}</span></p>
								<div v-if="d.photos && d.photos.length" class="mt-1.5 flex flex-wrap gap-1.5">
									<button v-for="(ph, pi) in d.photos" :key="pi" type="button" class="oak-press" @click="openLightbox(d.photos, pi)">
										<img :src="ph" class="h-12 w-12 rounded border border-gray-200 object-cover" />
									</button>
								</div>
							</div>
						</div>
						<p v-else class="mt-3 inline-flex items-center gap-1 text-sm text-leaf-600">
							<Icon name="check" :size="14" /> {{ labels.eirOutPrevClean }}
						</p>

						<div v-if="refEirIn.photos && refEirIn.photos.length" class="mt-3">
							<p class="mb-1.5 text-xs font-bold uppercase tracking-wide text-gray-400">{{ labels.eirOutPrevPhotos }}</p>
							<div class="flex flex-wrap gap-1.5">
								<button v-for="(ph, pi) in refEirIn.photos" :key="pi" type="button" class="oak-press" @click="openLightbox(refEirIn.photos, pi)">
									<img :src="ph" class="h-14 w-14 rounded-lg border border-gray-200 object-cover" />
								</button>
							</div>
						</div>
					</template>
					<p v-else class="text-sm text-gray-400">{{ labels.eirOutNoBaseline }}</p>
				</div>
			</section>

			<!-- Exterior + seals assessment -->
			<section class="oak-section space-y-3">
				<div class="flex items-center gap-2">
					<Icon name="eye" :size="16" class="text-gray-400" />
					<p class="oak-section-title">{{ labels.eirOutAssess }}</p>
				</div>
				<div>
					<label class="oak-label">{{ labels.eirOutExterior }}</label>
					<div class="grid grid-cols-3 gap-2">
						<button
							v-for="opt in exteriorOptions"
							:key="opt.value"
							type="button"
							class="rounded-xl border px-2 py-2 text-sm font-semibold transition"
							:class="exteriorCondition === opt.value ? opt.active : 'border-gray-200 bg-white text-gray-600'"
							@click="exteriorCondition = opt.value"
						>
							{{ opt.label }}
						</button>
					</div>
					<input v-model.trim="exteriorRemark" type="text" :placeholder="labels.eirOutExteriorNote" class="oak-input mt-2 px-2.5 py-2" />
				</div>
				<label class="flex items-start gap-3 rounded-xl border border-gray-200 p-3">
					<input v-model="sealsIntact" type="checkbox" class="mt-0.5 h-5 w-5 shrink-0 rounded accent-leaf-600" />
					<span class="min-w-0 flex-1">
						<span class="block font-semibold text-gray-800">{{ labels.eirOutSeals }}</span>
						<input v-model.trim="sealRemark" type="text" :placeholder="labels.eirOutSealNote" class="oak-input mt-1.5 px-2.5 py-2" @click.stop />
					</span>
				</label>
			</section>

			<!-- Foto Cepat (bulk) -->
			<section class="oak-section space-y-3">
				<div class="flex items-center gap-2">
					<Icon name="camera" :size="16" class="text-brand-500" />
					<p class="oak-section-title">{{ labels.bulkPhotoTitle }}</p>
				</div>
				<p class="text-xs text-gray-400">{{ labels.bulkPhotoHint }}</p>
				<div class="flex flex-wrap items-center gap-2">
					<div v-for="(url, idx) in bulkPhotos" :key="url" class="relative">
						<button type="button" class="oak-press block" @click="openLightbox(bulkPhotos, idx)">
							<img :src="url" class="h-20 w-20 rounded-lg border border-gray-200 object-cover" />
						</button>
						<button type="button" class="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-gray-900 text-white shadow" @click="removeBulkPhoto(idx)">
							<Icon name="x" :size="12" />
						</button>
					</div>
					<label class="flex h-20 w-20 cursor-pointer flex-col items-center justify-center gap-0.5 rounded-lg border border-dashed border-gray-300 text-gray-400 transition hover:border-brand-400 hover:text-brand-500">
						<input type="file" accept="image/*" capture="environment" multiple class="hidden" :disabled="bulkUploading" @change="onBulkPhotoPick($event)" />
						<span v-if="bulkUploading" class="text-xs">…</span>
						<template v-else><Icon name="camera" :size="20" /><span class="text-[9px] font-medium">{{ labels.photo }}</span></template>
					</label>
				</div>
				<p v-if="bulkErr" class="text-xs text-red-600">{{ bulkErr }}</p>
			</section>

			<!-- Current condition / new findings — search a section/part, add only the damaged ones -->
			<ChecklistDamage
				:rows="rows"
				:damage-codes="damageCodes"
				:repair-codes="repairCodes"
				:upload="uploadFile"
				:title="labels.eirOutCurrent"
			/>

			<!-- Sign-off -->
			<section class="oak-section space-y-3">
				<div class="flex items-center gap-2">
					<Icon name="edit-3" :size="16" class="text-gray-400" />
					<p class="oak-section-title">{{ labels.signOff }}</p>
				</div>
				<div>
					<label class="oak-label">{{ labels.eirRemarks }}</label>
					<textarea v-model.trim="remarks" rows="2" class="oak-input"></textarea>
				</div>
				<p class="text-sm text-gray-500">{{ labels.officer }}: <span class="font-semibold text-gray-800">{{ session.user }}</span></p>
			</section>

			<!-- Signature -->
			<section class="oak-section space-y-2">
				<div class="flex items-center gap-2">
					<Icon name="edit-2" :size="16" class="text-gray-400" />
					<p class="oak-section-title">{{ labels.signature }}</p>
				</div>
				<div v-if="signatureUrl && !signing">
					<img :src="signatureUrl" class="h-28 w-full rounded-xl border border-gray-200 bg-white object-contain" />
					<button type="button" class="oak-link mt-1.5 inline-flex items-center gap-1 text-sm" @click="startResign">
						<Icon name="rotate-ccw" :size="14" /> {{ labels.signAgain }}
					</button>
				</div>
				<div v-else>
					<canvas ref="sigCanvas" class="w-full touch-none rounded-xl border border-gray-200 bg-white" style="height: 150px"
						@pointerdown="sigDown" @pointermove="sigMove" @pointerup="sigUp" @pointercancel="sigUp" @pointerleave="sigUp"></canvas>
					<div class="mt-1.5 flex items-center gap-3 text-sm">
						<button type="button" class="text-gray-600 underline underline-offset-2" @click="clearSignature">{{ labels.clear }}</button>
						<span v-if="sigUploading" class="text-gray-400">…</span>
						<span v-else-if="sigErr" class="text-red-600">{{ sigErr }}</span>
						<span v-else class="text-gray-400">{{ labels.signHint }}</span>
					</div>
				</div>
			</section>

			<!-- Readiness preview + submit -->
			<section class="space-y-2">
				<div class="rounded-xl border p-3 text-sm" :class="isClean ? 'border-leaf-200 bg-leaf-50' : 'border-amber-200 bg-amber-50'">
					<p class="flex items-center gap-1.5 font-semibold" :class="isClean ? 'text-leaf-700' : 'text-amber-700'">
						<Icon :name="isClean ? 'check-circle' : 'alert-triangle'" :size="16" />
						{{ isClean ? labels.eirOutWillReady : labels.eirOutWillHold }}
					</p>
					<p v-if="!isClean && holdReasons.length" class="mt-0.5 pl-6 text-xs text-amber-700">{{ holdReasons.join(", ") }}</p>
				</div>
				<p class="flex items-center gap-1.5 text-xs">
					<span v-if="saveRes.loading" class="text-gray-400">{{ labels.savingDraft }}</span>
					<span v-else-if="saveError" class="text-red-600">{{ saveError }}</span>
					<span v-else-if="savedOk" class="inline-flex items-center gap-1 text-leaf-600"><Icon name="check" :size="13" /> {{ labels.draftSaved }}</span>
					<span v-else class="text-gray-400">{{ labels.eirAutosaveHint }}</span>
				</p>
				<button class="oak-btn w-full py-3" :class="isClean ? 'oak-btn-primary' : 'bg-amber-500 text-white hover:bg-amber-600'" :disabled="saveRes.loading" @click="confirmSubmit">
					<Icon v-if="!saveRes.loading" name="check-circle" :size="18" />
					{{ saveRes.loading ? "…" : (isClean ? labels.eirOutSubmitReady : labels.eirOutSubmitHold) }}
				</button>
			</section>
			</template>
		</template>
	</div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from "vue"
import { createResource } from "frappe-ui"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
import { confirm } from "@/utils/confirm"
import { openLightbox } from "@/utils/lightbox"
import { session } from "@/data/session"
import Icon from "@/components/Icon.vue"
import ChecklistDamage from "@/components/ChecklistDamage.vue"

// Form-only EIR-Out view. The combined worklist lives in Eir.vue, which opens this with
// the picked draft's name and listens for `back` / `submitted`.
const props = defineProps({ inspection: { type: String, required: true } })
const emit = defineEmits(["back", "submitted"])

const ACCEPTABLE_DAMAGE = "v"
const NO_ACTION_REPAIR = "X"

// ---- form state ----
const header = ref(null)
const inspection = ref(null)
const workStartedOn = ref("") // set once the operator presses Mulai; gates editing
const reference = ref(null)
const eirCode = computed(() => header.value?.inspection_id || inspection.value || "")
const refEirIn = computed(() => reference.value?.eir_in || null)

const tanggal = ref(new Date().toISOString().slice(0, 10))
const tankStatus = ref("")
const remarks = ref("")
const referredVoucher = ref("")
const cargo = ref("")
const bookingCode = ref("")
const exteriorCondition = ref("")
const exteriorRemark = ref("")
const sealsIntact = ref(false)
const sealRemark = ref("")
const savedOk = ref(false)
const suppressSave = ref(false)
let saveTimer = null

const rows = ref([])
const damageCodes = ref([])
const repairCodes = ref([])

const bulkPhotos = ref([])
const bulkUploading = ref(false)
const bulkErr = ref("")

const exteriorOptions = [
	{ value: "Clean", label: labels.eirOutClean, active: "border-leaf-500 bg-leaf-500 text-white" },
	{ value: "Dirty", label: labels.eirOutDirty, active: "border-amber-500 bg-amber-500 text-white" },
	{ value: "Needs Wash", label: labels.eirOutNeedsWash, active: "border-red-500 bg-red-500 text-white" },
]

function rowHasFinding(r) {
	const dmg = r.damage_code && r.damage_code !== ACCEPTABLE_DAMAGE
	const rep = r.repair_code && r.repair_code !== NO_ACTION_REPAIR
	return Boolean(dmg || rep || (r.remarks && r.remarks.trim()))
}
const hasDamage = computed(() => rows.value.some(rowHasFinding))

const holdReasons = computed(() => {
	const out = []
	if (exteriorCondition.value !== "Clean") out.push(labels.eirOutReasonExterior)
	if (!sealsIntact.value) out.push(labels.eirOutReasonSeals)
	if (hasDamage.value) out.push(labels.eirOutReasonDamage)
	return out
})
const isClean = computed(() => holdReasons.value.length === 0)

const headerCells = computed(() => {
	const h = header.value || {}
	return [
		{ label: labels.containerNumber, value: h.container_no },
		{ label: labels.serialNo, value: h.serial_no },
		{ label: labels.ownerPrincipal, value: h.principal },
		{ label: labels.eirInDate, value: h.eir_in_date },
		{ label: labels.capacity, value: h.capacity },
		{ label: labels.lastCargo, value: h.last_cargo },
	]
})

// ---- masters (checklist + codes), loaded once ----
const mastersRes = createResource({
	url: "container_depot.ess.inspections.eir_masters",
	method: "GET",
	auto: true,
	onSuccess(data) {
		damageCodes.value = data.damage_codes || []
		repairCodes.value = data.repair_codes || []
		rows.value = (data.checklist || []).map((i) =>
			reactive({ ...i, damage_code: ACCEPTABLE_DAMAGE, repair_code: NO_ACTION_REPAIR, remarks: "", photos: [], uploading: false, photoErr: "", added: false })
		)
		if (header.value) applyDraftToRows(header.value)
	},
})

// ---- open a draft EIR-Out ----
const openRes = createResource({
	url: "container_depot.ess.inspections.eir_out_open",
	method: "GET",
	onSuccess(data) {
		suppressSave.value = true
		header.value = data
		inspection.value = data.inspection
		workStartedOn.value = data.work_started_on || ""
		reference.value = data.reference || null
		tanggal.value = data.eir_date || new Date().toISOString().slice(0, 10)
		tankStatus.value = data.tank_status || ""
		remarks.value = data.doc_remarks || ""
		referredVoucher.value = data.referred_voucher || ""
		cargo.value = data.cargo || data.last_cargo || ""
		bookingCode.value = data.booking_code || ""
		exteriorCondition.value = data.exterior_condition || ""
		exteriorRemark.value = data.exterior_remark || ""
		sealsIntact.value = data.seals_intact === 1
		sealRemark.value = data.seal_remark || ""
		signatureUrl.value = data.inspector_signature || ""
		signing.value = false
		savedOk.value = false
		applyDraftToRows(data)
		nextTick(() => { suppressSave.value = false })
	},
	onError(err) {
		toast.error(err?.messages?.[0] || err?.message || labels.error)
	},
})
const fetchError = computed(() => (openRes.error ? openRes.error.messages?.[0] || openRes.error.message : null))

// Mulai: stamp work_started_on server-side, then unlock the checklist.
const startRes = createResource({
	url: "container_depot.ess.inspections.eir_start",
	method: "POST",
	onSuccess(data) {
		workStartedOn.value = data.work_started_on || new Date().toISOString().slice(0, 19).replace("T", " ")
	},
	onError(err) {
		toast.error(err?.messages?.[0] || err?.message || labels.error)
	},
})
function startWork() {
	if (inspection.value) startRes.submit({ inspection: inspection.value })
}

function applyDraftToRows(data) {
	if (!data || !rows.value.length) return
	const lineMap = {}
	;(data.lines || []).forEach((l) => { lineMap[l.item_code] = l })
	const photoMap = {}
	const bulk = []
	;(data.photos || []).forEach((p) => {
		if (!p.item_code) { bulk.push(p.photo); return }
		;(photoMap[p.item_code] = photoMap[p.item_code] || []).push(p.photo)
	})
	bulkPhotos.value = bulk
	rows.value.forEach((r) => {
		const l = lineMap[r.item_code]
		r.damage_code = (l && l.damage_code) || ACCEPTABLE_DAMAGE
		r.repair_code = (l && l.repair_code) || NO_ACTION_REPAIR
		r.remarks = (l && l.remarks) || ""
		r.photos = photoMap[r.item_code] ? [...photoMap[r.item_code]] : []
		r.photoErr = ""
		r.added = rowHasFinding(r) || r.photos.length > 0
	})
}

function buildLines() {
	return rows.value.filter(rowHasFinding).map((r) => ({
		item_code: r.item_code,
		damage_code: r.damage_code || undefined,
		repair_code: r.repair_code || undefined,
		remarks: (r.remarks || "").trim() || undefined,
	}))
}
function buildPhotos() {
	const perItem = rows.value.flatMap((r) => (r.photos || []).map((url) => ({ item_code: r.item_code, photo: url })))
	const bulk = bulkPhotos.value.map((url) => ({ item_code: "", photo: url }))
	return [...perItem, ...bulk]
}

// ---- file upload ----
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
async function onBulkPhotoPick(event) {
	const files = Array.from(event.target.files || [])
	event.target.value = ""
	if (!files.length) return
	bulkErr.value = ""
	bulkUploading.value = true
	try {
		for (const f of files) bulkPhotos.value.push(await uploadFile(f))
	} catch (e) {
		bulkErr.value = labels.photoError
	} finally {
		bulkUploading.value = false
	}
}
function removeBulkPhoto(idx) {
	bulkPhotos.value.splice(idx, 1)
}

// ---- signature pad ----
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
		signatureUrl.value = await uploadFile(new File([blob], "eir-out-signature.png", { type: "image/png" }))
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

// ---- save / submit ----
const saveRes = createResource({
	url: "container_depot.ess.inspections.eir_save_draft",
	method: "POST",
	onSuccess(data) {
		if (data.docstatus === 1) {
			toast.success(isClean.value ? labels.eirOutDoneReady : labels.eirOutDoneHold, { title: data.inspection })
			emit("submitted", data.inspection)
			emit("back")
		} else {
			savedOk.value = true
		}
	},
	onError(err) {
		toast.error(err?.messages?.[0] || err?.message || labels.error)
	},
})
const saveError = computed(() => (saveRes.error ? saveRes.error.messages?.[0] || saveRes.error.message : null))

function doSave(submit = false) {
	if (!inspection.value) return
	if (saveTimer) { clearTimeout(saveTimer); saveTimer = null }
	saveRes.submit({
		inspection: inspection.value,
		inspection_type: "EIR-Out",
		eir_date: tanggal.value || undefined,
		tank_status: tankStatus.value || undefined,
		referred_voucher: referredVoucher.value || undefined,
		cargo: cargo.value || undefined,
		remarks: remarks.value || undefined,
		signature: signatureUrl.value || undefined,
		exterior_condition: exteriorCondition.value || undefined,
		exterior_remark: exteriorRemark.value || undefined,
		seals_intact: sealsIntact.value ? 1 : 0,
		seal_remark: sealRemark.value || undefined,
		lines: JSON.stringify(buildLines()),
		photos: JSON.stringify(buildPhotos()),
		submit: submit ? 1 : 0,
	})
}
function scheduleSave() {
	savedOk.value = false
	if (saveTimer) clearTimeout(saveTimer)
	saveTimer = setTimeout(() => doSave(false), 1200)
}
watch([exteriorCondition, exteriorRemark, sealsIntact, sealRemark, remarks, cargo, rows, bulkPhotos], () => {
	if (suppressSave.value || !inspection.value) return
	scheduleSave()
}, { deep: true })

async function confirmSubmit() {
	const ok = await confirm({
		title: isClean.value ? labels.eirOutConfirmReadyTitle : labels.eirOutConfirmHoldTitle,
		message: isClean.value ? labels.eirOutConfirmReadyMsg : (labels.eirOutConfirmHoldMsg + (holdReasons.value.length ? ("\n\n• " + holdReasons.value.join("\n• ")) : "")),
		confirmLabel: isClean.value ? labels.eirOutSubmitReady : labels.eirOutSubmitHold,
		cancelLabel: labels.confirmCancel,
	})
	if (ok) doSave(true)
}

onMounted(() => {
	openRes.submit({ inspection: props.inspection })
})
</script>
