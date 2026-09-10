<template>
	<div class="space-y-4">
		<!-- Header + bar langkah, komponen yang sama dengan EIR-In: satu operator mengerjakan
		     kedua arah dalam satu shift, dan dua kerangka form yang berbeda untuk pekerjaan
		     yang sama bentuknya hanya menambah yang harus dihafal. -->
		<EirFormHeader
			:title="headerTitle"
			:steps="workStartedOn ? STEPS : []"
			:step="step"
			:started-ms="startedMs"
			:status="saveStatus"
			@back="emit('back')"
		/>

		<!-- Rekan yang menyentuhnya terakhir. Di atas isian, bukan di bawahnya: yang perlu
		     dibaca sebelum menimpa sesuatu tidak boleh berada di ujung gulungan. -->
		<EditedBy :by="header?.updated_by" :name="header?.updated_by_name" :at="header?.updated_on" />

		<p v-if="fetchError" class="oak-card border-red-200 bg-red-50 p-3 text-sm text-red-700">{{ fetchError }}</p>

		<!-- Until the EIR loads there was nothing here at all: a back button, an empty title,
		     and a blank page. This is the heaviest form in the app and the one most often
		     opened on a bad link, so it is the last place that should look broken while it
		     works. -->
		<SkeletonDetail v-if="!header && !fetchError" :cells="6" :sections="3" />

		<template v-if="header">
			<!-- Work-timing gate: the checklist stays locked until the operator presses Mulai,
			     so Mulai → Submit measures how long the inspection actually took. -->
			<template v-if="!workStartedOn">
				<section class="oak-section space-y-1">
					<div class="flex items-baseline justify-between gap-2">
						<p class="truncate font-mono text-base font-extrabold text-gray-900">{{ header.container_no }}</p>
						<span class="shrink-0 font-mono text-[10px] text-gray-400">{{ eirCode }}</span>
					</div>
					<p class="truncate text-xs text-gray-500">{{ identityLine }}</p>
				</section>

				<div class="oak-footer -mx-4 border-t border-gray-200/80 bg-gray-50/95 px-4 py-3 backdrop-blur">
					<button class="oak-btn oak-btn-primary w-full py-3" @click="startWork">
						<Icon name="play" :size="18" />
						{{ labels.eirStartOne }} {{ header.container_no }}
					</button>
					<p class="mt-1.5 text-center text-[11px] text-gray-400">
						{{ batchMode ? labels.eirStartBatchHint : labels.eirStartHint }}
					</p>
				</div>
			</template>

			<!-- v-show, bukan v-if: berpindah langkah tidak boleh membongkar grid foto yang
			     sedang meng-upload atau daftar seal yang setengah diketik. -->
			<div v-show="workStartedOn && step === 0" class="space-y-4">
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

						<!-- Kelengkapan saat EIR-In. The damage list above says what was broken
						     when the tank came in; this says what it CARRIED — the only thing a
						     strap that never left shows up against. Read-only here on purpose:
						     the boxes to fill are the ones further down, which carry the same
						     numbers per slot as their baseline. -->
						<div v-if="prevFittings.length" class="mt-3">
							<p class="mb-1.5 text-xs font-bold uppercase tracking-wide text-gray-400">{{ labels.eirOutPrevFittings }}</p>
							<div class="overflow-hidden rounded-lg border border-gray-100">
								<template v-for="g in prevFittings" :key="g.compartment">
									<p v-if="g.compartment" class="bg-gray-50 px-3 py-1 text-[10px] font-bold uppercase tracking-wide text-gray-500">{{ g.compartment }}</p>
									<div v-for="(f, i) in g.items" :key="i" class="flex items-baseline justify-between gap-3 border-t border-gray-100 px-3 py-1.5 first:border-t-0">
										<p class="min-w-0 truncate text-xs text-gray-600">
											{{ f.item_label }}<span v-if="f.slot_label" class="text-gray-400"> · {{ f.slot_label }}</span>
										</p>
										<p class="shrink-0 text-xs font-semibold text-gray-800">
											{{ f.value }}<span v-if="f.uom" class="font-normal text-gray-400"> {{ f.uom }}</span>
										</p>
									</div>
								</template>
							</div>
						</div>

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

			</div>

			<div v-show="workStartedOn && step === 1" class="space-y-4">
			<!-- Kelengkapan tank — the same fill-in boxes as EIR-In, shown beside what the
			     tank arrived with, so a strap that never left is a visible difference. -->
			<TankFittings v-if="fittings.length" :rows="fittings" :hint="labels.fittingsHintOut" show-baseline />

			<!-- Seal numbers — one row per seal, added as the surveyor fits them. Kept LAST
			     of the input blocks: seals are fitted after everything else is checked. -->
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
							autocorrect="off"
							autocomplete="off"
							spellcheck="false"
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

			</div>

			<div v-show="workStartedOn && step === 2" class="space-y-4">
			<!-- Foto Cepat (bulk) -->
			<section class="oak-section space-y-3">
				<div class="flex items-center gap-2">
					<Icon name="camera" :size="16" class="text-brand-500" />
					<p class="oak-section-title">{{ labels.bulkPhotoTitle }}</p>
				</div>
				<p class="text-xs text-gray-400">{{ labels.bulkPhotoHint }}</p>
				<!-- Dua kolom, tiap foto dengan kotak keterangannya sendiri di bawahnya. Kotak
				     selebar thumbnail 80 px tidak bisa diketik di HP; separuh kartu bisa — pola yang
				     sama dipakai foto M&R. Keterangan itulah yang dibaca orang Desk di sebelah
				     fotonya, karena kode kerusakan hanya menyebut JENIS-nya. -->
				<div class="grid grid-cols-2 items-start gap-2">
					<div v-for="(url, idx) in bulkPhotos" :key="url" class="space-y-1">
						<div class="relative aspect-square">
							<button type="button" class="oak-press h-full w-full" @click="openLightbox(bulkPhotos.map(photoSrc), idx)">
								<img :src="photoSrc(url)" class="h-full w-full rounded-lg border border-gray-200 object-cover" />
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
							<PhotoMark :photo="url" />
						</div>
						<input
							v-model="photoNotes[url]"
							type="text"
							class="oak-input px-2 py-1.5 text-xs"
							:placeholder="labels.photoCaption"
						/>
					</div>
					<!-- Sel yang bentuknya sama dengan foto yang sudah mendarat, jadi grid tidak
					     melompat begitu unggahannya selesai. -->
					<PhotoTile v-for="it in photoQueue.items" :key="it.id" :item="it" tile="aspect-square w-full" />
				</div>
				<div class="flex w-full gap-2">
					<!-- Kamera bawaan HP, hanya dipakai kalau viewfinder in-app tidak bisa jalan —
					     lihat utils/camera.js. -->
					<input
						ref="bulkCamInput"
						type="file"
						accept="image/*"
						capture="environment"
						multiple
						class="hidden"
						@change="onBulkPhotoPick($event)"
					/>
					<button
						type="button"
						class="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-dashed border-brand-300 bg-brand-50 py-2.5 text-sm font-medium text-brand-600 active:bg-brand-100"
						:disabled="bulkUploading"
						@click="openCameraOrFallback"
					>
						<Icon v-if="bulkUploading" name="loader" :size="16" class="animate-spin" />
						<template v-else><Icon name="camera" :size="16" /> {{ labels.photoCamera }}</template>
					</button>
					<label class="flex flex-1 cursor-pointer items-center justify-center gap-1.5 rounded-lg border border-dashed border-brand-300 bg-brand-50 py-2.5 text-sm font-medium text-brand-600 active:bg-brand-100">
						<input type="file" accept="image/*" multiple class="hidden" :disabled="bulkUploading" @change="onBulkPhotoPick($event)" />
						<Icon v-if="bulkUploading" name="loader" :size="16" class="animate-spin" />
						<template v-else><Icon name="image" :size="16" /> {{ labels.photoGallery }}</template>
					</label>
				</div>
				<p v-if="bulkErr" class="text-xs text-red-600">{{ bulkErr }}</p>
			</section>

			</div>

			<div v-show="workStartedOn && step === 3" class="space-y-4">
				<!-- Tiga angka yang menentukan apakah EIR-Out ini layak dikirim. Seal ikut
				     dihitung: tank yang keluar tanpa satu pun segel tercatat adalah hal yang
				     harus terlihat SEBELUM tombol kirim, bukan sesudahnya. -->
				<section class="oak-section space-y-3">
					<div class="flex items-center gap-2">
						<Icon name="check-circle" :size="16" class="text-gray-400" />
						<p class="oak-section-title">{{ labels.eirReviewSummary }} {{ header.container_no }}</p>
					</div>
					<div class="grid grid-cols-3 gap-2 text-center">
						<div class="rounded-xl bg-leaf-50 py-3">
							<p class="text-xl font-extrabold text-leaf-600">{{ fittingsFilled }}</p>
							<p class="text-[11px] text-gray-500">{{ labels.eirReviewFilled }}</p>
						</div>
						<div class="rounded-xl py-3" :class="fittingsBlank ? 'bg-amber-50' : 'bg-gray-50'">
							<p class="text-xl font-extrabold" :class="fittingsBlank ? 'text-amber-600' : 'text-gray-400'">{{ fittingsBlank }}</p>
							<p class="text-[11px] text-gray-500">{{ labels.eirReviewBlank }}</p>
						</div>
						<div class="rounded-xl py-3" :class="filledSeals.length ? 'bg-blue-50' : 'bg-gray-50'">
							<p class="text-xl font-extrabold" :class="filledSeals.length ? 'text-blue-700' : 'text-gray-400'">{{ filledSeals.length }}</p>
							<p class="text-[11px] text-gray-500">{{ labels.eirOutSealsTitle }}</p>
						</div>
					</div>
					<p class="text-[11px] text-gray-400">{{ bulkPhotos.length }} {{ labels.eirReviewPhotos }}</p>
				</section>

				<!-- Status batch: satu-satunya tempat operator bisa memastikan tidak ada tank
				     dari truk ini yang tertinggal sebelum ia menutup batch. -->
				<section v-if="batchMode" class="oak-section space-y-2">
					<div class="flex items-center justify-between gap-2">
						<div class="flex items-center gap-2">
							<Icon name="layers" :size="16" class="text-gray-400" />
							<p class="oak-section-title">{{ labels.eirBatchStatusTitle }}</p>
						</div>
						<span class="shrink-0 text-[11px] text-gray-400">{{ batch.names.length }} {{ labels.eirBadge }}</span>
					</div>
					<ul class="divide-y divide-gray-100">
						<li v-for="m in batchStatus" :key="m.name" class="flex items-center gap-2.5 py-2">
							<span class="oak-icon-tile h-6 w-6 shrink-0" :class="m.done ? 'bg-leaf-100 text-leaf-700' : 'bg-gray-100 text-gray-400'">
								<Icon :name="m.done ? 'check' : 'clock'" :size="13" />
							</span>
							<span class="min-w-0 flex-1">
								<span class="block truncate font-mono text-sm font-bold text-gray-900">{{ m.container_no }}</span>
								<span class="block truncate text-[11px] text-gray-500">{{ m.line }}</span>
							</span>
							<span class="oak-chip shrink-0" :class="m.tone">{{ m.chip }}</span>
						</li>
					</ul>
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
					<img :src="photoSrc(signatureUrl)" class="h-28 w-full rounded-xl border border-gray-200 bg-paper object-contain" />
					<button type="button" class="oak-link mt-1.5 inline-flex items-center gap-1 text-sm" @click="startResign">
						<Icon name="rotate-ccw" :size="14" /> {{ labels.signAgain }}
					</button>
				</div>
				<div v-else>
					<canvas ref="sigCanvas" class="w-full touch-none rounded-xl border border-gray-200 bg-paper" style="height: 150px"
						@pointerdown="sigDown" @pointermove="sigMove" @pointerup="sigUp" @pointercancel="sigUp" @pointerleave="sigUp"></canvas>
					<div class="mt-1.5 flex items-center gap-3 text-sm">
						<button type="button" class="text-gray-600 underline underline-offset-2" @click="clearSignature">{{ labels.clear }}</button>
						<span v-if="sigUploading" class="text-gray-400">…</span>
						<span v-else-if="sigErr" class="text-red-600">{{ sigErr }}</span>
						<span v-else class="text-gray-400">{{ labels.signHint }}</span>
					</div>
				</div>
			</section>

			<!-- Apa yang terjadi setelah Adm Ops meng-ACC. Dibiarkan sebagai satu-satunya
			     kalimat hijau di langkah ini: ia bukan status, melainkan akibat. -->
				<div class="rounded-xl border border-leaf-200 bg-leaf-50 p-3 text-sm">
					<p class="flex items-center gap-1.5 font-semibold text-leaf-700">
						<Icon name="check-circle" :size="16" /> {{ labels.eirOutWillReady }}
					</p>
				</div>
			</div>

			<!-- Aksi langkah — kembarannya di EirInForm.vue. Tombol kirim sengaja TIDAK
			     menunggu autosave: submit membawa seluruh payload-nya sendiri. -->
			<div v-if="workStartedOn" class="oak-footer -mx-4 border-t border-gray-200/80 bg-gray-50/95 px-4 py-3 backdrop-blur">
				<div class="flex items-center gap-2">
					<button class="oak-btn oak-btn-secondary flex-1 py-3" @click="step ? goStep(step - 1) : saveAndExit()">
						{{ step ? labels.eirStepBack : labels.eirSaveDraftExit }}
					</button>
					<button
						v-if="step < STEPS.length - 1"
						class="oak-btn oak-btn-primary flex-[1.6] py-3"
						@click="goStep(step + 1)"
					>
						{{ labels.eirStepNext }} · {{ STEPS[step + 1] }}
						<Icon name="arrow-right" :size="16" />
					</button>
					<button v-else class="oak-btn oak-btn-primary flex-[1.6] py-3" :disabled="submitting" @click="confirmSubmit">
						<Icon v-if="!submitting" name="send" :size="18" />
						{{ submitting ? "…" : submitLabel }}
					</button>
				</div>
				<p v-if="step === STEPS.length - 1 && submitHint" class="mt-1.5 text-center text-[11px] text-gray-400">
					{{ submitHint }}
				</p>
			</div>
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
import { groupByCompartment } from "@/utils/fittings"
import { openLightbox } from "@/utils/lightbox"
import { shootOrFallback } from "@/utils/camera"
import { session } from "@/data/session"
import { isLocalRef, photoSrc, send, uploadPhoto } from "@/data/send"
import Icon from "@/components/Icon.vue"
import PhotoMark from "@/components/PhotoMark.vue"
import PhotoTile from "@/components/PhotoTile.vue"
import { usePhotoQueue } from "@/utils/photoQueue"
import SkeletonDetail from "@/components/SkeletonDetail.vue"
import EirFormHeader from "@/components/EirFormHeader.vue"
import EditedBy from "@/components/EditedBy.vue"
import TankFittings from "@/components/TankFittings.vue"
import {
	batch,
	getStep,
	inBatch,
	markSent,
	markStarted,
	setStep,
	startMs,
	tankNo,
} from "@/utils/eirBatch"

