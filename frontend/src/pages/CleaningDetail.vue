<template>
	<!-- Tata letak = detail Jadwal Survey: kepala, kartu info yang sama dengan barisnya di
	     daftar, tanggal, siapa — lalu isi order-nya. Layar yang sama sebelum dan sesudah Mulai:
	     spesifikasi tank, muatan terakhir, layanan yang diminta tidak bergantung pada apakah
	     cucian sudah jalan; yang berubah hanya aksi di bawah. -->
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<DetailHeader :title="labels.cleaningTitle" :chip="order ? cleaningChip(order) : null" @back="backToList" />

		<!-- Placeholder while the detail is fetched — a tap must never read as a dead button. -->
		<SkeletonDetail v-if="detailPending" :cells="8" :sections="3" />

		<!-- The detail could not be fetched and there is no cached copy to fall back on. -->
		<section v-else-if="detailFailed" class="oak-card space-y-3 p-6 text-center">
			<span class="oak-icon-tile mx-auto h-12 w-12 bg-red-50 text-red-500">
				<Icon name="alert-triangle" :size="24" />
			</span>
			<p class="text-sm text-gray-600">{{ detailError }}</p>
			<div class="flex gap-2">
				<button class="oak-btn oak-btn-secondary flex-1" @click="backToList">{{ labels.cleaningBack }}</button>
				<button class="oak-btn oak-btn-primary flex-1" @click="retryDetail">{{ labels.retry }}</button>
			</div>
		</section>

		<template v-else-if="order">
			<!-- Rekan yang menyentuhnya terakhir — di atas kartu, sebelum apa pun diisi. -->
			<EditedBy :by="order.updated_by" :name="order.updated_by_name" :at="order.updated_on" />
			<section class="oak-card space-y-3 p-4">
				<!-- Info yang sama persis dengan barisnya di list — satu komponen. -->
				<CleaningOrderInfo :o="order" />
				<LiftOnBadge :survey="order.target_survey_on" :target="order.target_lift_on" :urgent="order.target_urgent_on" />
				<div class="grid grid-cols-3 gap-2 border-t border-gray-100 pt-3">
					<div v-for="d in dateCells" :key="d.label" class="min-w-0">
						<p class="text-[11px] text-gray-400">{{ d.label }}</p>
						<p class="text-sm font-bold leading-tight text-gray-900">{{ d.value ? fmtDateTime(d.value) : "—" }}</p>
					</div>
				</div>
				<div class="space-y-1 border-t border-gray-100 pt-3 text-xs">
					<p class="flex gap-2">
						<span class="w-24 shrink-0 text-gray-400">{{ labels.svCreatedBy }}</span>
						<span class="min-w-0 font-semibold text-gray-700">{{ order.created_by_name || "—" }}</span>
					</p>
					<p class="flex gap-2">
						<span class="w-24 shrink-0 text-gray-400">{{ labels.svWorkedBy }}</span>
						<span class="min-w-0 font-semibold" :class="order.assigned_to_name ? 'text-gray-700' : 'text-gray-400'">
							{{ order.assigned_to_name || labels.svNotStarted }}
						</span>
					</p>
					<p v-if="order.inspection" class="flex gap-2">
						<span class="w-24 shrink-0 text-gray-400">{{ labels.cleaningRefEir }}</span>
						<span class="min-w-0 font-mono text-gray-700">{{ order.inspection }}</span>
					</p>
				</div>

				<!-- Where the filling-in stands: which of the three parts is still empty, without
				     scrolling to the bottom to find out. -->
				<div v-if="started" class="flex flex-wrap gap-1.5 border-t border-gray-100 pt-3">
					<span
						v-for="s in steps"
						:key="s.label"
						class="oak-chip"
						:class="s.done ? 'bg-leaf-50 text-leaf-700' : 'bg-gray-100 text-gray-500'"
					>
						<Icon :name="s.done ? 'check-circle' : 'circle'" :size="12" />{{ s.label }}
					</span>
				</div>
			</section>

			<!-- What Admin Ops asked for. Read-only on purpose: the services are what the owner
			     is billed for, and the operator washing the tank does not price the job. -->
			<section class="oak-card space-y-2 p-4">
				<p class="oak-section-title">{{ labels.cleaningRequested }}</p>
				<div v-if="order.cleaning_services && order.cleaning_services.length" class="flex flex-wrap gap-1.5">
					<span v-for="s in order.cleaning_services" :key="s.item_code" class="oak-chip bg-brand-100 text-brand-700">
						{{ s.item_name || s.item_code }}
					</span>
				</div>
				<p v-else class="text-sm text-gray-400">{{ labels.cleaningNoMethod }}</p>
				<p class="text-[11px] text-gray-400">
					<template v-if="order.cleaning_type">{{ order.cleaning_type }} · </template>
					{{ (order.cleaning_services || []).length }} {{ labels.cleaningServicesCount }}
				</p>
			</section>

			<!-- Instruksi Cleaning — free text Admin Ops left on the order (read-only). -->
			<section v-if="order.cleaning_instructions" class="oak-card space-y-2 p-4">
				<p class="oak-section-title">{{ labels.cleaningInstructions }}</p>
				<p class="whitespace-pre-line text-sm text-gray-800">{{ order.cleaning_instructions }}</p>
			</section>

			<!-- Tank spec -->
			<section class="oak-card p-4">
				<p class="oak-section-title mb-2">{{ labels.cleaningTankDetails }}</p>
				<dl class="grid grid-cols-2 gap-x-3 gap-y-3 text-sm">
					<div v-for="cell in headerCells" :key="cell.label" class="min-w-0">
						<dt class="text-[11px] uppercase tracking-wide text-gray-400">{{ cell.label }}</dt>
						<dd class="truncate font-semibold text-gray-800">{{ cell.value || "—" }}</dd>
					</div>
				</dl>
			</section>

			<!-- Cargo history -->
			<section class="oak-card p-4">
				<p class="oak-section-title mb-2">{{ labels.cleaningCargoHistory }}</p>
				<ul v-if="order.cargo_history && order.cargo_history.length" class="divide-y divide-gray-100 text-sm">
					<li v-for="(h, i) in order.cargo_history" :key="i" class="flex justify-between gap-2 py-1.5">
						<span class="truncate font-semibold text-gray-800">{{ h.cargo }}</span>
						<span class="shrink-0 text-xs text-gray-400">{{ h.date }}</span>
					</li>
				</ul>
				<p v-else class="text-sm text-gray-400">{{ labels.cleaningNoCargoHistory }}</p>
			</section>

			<!-- NOT STARTED: one action, and what pressing it records. -->
			<template v-if="!started">
				<template v-if="canStart">
					<button class="oak-btn oak-btn-primary w-full py-3 text-base" @click="startCurrent">
						<Icon name="play" :size="18" /> {{ labels.cleaningStartFull }}
					</button>
					<p class="text-center text-xs text-gray-400">{{ labels.cleaningStartAuto }}</p>
				</template>
				<!-- Already sent for review, or already finished. The server refuses a second
				     start (cleaning.start_cleaning), so offering the button here would only ever
				     produce an error message; the record (Riwayat: photos, signature, Ajukan
				     Revisi) is what the operator wants instead. -->
				<template v-else>
					<!-- Pulling it back out of review is the operator's own fix — no Admin Ops. -->
					<button
						v-if="order.status === 'Pending Review'"
						type="button"
						class="oak-btn oak-btn-secondary w-full py-2.5"
						:disabled="withdrawRes.loading"
						@click="withdrawReview(order)"
					>
						<Icon name="rotate-ccw" :size="16" /> {{ labels.cleaningWithdrawReview }}
					</button>
					<button
						type="button"
						class="oak-card oak-press flex w-full items-center gap-3 p-4 text-left"
						@click="goFinished(order)"
					>
						<span class="oak-icon-tile h-9 w-9 shrink-0 bg-sky-50 text-sky-600">
							<Icon name="clock" :size="16" />
						</span>
						<span class="min-w-0 flex-1 text-sm font-semibold text-gray-800">{{ labels.cleaningViewRecord }}</span>
						<Icon name="chevron-right" :size="16" class="shrink-0 text-gray-300" />
					</button>
				</template>
			</template>

			<!-- STARTED: the three things the operator fills in. -->
			<template v-else>
				<!-- Foto QC -->
				<section class="oak-card space-y-3 p-4">
					<p class="oak-section-title">{{ labels.cleaningQcPhotos }}</p>

					<!-- Thumbnails (3-up, square tap-friendly tiles) + inline "add" tile -->
					<div class="grid grid-cols-3 items-start gap-2">
						<!-- Keterangan per foto, di bawah petaknya — sebentuk dengan foto M&R dan
						     Letak Tank. Kolomnya sudah ada di Cleaning QC Photo dan sudah dibaca
						     Desk maupun Riwayat; tanpa kotak ini ia tidak pernah bisa terisi. -->
						<div v-for="(p, i) in qcPhotos" :key="i" class="space-y-1">
							<div class="relative aspect-square">
								<img
									:src="photoSrc(p.photo)"
									class="h-full w-full rounded-lg border border-gray-200 object-cover"
									@click="openLightbox(qcPhotos.map((x) => ({ src: photoSrc(x.photo), caption: x.caption })), i)"
								/>
								<button
									type="button"
									class="absolute right-1 top-1 flex h-8 w-8 items-center justify-center rounded-full bg-black/70 text-white shadow active:bg-black"
									:aria-label="labels.remove || 'Hapus'"
									@click="removeQcPhoto(i)"
								>
									<Icon name="x" :size="16" />
								</button>
								<PhotoMark :photo="p.photo" />
							</div>
							<input
								v-model="p.caption"
								type="text"
								class="oak-input px-2 py-1.5 text-xs"
								:placeholder="labels.photoCaption"
							/>
						</div>
						<PhotoTile v-for="it in photoQueue.items" :key="it.id" :item="it" tile="aspect-square w-full" />

						<!-- Two add tiles — the camera straight away, or the gallery for several at once -->
						<!-- The phone's own camera app, only ever reached as the fallback — see
						     utils/camera.js. -->
						<input
							ref="camInput"
							type="file"
							accept="image/*"
							capture="environment"
							multiple
							class="hidden"
							@change="onQcPhotos"
						/>
						<button
							type="button"
							class="flex aspect-square flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed border-brand-300 bg-brand-50 text-brand-600 active:bg-brand-100"
							:disabled="photoUploading"
							@click="openCameraOrFallback"
						>
							<Icon v-if="photoUploading" name="loader" :size="22" class="animate-spin" />
							<template v-else>
								<Icon name="camera" :size="22" />
								<span class="text-xs font-medium">{{ labels.photoCamera }}</span>
							</template>
						</button>
						<label
							class="flex aspect-square cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed border-brand-300 bg-brand-50 text-brand-600 active:bg-brand-100"
						>
							<Icon v-if="photoUploading" name="loader" :size="22" class="animate-spin" />
							<template v-else>
								<Icon name="image" :size="22" />
								<span class="text-xs font-medium">{{ labels.photoGallery }}</span>
							</template>
							<input
								type="file"
								accept="image/*"
								multiple
								class="hidden"
								:disabled="photoUploading"
								@change="onQcPhotos"
							/>
						</label>
					</div>
					<p v-if="!qcPhotos.length && !photoUploading" class="text-xs text-gray-400">{{ labels.cleaningQcPhotoEmpty }}</p>
				</section>

				<!-- Catatan -->
				<section class="oak-card space-y-2 p-4">
					<label class="oak-label flex items-center justify-between gap-2">
						{{ labels.cleaningRemarks }}
						<span class="font-normal normal-case text-gray-400">{{ labels.optional }}</span>
					</label>
					<textarea v-model="remarks" rows="3" class="oak-input"></textarea>
				</section>

				<!-- Tanda Tangan -->
				<section class="oak-card space-y-2 p-4">
					<div class="flex items-center justify-between">
						<p class="oak-section-title">{{ labels.cleaningSignature }}</p>
						<button v-if="signatureUrl" type="button" class="oak-link text-sm" @click="startResign">
							{{ labels.cleaningResign }}
						</button>
					</div>
					<div v-if="signatureUrl && !signing">
						<img :src="photoSrc(signatureUrl)" class="h-28 w-full rounded-xl oak-sign-paper object-contain" />
					</div>
					<div v-else>
						<canvas
							ref="sigCanvas"
							class="h-28 w-full touch-none rounded-xl oak-sign-paper border-dashed border-gray-300"
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
				<!-- Not gated on `saveRes.loading` — see EirInForm.vue: the finalise sends the whole
				     payload, so a slow autosave must never hold the button hostage. -->
				<button class="oak-btn oak-btn-primary w-full py-3" :disabled="submitting" @click="confirmComplete">
					<Icon v-if="submitting" name="loader" :size="18" class="animate-spin" />
					<span v-else>{{ labels.cleaningComplete }}</span>
				</button>
				<p class="text-center text-xs text-gray-400">{{ labels.cleaningCompleteHint }}</p>
			</template>
		</template>
	</div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { createResource } from "frappe-ui"
