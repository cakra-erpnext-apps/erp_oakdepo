<template>
	<div class="mx-auto w-full max-w-lg space-y-4">
		<h1 class="text-lg font-semibold">{{ labels.eirTitle }}</h1>

		<!-- Step 1 — source: container number + EIR type -->
		<section class="space-y-3 rounded-lg border bg-white p-4">
			<div>
				<label class="text-sm font-medium">{{ labels.containerNumber }}</label>
				<div class="mt-1 flex gap-2">
					<input
						v-model.trim="containerNo"
						type="text"
						autocapitalize="characters"
						:placeholder="labels.containerNumberPlaceholder"
						class="w-full rounded-md border px-3 py-2 text-sm uppercase"
						@keyup.enter="doFetch"
					/>
					<button
						class="shrink-0 rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
						:disabled="!containerNo || openRes.loading"
						@click="doFetch"
					>
						{{ openRes.loading ? "…" : labels.eirFetch }}
					</button>
				</div>
				<p v-if="fetchError" class="mt-1 text-sm text-red-600">{{ fetchError }}</p>
				<p class="mt-1 text-xs text-gray-400">{{ labels.eirDraftHint }}</p>
			</div>
			<div>
				<label class="text-sm font-medium">{{ labels.eirType }}</label>
				<div class="mt-1 grid grid-cols-2 gap-2">
					<button
						v-for="t in ['EIR-In', 'EIR-Out']"
						:key="t"
						class="rounded-md border px-3 py-2 text-sm font-medium"
						:class="eirType === t ? 'border-blue-600 bg-blue-50 text-blue-700' : 'bg-white text-gray-700'"
						@click="eirType = t"
					>
						{{ t }}
					</button>
				</div>
			</div>
		</section>

		<!-- Steps 2-6 appear once a draft is open -->
		<template v-if="header">
			<!-- Step 1b — referred voucher: pull shipper / truck / driver (read-only) -->
			<section class="space-y-3 rounded-lg border bg-white p-4">
				<p class="text-sm font-semibold text-gray-700">{{ labels.referredVoucher }}</p>
				<div>
					<div class="flex gap-2">
						<input
							v-model.trim="referredVoucher"
							type="text"
							:placeholder="voucherPlaceholder"
							class="w-full rounded-md border px-3 py-2 text-sm"
							@keyup.enter="doVoucherFetch"
						/>
						<button
							class="shrink-0 rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
							:disabled="voucherRes.loading"
							@click="doVoucherFetch"
						>
							{{ voucherRes.loading ? "…" : labels.eirFetch }}
						</button>
					</div>
					<p class="mt-1 text-xs text-gray-400">{{ voucherHint }}</p>
					<p v-if="voucherError" class="mt-1 text-sm text-red-600">{{ voucherError }}</p>
				</div>
				<dl class="grid grid-cols-2 gap-x-3 gap-y-1.5 text-sm">
					<div>
						<dt class="text-gray-500">{{ labels.shipper }}</dt>
						<dd class="font-medium">{{ shipper || "—" }}</dd>
					</div>
					<div>
						<dt class="text-gray-500">{{ labels.truckNo }}</dt>
						<dd class="font-medium">{{ truckNo || "—" }}</dd>
					</div>
					<div>
						<dt class="text-gray-500">{{ labels.driverName }}</dt>
						<dd class="font-medium">{{ driver || "—" }}</dd>
					</div>
					<div>
						<dt class="text-gray-500">{{ labels.driverPhone }}</dt>
						<dd class="font-medium">{{ driverPhone || "—" }}</dd>
					</div>
				</dl>
			</section>

			<!-- Step 2 — tank header (all from the Container master) -->
			<section class="space-y-3 rounded-lg border bg-white p-4">
				<p class="text-sm font-semibold text-gray-700">{{ labels.eirHeader }}</p>
				<dl class="grid grid-cols-3 gap-x-3 gap-y-1.5 text-sm">
					<div v-for="f in headerCells" :key="f.label">
						<dt class="text-gray-500">{{ f.label }}</dt>
						<dd class="font-medium">{{ f.value ?? "—" }}</dd>
					</div>
				</dl>
				<div>
					<label class="text-sm font-medium">{{ labels.tanggal }}</label>
					<input v-model="tanggal" type="date" class="mt-1 w-full rounded-md border px-3 py-2 text-sm" />
				</div>
			</section>

			<!-- Step 3 — tank status -->
			<section class="space-y-2 rounded-lg border bg-white p-4">
				<label class="text-sm font-medium">{{ labels.tankStatus }}</label>
				<div class="grid grid-cols-3 gap-2">
					<button
						v-for="s in [labels.emptyClean, labels.emptyDirty, labels.laden]"
						:key="s"
						class="rounded-md border px-2 py-3 text-sm font-semibold"
						:class="tankStatus === s ? 'border-blue-600 bg-blue-50 text-blue-700' : 'bg-white text-gray-700'"
						@click="tankStatus = s"
					>
						{{ s }}
					</button>
				</div>
			</section>

			<!-- Step 3b — cargo (updates the container's Last Cargo on submit) -->
			<section class="space-y-2 rounded-lg border bg-white p-4">
				<label class="text-sm font-medium">{{ labels.cargo }}</label>
				<select v-model="cargo" class="w-full rounded-md border px-3 py-2 text-sm">
					<option value="">— {{ labels.cargo }} —</option>
					<option v-for="c in cargos" :key="c" :value="c">{{ c }}</option>
				</select>
				<p class="text-xs text-gray-400">{{ labels.cargoHint }}</p>
			</section>

			<!-- Step 4 — checklist grid (fixed 50 rows, grouped by area) -->
			<section class="rounded-lg border bg-white p-4">
				<div class="mb-2 flex items-baseline justify-between">
					<p class="text-sm font-semibold text-gray-700">{{ labels.checklist }}</p>
					<p class="text-xs text-gray-400">{{ labels.acceptableHint }}</p>
				</div>
				<div v-for="g in groups" :key="g.area">
					<p class="sticky top-0 z-10 -mx-4 bg-gray-100 px-4 py-1 text-xs font-semibold uppercase text-gray-600">
						{{ g.area }}
					</p>
					<div v-for="item in g.items" :key="item.item_code" class="border-t py-2">
						<p class="text-sm font-medium">{{ item.printed_no }}. {{ item.item_name }}</p>
						<div class="mt-1 grid grid-cols-2 gap-2">
							<select v-model="item.damage_code" class="rounded-md border px-2 py-1.5 text-sm">
								<option value="">— {{ labels.colDamage }} —</option>
								<option v-for="d in damageCodes" :key="d.code" :value="d.code">{{ d.code }} — {{ d.description }}</option>
							</select>
							<select v-model="item.repair_code" class="rounded-md border px-2 py-1.5 text-sm">
								<option value="">— {{ labels.colRepair }} —</option>
								<option v-for="r in repairCodes" :key="r.code" :value="r.code">{{ r.code }} — {{ r.description }}</option>
							</select>
						</div>
						<!-- Photos for this item (multi) — saved per section, above the keterangan -->
						<div class="mt-2 flex flex-wrap items-center gap-2">
							<div v-for="(url, idx) in item.photos" :key="url" class="relative">
								<img :src="url" class="h-14 w-14 rounded border object-cover" />
								<button
									type="button"
									class="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-gray-800 text-xs leading-none text-white"
									@click="removePhoto(item, idx)"
								>
									×
								</button>
							</div>
							<label
								class="flex h-14 w-14 cursor-pointer flex-col items-center justify-center rounded border border-dashed border-gray-300 text-gray-400"
							>
								<input
									type="file"
									accept="image/*"
									capture="environment"
									multiple
									class="hidden"
									:disabled="item.uploading"
									@change="onPhotoPick(item, $event)"
								/>
								<span v-if="item.uploading" class="text-xs">…</span>
								<template v-else>
									<span class="text-lg leading-none">＋</span>
									<span class="text-[9px]">{{ labels.photo }}</span>
								</template>
							</label>
						</div>
						<p v-if="item.photoErr" class="mt-1 text-xs text-red-600">{{ item.photoErr }}</p>
						<input
							v-model.trim="item.remarks"
							type="text"
							:placeholder="labels.colRemarks"
							class="mt-1 w-full rounded-md border px-2 py-1.5 text-sm"
						/>
					</div>
				</div>
			</section>

			<!-- Step 5 — sign-off -->
			<section class="space-y-3 rounded-lg border bg-white p-4">
				<p class="text-sm font-semibold text-gray-700">{{ labels.signOff }}</p>
				<div>
					<label class="text-sm font-medium">{{ labels.eirRemarks }}</label>
					<textarea v-model.trim="remarks" rows="2" class="mt-1 w-full rounded-md border px-3 py-2 text-sm"></textarea>
				</div>
				<p class="text-sm text-gray-500">{{ labels.officer }}: <span class="font-medium text-gray-800">{{ session.user }}</span></p>
			</section>

			<!-- Step 5b — virtual signature of the EIR creator, directly above Submit -->
			<section class="space-y-2 rounded-lg border bg-white p-4">
				<p class="text-sm font-semibold text-gray-700">{{ labels.signature }}</p>
				<p class="text-xs text-gray-500">
					{{ labels.signedBy }}: <span class="font-medium text-gray-800">{{ session.user }}</span>
				</p>
				<div v-if="signatureUrl && !signing">
					<img :src="signatureUrl" class="h-28 w-full rounded border bg-white object-contain" />
					<button type="button" class="mt-1 text-sm text-blue-600 underline" @click="startResign">
						{{ labels.signAgain }}
					</button>
				</div>
				<div v-else>
					<canvas
						ref="sigCanvas"
						class="w-full touch-none rounded border bg-white"
						style="height: 150px"
						@pointerdown="sigDown"
						@pointermove="sigMove"
						@pointerup="sigUp"
						@pointercancel="sigUp"
						@pointerleave="sigUp"
					></canvas>
					<div class="mt-1 flex items-center gap-3 text-sm">
						<button type="button" class="text-gray-600 underline" @click="clearSignature">{{ labels.clear }}</button>
						<span v-if="sigUploading" class="text-gray-400">…</span>
						<span v-else-if="sigErr" class="text-red-600">{{ sigErr }}</span>
						<span v-else class="text-gray-400">{{ labels.signHint }}</span>
					</div>
				</div>
			</section>

			<!-- Step 6 — auto-save status + finalize -->
			<section class="space-y-2">
				<p class="text-xs">
					<span v-if="saveRes.loading" class="text-gray-400">{{ labels.savingDraft }}</span>
					<span v-else-if="saveError" class="text-red-600">{{ saveError }}</span>
					<span v-else-if="savedOk" class="text-green-600">✓ {{ labels.draftSaved }}</span>
					<span v-else class="text-gray-400">{{ labels.eirAutosaveHint }}</span>
				</p>
				<button
					class="w-full rounded-md bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
					:disabled="saveRes.loading"
					@click="doSave(true)"
				>
					{{ saveRes.loading ? "…" : labels.submitEir }}
				</button>
				<button class="block w-full text-center text-sm text-blue-600 underline" @click="reset">
					{{ labels.newEir }}
				</button>
			</section>
		</template>

		<!-- Finalized -->
		<section v-if="submitted" class="rounded-lg border border-green-200 bg-green-50 p-4">
			<p class="font-medium text-green-800">✓ {{ labels.eirSubmitted }}</p>
			<p class="mt-1 text-sm text-gray-700">{{ submitted }}</p>
			<button class="mt-2 text-sm text-blue-600 underline" @click="submitted = null">{{ labels.newEir }}</button>
		</section>
	</div>
</template>

<script setup>
import { computed, nextTick, reactive, ref, watch } from "vue"
import { createResource } from "frappe-ui"
import { labels } from "@/utils/labels"
import { session } from "@/data/session"

const containerNo = ref("")
const eirType = ref("EIR-In")
const header = ref(null)
const inspection = ref(null)
const tanggal = ref(new Date().toISOString().slice(0, 10))
const tankStatus = ref("")
const remarks = ref("")
// Referred-voucher reference + its read-only shipment snapshot (from the bon).
const referredVoucher = ref("")
const truckNo = ref("")
const driver = ref("")
const driverPhone = ref("")
const shipper = ref("")
// Cargo recorded on the EIR (writes Container.last_cargo on submit only).
const cargo = ref("")
const cargos = ref([])
const result = ref(null)
const savedOk = ref(false) // last auto-save succeeded
const submitted = ref(null) // finalized EIR name (shown after Submit)
const suppressSave = ref(false) // mute auto-save while a draft is being loaded
let saveTimer = null

const rows = ref([])
const damageCodes = ref([])
const repairCodes = ref([])

// Checklist taxonomy + code lists (loaded once).
const mastersRes = createResource({
	url: "container_depot.ess.inspections.eir_masters",
	method: "GET",
	auto: true,
	onSuccess(data) {
		damageCodes.value = data.damage_codes || []
		repairCodes.value = data.repair_codes || []
		cargos.value = data.cargos || []
		rows.value = (data.checklist || []).map((i) =>
			reactive({ ...i, damage_code: "", repair_code: "", remarks: "", photos: [], uploading: false, photoErr: "" })
		)
		// If a draft is already open (rare: fetch resolved before masters), apply it now.
		if (header.value) applyDraftToRows(header.value)
	},
})

const groups = computed(() => {
	const out = []
	let cur = null
	for (const r of rows.value) {
		if (!cur || cur.area !== r.area) {
			cur = { area: r.area, items: [] }
			out.push(cur)
		}
		cur.items.push(r)
	}
	return out
})

// Tank header: Container Number + the master fields (no ISO 6346 prefix/number/cd —
// the container number is the identity; all values come from the Container master).
const headerCells = computed(() => {
	const h = header.value || {}
	return [
		{ label: labels.containerNumber, value: h.container_no },
		{ label: labels.serialNo, value: h.serial_no },
		{ label: labels.dateManufacture, value: h.manufacture_date },
		{ label: labels.ownerPrincipal, value: h.principal },
		{ label: labels.lastTest, value: h.last_test_date },
		{ label: labels.capacity, value: h.capacity },
		{ label: labels.tare, value: h.tare_weight },
		{ label: labels.maxGross, value: h.max_gross_weight },
		{ label: labels.lastCargo, value: h.last_cargo },
		{ label: labels.exVessel, value: h.ex_vessel },
		{ label: labels.depot, value: h.depot },
	]
})

// Fetch = get-or-create the container's draft EIR (so nothing is lost before save,
// and re-fetching the same container reopens the same draft — no duplicates).
const openRes = createResource({
	url: "container_depot.ess.inspections.eir_open_draft",
	method: "POST",
	onSuccess(data) {
		// Mute auto-save while we populate the form from the loaded draft.
		suppressSave.value = true
		header.value = data
		inspection.value = data.inspection
		result.value = null
		savedOk.value = false
		if (data.inspection_type) eirType.value = data.inspection_type
		tanggal.value = data.eir_date || new Date().toISOString().slice(0, 10)
		tankStatus.value = data.tank_status || ""
		remarks.value = data.doc_remarks || ""
		referredVoucher.value = data.referred_voucher || ""
		truckNo.value = data.truck_no || ""
		driver.value = data.driver || ""
		driverPhone.value = data.driver_phone || ""
		shipper.value = data.shipper || ""
		cargo.value = data.cargo || data.last_cargo || ""
		signatureUrl.value = data.inspector_signature || ""
		signing.value = false
		applyDraftToRows(data)
		nextTick(() => {
			suppressSave.value = false
		})
	},
})

const saveRes = createResource({
	url: "container_depot.ess.inspections.eir_save_draft",
	method: "POST",
	onSuccess(data) {
		result.value = data
		if (data.docstatus === 1) {
			// Finalized — show the success banner and clear the form for the next unit.
			submitted.value = data.inspection
			reset()
		} else {
			savedOk.value = true
		}
	},
})

const fetchError = computed(() => {
	if (openRes.error) return openRes.error.messages?.[0] || openRes.error.message
	return null
})
const saveError = computed(() => {
	if (saveRes.error) return saveRes.error.messages?.[0] || saveRes.error.message
	return null
})

// Referred voucher — fetch the read-only shipment snapshot (Order Bongkar for EIR-In,
// Order Muat for EIR-Out). On success, persist the validated reference via auto-save.
const voucherRes = createResource({
	url: "container_depot.ess.inspections.eir_voucher",
	method: "GET",
	onSuccess(data) {
		truckNo.value = data.truck_no || ""
		driver.value = data.driver || ""
		driverPhone.value = data.driver_phone || ""
		shipper.value = data.shipper || ""
		scheduleSave() // persist the (now validated) voucher reference onto the draft
	},
})
const voucherError = computed(() => {
	if (voucherRes.error) return voucherRes.error.messages?.[0] || voucherRes.error.message
	return null
})
const voucherPlaceholder = computed(() => (eirType.value === "EIR-In" ? "ORD-BKR-…" : "ORD-MT-…"))
const voucherHint = computed(() => (eirType.value === "EIR-In" ? labels.voucherHintIn : labels.voucherHintOut))
function doVoucherFetch() {
	voucherRes.submit({ voucher: referredVoucher.value || "", inspection_type: eirType.value })
}

// Restore the draft's saved checklist lines + photos onto the (master) rows.
function applyDraftToRows(data) {
	if (!data || !rows.value.length) return
	const lineMap = {}
	;(data.lines || []).forEach((l) => {
		lineMap[l.item_code] = l
	})
	const photoMap = {}
	;(data.photos || []).forEach((p) => {
		;(photoMap[p.item_code] = photoMap[p.item_code] || []).push(p.photo)
	})
	rows.value.forEach((r) => {
		const l = lineMap[r.item_code]
		r.damage_code = (l && l.damage_code) || ""
		r.repair_code = (l && l.repair_code) || ""
		r.remarks = (l && l.remarks) || ""
		r.photos = photoMap[r.item_code] ? [...photoMap[r.item_code]] : []
		r.photoErr = ""
	})
}

function doFetch() {
	if (!containerNo.value) return
	result.value = null
	submitted.value = null
	openRes.submit({ container_no: containerNo.value, inspection_type: eirType.value })
}

function buildLines() {
	return rows.value
		.filter((r) => r.damage_code || r.repair_code || (r.remarks && r.remarks.trim()))
		.map((r) => ({
			item_code: r.item_code,
			damage_code: r.damage_code || undefined,
			repair_code: r.repair_code || undefined,
			remarks: (r.remarks || "").trim() || undefined,
		}))
}

// Flat {item_code, photo} list — one entry per uploaded photo (multi per item).
function buildPhotos() {
	return rows.value.flatMap((r) => (r.photos || []).map((url) => ({ item_code: r.item_code, photo: url })))
}

// Upload one image to Frappe and return its file_url. Reuses the session cookie +
// the CSRF token injected into the /depot shell (www/depot.html).
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

async function onPhotoPick(item, event) {
	const files = Array.from(event.target.files || [])
	event.target.value = "" // allow re-picking the same file
	if (!files.length) return
	item.photoErr = ""
	item.uploading = true
	try {
		for (const f of files) {
			const url = await uploadFile(f)
			item.photos.push(url)
		}
	} catch (e) {
		item.photoErr = labels.photoError
	} finally {
		item.uploading = false
	}
}

function removePhoto(item, idx) {
	item.photos.splice(idx, 1)
}

// --- Virtual signature pad (EIR creator) -------------------------------------
// A tiny canvas pad: draw with pointer events, upload the result as a file (like
// item photos) and persist its URL on the draft (Inspection.inspector_signature).
const sigCanvas = ref(null)
const signatureUrl = ref("") // uploaded signature file_url (persisted on the draft)
const signing = ref(false) // true while (re)drawing — show the canvas, not the saved image
const sigUploading = ref(false)
const sigErr = ref("")
let sigCtx = null
let sigDrawing = false
let sigHasInk = false
let sigTimer = null

// Lazily size + configure the canvas backing store (crisp on hi-dpi screens).
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
	// Upload once the pen settles, so a multi-stroke signature is sent once.
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
		signing.value = false // reveal the saved signature; the watch picks up the new URL
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

// Re-sign: discard the saved image and show a fresh canvas.
function startResign() {
	signatureUrl.value = ""
	signing.value = true
	sigHasInk = false
	sigCtx = null
	nextTick(sigCtxInit)
}

// Persist the draft. submit=false = auto-save; submit=true = finalize (Submit).
function doSave(submit = false) {
	if (!inspection.value) return
	if (saveTimer) {
		clearTimeout(saveTimer)
		saveTimer = null
	}
	saveRes.submit({
		inspection: inspection.value,
		inspection_type: eirType.value,
		eir_date: tanggal.value || undefined,
		tank_status: tankStatus.value || undefined,
		referred_voucher: referredVoucher.value || undefined,
		cargo: cargo.value || undefined,
		remarks: remarks.value || undefined,
		signature: signatureUrl.value || undefined,
		lines: JSON.stringify(buildLines()),
		photos: JSON.stringify(buildPhotos()),
		submit: submit ? 1 : 0,
	})
}

// Auto-save on every action: debounce so rapid edits collapse into one request.
function scheduleSave() {
	if (!inspection.value || suppressSave.value) return
	savedOk.value = false
	if (saveTimer) clearTimeout(saveTimer)
	saveTimer = setTimeout(() => doSave(false), 700)
}

// Header fields + the whole checklist (codes, remarks, photos) trigger an auto-save.
// The voucher reference is persisted via doVoucherFetch (only after it validates), so
// it is intentionally not watched here.
watch([eirType, tanggal, tankStatus, cargo, remarks, signatureUrl], scheduleSave)
watch(rows, scheduleSave, { deep: true })

// Flipping EIR direction changes the voucher doctype — clear the stale reference + snapshot.
watch(eirType, () => {
	if (suppressSave.value) return // a draft load sets the type; don't wipe its voucher
	referredVoucher.value = ""
	truckNo.value = ""
	driver.value = ""
	driverPhone.value = ""
	shipper.value = ""
})

function reset() {
	containerNo.value = ""
	header.value = null
	inspection.value = null
	tankStatus.value = ""
	remarks.value = ""
	referredVoucher.value = ""
	truckNo.value = ""
	driver.value = ""
	driverPhone.value = ""
	shipper.value = ""
	cargo.value = ""
	signatureUrl.value = ""
	signing.value = false
	sigHasInk = false
	sigCtx = null
	result.value = null
	rows.value.forEach((r) => {
		r.damage_code = ""
		r.repair_code = ""
		r.remarks = ""
		r.photos = []
		r.photoErr = ""
	})
}
</script>