// Form-only EIR-Out view. The combined worklist lives in Eir.vue, which opens this with
// the picked draft's name and listens for `back` / `submitted`.
//
// There is no damage checklist here: a tank only reaches load-out once its work is
// finished, so the surveyor records what the tank leaves WITH — photos and seal
// numbers — not what is wrong with it. Findings belong to EIR-In.
const props = defineProps({ inspection: { type: String, required: true } })
const emit = defineEmits(["back", "submitted"])

// Empat langkah, kerangka yang sama dengan EIR-In (lihat komentarnya di sana). Isinya yang
// berbeda: tank yang KELUAR tidak punya checklist kerusakan — yang dicatat adalah kotak
// kelengkapan dibanding EIR-In-nya, segel yang terpasang, dan fotonya.
const STEPS = [labels.eirStepTank, labels.eirStepFittings, labels.eirStepPhotos, labels.eirStepReview]
const step = ref(0)
watch(step, (s) => setStep(props.inspection, s))

function goStep(n) {
	step.value = Math.min(STEPS.length - 1, Math.max(0, n))
	window.scrollTo({ top: 0, behavior: "smooth" })
}

// "Simpan draft": satu simpanan paksa, lalu keluar. Autosave sudah berjalan sendiri.
function saveAndExit() {
	doSave(false)
	emit("back")
}

