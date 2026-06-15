<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<div class="flex flex-wrap items-center justify-between gap-2">
			<div class="flex items-center gap-2">
				<span class="oak-icon-tile h-9 w-9 bg-leaf-50 text-leaf-600"><Icon name="clipboard" :size="20" /></span>
				<h1 class="text-lg font-extrabold tracking-tight">{{ labels.eirTitle }}</h1>
			</div>
			<div class="flex items-center gap-2">
				<router-link to="/eir/history" class="oak-btn oak-btn-secondary px-3 py-2">
					<Icon name="clock" :size="16" /> {{ labels.eirHistory }}
				</router-link>
				<button v-if="header" class="oak-btn oak-btn-secondary px-3 py-2" @click="reset">
					<Icon name="rotate-ccw" :size="16" /> {{ labels.newEir }}
				</button>
			</div>
		</div>

		<!-- Step 1 — source: container number + EIR type -->
		<section class="oak-section space-y-4">
			<div>
				<label class="oak-label">{{ labels.containerNumber }}</label>
				<div class="flex gap-2">
					<input
						v-model.trim="containerNo"
						type="text"
						autocapitalize="characters"
						:placeholder="labels.containerNumberPlaceholder"
						class="oak-input uppercase"
						@keyup.enter="doFetch"
					/>
					<button
						class="oak-btn oak-btn-primary shrink-0 px-4"
						:disabled="!containerNo || openRes.loading"
						@click="doFetch"
					>
						<Icon v-if="!openRes.loading" name="search" :size="16" />
						{{ openRes.loading ? "…" : labels.eirFetch }}
					</button>
				</div>
				<p v-if="fetchError" class="mt-1.5 flex items-center gap-1.5 text-sm text-red-600">
					<Icon name="alert-circle" :size="15" /> {{ fetchError }}
				</p>
				<p class="mt-1.5 text-xs text-gray-400">{{ labels.eirDraftHint }}</p>
			</div>
			<div>
				<label class="oak-label">{{ labels.eirType }}</label>
				<div class="grid grid-cols-2 gap-2">
					<button
						v-for="t in ['EIR-In', 'EIR-Out']"
						:key="t"
						class="oak-toggle"
						:class="eirType === t ? 'oak-toggle-on' : 'oak-toggle-off'"
						@click="eirType = t"
					>
						{{ t }}
					</button>
				</div>
			</div>
		</section>

		<!-- Quick lists (landing only): latest drafts to resume + latest completed -->
		<template v-if="!header">
			<!-- Draft EIRs -->
			<section class="oak-section space-y-3">
				<div class="flex items-center justify-between gap-2">
					<div class="flex items-center gap-2">
						<Icon name="edit-3" :size="16" class="text-amber-500" />
						<p class="oak-section-title">{{ labels.eirDraftList }}</p>
					</div>
					<router-link to="/eir/history" class="oak-link text-sm">{{ labels.eirListMore }}</router-link>
				</div>
				<ul v-if="draftRes.loading && !draftItems.length" class="space-y-2">
					<li v-for="n in 3" :key="n" class="oak-skeleton h-12 rounded-xl"></li>
				</ul>
				<p v-else-if="!draftItems.length" class="py-2 text-center text-sm text-gray-400">{{ labels.eirDraftEmpty }}</p>
				<ul v-else class="divide-y divide-gray-100">
					<li v-for="r in draftItems" :key="r.name">
						<button class="flex w-full items-center gap-3 py-2.5 text-left" @click="resumeDraft(r)">
							<span class="oak-icon-tile h-9 w-9 shrink-0 bg-amber-50 text-amber-600"><Icon name="clipboard" :size="16" /></span>
							<div class="min-w-0 flex-1">
								<p class="truncate font-semibold text-gray-900">{{ r.container_no || r.container }}</p>
								<p class="truncate text-xs text-gray-500">{{ r.inspection_type }} · {{ fmtDate(r.eir_date || r.creation) }}</p>
								<p class="truncate text-[11px] text-gray-400">{{ r.inspection_id || r.name }}</p>
							</div>
							<span class="oak-chip shrink-0 bg-amber-100 text-amber-800">{{ labels.eirResume }}</span>
						</button>
					</li>
				</ul>
			</section>

			<!-- Completed (submitted) EIRs -->
			<section class="oak-section space-y-3">
				<div class="flex items-center justify-between gap-2">
					<div class="flex items-center gap-2">
						<Icon name="check-circle" :size="16" class="text-leaf-600" />
						<p class="oak-section-title">{{ labels.eirCompleteList }}</p>
					</div>
					<router-link to="/eir/history" class="oak-link text-sm">{{ labels.eirListMore }}</router-link>
				</div>
				<ul v-if="doneRes.loading && !doneItems.length" class="space-y-2">
					<li v-for="n in 3" :key="n" class="oak-skeleton h-12 rounded-xl"></li>
				</ul>
				<p v-else-if="!doneItems.length" class="py-2 text-center text-sm text-gray-400">{{ labels.eirCompleteEmpty }}</p>
				<ul v-else class="divide-y divide-gray-100">
					<li v-for="r in doneItems" :key="r.name" class="flex items-center gap-3 py-2.5">
						<span class="oak-icon-tile h-9 w-9 shrink-0 bg-leaf-50 text-leaf-600"><Icon name="clipboard" :size="16" /></span>
						<div class="min-w-0 flex-1">
							<p class="truncate font-semibold text-gray-900">{{ r.container_no || r.container }}</p>
							<p class="truncate text-xs text-gray-500">{{ r.inspection_type }}<span v-if="r.tank_status"> · {{ r.tank_status }}</span> · {{ fmtDate(r.eir_date || r.creation) }}</p>
							<p class="truncate text-[11px] text-gray-400">{{ r.inspection_id || r.name }}</p>
						</div>
						<span class="oak-chip shrink-0 bg-leaf-100 text-leaf-800">{{ labels.eirStatusSubmitted }}</span>
					</li>
				</ul>
			</section>
		</template>

		<!-- Steps 2-6 appear once a draft is open -->
		<template v-if="header">
			<!-- Step 1b — referred voucher: pull shipper / truck / driver (read-only) -->
			<section class="oak-section space-y-3">
				<div class="flex items-center gap-2">
					<Icon name="file-text" :size="16" class="text-gray-400" />
					<p class="oak-section-title">{{ labels.referredVoucher }}</p>
				</div>
				<div>
					<div class="flex gap-2">
						<input
							v-model.trim="referredVoucher"
							type="text"
							:placeholder="voucherPlaceholder"
							class="oak-input"
							@keyup.enter="doVoucherFetch"
						/>
						<button
							class="oak-btn oak-btn-primary shrink-0 px-4"
							:disabled="voucherRes.loading"
							@click="doVoucherFetch"
						>
							<Icon v-if="!voucherRes.loading" name="search" :size="16" />
							{{ voucherRes.loading ? "…" : labels.eirFetch }}
						</button>
					</div>
					<p class="mt-1.5 text-xs text-gray-400">{{ voucherHint }}</p>
					<p v-if="voucherError" class="mt-1.5 flex items-center gap-1.5 text-sm text-red-600">
						<Icon name="alert-circle" :size="15" /> {{ voucherError }}
					</p>
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
				<div>
					<label class="oak-label">{{ labels.tanggal }}</label>
					<input v-model="tanggal" type="date" class="oak-input bg-gray-50 text-gray-500" readonly />
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
				<select v-model="cargo" class="oak-input">
					<option value="">— {{ labels.cargo }} —</option>
					<option v-for="c in cargos" :key="c" :value="c">{{ c }}</option>
				</select>
				<p class="text-xs text-gray-400">{{ labels.cargoHint }}</p>
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
				<div v-for="g in groups" :key="g.area">
					<p class="border-b border-gray-100 bg-gray-50 px-4 py-1.5 text-xs font-bold uppercase tracking-wide text-gray-500">
						{{ g.area }}
					</p>
					<div
						v-for="item in g.items"
						:key="item.item_code"
						class="border-b border-gray-100 px-4 py-3 last:border-b-0"
					>
						<p class="text-sm font-semibold text-gray-800">{{ item.printed_no }}. {{ item.item_name }}</p>
						<div class="mt-2 grid grid-cols-2 gap-2">
							<select v-model="item.damage_code" class="oak-input px-2.5 py-2">
								<option value="">— {{ labels.colDamage }} —</option>
								<option v-for="d in damageCodes" :key="d.code" :value="d.code">{{ d.code }} — {{ d.description }}</option>
							</select>
							<select v-model="item.repair_code" class="oak-input px-2.5 py-2">
								<option value="">— {{ labels.colRepair }} —</option>
								<option v-for="r in repairCodes" :key="r.code" :value="r.code">{{ r.code }} — {{ r.description }}</option>
							</select>
						</div>
						<!-- Photos for this item (multi) — saved per section, above the keterangan -->
						<div class="mt-2 flex flex-wrap items-center gap-2">
							<div v-for="(url, idx) in item.photos" :key="url" class="relative">
								<img :src="url" class="h-16 w-16 rounded-lg border border-gray-200 object-cover" />
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
									multiple
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
			</section>

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
					@click="doSave(true)"
				>
					<Icon v-if="!saveRes.loading" name="check-circle" :size="18" />
					{{ saveRes.loading ? "…" : labels.submitEir }}
				</button>
			</section>
		</template>

		<!-- Finalized -->
		<section v-if="submitted" class="animate-slide-up rounded-2xl border border-leaf-200 bg-leaf-50 p-4">
			<p class="flex items-center gap-2 font-bold text-leaf-800">
				<Icon name="check-circle" :size="18" /> {{ labels.eirSubmitted }}
			</p>
			<p class="mt-1 pl-7 text-sm text-gray-700">{{ submitted }}</p>
			<button class="oak-link mt-2 inline-flex items-center gap-1 pl-7 text-sm" @click="submitted = null">
				<Icon name="plus" :size="14" /> {{ labels.newEir }}
			</button>
		</section>
	</div>
