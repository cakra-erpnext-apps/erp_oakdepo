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
									<button v-for="(ph, pi) in d.photos" :key="pi" type="button" class="oak-press" @click="openLightbox(d.photos.map(photoSrc), pi)">
										<img :src="photoSrc(ph)" class="h-12 w-12 rounded border border-gray-200 object-cover" />
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
								<button v-for="(ph, pi) in refEirIn.photos" :key="pi" type="button" class="oak-press" @click="openLightbox(refEirIn.photos.map(photoSrc), pi)">
									<img :src="photoSrc(ph)" class="h-14 w-14 rounded-lg border border-gray-200 object-cover" />
								</button>
							</div>
						</div>
					</template>
					<p v-else class="text-sm text-gray-400">{{ labels.eirOutNoBaseline }}</p>
				</div>
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
						<button type="button" class="oak-press block" @click="openLightbox(bulkPhotos.map(photoSrc), idx)">
							<img :src="photoSrc(url)" class="h-20 w-20 rounded-lg border border-gray-200 object-cover" />
						</button>
						<span
							v-if="bulkMeta[url]"
							class="absolute bottom-1 left-1 flex items-center gap-0.5 rounded bg-leaf-600/90 px-1 py-0.5 text-[9px] font-semibold text-white"
						>
							<Icon name="check" :size="10" /> {{ bulkMeta[url] }}
						</span>
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

			<!-- Seal numbers — one row per seal, added as the surveyor fits them -->
			<section class="oak-section space-y-3">
				<div class="flex items-center gap-2">
					<Icon name="lock" :size="16" class="text-gray-400" />
					<p class="oak-section-title">{{ labels.eirOutSealsTitle }}</p>
					<span class="oak-chip bg-gray-100 text-gray-600">{{ seals.length }}</span>
				</div>
				<p class="text-xs text-gray-400">{{ labels.eirOutSealsHint }}</p>
				<div v-for="(s, i) in seals" :key="i" class="flex items-start gap-2">
					<span class="mt-2.5 w-5 shrink-0 text-center text-xs font-bold text-gray-400">{{ i + 1 }}</span>
					<div class="min-w-0 flex-1 space-y-1.5">
						<input
							v-model.trim="s.seal_no"
							type="text"
							autocapitalize="characters"
							:placeholder="labels.eirOutSealNoPlaceholder"
							class="oak-input uppercase"
						/>
						<input
							v-model.trim="s.remarks"
							type="text"
							:placeholder="labels.eirOutSealRemarkPlaceholder"
							class="oak-input px-2.5 py-2 text-sm"
						/>
					</div>
					<button
						type="button"
						class="mt-1 rounded-lg p-2 text-gray-400 transition hover:bg-red-50 hover:text-red-500"
						@click="removeSeal(i)"
					>
						<Icon name="trash-2" :size="16" />
					</button>
				</div>
				<button type="button" class="oak-btn oak-btn-secondary w-full" @click="addSeal">
					<Icon name="plus" :size="18" /> {{ labels.eirOutSealAdd }}
				</button>
			</section>

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
					<img :src="photoSrc(signatureUrl)" class="h-28 w-full rounded-xl border border-gray-200 bg-white object-contain" />
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
				<div class="rounded-xl border border-leaf-200 bg-leaf-50 p-3 text-sm">
					<p class="flex items-center gap-1.5 font-semibold text-leaf-700">
						<Icon name="check-circle" :size="16" /> {{ labels.eirOutWillReady }}
					</p>
				</div>
				<p class="flex items-center gap-1.5 text-xs">
					<span v-if="saveRes.loading" class="text-gray-400">{{ labels.savingDraft }}</span>
					<span v-else-if="saveError" class="text-red-600">{{ saveError }}</span>
					<span v-else-if="savedOk" class="inline-flex items-center gap-1 text-leaf-600"><Icon name="check" :size="13" /> {{ labels.draftSaved }}</span>
					<span v-else class="text-gray-400">{{ labels.eirAutosaveHint }}</span>
				</p>
				<!-- One action, whatever the outcome: this hands the EIR-Out to Adm Ops. The
				     colour and the preview box above already say what it will become. -->
				<button class="oak-btn oak-btn-primary w-full py-3" :disabled="saveRes.loading" @click="confirmSubmit">
					<Icon v-if="!saveRes.loading" name="send" :size="18" />
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
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
import { confirm } from "@/utils/confirm"
import { openLightbox } from "@/utils/lightbox"
import { session } from "@/data/session"
import { compressPhoto } from "@/utils/photo"
import { clearDraft, loadDraft, saveDraft } from "@/data/drafts"
import { enqueue, hydratePreviews, isLocalRef, outbox, photoSrc, stashPhoto } from "@/data/outbox"
import Icon from "@/components/Icon.vue"