import { labels } from "@/utils/labels"
import { saveToast, toast } from "@/utils/toast"
import { confirm } from "@/utils/confirm"
import { openLightbox } from "@/utils/lightbox"
import { shootOrFallback } from "@/utils/camera"
import EditedBy from "@/components/EditedBy.vue"
import Icon from "@/components/Icon.vue"
import LiftOnBadge from "@/components/LiftOnBadge.vue"
import CleaningOrderInfo from "@/components/CleaningOrderInfo.vue"
import DetailHeader from "@/components/list/DetailHeader.vue"
import PhotoMark from "@/components/PhotoMark.vue"
import PhotoTile from "@/components/PhotoTile.vue"
import { usePhotoQueue } from "@/utils/photoQueue"
import SkeletonDetail from "@/components/SkeletonDetail.vue"
import { cachedResource } from "@/data/cache"
import { isLocalRef, photoSrc, send, uploadPhoto } from "@/data/send"
import { fmtDateTime } from "@/utils/surveyStatus"
import { cleaningChip } from "@/utils/cleaningStatus"


const route = useRoute()
const router = useRouter()

const order = ref(null)

// Auto-save (mirrors the EIR flow): debounced draft save on every edit.
let saveTimer = null
const savedOk = ref(false) // last auto-save succeeded
const suppressSave = ref(false) // mute auto-save while a draft is being loaded