// ---- form state ----
const header = ref(null)
const inspection = ref(null)
const workStartedOn = ref("") // set once the operator presses Mulai; gates editing
const reference = ref(null)
const eirCode = computed(() => header.value?.inspection_id || inspection.value || "")
const refEirIn = computed(() => reference.value?.eir_in || null)
// Kelengkapan saat EIR-In, dikelompokkan seperti lembar cetaknya (lihat utils/fittings.js).
const prevFittings = computed(() => groupByCompartment(refEirIn.value?.fittings))

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
// Kelengkapan tank — one reactive row per master slot (see TankFittings.vue). Carries the
// EIR-In value as `baseline` so the surveyor checks against what came in.
const fittings = ref([])

const bulkPhotos = ref([])
// foto cepat URL → the checklist item Admin sorted it into ("" = unsorted). Keeps sorting
// through a save so a sorted photo stays in Foto Cepat without losing its item_code.
const bulkMeta = ref({})
// Keterangan per FOTO, dikunci pada url-nya — lihat EirInForm untuk alasannya.
const photoNotes = ref({})
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

// --- batch: judul, penghitung waktu, dan status kiriman -----------------------
// Kembaran dari EirInForm; keduanya membaca satu penyimpan yang sama (utils/eirBatch),
// jadi satu batch boleh berisi tank masuk dan tank keluar sekaligus.
const batchMode = computed(() => inBatch(props.inspection))
const headerTitle = computed(() =>
	[labels.eirBadgeOut, header.value?.container_no, header.value?.principal].filter(Boolean).join(" · ")
)
const identityLine = computed(() =>
	[header.value?.principal, bookingCode.value ? `${labels.bookingCode} ${bookingCode.value}` : ""]
		.filter(Boolean)
		.join(" · ")
)
const startedMs = computed(() => (workStartedOn.value ? startMs(props.inspection, workStartedOn.value) : 0))
const saveStatus = computed(() => {
	if (saveRes.loading) return labels.eirSavingShort
	if (saveError.value) return saveError.value
	if (savedOk.value) return labels.eirSavedShort
	return labels.eirAutosaveShort
})

