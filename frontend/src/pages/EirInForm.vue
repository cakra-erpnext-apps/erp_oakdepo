<template>
	<div class="space-y-4">
		<!-- Compact form header (the page header + worklist live in Eir.vue) -->
		<div class="flex items-center gap-2">
			<button class="oak-btn oak-btn-secondary px-2 py-2" @click="emit('back')">
				<Icon name="arrow-left" :size="18" />
			</button>
			<span class="oak-icon-tile h-9 w-9 bg-leaf-50 text-leaf-600"><Icon name="clipboard" :size="20" /></span>
			<div class="min-w-0">
				<h2 class="text-base font-extrabold leading-tight tracking-tight">{{ labels.eirBadgeIn }} · {{ header?.container_no || "" }}</h2>
				<p v-if="eirCode" class="truncate font-mono text-[11px] text-gray-500">{{ eirCode }}</p>
				<p v-if="bookingCode" class="truncate font-mono text-[11px] font-semibold text-brand-600">{{ labels.bookingCode }}: {{ bookingCode }}</p>
			</div>
		</div>

		<p v-if="fetchError" class="oak-card border-red-200 bg-red-50 p-3 text-sm text-red-700">{{ fetchError }}</p>

		<template v-if="header">
			<!-- Work-timing gate: the checklist stays locked until the operator presses Mulai,
			     so Mulai → Submit measures how long the inspection actually took. -->
			<section v-if="!workStartedOn" class="oak-card space-y-3 p-5 text-center">
				<span class="oak-icon-tile mx-auto h-12 w-12 bg-leaf-50 text-leaf-600"><Icon name="play" :size="24" /></span>
				<div>
					<p class="text-base font-extrabold text-gray-900">{{ labels.eirStartTitle }}</p>
					<p class="mt-1 text-sm text-gray-500">{{ labels.eirStartHint }}</p>
				</div>
				<button class="oak-btn oak-btn-primary w-full py-3" @click="startWork">
					<Icon name="play" :size="18" />
					{{ labels.eirStartBtn }}
				</button>
			</section>

			<template v-else>
			<p class="flex items-center gap-1.5 text-[11px] text-gray-400">
				<Icon name="clock" :size="12" /> {{ labels.eirStartedAt }}: {{ workStartedOn }}
			</p>
			<!-- Step 1b — referred voucher: pull shipper / truck / driver (read-only) -->
			<section class="oak-section space-y-3">
				<div class="flex items-center gap-2">
					<Icon name="file-text" :size="16" class="text-gray-400" />
					<p class="oak-section-title">{{ labels.referredVoucher }}</p>
				</div>
				<div class="rounded-xl bg-gray-50 p-3">
					<div class="grid grid-cols-2 gap-3">
						<div>
							<p class="text-xs text-gray-500">{{ labels.bookingCode }}</p>
							<p class="font-mono font-semibold text-brand-600">{{ bookingCode || "—" }}</p>
						</div>
						<div>
							<p class="text-xs text-gray-500">{{ labels.referredVoucher }}</p>
							<p class="font-mono font-semibold text-gray-800">{{ referredVoucher || "—" }}</p>
						</div>
					</div>
					<p class="mt-1 text-[11px] text-gray-400">{{ labels.eirVoucherLocked }}</p>
				</div>
				<dl class="grid grid-cols-2 gap-x-4 gap-y-2.5 rounded-xl bg-gray-50 p-3 text-sm">
					<div>
						<dt class="text-xs text-gray-500">{{ labels.shipper }}</dt>
						<dd class="font-semibold text-gray-800">{{ shipper || "—" }}</dd>
					</div>
					<div>
						<dt class="text-xs text-gray-500">{{ labels.truckNo }}</dt>
						<dd class="font-semibold text-gray-800">{{ truckNo || "—" }}</dd>
					</div>
					<div>
						<dt class="text-xs text-gray-500">{{ labels.driverName }}</dt>
						<dd class="font-semibold text-gray-800">{{ driver || "—" }}</dd>
					</div>
					<div>
						<dt class="text-xs text-gray-500">{{ labels.driverPhone }}</dt>
						<dd class="font-semibold text-gray-800">{{ driverPhone || "—" }}</dd>
					</div>
				</dl>
			</section>

			<!-- Step 2 — tank header (all from the Container master) -->
			<section class="oak-section space-y-3">
				<div class="flex items-center gap-2">
					<Icon name="package" :size="16" class="text-gray-400" />
					<p class="oak-section-title">{{ labels.eirHeader }}</p>
				</div>
				<dl class="grid grid-cols-2 gap-x-4 gap-y-2.5 rounded-xl bg-gray-50 p-3 text-sm sm:grid-cols-3">
					<div v-for="f in headerCells" :key="f.label">
						<dt class="text-xs text-gray-500">{{ f.label }}</dt>
						<dd class="font-semibold text-gray-800">{{ f.value ?? "—" }}</dd>
					</div>
				</dl>
			</section>

			<!-- Step 3 — tank status -->
			<section class="oak-section space-y-2">
				<label class="oak-label">{{ labels.tankStatus }}</label>
				<div class="grid grid-cols-3 gap-2">
					<button
						v-for="s in [labels.emptyClean, labels.emptyDirty, labels.laden]"
						:key="s"
						class="oak-toggle px-2 py-3"
						:class="tankStatus === s ? 'oak-toggle-on' : 'oak-toggle-off'"
						@click="tankStatus = s"
					>
						{{ s }}
					</button>
				</div>
			</section>

			<!-- Step 3b — cargo (updates the container's Last Cargo on submit) -->
			<section class="oak-section space-y-2">
				<label class="oak-label">{{ labels.cargo }}</label>
				<SearchSelect
					v-model="cargo"
					:options="cargos"
					:placeholder="labels.cargo"
					:search-placeholder="labels.cargoSearch"
					:empty-label="labels.sectionSearchEmpty"
				/>
				<p class="text-xs text-gray-400">{{ labels.cargoHint }}</p>
			</section>

			<!-- Foto Cepat (bulk): foto tanpa perlu pilih section; admin menyortir belakangan. -->
			<section class="oak-section space-y-3">
				<div class="flex items-center gap-2">
					<Icon name="camera" :size="16" class="text-brand-500" />
					<p class="oak-section-title">{{ labels.bulkPhotoTitle }}</p>
				</div>
				<p class="text-xs text-gray-400">{{ labels.bulkPhotoHint }}</p>
				<div class="flex flex-wrap items-center gap-2">
					<div v-for="(url, idx) in bulkPhotos" :key="url" class="relative">
						<button type="button" class="oak-press block" @click="openLightbox(bulkPhotos.map(photoSrc), idx)">
							<img :src="photoSrc(url)" class="h-20 w-20 rounded-lg border border-gray-200 object-cover" />
						</button>
						<!-- Sudah disortir Admin ke item checklist — tetap di Foto Cepat, sortirannya dijaga. -->
						<span
							v-if="bulkMeta[url]"
							class="absolute bottom-1 left-1 flex items-center gap-0.5 rounded bg-leaf-600/90 px-1 py-0.5 text-[9px] font-semibold text-white"
						>
							<Icon name="check" :size="10" /> {{ bulkMeta[url] }}
						</span>
						<button
							type="button"
							class="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-gray-900 text-white shadow"
							@click="removeBulkPhoto(idx)"
						>
							<Icon name="x" :size="12" />
						</button>
					</div>
					<label
						class="flex h-20 w-20 cursor-pointer flex-col items-center justify-center gap-0.5 rounded-lg border border-dashed border-gray-300 text-gray-400 transition hover:border-brand-400 hover:text-brand-500"
					>
						<input
							type="file"
							accept="image/*"
							capture="environment"
							multiple
							class="hidden"
							:disabled="bulkUploading"
							@change="onBulkPhotoPick($event)"
						/>
						<span v-if="bulkUploading" class="text-xs">…</span>
						<template v-else>
							<Icon name="camera" :size="20" />
							<span class="text-[9px] font-medium">{{ labels.photo }}</span>
						</template>
					</label>
				</div>
				<p v-if="bulkErr" class="text-xs text-red-600">{{ bulkErr }}</p>
			</section>

			<!-- Step 4 — checklist: search a section/part, add only the damaged ones -->
			<ChecklistDamage
				:rows="rows"
				:damage-codes="damageCodes"
				:repair-codes="repairCodes"
				:upload="uploadFile"
				:title="labels.checklist"
			/>

			<!-- Follow-up orders (Cleaning / M&R) are created automatically on submit
			     when applicable — the opt-out toggles are intentionally not shown. -->

			<!-- Step 5 — sign-off -->
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

			<!-- Step 5b — virtual signature of the EIR creator, directly above Submit -->
			<section class="oak-section space-y-2">
				<div class="flex items-center gap-2">
					<Icon name="edit-2" :size="16" class="text-gray-400" />
					<p class="oak-section-title">{{ labels.signature }}</p>
				</div>
				<p class="text-xs text-gray-500">
					{{ labels.signedBy }}: <span class="font-semibold text-gray-800">{{ session.user }}</span>
				</p>
				<div v-if="signatureUrl && !signing">
					<img :src="photoSrc(signatureUrl)" class="h-28 w-full rounded-xl border border-gray-200 bg-white object-contain" />
					<button type="button" class="oak-link mt-1.5 inline-flex items-center gap-1 text-sm" @click="startResign">
						<Icon name="rotate-ccw" :size="14" /> {{ labels.signAgain }}
					</button>
				</div>
				<div v-else>
					<canvas
						ref="sigCanvas"
						class="w-full touch-none rounded-xl border border-gray-200 bg-white"
						style="height: 150px"
						@pointerdown="sigDown"
						@pointermove="sigMove"
						@pointerup="sigUp"
						@pointercancel="sigUp"
						@pointerleave="sigUp"
					></canvas>
					<div class="mt-1.5 flex items-center gap-3 text-sm">
						<button type="button" class="text-gray-600 underline underline-offset-2" @click="clearSignature">{{ labels.clear }}</button>
						<span v-if="sigUploading" class="text-gray-400">…</span>
						<span v-else-if="sigErr" class="text-red-600">{{ sigErr }}</span>
						<span v-else class="text-gray-400">{{ labels.signHint }}</span>
					</div>
				</div>
			</section>

			<!-- Step 6 — auto-save status + finalize -->
			<section class="space-y-2">
				<!-- Required-before-submit: Cargo + Tank Status + Signature. -->
				<div v-if="missingFields.length" class="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm">
					<p class="flex items-center gap-1.5 font-semibold text-amber-700">
						<Icon name="alert-triangle" :size="16" /> {{ labels.eirNeedComplete }}
					</p>
					<p class="mt-0.5 pl-6 text-xs text-amber-700">{{ missingFields.join(", ") }}</p>
				</div>
				<p class="flex items-center gap-1.5 text-xs">
					<span v-if="saveRes.loading" class="text-gray-400">{{ labels.savingDraft }}</span>
					<span v-else-if="saveError" class="text-red-600">{{ saveError }}</span>
					<span v-else-if="savedOk" class="inline-flex items-center gap-1 text-leaf-600"><Icon name="check" :size="13" /> {{ labels.draftSaved }}</span>
					<span v-else class="text-gray-400">{{ labels.eirAutosaveHint }}</span>
				</p>
				<button
					class="oak-btn oak-btn-primary w-full py-3"
					:disabled="saveRes.loading || missingFields.length > 0"
					@click="confirmSubmit"
				>
					<Icon v-if="!saveRes.loading" name="check-circle" :size="18" />
					{{ saveRes.loading ? "…" : labels.eirSendReview }}
				</button>
			</section>
			</template>
		</template>
	</div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from "vue"
import { createResource } from "frappe-ui"
import { cachedResource } from "@/data/cache"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
import { confirm } from "@/utils/confirm"
import { openLightbox } from "@/utils/lightbox"
import { session } from "@/data/session"
import Icon from "@/components/Icon.vue"
import SearchSelect from "@/components/SearchSelect.vue"
import ChecklistDamage from "@/components/ChecklistDamage.vue"
import { compressPhoto } from "@/utils/photo"
import { clearDraft, loadDraft, saveDraft } from "@/data/drafts"
import { enqueue, hydratePreviews, isLocalRef, outbox, photoSrc, stashPhoto } from "@/data/outbox"

// Form-only EIR-In view. The combined worklist lives in Eir.vue, which opens this with
// the picked draft's name and listens for `back` / `submitted`.
const props = defineProps({ inspection: { type: String, required: true } })
const emit = defineEmits(["back", "submitted"])

const eirType = "EIR-In"
const header = ref(null)
const inspection = ref(null)
const workStartedOn = ref("") // set once the operator presses Mulai; gates editing
const eirCode = computed(() => header.value?.inspection_id || inspection.value || "")
const tanggal = ref(new Date().toISOString().slice(0, 10))
const tankStatus = ref("")
const remarks = ref("")
const reffDoc = ref("")
const createCleaning = ref(true)
const createRepair = ref(true)
const referredVoucher = ref("")
const truckNo = ref("")
const driver = ref("")
const driverPhone = ref("")
const shipper = ref("")
const cargo = ref("")
const cargos = ref([])
const bookingCode = ref("")
const result = ref(null)
const savedOk = ref(false)
const suppressSave = ref(false)
let saveTimer = null

const rows = ref([])
const damageCodes = ref([])
const repairCodes = ref([])

const bulkPhotos = ref([])
// A "foto cepat" keeps its Foto Cepat spot even after Admin sorts it into a checklist item
// on the Sortir screen — sorting is just categorisation, the photo still belongs here. This
// maps each bulk photo URL → the checklist item it was sorted into ("" = not yet sorted), so
// buildPhotos re-sends that assignment and a save never un-sorts it.
const bulkMeta = ref({})
const bulkUploading = ref(false)
const bulkErr = ref("")

const ACCEPTABLE_DAMAGE = "v"
const NO_ACTION_REPAIR = "X"
function rowHasFinding(r) {
	const dmg = r.damage_code && r.damage_code !== ACCEPTABLE_DAMAGE
	const rep = r.repair_code && r.repair_code !== NO_ACTION_REPAIR
	return Boolean(dmg || rep || (r.remarks && r.remarks.trim()))
}

const hasDamage = computed(() => rows.value.some(rowHasFinding))
const showCleaningToggle = computed(() => tankStatus.value === "Empty Dirty")
const showRepairToggle = computed(() => hasDamage.value)

// Required before Submit (per ops): Tank Status + Signature, plus Cargo (Last Cargo) —
// except when the tank is Empty Clean, where there is no prior cargo to record.
const missingFields = computed(() => {
	const out = []
	if (!cargo.value && tankStatus.value !== "Empty Clean") out.push(labels.eirNeedCargo)
	if (!tankStatus.value) out.push(labels.eirNeedTankStatus)
	if (!signatureUrl.value) out.push(labels.eirNeedSignature)
	return out
})

const mastersRes = cachedResource({
	url: "container_depot.ess.inspections.eir_masters",
	method: "GET",
	auto: true,
	onSuccess(data) {
		damageCodes.value = data.damage_codes || []
		repairCodes.value = data.repair_codes || []
		cargos.value = data.cargos || []
		rows.value = (data.checklist || []).map((i) =>
			reactive({ ...i, damage_code: ACCEPTABLE_DAMAGE, repair_code: NO_ACTION_REPAIR, remarks: "", photos: [], uploading: false, photoErr: "", added: false })
		)
		if (header.value) applyDraftToRows(header.value)
	},
})

const headerCells = computed(() => {
	const h = header.value || {}
	return [
		{ label: labels.containerNumber, value: h.container_no },
		{ label: labels.serialNo, value: h.serial_no },
		{ label: labels.dateManufacture, value: h.manufacture_date },
		{ label: labels.ownerPrincipal, value: h.principal },
		{ label: labels.eirInDate, value: h.eir_in_date },
		{ label: labels.capacity, value: h.capacity },
		{ label: labels.tare, value: h.tare_weight },
		{ label: labels.maxGross, value: h.max_gross_weight },
		{ label: labels.lastCargo, value: h.last_cargo },
		{ label: labels.exVessel, value: h.ex_vessel },
		{ label: labels.depot, value: h.depot },
	]
})

const openRes = cachedResource({
	url: "container_depot.ess.inspections.eir_open",
	method: "GET",
	onSuccess(data) {
		suppressSave.value = true
		header.value = data
		inspection.value = data.inspection
		workStartedOn.value = data.work_started_on || ""
		result.value = null
		savedOk.value = false
		tanggal.value = data.eir_date || new Date().toISOString().slice(0, 10)
		tankStatus.value = data.tank_status || ""
		remarks.value = data.doc_remarks || ""
		reffDoc.value = data.reff_doc || ""
		referredVoucher.value = data.referred_voucher || ""
		truckNo.value = data.truck_no || ""
		driver.value = data.driver || ""
		driverPhone.value = data.driver_phone || ""
		shipper.value = data.shipper || ""
		cargo.value = data.cargo || data.last_cargo || ""
		bookingCode.value = data.booking_code || ""
		createCleaning.value = data.create_cleaning_order !== 0
		createRepair.value = data.create_repair_order !== 0
		signatureUrl.value = data.inspector_signature || ""
		signing.value = false
		applyDraftToRows(data)
		restoreLocalDraft().finally(() => {
			nextTick(() => {
				suppressSave.value = false
			})
		})
	},
})

const saveRes = createResource({
	url: "container_depot.ess.inspections.eir_save_draft",
	method: "POST",
	onSuccess(data) {
		// The server now holds everything except photos still waiting in the outbox, so the
		// local draft has nothing left to protect. Dropping it here is what keeps
		// restoreLocalDraft from ever putting stale text back over fresher server data.
		if (!hasStashedPhotos()) clearDraft(draftKey.value)
		result.value = data
		// Field submit now moves the EIR to Pending Review (docstatus stays 0) — Admin Ops
		// finalises it on the Desk. Treat that as "done" from the operator's side.
		if (data.docstatus === 1 || data.pending_review) {
			toast.success(data.pending_review ? labels.eirSentForReview : labels.eirSubmitted, {
				title: data.inspection_id || data.inspection,
			})
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

const fetchError = computed(() => (openRes.error ? openRes.error.messages?.[0] || openRes.error.message : null))
const saveError = computed(() => (saveRes.error ? saveRes.error.messages?.[0] || saveRes.error.message : null))

// Mulai: stamp work_started_on server-side, then unlock the checklist.
// Mulai goes through the outbox and stamps the start time locally rather than waiting for
// the server to hand one back. The response carried nothing else the form needed, and waiting
// for it is what made Mulai impossible in a dead spot — which locked the surveyor out of the
// entire checklist, the one screen the offline queue exists to protect.
//
// No `ref` on this row: starting is not finishing, so the EIR stays in the worklist.
async function startWork() {
	if (!inspection.value) return
	try {
		await enqueue({
			kind: "eir-start",
			title: `EIR · Mulai`,
			url: "container_depot.ess.inspections.eir_start",
			payload: { inspection: inspection.value },
		})
		workStartedOn.value = new Date().toISOString().slice(0, 19).replace("T", " ")
	} catch (e) {
		toast.error(e?.message || labels.error)
	}
}

function applyDraftToRows(data) {
	if (!data || !rows.value.length) return
	const lineMap = {}
	;(data.lines || []).forEach((l) => {
		lineMap[l.item_code] = l
	})
	// Split incoming photos into two buckets:
	//  • damage-card photos — a photo on an item that HAS a damage finding is evidence for
	//    that finding, so it lives on the damage card.
	//  • Foto Cepat — everything else: unsorted quick photos AND ones Admin already sorted
	//    into a checklist item (no finding). A sorted foto cepat still belongs in Foto Cepat;
	//    its assigned item_code is remembered in bulkMeta so a save never un-sorts it, and it
	//    is never shown as a damage card (which would mislabel it / risk accidental deletion).
	const photoMap = {}
	const bulk = []
	const meta = {}
	;(data.photos || []).forEach((p) => {
		const code = p.item_code
		if (code && lineMap[code]) {
			;(photoMap[code] = photoMap[code] || []).push(p.photo)
		} else {
			bulk.push(p.photo)
			meta[p.photo] = code || ""
		}
	})
	bulkPhotos.value = bulk
	bulkMeta.value = meta
	rows.value.forEach((r) => {
		const l = lineMap[r.item_code]
		r.damage_code = (l && l.damage_code) || ACCEPTABLE_DAMAGE
		r.repair_code = (l && l.repair_code) || NO_ACTION_REPAIR
		r.remarks = (l && l.remarks) || ""
		r.photos = photoMap[r.item_code] ? [...photoMap[r.item_code]] : []
		r.photoErr = ""
		r.added = rowHasFinding(r)
	})
}

function buildLines() {
	return rows.value
		.filter(rowHasFinding)
		.map((r) => ({
			item_code: r.item_code,
			damage_code: r.damage_code || undefined,
			repair_code: r.repair_code || undefined,
			remarks: (r.remarks || "").trim() || undefined,
		}))
}

function buildPhotos() {
	const perItem = rows.value.flatMap((r) => (r.photos || []).map((url) => ({ item_code: r.item_code, photo: url })))
	// Keep each foto cepat's sorted item_code (bulkMeta) so a save preserves Admin's sorting.
	const bulk = bulkPhotos.value.map((url) => ({ item_code: bulkMeta.value[url] || "", photo: url }))
	return [...perItem, ...bulk]
}

/**
 * Take a picked photo and hand back a reference the form can hold onto.
 *
 * This used to upload immediately, which made the yard's dead spots brutal: the surveyor
 * photographed a dent, the POST failed, and the evidence was gone on the spot — long before
 * anyone reached the Kirim button. Now the file is shrunk and parked in IndexedDB, and the
 * `local:` reference it returns travels through the form exactly like a file_url. The
 * outbox swaps it for the real one when there is a network (see data/outbox.js).
 */
async function uploadFile(file) {
	return stashPhoto(await compressPhoto(file))
}

async function onBulkPhotoPick(event) {
	const files = Array.from(event.target.files || [])
	event.target.value = ""
	if (!files.length) return
	bulkErr.value = ""
	bulkUploading.value = true
	try {
		for (const f of files) {
			const url = await uploadFile(f)
			bulkPhotos.value.push(url)
			bulkMeta.value[url] = "" // freshly taken → not sorted into a checklist item yet
		}
	} catch (e) {
		bulkErr.value = labels.photoError
	} finally {
		bulkUploading.value = false
	}
}

function removeBulkPhoto(idx) {
	const [url] = bulkPhotos.value.splice(idx, 1)
	if (url) delete bulkMeta.value[url]
}

// --- Virtual signature pad (EIR creator) -------------------------------------
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
		signatureUrl.value = await uploadFile(new File([blob], "eir-signature.png", { type: "image/png" }))
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

// --- Offline safety net -------------------------------------------------------
// Two different problems, two different mechanisms, and conflating them is the usual way
// this goes wrong:
//
//   the LOCAL DRAFT answers "the tab died"   — IndexedDB, every keystroke, disposable
//   the OUTBOX answers    "there is no signal" — IndexedDB, on Kirim, never dropped
//
// The periodic autosave still goes straight to the server when it can: that keeps Admin Ops
// seeing live progress on the Desk. It just cannot carry photos that have not been uploaded
// yet, so those are stripped and travel with the final submit instead.

const draftKey = computed(() => `eir-in:${inspection.value || props.inspection}`)

function eirPayload(submit) {
	return {
		inspection: inspection.value,
		inspection_type: eirType,
		eir_date: tanggal.value || undefined,
		tank_status: tankStatus.value || undefined,
		referred_voucher: referredVoucher.value || undefined,
		cargo: cargo.value || undefined,
		reff_doc: reffDoc.value,
		remarks: remarks.value || undefined,
		signature: signatureUrl.value || undefined,
		create_cleaning_order: createCleaning.value ? 1 : 0,
		create_repair_order: createRepair.value ? 1 : 0,
		// Sent as arrays, not JSON strings: the outbox has to be able to walk the payload to
		// find the `local:` photo references and swap them for real file_urls.
		lines: buildLines(),
		photos: buildPhotos(),
		submit: submit ? 1 : 0,
	}
}

/** Everything the operator has typed, in a shape restoreLocalDraft can put back. */
function localSnapshot() {
	return {
		saved_at: Date.now(),
		tanggal: tanggal.value,
		tankStatus: tankStatus.value,
		cargo: cargo.value,
		remarks: remarks.value,
		reffDoc: reffDoc.value,
		signatureUrl: signatureUrl.value,
		createCleaning: createCleaning.value,
		createRepair: createRepair.value,
		bulkPhotos: [...bulkPhotos.value],
		bulkMeta: { ...bulkMeta.value },
		rows: rows.value.map((r) => ({
			item_code: r.item_code,
			damage_code: r.damage_code,
			repair_code: r.repair_code,
			remarks: r.remarks,
			photos: [...(r.photos || [])],
			added: r.added,
		})),
	}
}

async function restoreLocalDraft() {
	const saved = await loadDraft(draftKey.value)
	if (!saved) return
	tanggal.value = saved.tanggal || tanggal.value
	tankStatus.value = saved.tankStatus || tankStatus.value
	cargo.value = saved.cargo || cargo.value
	remarks.value = saved.remarks ?? remarks.value
	reffDoc.value = saved.reffDoc ?? reffDoc.value
	signatureUrl.value = saved.signatureUrl || signatureUrl.value
	createCleaning.value = saved.createCleaning
	createRepair.value = saved.createRepair
	bulkPhotos.value = saved.bulkPhotos || []
	bulkMeta.value = saved.bulkMeta || {}
	;(saved.rows || []).forEach((sr) => {
		const row = rows.value.find((r) => r.item_code === sr.item_code)
		if (!row) return
		Object.assign(row, { damage_code: sr.damage_code, repair_code: sr.repair_code, remarks: sr.remarks, photos: sr.photos || [], added: sr.added })
	})
	// Object URLs die with the document that created them, so a restored draft has to
	// re-open one per stashed photo or the thumbnails come back blank.
	await hydratePreviews([...bulkPhotos.value, ...rows.value.flatMap((r) => r.photos || []), signatureUrl.value])
	toast.info(labels.draftRestored)
}

const hasStashedPhotos = () =>
	buildPhotos().some((p) => isLocalRef(p.photo)) || isLocalRef(signatureUrl.value)

function doSave(submit = false) {
	if (!inspection.value) return
	if (saveTimer) {
		clearTimeout(saveTimer)
		saveTimer = null
	}
	saveDraft(draftKey.value, localSnapshot())
	if (submit) {
		queueSubmit()
		return
	}
	// Draft autosave to the server. Strip anything still sitting in the outbox — a
	// `local:` string written into Inspection Photo would be a broken image for ever.
	const payload = eirPayload(false)
	saveRes.submit({
		...payload,
		signature: isLocalRef(payload.signature) ? undefined : payload.signature,
		lines: JSON.stringify(payload.lines),
		photos: JSON.stringify(payload.photos.filter((p) => !isLocalRef(p.photo))),
	})
}

/**
 * Hand the finished EIR to the outbox rather than posting it.
 *
 * Same path online and off, deliberately. A "send now if we can, queue if we cannot" fork
 * gives two code paths of which one is barely ever exercised — and it is the one that runs
 * on the worst day. Queued-then-flushed is a few milliseconds slower with signal and is the
 * only path that has been tested.
 */
async function queueSubmit() {
	try {
		await enqueue({
			kind: "eir-in-submit",
			title: `EIR-In · ${header.value?.container_no || eirCode.value}`,
			// Names the EIR so the worklist can drop it the moment it is queued — see
			// Eir.vue's pendingItems.
			ref: inspection.value,
			url: "container_depot.ess.inspections.eir_save_draft",
			payload: eirPayload(true),
		})
		await clearDraft(draftKey.value)
		toast.success(outbox.online ? labels.eirSentForReview : labels.queuedOffline, {
			title: eirCode.value || inspection.value,
		})
		emit("submitted", inspection.value)
		emit("back")
	} catch (e) {
		toast.error(e?.message || labels.error)
	}
}

async function confirmSubmit() {
	// Belt-and-suspenders: the button is already disabled while anything is missing.
	if (missingFields.value.length) {
		toast.error(`${labels.eirNeedComplete} ${missingFields.value.join(", ")}`)
		return
	}
	const ok = await confirm({
		title: labels.confirmSubmitTitle,
		message: labels.confirmSubmitMessage,
		confirmLabel: labels.confirmSubmitYes,
		cancelLabel: labels.confirmCancel,
	})
	if (ok) doSave(true)
}

function scheduleSave() {
	if (!inspection.value || suppressSave.value) return
	savedOk.value = false
	if (saveTimer) clearTimeout(saveTimer)
	saveTimer = setTimeout(() => doSave(false), 700)
}

watch([tanggal, tankStatus, cargo, remarks, reffDoc, signatureUrl, createCleaning, createRepair], scheduleSave)
watch(rows, scheduleSave, { deep: true })
watch(bulkPhotos, scheduleSave, { deep: true })

onMounted(() => {
	openRes.submit({ inspection: props.inspection })
})
</script>