// The operator only signs off now: Catatan (remarks) + Tanda Tangan (signature). The cleaning
// method(s) are chosen upstream by Admin Ops and shown read-only.
const remarks = ref("")
// QC photo list (uploaded file_urls).
const qcPhotos = ref([])
const photoUploading = ref(false)

// Finished (or field-done) work has no editable form to open — the Riwayat detail takes an
// ?open= deep link and fetches the order straight from the server.
function goFinished(r) {
	router.push({ path: "/cleaning/history", query: { open: r.name } })
}

// Back to In_Progress — refetch, and the sign-off form opens in place.
const withdrawRes = createResource({
	url: "container_depot.ess.cleaning.cleaning_withdraw_review",
	method: "POST",
	onSuccess: () => {
		toast.success(labels.cleaningWithdrawReviewDone)
		retryDetail()
	},
	onError: (e) => toast.error(e?.messages?.[0] || e?.message || labels.error),
})
function withdrawReview(r) {
	withdrawRes.submit({ cleaning_order: r.name })
}

// Started = the wash is running and the form is open. Before that the same screen shows the
// same facts with one button instead of three inputs.
const started = computed(() => order.value?.status === "In_Progress")
// Only a wash nobody has finished can be started. The server says so too
// (cleaning.start_cleaning refuses Completed / Pending Review); this keeps the button from
// being offered in the first place.
const canStart = computed(() => ["Pending", "Service Setup"].includes(order.value?.status))