const fittingsFilled = computed(() => fittings.value.filter((r) => String(r.value ?? "").trim()).length)
const fittingsBlank = computed(() => fittings.value.length - fittingsFilled.value)

const unsentOthers = computed(() =>
	batchMode.value ? batch.names.filter((n) => n !== props.inspection && !batch.sent[n]) : []
)

const batchStatus = computed(() =>
	batch.names.map((n) => {
		const sent = batch.sent[n]
		const container_no = tankNo(n) || sent?.container_no || n
		if (sent)
			return {
				name: n,
				container_no,
				done: true,
				line: `${labels.eirBatchSentAt} ${clock(sent.at)} · ${sent.damages || 0} ${labels.eirReviewDamage}`,
				chip: labels.eirStatusPendingReview,
				tone: "bg-sky-100 text-sky-700",
			}
		if (n === props.inspection)
			return {
				name: n,
				container_no,
				done: false,
				line: `${labels.eirBatchReadyToSend} · ${filledSeals.value.length} ${labels.eirOutSealsTitle}`,
				chip: labels.eirBatchNotSentYet,
				tone: "bg-amber-100 text-amber-800",
			}
		return {
			name: n,
			container_no,
			done: false,
			line: labels.eirBatchNotStarted,
			chip: labels.eirBatchNotSentYet,
			tone: "bg-gray-100 text-gray-500",
		}
	})
)