</template>

<script setup>
import { computed, nextTick, reactive, ref, watch } from "vue"
import { createResource } from "frappe-ui"
import { labels } from "@/utils/labels"
import { session } from "@/data/session"
import Icon from "@/components/Icon.vue"

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
	// The gate-date cell follows the chosen EIR type: In -> EIR-In Date, Out -> EIR-Out Date.
	const isOut = eirType.value === "EIR-Out"
	return [
		{ label: labels.containerNumber, value: h.container_no },
		{ label: labels.serialNo, value: h.serial_no },
		{ label: labels.dateManufacture, value: h.manufacture_date },
		{ label: labels.ownerPrincipal, value: h.principal },
		{ label: isOut ? labels.eirOutDate : labels.eirInDate, value: isOut ? h.eir_out_date : h.eir_in_date },
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

// Landing quick lists: the user's 3 latest drafts (resumable) + 3 latest submitted.
const LANDING_LIMIT = 3
const draftItems = ref([])
const doneItems = ref([])
const draftRes = createResource({
	url: "container_depot.ess.inspections.eir_history",
	method: "GET",
	makeParams: () => ({ docstatus: 0, page_length: LANDING_LIMIT }),
	auto: true,
	onSuccess: (data) => (draftItems.value = data.items || []),
})
const doneRes = createResource({
	url: "container_depot.ess.inspections.eir_history",
	method: "GET",
	makeParams: () => ({ docstatus: 1, page_length: LANDING_LIMIT }),
	auto: true,
	onSuccess: (data) => (doneItems.value = data.items || []),
})
function reloadLandingLists() {
	draftRes.reload()
	doneRes.reload()
}
function resumeDraft(r) {
	containerNo.value = r.container_no || r.container
	if (r.inspection_type) eirType.value = r.inspection_type
	doFetch()
}
function fmtDate(v) {
	return v ? String(v).slice(0, 10) : "—"
}

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
		// Tank status + cargo are pulled from the voucher (Container Booking Item) as
		// editable defaults — the user can still change them before submit.
		if (data.tank_status) tankStatus.value = data.tank_status
		if (data.cargo) cargo.value = data.cargo
		// Depot follows the bon's booking (Container Booking.depot) — refresh the header.
		if (data.depot && header.value) header.value.depot = data.depot
		// Persist immediately (no debounce): the voucher reference and its snapshot
		// (truck / driver / driver phone / shipper) are saved onto the draft the moment
		// they are fetched. The server re-resolves the read-only snapshot from the ref.
		doSave(false)
	},
})
const voucherError = computed(() => {
	if (voucherRes.error) return voucherRes.error.messages?.[0] || voucherRes.error.message
	return null
})
const voucherPlaceholder = computed(() => (eirType.value === "EIR-In" ? "ORD-BKR-…" : "ORD-MT-…"))
const voucherHint = computed(() => (eirType.value === "EIR-In" ? labels.voucherHintIn : labels.voucherHintOut))
function doVoucherFetch() {
	voucherRes.submit({
		voucher: referredVoucher.value || "",
		inspection_type: eirType.value,
		container: header.value?.container || containerNo.value || "",
	})
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
	reloadLandingLists()
}
</script>