// Form-only EIR-Out view. The combined worklist lives in Eir.vue, which opens this with
// the picked draft's name and listens for `back` / `submitted`.
//
// There is no damage checklist here: a tank only reaches load-out once its work is
// finished, so the surveyor records what the tank leaves WITH — photos and seal
// numbers — not what is wrong with it. Findings belong to EIR-In.
const props = defineProps({ inspection: { type: String, required: true } })
const emit = defineEmits(["back", "submitted"])

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
const savedOk = ref(false)
const suppressSave = ref(false)
let saveTimer = null

const seals = ref([])

const bulkPhotos = ref([])
// foto cepat URL → the checklist item Admin sorted it into ("" = unsorted). Keeps sorting
// through a save so a sorted photo stays in Foto Cepat without losing its item_code.
const bulkMeta = ref({})
const bulkUploading = ref(false)
const bulkErr = ref("")

function addSeal() {
	seals.value.push(reactive({ seal_no: "", remarks: "" }))
}
function removeSeal(i) {
	seals.value.splice(i, 1)
}
// Blank rows are the operator tapping "Tambah" and changing their mind — never saved.
const filledSeals = computed(() => seals.value.filter((s) => (s.seal_no || "").trim()))

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
		signatureUrl.value = data.inspector_signature || ""
		signing.value = false
		savedOk.value = false
		seals.value = (data.seals || []).map((s) => reactive({ seal_no: s.seal_no || "", remarks: s.remarks || "" }))
		applyDraftPhotos(data)
		restoreLocalDraft().finally(() => {
			nextTick(() => { suppressSave.value = false })
		})
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

// With no checklist on this form every photo is a "foto cepat". Each one's sorted
// item_code is still carried in bulkMeta so a save never un-sorts what Admin filed.
function applyDraftPhotos(data) {
	if (!data) return
	const bulk = []
	const meta = {}
	;(data.photos || []).forEach((p) => {
		bulk.push(p.photo)
		meta[p.photo] = p.item_code || ""
	})
	bulkPhotos.value = bulk
	bulkMeta.value = meta
}

function buildPhotos() {
	return bulkPhotos.value.map((url) => ({ item_code: bulkMeta.value[url] || "", photo: url }))
}
function buildSeals() {
	return filledSeals.value.map((s) => ({
		seal_no: s.seal_no.trim(),
		remarks: (s.remarks || "").trim() || undefined,
	}))
}

