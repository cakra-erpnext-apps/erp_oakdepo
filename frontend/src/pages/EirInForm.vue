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
			</div>
		</div>

		<p v-if="fetchError" class="oak-card border-red-200 bg-red-50 p-3 text-sm text-red-700">{{ fetchError }}</p>

		<template v-if="header">
			<!-- Step 1b — referred voucher: pull shipper / truck / driver (read-only) -->
			<section class="oak-section space-y-3">
				<div class="flex items-center gap-2">
					<Icon name="file-text" :size="16" class="text-gray-400" />
					<p class="oak-section-title">{{ labels.referredVoucher }}</p>
				</div>
				<div class="rounded-xl bg-gray-50 p-3">
					<p class="text-xs text-gray-500">{{ labels.referredVoucher }}</p>
					<p class="font-mono font-semibold text-gray-800">{{ referredVoucher || "—" }}</p>
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
						<button type="button" class="oak-press block" @click="openLightbox(bulkPhotos, idx)">
							<img :src="url" class="h-20 w-20 rounded-lg border border-gray-200 object-cover" />
						</button>
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

			<!-- Step 4 — checklist grid (fixed 50 rows, grouped by area) -->
			<section class="oak-card overflow-hidden">
				<div class="flex items-center justify-between gap-2 border-b border-gray-100 px-4 py-3">
					<div class="flex items-center gap-2">
						<Icon name="check-square" :size="16" class="text-gray-400" />
						<p class="oak-section-title">{{ labels.checklist }}</p>
					</div>
					<p class="text-xs text-gray-400">{{ labels.acceptableHint }}</p>
				</div>
				<div class="border-b border-gray-100 px-4 py-2.5">
					<div class="relative">
						<span class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"><Icon name="search" :size="15" /></span>
						<input v-model.trim="sectionSearch" type="text" :placeholder="labels.sectionSearch" class="oak-input pl-9" />
					</div>
				</div>
				<div class="max-h-[70vh] overflow-y-auto overscroll-contain">
					<p v-if="!filteredGroups.length" class="px-4 py-4 text-center text-sm text-gray-400">{{ labels.sectionSearchEmpty }}</p>
					<div v-for="g in filteredGroups" :key="g.area">
						<p class="sticky top-0 z-10 border-b border-gray-100 bg-gray-50/95 px-4 py-1.5 text-xs font-bold uppercase tracking-wide text-gray-500 backdrop-blur">
							{{ g.area }}
						</p>
						<div
							v-for="item in g.items"
							:key="item.item_code"
							class="border-b border-gray-100 px-4 py-3 last:border-b-0"
						>
						<p class="text-sm font-semibold text-gray-800">{{ item.printed_no }}. {{ item.item_name }}</p>
						<div class="mt-2 grid grid-cols-2 gap-2">
							<SearchSelect
								v-model="item.damage_code"
								:options="damageCodes"
								:option-value="(d) => d.code"
								:option-label="(d) => `${d.code} — ${d.description}`"
								:placeholder="labels.colDamage"
								:search-placeholder="labels.selectSearch"
								trigger-class="px-2.5 py-2"
							/>
							<SearchSelect
								v-model="item.repair_code"
								:options="repairCodes"
								:option-value="(r) => r.code"
								:option-label="(r) => `${r.code} — ${r.description}`"
								:placeholder="labels.colRepair"
								:search-placeholder="labels.selectSearch"
								trigger-class="px-2.5 py-2"
							/>
						</div>
						<div class="mt-2 flex flex-wrap items-center gap-2">
							<div v-for="(url, idx) in item.photos" :key="url" class="relative">
								<button type="button" class="oak-press block" @click="openLightbox(item.photos, idx)">
									<img :src="url" class="h-16 w-16 rounded-lg border border-gray-200 object-cover" />
								</button>
								<button
									type="button"
									class="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-gray-900 text-white shadow"
									@click="removePhoto(item, idx)"
								>
									<Icon name="x" :size="12" />
								</button>
							</div>
							<label
								class="flex h-16 w-16 cursor-pointer flex-col items-center justify-center gap-0.5 rounded-lg border border-dashed border-gray-300 text-gray-400 transition hover:border-brand-400 hover:text-brand-500"
							>
								<input
									type="file"
									accept="image/*"
									capture="environment"
									class="hidden"
									:disabled="item.uploading"
									@change="onPhotoPick(item, $event)"
								/>
								<span v-if="item.uploading" class="text-xs">…</span>
								<template v-else>
									<Icon name="camera" :size="18" />
									<span class="text-[9px] font-medium">{{ labels.photo }}</span>
								</template>
							</label>
						</div>
						<p v-if="item.photoErr" class="mt-1 text-xs text-red-600">{{ item.photoErr }}</p>
						<input
							v-model.trim="item.remarks"
							type="text"
							:placeholder="labels.colRemarks"
							class="oak-input mt-2 px-2.5 py-2"
						/>
						</div>
					</div>
				</div>
			</section>

			<!-- Step 4b — follow-up orders (opt-out): create Cleaning Order and/or M&R on submit. -->
			<section v-if="showCleaningToggle || showRepairToggle" class="oak-section space-y-3">
				<div class="flex items-center gap-2">
					<Icon name="clipboard" :size="16" class="text-gray-400" />
					<p class="oak-section-title">{{ labels.eirFollowupTitle }}</p>
				</div>
				<label v-if="showCleaningToggle" class="flex items-start gap-3 rounded-xl border border-gray-200 p-3">
					<input v-model="createCleaning" type="checkbox" class="mt-0.5 h-5 w-5 shrink-0 rounded accent-leaf-600" />
					<span class="min-w-0 flex-1">
						<span class="block font-semibold text-gray-800">{{ labels.eirCreateCleaning }}</span>
						<span class="block text-xs text-gray-400">{{ labels.eirCreateCleaningHint }}</span>
					</span>
				</label>
				<label v-if="showRepairToggle" class="flex items-start gap-3 rounded-xl border border-gray-200 p-3">
					<input v-model="createRepair" type="checkbox" class="mt-0.5 h-5 w-5 shrink-0 rounded accent-leaf-600" />
					<span class="min-w-0 flex-1">
						<span class="block font-semibold text-gray-800">{{ labels.eirCreateRepair }}</span>
						<span class="block text-xs text-gray-400">{{ labels.eirCreateRepairHint }}</span>
					</span>
				</label>
			</section>

			<!-- Step 5 — sign-off -->
			<section class="oak-section space-y-3">
				<div class="flex items-center gap-2">
					<Icon name="edit-3" :size="16" class="text-gray-400" />
					<p class="oak-section-title">{{ labels.signOff }}</p>
				</div>
				<div>
					<label class="oak-label">{{ labels.reffDoc }}</label>
					<input v-model.trim="reffDoc" type="text" class="oak-input" :placeholder="labels.reffDocHint" />
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
					<img :src="signatureUrl" class="h-28 w-full rounded-xl border border-gray-200 bg-white object-contain" />
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
				<p class="flex items-center gap-1.5 text-xs">
					<span v-if="saveRes.loading" class="text-gray-400">{{ labels.savingDraft }}</span>
					<span v-else-if="saveError" class="text-red-600">{{ saveError }}</span>
					<span v-else-if="savedOk" class="inline-flex items-center gap-1 text-leaf-600"><Icon name="check" :size="13" /> {{ labels.draftSaved }}</span>
					<span v-else class="text-gray-400">{{ labels.eirAutosaveHint }}</span>
				</p>
				<button
					class="oak-btn oak-btn-primary w-full py-3"
					:disabled="saveRes.loading"
					@click="confirmSubmit"
				>
					<Icon v-if="!saveRes.loading" name="check-circle" :size="18" />
					{{ saveRes.loading ? "…" : labels.submitEir }}
				</button>
			</section>
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
import SearchSelect from "@/components/SearchSelect.vue"

