<template>
	<div class="space-y-4">
		<!-- Form header (the page header + worklist live in Eir.vue). Floats under the app
		     bar so the surveyor always knows which tank the checklist under their thumb
		     belongs to — this form is long enough to scroll for a minute straight.
		     Everything shown once elsewhere is gone from here: the booking code has its own
		     row in Dokumen Rujukan, the container number is the title, and the start time is
		     a stamp, not a sentence. -->
		<div class="oak-subheader-stacked -mx-4 flex items-center gap-2 border-b border-gray-200/80 bg-gray-50/95 px-4 py-2 backdrop-blur">
			<button class="oak-btn oak-btn-secondary px-2 py-2" @click="emit('back')">
				<Icon name="arrow-left" :size="18" />
			</button>
			<div class="min-w-0 flex-1">
				<h2 class="truncate text-base font-extrabold leading-tight tracking-tight">
					{{ labels.eirBadgeIn }} · {{ header?.container_no || "" }}<span v-if="header?.principal" class="font-semibold text-gray-500"> · {{ header.principal }}</span>
				</h2>
				<p class="truncate text-[11px] text-gray-500">
					<span v-if="eirCode" class="font-mono">{{ eirCode }}</span>
					<span v-if="workStartedShort"> · {{ labels.eirStartedAt }} {{ workStartedShort }}</span>
				</p>
			</div>
		</div>

		<p v-if="fetchError" class="oak-card border-red-200 bg-red-50 p-3 text-sm text-red-700">{{ fetchError }}</p>

		<!-- Until the EIR loads there was nothing here at all: a back button, an empty title,
		     and a blank page. This is the heaviest form in the app and the one most often
		     opened on a bad link, so it is the last place that should look broken while it
		     works. -->
		<SkeletonDetail v-if="!header && !fetchError" :cells="6" :sections="3" />

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
			<!-- Step 1b — referred voucher: shipper / truck / driver, one read-only block.
			     Was two grey cards stacked (bon codes, then the crew) which read as two
			     different facts about the same bon. -->
			<section class="oak-section space-y-2">
				<div class="flex items-center gap-2">
					<Icon name="file-text" :size="16" class="text-gray-400" />
					<p class="oak-section-title">{{ labels.referredVoucher }}</p>
				</div>
				<dl class="grid grid-cols-2 gap-x-4 gap-y-2.5 rounded-xl bg-gray-50 p-3 text-sm sm:grid-cols-3">
					<div v-for="f in voucherCells" :key="f.label">
						<dt class="text-xs text-gray-500">{{ f.label }}</dt>
						<dd class="truncate font-semibold" :class="f.mono ? 'font-mono text-brand-600' : 'text-gray-800'">{{ f.value || "—" }}</dd>
					</div>
				</dl>
				<p class="text-[11px] text-gray-400">{{ labels.eirVoucherLocked }}</p>
			</section>

			<!-- Step 2 — tank data. The tank's OWN facts are editable here and saved onto the
			     Container master: the EIR is the one moment somebody is standing at the tank
			     with its data plate in front of them, and a master left half empty stays that
			     way for ever. What the depot fills in by itself (owner, depot, ex vessel)
			     stays read-only underneath. -->
			<section class="oak-section space-y-3">
				<div class="flex items-center gap-2">
					<Icon name="package" :size="16" class="text-gray-400" />
					<p class="oak-section-title">{{ labels.eirHeader }}</p>
				</div>
				<p class="text-xs text-gray-400">{{ labels.eirTankHint }}</p>
				<div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
					<div>
						<label class="oak-label">{{ labels.type }}</label>
						<select v-model="tank.container_type" class="oak-input">
							<option value="">—</option>
							<option v-for="o in tankOptions.container_type" :key="o" :value="o">{{ o }}</option>
						</select>
					</div>
					<div>
						<label class="oak-label">{{ labels.tankSize }}</label>
						<select v-model="tank.size" class="oak-input">
							<option value="">—</option>
							<option v-for="o in tankOptions.size" :key="o" :value="o">{{ o }}</option>
						</select>
					</div>
					<div>
						<label class="oak-label">{{ labels.serialNo }}</label>
						<input v-model.trim="tank.serial_no" class="oak-input" />
					</div>
					<div>
						<label class="oak-label">{{ labels.dateManufacture }}</label>
						<input v-model="tank.manufacture_date" type="date" class="oak-input" />
					</div>
					<div>
						<label class="oak-label">{{ labels.capacity }}</label>
						<input v-model="tank.capacity" type="number" inputmode="decimal" placeholder="L" class="oak-input" />
					</div>
					<div>
						<label class="oak-label">{{ labels.tare }}</label>
						<input v-model="tank.tare_weight" type="number" inputmode="decimal" class="oak-input" />
					</div>
					<div>
						<label class="oak-label">{{ labels.maxGross }}</label>
						<input v-model="tank.max_gross_weight" type="number" inputmode="decimal" class="oak-input" />
					</div>
				</div>
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
				<!-- Deliberately NOT gated on `saveRes.loading`. The submit builds and sends the
				     whole EIR itself, so waiting for an autosave to land buys nothing — and on a
				     weak link it left the operator tapping a dead button for twenty seconds. -->
				<button
					class="oak-btn oak-btn-primary w-full py-3"
					:disabled="submitting || missingFields.length > 0"
					@click="confirmSubmit"
				>
					<Icon v-if="!submitting" name="check-circle" :size="18" />
					{{ submitting ? "…" : labels.eirSendReview }}
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
import { saveToast, toast } from "@/utils/toast"
import { confirm } from "@/utils/confirm"
import { openLightbox } from "@/utils/lightbox"
import { session } from "@/data/session"
import Icon from "@/components/Icon.vue"
import SkeletonDetail from "@/components/SkeletonDetail.vue"
import SearchSelect from "@/components/SearchSelect.vue"
import ChecklistDamage from "@/components/ChecklistDamage.vue"
import { isLocalRef, photoSrc, send, uploadPhoto } from "@/data/send"