// ---- file upload ----
/** Shrink and park the photo locally; the outbox uploads it. See EirInForm for why. */
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
			bulkMeta.value[url] = "" // freshly taken → not sorted yet
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
		// Server has it — the local draft has nothing left to protect (see EirInForm).
		if (!hasStashedPhotos()) clearDraft(draftKey.value)
		// Field submit → Pending Review (docstatus 0); Admin Ops finalises on the Desk.
		if (data.docstatus === 1 || data.pending_review) {
			toast.success(
				data.pending_review ? labels.eirSentForReview : labels.eirSubmitted,
				{ title: data.inspection },
			)
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

// Offline handling mirrors EirInForm exactly — see the long note there. Local draft for a
// dead tab, outbox for a dead signal, photos stripped from the server autosave until they
// have actually been uploaded.
const draftKey = computed(() => `eir-out:${inspection.value || props.inspection}`)

function eirPayload(submit) {
	return {
		inspection: inspection.value,
		inspection_type: "EIR-Out",
		eir_date: tanggal.value || undefined,
		tank_status: tankStatus.value || undefined,
		referred_voucher: referredVoucher.value || undefined,
		cargo: cargo.value || undefined,
		remarks: remarks.value || undefined,
		signature: signatureUrl.value || undefined,
		photos: buildPhotos(),
		seals: buildSeals(),
		submit: submit ? 1 : 0,
	}
}

function localSnapshot() {
	return {
		saved_at: Date.now(),
		tanggal: tanggal.value,
		tankStatus: tankStatus.value,
		cargo: cargo.value,
		remarks: remarks.value,
		signatureUrl: signatureUrl.value,
		bulkPhotos: [...bulkPhotos.value],
		seals: seals.value.map((r) => ({ seal_no: r.seal_no, remarks: r.remarks })),
	}
}

async function restoreLocalDraft() {
	const saved = await loadDraft(draftKey.value)
	if (!saved) return
	tanggal.value = saved.tanggal || tanggal.value
	tankStatus.value = saved.tankStatus || tankStatus.value
	cargo.value = saved.cargo || cargo.value
	remarks.value = saved.remarks ?? remarks.value
	signatureUrl.value = saved.signatureUrl || signatureUrl.value
	bulkPhotos.value = saved.bulkPhotos || []
	;(saved.seals || []).forEach((sv, i) => seals.value[i] && Object.assign(seals.value[i], sv))
	await hydratePreviews([...bulkPhotos.value, signatureUrl.value])
	toast.info(labels.draftRestored)
}

const hasStashedPhotos = () =>
	buildPhotos().some((p) => isLocalRef(p.photo)) || isLocalRef(signatureUrl.value)

function doSave(submit = false) {
	if (!inspection.value) return
	if (saveTimer) { clearTimeout(saveTimer); saveTimer = null }
	saveDraft(draftKey.value, localSnapshot())
	if (submit) {
		queueSubmit()
		return
	}
	const payload = eirPayload(false)
	saveRes.submit({
		...payload,
		signature: isLocalRef(payload.signature) ? undefined : payload.signature,
		photos: JSON.stringify(payload.photos.filter((p) => !isLocalRef(p.photo))),
		seals: JSON.stringify(payload.seals),
	})
}

async function queueSubmit() {
	try {
		await enqueue({
			kind: "eir-out-submit",
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
function scheduleSave() {
	savedOk.value = false
	if (saveTimer) clearTimeout(saveTimer)
	saveTimer = setTimeout(() => doSave(false), 1200)
}
watch([remarks, cargo, seals, bulkPhotos], () => {
	if (suppressSave.value || !inspection.value) return
	scheduleSave()
}, { deep: true })

async function confirmSubmit() {
	// Surface the seal count here rather than blocking submit on it: a tank can legitimately
	// leave unsealed, but forgetting to record a seal that IS fitted must not pass quietly.
	const n = filledSeals.value.length
	const ok = await confirm({
		title: labels.eirOutConfirmReadyTitle,
		message:
			labels.eirOutConfirmReadyMsg +
			"\n\n" +
			(n ? `${labels.eirOutSealsRecorded}: ${n}` : labels.eirOutNoSealWarn),
		confirmLabel: labels.eirSendReview,
		cancelLabel: labels.confirmCancel,
	})
	if (ok) doSave(true)
}

onMounted(() => {
	openRes.submit({ inspection: props.inspection })
})
</script>