// Form-only EIR-In view. The combined worklist lives in Eir.vue, which opens this with
// the picked draft's name and listens for `back` / `submitted`.
const props = defineProps({ inspection: { type: String, required: true } })
const emit = defineEmits(["back", "submitted"])

const eirType = "EIR-In"
const header = ref(null)
const inspection = ref(null)
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
const result = ref(null)
const savedOk = ref(false)
const suppressSave = ref(false)
let saveTimer = null

const rows = ref([])
const damageCodes = ref([])
const repairCodes = ref([])

const bulkPhotos = ref([])
const bulkUploading = ref(false)
const bulkErr = ref("")
const sectionSearch = ref("")

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

const mastersRes = createResource({
	url: "container_depot.ess.inspections.eir_masters",
	method: "GET",
	auto: true,
	onSuccess(data) {
		damageCodes.value = data.damage_codes || []
		repairCodes.value = data.repair_codes || []
		cargos.value = data.cargos || []
		rows.value = (data.checklist || []).map((i) =>
			reactive({ ...i, damage_code: ACCEPTABLE_DAMAGE, repair_code: NO_ACTION_REPAIR, remarks: "", photos: [], uploading: false, photoErr: "" })
		)
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

const filteredGroups = computed(() => {
	const q = sectionSearch.value.trim().toLowerCase()
	if (!q) return groups.value
	const out = []
	for (const g of groups.value) {
		if ((g.area || "").toLowerCase().includes(q)) {
			out.push(g)
			continue
		}
		const items = g.items.filter((it) => `${it.printed_no} ${it.item_name}`.toLowerCase().includes(q))
		if (items.length) out.push({ area: g.area, items })
	}
	return out
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

const openRes = createResource({
	url: "container_depot.ess.inspections.eir_open",
	method: "GET",
	onSuccess(data) {
		suppressSave.value = true
		header.value = data
		inspection.value = data.inspection
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
		createCleaning.value = data.create_cleaning_order !== 0
		createRepair.value = data.create_repair_order !== 0
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
			toast.success(labels.eirSubmitted, { title: data.inspection_id || data.inspection })
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

function applyDraftToRows(data) {
	if (!data || !rows.value.length) return
	const lineMap = {}
	;(data.lines || []).forEach((l) => {
		lineMap[l.item_code] = l
	})
	const photoMap = {}
	const bulk = []
	;(data.photos || []).forEach((p) => {
		if (!p.item_code) {
			bulk.push(p.photo)
			return
		}
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
	const bulk = bulkPhotos.value.map((url) => ({ item_code: "", photo: url }))
	return [...perItem, ...bulk]
}

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
	event.target.value = ""
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
		}
	} catch (e) {
		bulkErr.value = labels.photoError
	} finally {
		bulkUploading.value = false
	}
}

function removeBulkPhoto(idx) {
	bulkPhotos.value.splice(idx, 1)
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

function doSave(submit = false) {
	if (!inspection.value) return
	if (saveTimer) {
		clearTimeout(saveTimer)
		saveTimer = null
	}
	saveRes.submit({
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
		lines: JSON.stringify(buildLines()),
		photos: JSON.stringify(buildPhotos()),
		submit: submit ? 1 : 0,
	})
}

async function confirmSubmit() {
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