// Form-only EIR-In view. The combined worklist lives in Eir.vue, which opens this with
// the picked draft's name and listens for `back` / `submitted`.
const props = defineProps({ inspection: { type: String, required: true } })
const emit = defineEmits(["back", "submitted"])

const eirType = "EIR-In"
const header = ref(null)
const inspection = ref(null)
const workStartedOn = ref("") // set once the operator presses Mulai; gates editing
const eirCode = computed(() => header.value?.inspection_id || inspection.value || "")
// "2026-08-19 22:14:53.627161" is a database row, not something to read on a phone.
const workStartedShort = computed(() => {
	const [d, t] = String(workStartedOn.value || "").split(" ")
	return d ? `${d.slice(8, 10)}/${d.slice(5, 7)} ${(t || "").slice(0, 5)}` : ""
})
// The tank's own facts, editable here and written to the Container master on save
// (eir.TANK_MASTER_FIELDS). Everything the depot fills in by itself stays out.
const tank = reactive({
	container_type: "",
	size: "",
	serial_no: "",
	manufacture_date: "",
	capacity: "",
	tare_weight: "",
	max_gross_weight: "",
})
const tankOptions = ref({ container_type: [], size: [] })
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
		tankOptions.value = { container_type: [], size: [], ...(data.tank_options || {}) }
		rows.value = (data.checklist || []).map((i) =>
			reactive({ ...i, damage_code: ACCEPTABLE_DAMAGE, repair_code: NO_ACTION_REPAIR, remarks: "", photos: [], uploading: false, photoErr: "", added: false })
		)
		if (header.value) applyDraftToRows(header.value)
	},
})

// The read-only block: what this EIR was handed rather than what the surveyor writes. Depo
// sits here too — it comes from the bon's booking, not off the tank. Owner and container
// number are the screen title, and Last Cargo is the Cargo picker below; neither repeats.
const voucherCells = computed(() => [
	{ label: labels.bookingCode, value: bookingCode.value, mono: true },
	{ label: labels.referredVoucher, value: referredVoucher.value, mono: true },
	{ label: labels.depot, value: header.value?.depot },
	{ label: labels.shipper, value: shipper.value },
	{ label: labels.truckNo, value: truckNo.value },
	{ label: labels.driverName, value: driver.value },
	{ label: labels.driverPhone, value: driverPhone.value },
])

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
		Object.keys(tank).forEach((k) => {
			tank[k] = data[k] ?? ""
		})
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
		// Field submit now moves the EIR to Pending Review (docstatus stays 0) — Admin Ops
		// finalises it on the Desk. Treat that as "done" from the operator's side.
		if (data.docstatus === 1 || data.pending_review) {
			saveToast.close()
			toast.success(data.pending_review ? labels.eirSentForReview : labels.eirSubmitted, {
				title: data.inspection_id || data.inspection,
			})
			emit("submitted", data.inspection)
			emit("back")
		} else {
			savedOk.value = true
			saveToast.done()
		}
		flushPendingSave()
	},
	onError(err) {
		saveToast.fail(err?.messages?.[0] || err?.message || labels.error)
		flushPendingSave()
	},
})

const fetchError = computed(() => (openRes.error ? openRes.error.messages?.[0] || openRes.error.message : null))
const saveError = computed(() => (saveRes.error ? saveRes.error.messages?.[0] || saveRes.error.message : null))