const submitLabel = computed(() => {
	if (!batchMode.value) return labels.eirSendReview
	const tail = unsentOthers.value.length ? "" : ` ${labels.eirSendClose}`
	return `${labels.eirSendOne} ${header.value?.container_no || ""}${tail}`
})

const submitHint = computed(() => {
	if (!batchMode.value) return ""
	const parts = []
	const sent = batch.names.filter((n) => batch.sent[n])
	if (sent.length === 1) parts.push(`${tankNo(sent[0])} ${labels.eirSendHintSent}`)
	else if (sent.length > 1) parts.push(`${sent.length} ${labels.eirBadge} ${labels.eirSendHintSent}`)
	const next = unsentOthers.value[0]
	parts.push(next ? `${labels.eirSendHintNext} ${tankNo(next)}` : labels.eirSendHintLast)
	return parts.join(" · ")
})

function clock(ms) {
	const d = new Date(ms)
	return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`
}

/** Catat EIR ini sebagai terkirim di batch — bahan layar penutup batch. */
function noteSent() {
	if (!batch.names.includes(props.inspection)) return
	markSent(props.inspection, {
		container_no: header.value?.container_no || "",
		damages: 0, // EIR-Out tidak punya checklist kerusakan
		photos: bulkPhotos.value.length,
		minutes: startedMs.value ? Math.max(1, Math.round((Date.now() - startedMs.value) / 60000)) : 0,
	})
}

const headerCells = computed(() => {
	const h = header.value || {}
	// Data master tank apa adanya, termasuk yang "sekali isi" (tanggal buat, tanggal uji,
	// tara, MGW). Di sini ia hanya dibaca: tank yang KELUAR bukan saat yang tepat untuk
	// melengkapi master — yang mengisinya adalah EIR masuk, di depan pelat, sebelum tank
	// dipakai lagi. Yang kosong tetap dicetak sebagai "—" supaya kelihatan bahwa ia kosong.
	return [
		{ label: labels.containerNumber, value: h.container_no },
		{ label: labels.serialNo, value: h.serial_no },
		{ label: labels.ownerPrincipal, value: h.principal },
		{ label: labels.dateManufacture, value: h.manufacture_date },
		{ label: labels.lastTest, value: h.last_test_date },
		{ label: labels.eirInDate, value: h.eir_in_date },
		{ label: labels.capacity, value: h.capacity },
		{ label: labels.tare, value: h.tare_weight },
		{ label: labels.maxGross, value: h.max_gross_weight },
		{ label: labels.lastCargo, value: h.last_cargo },
	]
})

// Kelengkapan master. Same endpoint the EIR-In form uses, so the two share one cached
// response; only the fittings half is read here (EIR-Out has no damage checklist).
const mastersRes = cachedResource({
	url: "container_depot.ess.inspections.eir_masters",
	method: "GET",
	auto: true,
	onSuccess(data) {
		// Masters can land after the draft. Applying them fills the boxes from the EIR-In
		// baseline, and that must NOT trip the autosave: a prefill nobody has looked at yet
		// is a suggestion, not a reading the surveyor took.
		suppressSave.value = true
		fittings.value = (data.fittings || []).map((f) => reactive({ ...f, value: "", baseline: "", otherMode: false }))
		if (header.value) applyDraftToFittings(header.value)
		nextTick(() => { suppressSave.value = false })
	},
})

// ---- open a draft EIR-Out ----
const openRes = cachedResource({
	url: "container_depot.ess.inspections.eir_out_open",
	method: "GET",
	onSuccess(data) {
		suppressSave.value = true
		header.value = data
		inspection.value = data.inspection
		workStartedOn.value = data.work_started_on || ""
		// Mendarat di langkah tempat tank ini ditinggalkan (0 untuk yang belum pernah dibuka).
		step.value = getStep(props.inspection)
		// Dicatat juga saat langkahnya kebetulan 0: tanpa ini watcher di bawah tidak pernah
		// menyala, dan baris worklist kehilangan "Draft 1/4" untuk EIR yang baru dimulai.
		if (data.work_started_on) setStep(props.inspection, step.value)
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
		applyDraftToFittings(data)
		applyDraftPhotos(data)
				nextTick(() => { suppressSave.value = false })
	},
	onError(err) {
		toast.error(err?.messages?.[0] || err?.message || labels.error)
	},
})
const fetchError = computed(() => (openRes.error ? openRes.error.messages?.[0] || openRes.error.message : null))

// Mulai: stamp work_started_on server-side, then unlock the checklist.
// Mulai stamps the start time locally rather than reading it back off the response — see the
// same call in EirInForm.vue. Waiting for
// the server to hand one back. The response carried nothing else the form needed, and waiting
// for it is what made Mulai impossible in a dead spot — which locked the surveyor out of the
// entire checklist, the one screen the offline queue exists to protect.
//
// No `ref` on this row: starting is not finishing, so the EIR stays in the worklist.
async function startWork() {
	if (!inspection.value) return
	try {
		await send({
			url: "container_depot.ess.inspections.eir_start",
			payload: { inspection: inspection.value },
		})
		// Jam LOKAL, bukan UTC — lihat EirInForm.startWork: cap ini yang menghitung durasi
		// pemeriksaan di header.
		const d = new Date()
		const p2 = (n) => String(n).padStart(2, "0")
		workStartedOn.value = `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())}`
		markStarted(inspection.value)
		setStep(props.inspection, 0)
		step.value = 0
	} catch (e) {
		toast.error(e?.message || labels.error)
	}
}

// With no checklist on this form every photo is a "foto cepat". Each one's sorted
// item_code is still carried in bulkMeta so a save never un-sorts what Admin filed.
function applyDraftPhotos(data) {
	if (!data) return
	const bulk = []
	const meta = {}
	const notes = {}
	;(data.photos || []).forEach((p) => {
		bulk.push(p.photo)
		meta[p.photo] = p.item_code || ""
		if (p.caption) notes[p.photo] = p.caption
	})
	photoNotes.value = notes
	bulkPhotos.value = bulk
	bulkMeta.value = meta
}

function buildPhotos() {
	return bulkPhotos.value.map((url) => ({
		item_code: bulkMeta.value[url] || "",
		photo: url,
		caption: (photoNotes.value[url] || "").trim(),
	}))
}

// The server sends only the slots that carry a value, each with the EIR-In baseline beside
// it. On a draft that has recorded nothing yet the baseline arrives pre-filled as `value` —
// the surveyor confirms or corrects rather than retyping 24 boxes.
function applyDraftToFittings(data) {
	if (!fittings.value.length) return
	const saved = {}
	;(data.fittings || []).forEach((f) => {
		if (f.fitting_item) saved[f.fitting_item] = f
	})
	fittings.value.forEach((r) => {
		const f = saved[r.fitting_item]
		r.value = (f && f.value) || ""
		r.baseline = (f && f.baseline) || ""
		r.otherMode = r.value_type === "Choice" && Boolean(r.value) && !(r.options || []).includes(r.value)
	})
}

function buildFittings() {
	return fittings.value
		.filter((r) => String(r.value ?? "").trim())
		.map((r) => ({ fitting_item: r.fitting_item, value: String(r.value).trim() }))
}

function buildSeals() {
	return filledSeals.value.map((s) => ({
		seal_no: s.seal_no.trim(),
		remarks: (s.remarks || "").trim() || undefined,
	}))
}

// ---- file upload ----
/** Shrink and upload the photo now, parking it only if the link is down. See EirInForm. */
async function uploadFile(file) {
	return uploadPhoto(file)
}
async function onBulkPhotoPick(event) {
	const files = Array.from(event.target.files || [])
	event.target.value = ""
	await addBulkPhotos(files)
}

// In-app viewfinder: shutter -> upload, one shot at a time, no camera-app confirm screen
// in between (utils/camera.js).
const bulkCamInput = ref(null)
function openCameraOrFallback() {
	return shootOrFallback(bulkCamInput, (file) => addBulkPhotos([file]))
}

// Each photo shows itself while it goes up — see EirInForm for why.
const photoQueue = usePhotoQueue()

async function addBulkPhotos(files) {
	if (!files.length) return false
	// `last` adalah jawaban untuk viewfinder: strip di dalam kamera menandai jepretan ini dari
	// nilai yang dikembalikan (lihat utils/camera.js), jadi kegagalan yang ditelan di sini akan
	// tampil sebagai "terkirim" pada foto yang tidak ke mana-mana.
	let last = false
	bulkErr.value = ""
	photoQueue.clearFailed()
	bulkUploading.value = true
	try {
		for (const f of files) {
			const id = photoQueue.add(f)
			try {
				const url = await uploadFile(f)
				last = url
				bulkPhotos.value.push(url)
				bulkMeta.value[url] = "" // freshly taken → not sorted yet
				photoQueue.done(id)
			} catch (e) {
				last = false
				bulkErr.value = labels.photoError
				photoQueue.fail(id)
			}
		}
	} finally {
		bulkUploading.value = false
	}
	return last
}
function removeBulkPhoto(idx) {
	const [url] = bulkPhotos.value.splice(idx, 1)
	if (url) {
		delete bulkMeta.value[url]
		delete photoNotes.value[url]
	}
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
		// Field submit → Pending Review (docstatus 0); Admin Ops finalises on the Desk.
		if (data.docstatus === 1 || data.pending_review) {
			saveToast.close()
			toast.success(
				data.pending_review ? labels.eirSentForReview : labels.eirSubmitted,
				{ title: data.inspection },
			)
			noteSent()
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
const saveError = computed(() => (saveRes.error ? saveRes.error.messages?.[0] || saveRes.error.message : null))

// Photo handling mirrors EirInForm exactly — see the note there: a picked photo is parked
// locally and stripped from the server autosave until `send` has actually uploaded it.

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
		fittings: JSON.stringify(buildFittings()),
		submit: submit ? 1 : 0,
	}
}


function doSave(submit = false) {
	if (!inspection.value) return
	if (saveTimer) { clearTimeout(saveTimer); saveTimer = null }
	if (submit) {
		submitEir()
		return
	}
	const payload = eirPayload(false)
	saveToast.start()
	saveRes.submit({
		...payload,
		signature: isLocalRef(payload.signature) ? undefined : payload.signature,
		photos: JSON.stringify(payload.photos.filter((p) => !isLocalRef(p.photo))),
		seals: JSON.stringify(payload.seals),
	})
}

// Held while the send is in flight — same reason as EirInForm.vue: `send`
// waits for the photos and the server, and a second tap would raise a second EIR.
const submitting = ref(false)

async function submitEir() {
	if (submitting.value) return
	submitting.value = true
	try {
		await send({
			// Names the EIR so the worklist can drop it the moment it is queued — see
			// Eir.vue's pendingItems.
			url: "container_depot.ess.inspections.eir_save_draft",
			payload: eirPayload(true),
		})
		toast.success(labels.eirSentForReview, {
			title: eirCode.value || inspection.value,
		})
		noteSent()
		emit("submitted", inspection.value)
		emit("back")
	} catch (e) {
		toast.error(e?.message || labels.error)
	} finally {
		submitting.value = false
	}
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
	}, 1200)
}
watch([remarks, cargo, seals, bulkPhotos, photoNotes, fittings], scheduleSave, { deep: true })

async function confirmSubmit() {
	// Ya / Batal, nothing else: what happens after the hand-off is Adm Ops' business, not
	// something the field operator has to read past on every submit.
	const ok = await confirm({
		title: labels.eirOutConfirmReadyTitle,
		confirmLabel: labels.eirSendReview,
		cancelLabel: labels.confirmCancel,
	})
	if (ok) doSave(true)
}

onMounted(() => {
	openRes.submit({ inspection: props.inspection })
})
</script>