const headerCells = computed(() => {
	const h = order.value || {}
	return [
		{ label: labels.cleaningTankType, value: h.tank_type },
		{ label: labels.equipmentType, value: h.equipment_type },
		// Owner and last cargo are not repeated here — they lead the header card above, and a
		// spec table that restates the heading is a table people stop reading.
		{ label: labels.cleaningCapacity, value: h.capacity },
		{ label: labels.cleaningTare, value: h.tare },
		{ label: labels.cleaningMgw, value: h.mgw },
		{ label: labels.cleaningMfgDate, value: h.date_of_manufacture },
		// Tgl. Periodic Test Terakhir TIDAK di sini, dan tidak bisa ditulis dari layar cuci:
		// itu fakta uji berkala, dijawab di M&R Periodic Test / EIR (LastTestField).
	]
})

// Kapan order dibuat, mulai dicuci, selesai dicuci — dibaca bersamaan.
const dateCells = computed(() => [
	{ label: labels.leakCreated, value: order.value?.order_created },
	{ label: labels.cleaningStartAt, value: order.value?.cleaning_start },
	{ label: labels.cleaningEndAt, value: order.value?.cleaning_end },
])

// Whether a detail fetch is in flight, tracked explicitly rather than derived from
// `route.query.o && !order`. The derived version flickers: completing an order nulls `order`
// while the query is still set, and the screen would flash a skeleton on its way back to the
// worklist.
const detailPending = ref(false)
const detailFailed = ref(false)
const detailError = ref("")