// Mulai: stamp work_started_on server-side, then unlock the checklist.
// Mulai stamps the start time locally rather than reading it back off the response: the
// response carried nothing else the form needed, and in a dead spot the call is queued, which
// would otherwise lock the surveyor out of the entire checklist — the one screen the offline
// queue exists to protect. `start_eir` is idempotent, so a queued Mulai keeps the first stamp.
//
// No `ref` on this row: starting is not finishing, so the EIR stays in the worklist.
async function startWork() {
	if (!inspection.value) return
	try {
		await send({
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
		// Saved line = the card stays open, even one that only says "acceptable".
		r.added = Boolean(l) || rowHasFinding(r)
	})
}

// Every card the operator has OPENED travels, not only the ones that already say
// something. A freshly added part carries "v / X" (checked, acceptable) and nothing else,
// and used to be dropped on both sides — so it disappeared at the next reload and took its
// photos with it into Foto Cepat. `added` is what tells the server to keep such a line.
function buildLines() {
	return rows.value
		.filter((r) => r.added || rowHasFinding(r))
		.map((r) => ({
			item_code: r.item_code,
			damage_code: r.damage_code || undefined,
			repair_code: r.repair_code || undefined,
			remarks: (r.remarks || "").trim() || undefined,
			added: 1,
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
 * It goes up straight away, so the autosave a second later writes a real file_url into the
 * draft and a reload never costs the surveyor a photo. In a dead spot it falls back to a
 * `local:` reference that travels through the form exactly like a URL, and `send` uploads it
 * when the EIR is submitted (see data/send.js).
 */
async function uploadFile(file) {
	return uploadPhoto(file)
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

// --- Autosave -----------------------------------------------------------------
// The debounced autosave goes straight to the server: that is what keeps Admin Ops seeing
// live progress on the Desk, and it is the only thing standing between a closed tab and a
// re-typed EIR. It cannot carry photos that have not been uploaded yet, so those are
// stripped here and travel with the final submit instead.


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
		// Sent as arrays, not JSON strings: `send` has to be able to walk the payload to
		// find the `local:` photo references and swap them for real file_urls.
		lines: buildLines(),
		photos: buildPhotos(),
		// One JSON blob rather than seven params: the server takes only the keys it knows
		// (eir.TANK_MASTER_FIELDS) and writes nothing when none of them changed.
		tank: JSON.stringify(tank),
		submit: submit ? 1 : 0,
	}
}

function doSave(submit = false) {
	if (!inspection.value) return
	if (saveTimer) {
		clearTimeout(saveTimer)
		saveTimer = null
	}
	if (submit) {
		submitEir()
		return
	}
	// Draft autosave to the server. Strip anything not yet uploaded — a `local:` string
	// written into Inspection Photo would be a broken image for ever.
	const payload = eirPayload(false)
	saveToast.start()
	saveRes.submit({
		...payload,
		signature: isLocalRef(payload.signature) ? undefined : payload.signature,
		lines: JSON.stringify(payload.lines),
		photos: JSON.stringify(payload.photos.filter((p) => !isLocalRef(p.photo))),
	})
}

// Held while the send is in flight. `send` waits for the server, and for
// every stashed photo to upload first — on 3G that is long enough for an impatient second tap
// to raise a second EIR under a second request_id.
const submitting = ref(false)

/** Hand the finished EIR to `send`, which posts it and waits for the server's answer. */
async function submitEir() {
	if (submitting.value) return
	submitting.value = true
	try {
		await send({
			url: "container_depot.ess.inspections.eir_save_draft",
			payload: eirPayload(true),
		})
		toast.success(labels.eirSentForReview, {
			title: eirCode.value || inspection.value,
		})
		emit("submitted", inspection.value)
		emit("back")
	} catch (e) {
		toast.error(e?.message || labels.error)
	} finally {
		submitting.value = false
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

// Never two autosaves in flight at once. Each one writes the whole document, so on a slow
// link an earlier response landing after a later one restores stale text over what the
// operator has since typed. When the debounce fires mid-flight we remember the edit and
// re-arm from the response handler instead of stacking a second POST.
let resaveWanted = false

/** Called when a save settles: if edits arrived while it flew, start the debounce again. */
function flushPendingSave() {
	if (!resaveWanted) return
	resaveWanted = false
	scheduleSave()
}

function scheduleSave() {
	if (!inspection.value || suppressSave.value) return
	savedOk.value = false
	if (saveTimer) clearTimeout(saveTimer)
	saveTimer = setTimeout(() => {
		saveTimer = null
		if (saveRes.loading) {
			resaveWanted = true
			return
		}
		doSave(false)
	}, 700)
}

watch([tanggal, tankStatus, cargo, remarks, reffDoc, signatureUrl, createCleaning, createRepair], scheduleSave)
watch(tank, scheduleSave, { deep: true })
watch(rows, scheduleSave, { deep: true })
watch(bulkPhotos, scheduleSave, { deep: true })

onMounted(() => {
	openRes.submit({ inspection: props.inspection })
})
</script>