const detailRes = cachedResource({
	url: "container_depot.ess.cleaning.cleaning_order_detail",
	method: "GET",
	onSuccess(data) {
		detailPending.value = false
		detailFailed.value = false
		// Mute auto-save while we populate the form from the loaded order.
		suppressSave.value = true
		savedOk.value = false
		order.value = data
		remarks.value = data.remarks || ""
		signatureUrl.value = data.signature || ""
		qcPhotos.value = (data.qc_photos || []).map((p) => ({ ...p }))
				nextTick(() => {
				suppressSave.value = false
			})
	},
	// The error stays on the page here rather than in a toast: a toast disappears, and the
	// operator would be left staring at a worklist wondering why their tap did nothing.
	onError(err) {
		detailPending.value = false
		detailFailed.value = true
		detailError.value = err?.messages?.[0] || err?.message || labels.error
	},
})

function fetchDetail(name) {
	detailPending.value = true
	detailFailed.value = false
	detailRes.fetch({ cleaning_order: name })
}
function retryDetail() {
	if (route.query.o) fetchDetail(route.query.o)
}

watch(
	() => route.query.o,
	(o) => {
		if (o) {
			if (order.value?.name !== o) fetchDetail(o)
		} else {
			order.value = null
			detailPending.value = false
			detailFailed.value = false
		}
	},
	{ immediate: true }
)

// Mulai Cleaning (worklist or in-form).
//
// The status is flipped locally rather than re-fetched. The
// response carried nothing the form needed except the new status, so there is no reason to
// wait for it — and waiting is what made "Mulai" impossible in a dead spot, which locked the
// operator out of the whole form.
//
// No `ref` on this row: starting is not finishing, and the order must stay in the worklist.
async function startCleaning(name) {
	try {
		await send({
			url: "container_depot.ess.cleaning.cleaning_start",
			payload: { cleaning_order: name },
		})
		toast.success(labels.cleaningStarted)
		return true
	} catch (e) {
		toast.error(e?.message || labels.error)
		return false
	}
}

async function startCurrent() {
	if (!order.value) return
	if (await startCleaning(order.value.name)) order.value = { ...order.value, status: "In_Progress" }
}

// Server-side autosave only. The finalise has its own call (see submitCleaning), so this
// resource never sees submit=1 and never has to deal with the finalized branch.
const saveRes = createResource({
	url: "container_depot.ess.cleaning.cleaning_order_save",
	method: "POST",
	onSuccess() {
		savedOk.value = true
		saveToast.done()
		flushPendingSave()
	},
	// An autosave that could not reach the server is not worth a red toast — the operator is
	// mid-form, the local draft has the data, and the finalise will carry it. Anything the
	// server actively refused, they do need to see.
	// The busy toast is cleared either way — `fail("")` just takes the slot back.
	onError(err) {
		saveToast.fail(err?.response ? err?.messages?.[0] || err?.message || labels.error : "")
		flushPendingSave()
	},
})

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

// Debounced auto-save on every edit (mirrors EIR): only while an unfinished order is open.
function scheduleSave() {
	if (!order.value || order.value.docstatus === 1 || suppressSave.value) return
	savedOk.value = false
	if (saveTimer) clearTimeout(saveTimer)
	saveTimer = setTimeout(() => {
		saveTimer = null
		if (saveRes.loading) {
			resaveWanted = true
			return
		}
		save(false)
	}, 700)
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

function payload(submit) {
	return {
		cleaning_order: order.value.name,
		remarks: remarks.value || undefined,
		signature: signatureUrl.value || undefined,
		// An array, not a JSON string: `send` has to walk the payload to find the
		// `local:` photo references and swap them for real file_urls.
		qc_photos: qcPhotos.value.filter((p) => p.photo),
		submit: submit ? 1 : 0,
	}
}


function save(submit) {
	if (!order.value) return
	if (saveTimer) {
		clearTimeout(saveTimer)
		saveTimer = null
	}
	if (submit) {
		submitCleaning()
		return
	}
	const p = payload(false)
	saveToast.start()
	// Strip anything not yet uploaded: a `local:` string written into a QC photo
	// row would be a broken image for ever. Those travel with the finalise instead.
	saveRes.fetch({
		...p,
		signature: isLocalRef(p.signature) ? undefined : p.signature,
		qc_photos: JSON.stringify(p.qc_photos.filter((x) => !isLocalRef(x.photo))),
	})
}

// Held while the send is in flight. `send` waits for the server (and for
// any QC photos to upload), so the button is live for a real second or two — long enough for
// an impatient second tap to raise a second sign-off under a second request_id.
const submitting = ref(false)

/** Hand the finished sign-off to `send`: photos first, then the document, then wait. */
async function submitCleaning() {
	const o = order.value
	if (submitting.value) return
	submitting.value = true
	try {
		await send({
			// Cleared by the queue once the save has actually landed — not here. If this row
			// comes back refused (the order closed on the Desk meanwhile), the draft is what
			// still holds the photos and the remarks.
			url: "container_depot.ess.cleaning.cleaning_order_save",
			payload: payload(true),
		})
		toast.success(labels.cleaningSubmitted, {
			title: o.order_id || o.name,
		})
		// It is now in review — the list, filtered to that pill, is where it went.
		backToList()
	} catch (e) {
		toast.error(e?.message || labels.error)
	} finally {
		submitting.value = false
	}
}

// --- QC photo handlers ------------------------------------------------------
function removeQcPhoto(i) {
	qcPhotos.value.splice(i, 1)
}
async function onQcPhotos(e) {
	const files = Array.from(e.target.files || [])
	e.target.value = "" // allow re-picking the same file
	await addQcPhotos(files)
}

// In-app viewfinder: shutter -> upload, no camera-app confirm screen in between
// (utils/camera.js). QC evidence is shot in a run of several, so it stays open between them.
const camInput = ref(null)
function openCameraOrFallback() {
	return shootOrFallback(camInput, (file) => addQcPhotos([file]))
}

// Each photo shows itself while it goes up — see EirInForm for why.
const photoQueue = usePhotoQueue()

async function addQcPhotos(files) {
	if (!files.length) return false
	// `last` adalah jawaban untuk viewfinder: strip di dalam kamera menandai jepretan ini dari
	// nilai yang dikembalikan (lihat utils/camera.js), jadi kegagalan yang ditelan di sini akan
	// tampil sebagai "terkirim" pada foto yang tidak ke mana-mana.
	let last = false
	photoQueue.clearFailed()
	photoUploading.value = true
	try {
		for (const f of files) {
			const id = photoQueue.add(f)
			try {
				const url = await uploadFile(f)
				qcPhotos.value.push({ photo: url, caption: "" })
				last = url
				photoQueue.done(id)
			} catch (err) {
				last = false
				toast.error(labels.error)
				photoQueue.fail(id)
			}
		}
	} finally {
		photoUploading.value = false
	}
	return last
}

// A real Back when the list pushed us here (the list restores its scroll); a replace when
// we were landed on directly (a notification link), so Back never walks out of the app.
function backToList() {
	resetForm()
	if (window.history.state?.back) router.back()
	else router.replace({ path: "/cleaning", query: {} })
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
	qcPhotos.value = []
}

// --- file upload + virtual signature pad ------------------------------------

/**
 * Take a picked photo and hand back a reference the form can hold onto.
 *
 * It goes up straight away, so the autosave that follows puts a real file_url on the order
 * and the QC evidence survives a reload. When the link is down it is parked instead and the
 * `local:` reference travels through the form exactly like a URL, until `send` uploads it on
 * Selesaikan (see data/send.js).
 */
async function uploadFile(file) {
	return uploadPhoto(file)
}

const sigCanvas = ref(null)
const signatureUrl = ref("")

// The three parts of a sign-off, and which are filled. Nothing new is being asked for — the
// chips only save the operator scrolling to the bottom to find out what is still missing.
const steps = computed(() => [
	{ label: labels.cleaningStepMethod, done: !!(order.value?.cleaning_services || []).length },
	{ label: labels.cleaningQcPhotos, done: !!qcPhotos.value.length },
	{ label: labels.cleaningStepSign, done: !!signatureUrl.value },
])

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

// Auto-save on every edit: Catatan (remarks) + Tanda Tangan (signature) + QC/material.
watch([remarks, signatureUrl], scheduleSave)
watch(qcPhotos, scheduleSave, { deep: true })
</script>
