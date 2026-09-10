<template>
	<div class="space-y-4">
		<!-- Header form + bar langkah. Dipisah jadi komponen sendiri karena EIR-In dan EIR-Out
		     memakai kerangka yang sama, dan bar batch di atasnya (Eir.vue) harus tahu tinggi
		     keduanya. -->
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
			<!-- ============ SEBELUM MULAI ============ -->
			<!-- Work-timing gate: the checklist stays locked until the operator presses Mulai,
			     so Mulai → Submit measures how long the inspection actually took. Layar ini
			     sengaja tidak menawarkan "salin dari tank sebelumnya" — lihat komentar di
			     langkah Data tank. -->
			<template v-if="!workStartedOn">
				<section class="oak-section space-y-1">
					<div class="flex items-baseline justify-between gap-2">
						<p class="truncate font-mono text-base font-extrabold text-gray-900">{{ header.container_no }}</p>
						<span class="shrink-0 font-mono text-[10px] text-gray-400">{{ eirCode }}</span>
					</div>
					<p class="truncate text-xs text-gray-500">{{ identityLine }}</p>
				</section>
			</template>

			<!-- Step 1b — referred voucher: shipper / truck / driver, one read-only block.
			     Was two grey cards stacked (bon codes, then the crew) which read as two
			     different facts about the same bon. Muncul di layar Mulai DAN di langkah 1:
			     sebelum mulai ia yang menjawab "truk mana ini", sesudahnya ia rujukan yang
			     dibaca sambil mengisi. -->
			<section v-if="!workStartedOn || step === 0" class="oak-section space-y-2">
				<div class="flex items-center justify-between gap-2">
					<div class="flex items-center gap-2">
						<Icon name="file-text" :size="16" class="text-gray-400" />
						<p class="oak-section-title">{{ labels.referredVoucher }}</p>
					</div>
					<!-- Satu bon untuk beberapa tank: itu justru alasan batch ini dibuka, dan
					     operator perlu tahu data ini tidak akan ditanyakan lagi di tank berikutnya. -->
					<span v-if="batchMode" class="shrink-0 text-[11px] text-gray-400">
						{{ workStartedOn ? labels.eirVoucherForCount.replace("{n}", batch.names.length) : labels.eirVoucherFromBatch }}
					</span>
				</div>
				<dl class="grid grid-cols-2 gap-x-4 gap-y-2.5 rounded-xl bg-gray-50 p-3 text-sm sm:grid-cols-3">
					<div v-for="f in voucherCells" :key="f.label">
						<dt class="text-xs text-gray-500">{{ f.label }}</dt>
						<dd class="truncate font-semibold" :class="f.mono ? 'font-mono text-brand-600' : 'text-gray-800'">{{ f.value || "—" }}</dd>
					</div>
				</dl>
				<p class="text-[11px] text-gray-400">{{ labels.eirVoucherLocked }}</p>
			</section>

			<template v-if="!workStartedOn">
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

			<!-- ============ LANGKAH 1 · DATA TANK ============ -->
			<!-- v-show, bukan v-if: pindah langkah tidak boleh membongkar checklist dan grid
			     fotonya. Yang sedang di-upload akan ikut mati bersama komponennya, dan sebuah
			     langkah adalah tempat berpindah bolak-balik, bukan halaman baru. -->
			<div v-show="workStartedOn && step === 0" class="space-y-4">
				<!-- Data tank. Fakta milik TANK-nya, bukan milik EIR ini: EIR adalah satu-satunya
				     saat ada orang berdiri di depan pelat tank, dan master yang setengah kosong
				     akan tetap kosong selamanya kalau menunggu perjalanan terpisah ke Desk.
				     Karena itu ia diisi SEKALI dan dipakai semua EIR berikutnya — bukan daftar
				     sembilan kotak yang harus diketik ulang setiap tank datang. Chip "opsional"
				     dan centang per kotak yang mengatakan itu; tidak ada satu pun field di sini
				     yang menahan tombol kirim.

				     Pernah ada tombol "Salin ke <tank berikutnya>" di sini, dan ia dibuang
				     2026-09-09 atas keputusan pemilik alur: dua tank dari satu bon TIDAK
				     dijamin sama, dan operator yang tidak menyadari salinannya akan
				     menandatangani angka tank lain. Angka yang diketik sendiri di depan pelat
				     lebih murah daripada master yang salah tanpa ada yang tahu. -->
				<section class="oak-section space-y-3">
					<div class="flex items-center justify-between gap-2">
						<div class="flex min-w-0 items-center gap-2">
							<Icon name="package" :size="16" class="text-gray-400" />
							<p class="oak-section-title">{{ labels.eirHeader }}</p>
							<span class="oak-chip shrink-0 bg-gray-100 text-gray-500">{{ labels.eirOptional }}</span>
						</div>
						<span
							class="oak-chip shrink-0"
							:class="tankFilled === TANK_FIELDS.length ? 'bg-leaf-100 text-leaf-700' : 'bg-gray-100 text-gray-500'"
						>
							{{ tankFilled }}/{{ TANK_FIELDS.length }} {{ labels.eirTankFromMaster }}
						</span>
					</div>
					<p class="text-xs text-gray-400">{{ labels.eirTankHint }}</p>
					<div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
						<div v-for="f in TANK_FIELDS" :key="f.key">
							<label class="oak-label flex items-center gap-1">
								{{ f.label }}
								<!-- Centang = sudah ada di master. Yang tanpa centang adalah satu-satunya
								     yang layak dilihat lagi di depan tank. -->
								<Icon v-if="tankHas(f.key)" name="check" :size="12" class="text-leaf-500" />
							</label>
							<select v-if="f.options" v-model="tank[f.key]" class="oak-input">
								<option value="">—</option>
								<option v-for="o in tankOptions[f.options]" :key="o" :value="o">{{ o }}</option>
							</select>
							<input
								v-else
								v-model="tank[f.key]"
								:type="f.type || 'text'"
								:inputmode="f.type === 'number' ? 'decimal' : undefined"
								:placeholder="f.placeholder || ''"
								class="oak-input"
							/>
						</div>
					</div>
				</section>

				<!-- Status tank + cargo terakhir. Satu kartu, bukan dua: status "Empty dirty"
				     dan muatan terakhirnya adalah satu kalimat, dan yang kedua wajib justru
				     karena yang pertama dipilih. -->
				<section class="oak-section space-y-3">
					<div class="flex items-baseline justify-between gap-2">
						<label class="oak-label mb-0">{{ labels.tankStatus }}</label>
						<span class="text-[11px] text-gray-400">{{ labels.eirRequired }}</span>
					</div>
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
					<div>
						<label class="oak-label">{{ labels.cargo }}</label>
						<SearchSelect
							v-model="cargo"
							:options="cargos"
							:placeholder="labels.cargo"
							:search-placeholder="labels.cargoSearch"
							:empty-label="labels.sectionSearchEmpty"
						/>
						<p class="mt-1 text-xs text-gray-400">{{ labels.cargoHint }}</p>
					</div>
				</section>
			</div>

			<!-- ============ LANGKAH 2 · KELENGKAPAN ============ -->
			<!-- Kelengkapan tank: the fill-in boxes of the printed EIR sheet. Separate from the
			     damage checklist on purpose — see TankFittings.vue. -->
			<div v-show="workStartedOn && step === 1" class="space-y-4">
				<TankFittings v-if="fittings.length" :rows="fittings" />
				<p v-else class="oak-section text-center text-sm text-gray-400">{{ labels.eirNoFittings }}</p>
			</div>

			<!-- ============ LANGKAH 3 · KERUSAKAN & FOTO ============ -->
			<div v-show="workStartedOn && step === 2" class="space-y-4">
				<!-- Checklist: search a section/part, add only the damaged ones -->
				<ChecklistDamage
					:rows="rows"
					:damage-codes="damageCodes"
					:repair-codes="repairCodes"
					:upload="uploadFile"
					:notes="photoNotes"
					@note="setPhotoNote"
					:title="labels.checklist"
				/>

				<!-- Foto Cepat (bulk): foto tanpa perlu pilih section; admin menyortir belakangan. -->
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

			<!-- ============ LANGKAH 4 · REVIEW & KIRIM ============ -->
			<div v-show="workStartedOn && step === 3" class="space-y-4">
				<!-- Tiga angka yang menentukan apakah EIR ini layak dikirim, dihitung dari yang
				     sudah diisi — bukan daftar panjang untuk dibaca ulang di ujung pekerjaan. -->
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
						<div class="rounded-xl py-3" :class="damageCount ? 'bg-red-50' : 'bg-gray-50'">
							<p class="text-xl font-extrabold" :class="damageCount ? 'text-red-600' : 'text-gray-400'">{{ damageCount }}</p>
							<p class="text-[11px] text-gray-500">{{ labels.eirReviewDamage }}</p>
						</div>
					</div>
					<p class="text-[11px] text-gray-400">{{ photoCount }} {{ labels.eirReviewPhotos }}</p>
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

				<!-- Virtual signature of the EIR creator, directly above Submit -->
				<section class="oak-section space-y-2">
					<div class="flex items-center gap-2">
						<Icon name="edit-2" :size="16" class="text-gray-400" />
						<p class="oak-section-title">{{ labels.signature }}</p>
					</div>
					<p class="text-xs text-gray-500">
						{{ labels.signedBy }}: <span class="font-semibold text-gray-800">{{ session.user }}</span>
					</p>
					<div v-if="signatureUrl && !signing">
						<img :src="photoSrc(signatureUrl)" class="h-28 w-full rounded-xl border border-gray-200 bg-paper object-contain" />
						<button type="button" class="oak-link mt-1.5 inline-flex items-center gap-1 text-sm" @click="startResign">
							<Icon name="rotate-ccw" :size="14" /> {{ labels.signAgain }}
						</button>
					</div>
					<div v-else>
						<canvas
							ref="sigCanvas"
							class="w-full touch-none rounded-xl border border-gray-200 bg-paper"
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

				<!-- Required-before-submit: Cargo + Tank Status + Signature. -->
				<div v-if="missingFields.length" class="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm">
					<p class="flex items-center gap-1.5 font-semibold text-amber-700">
						<Icon name="alert-triangle" :size="16" /> {{ labels.eirNeedComplete }}
					</p>
					<p class="mt-0.5 pl-6 text-xs text-amber-700">{{ missingFields.join(", ") }}</p>
				</div>
			</div>

			<!-- Aksi langkah, menempel di bawah. Kiri selalu jalan mundur (atau keluar dari
			     langkah pertama), kanan selalu jalan maju — sampai langkah terakhir, di mana
			     jalan maju berarti menyerahkan EIR ini ke Adm Ops.

			     Tombol kirim sengaja TIDAK menunggu autosave: submit membangun dan mengirim
			     seluruh EIR sendiri, jadi menunggu simpanan mendarat tidak membeli apa pun —
			     dan di sinyal buruk itu membuat operator menekan tombol mati selama 20 detik. -->
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
					<button
						v-else
						class="oak-btn oak-btn-primary flex-[1.6] py-3"
						:disabled="submitting || missingFields.length > 0"
						@click="confirmSubmit"
					>
						<Icon v-if="!submitting" name="check-circle" :size="18" />
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
import { shootOrFallback } from "@/utils/camera"
import { openLightbox } from "@/utils/lightbox"
import { session } from "@/data/session"
import Icon from "@/components/Icon.vue"
import PhotoMark from "@/components/PhotoMark.vue"
import PhotoTile from "@/components/PhotoTile.vue"
import { usePhotoQueue } from "@/utils/photoQueue"
import SkeletonDetail from "@/components/SkeletonDetail.vue"
import EirFormHeader from "@/components/EirFormHeader.vue"
import EditedBy from "@/components/EditedBy.vue"
import SearchSelect from "@/components/SearchSelect.vue"
import ChecklistDamage from "@/components/ChecklistDamage.vue"
import TankFittings from "@/components/TankFittings.vue"
import { isLocalRef, photoSrc, send, uploadPhoto } from "@/data/send"
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

// Form-only EIR-In view. The combined worklist lives in Eir.vue, which opens this with
// the picked draft's name and listens for `back` / `submitted`.
const props = defineProps({ inspection: { type: String, required: true } })
const emit = defineEmits(["back", "submitted"])

const eirType = "EIR-In"

// Empat langkah, bukan satu gulungan sepanjang dua layar. Urutannya adalah urutan orang
// berjalan mengelilingi tank: bacaan pelat dan status dulu (masih di depan pintu), kotak
// kelengkapan, baru kerusakan dengan fotonya, dan terakhir apa yang ditandatangani.
// Nama langkah dipakai dua kali — di bar progres dan di tombol "Lanjut · <langkah>" —
// supaya tombolnya menjanjikan tujuan, bukan arah.
const STEPS = [labels.eirStepTank, labels.eirStepFittings, labels.eirStepDamage, labels.eirStepReview]
const step = ref(0)

const header = ref(null)
const inspection = ref(null)
const workStartedOn = ref("") // set once the operator presses Mulai; gates editing
const eirCode = computed(() => header.value?.inspection_id || inspection.value || "")
// The tank's own facts, editable here and written to the Container master on save
// (eir.TANK_MASTER_FIELDS). Everything the depot fills in by itself stays out.
const tank = reactive({
	container_type: "",
	equipment_type: "",
	size: "",
	serial_no: "",
	manufacture_date: "",
	// Tanggal uji di pelat. Sejak fitur Periodic Test dihapus (v0_66) tidak ada satu pun
	// layar yang bisa mengisinya lagi, padahal EIR mencetaknya dan Register Periodic Test
	// memakainya sebagai jatuh-balik. Surveyor yang berdiri di depan pelat adalah satu-
	// satunya orang yang bisa menutup lubang itu.
	last_test_date: "",
	capacity: "",
	tare_weight: "",
	max_gross_weight: "",
})

// Urutannya urutan membaca tank: identitasnya dulu, lalu apa yang tercetak di pelat, lalu
// bobotnya. `options` menunjuk ke daftar pilihan dari master (eir_masters.tank_options).
const TANK_FIELDS = [
	{ key: "container_type", label: labels.type, options: "container_type" },
	{ key: "size", label: labels.tankSize, options: "size" },
	{ key: "equipment_type", label: labels.equipmentType, options: "equipment_type" },
	{ key: "serial_no", label: labels.serialNo },
	{ key: "manufacture_date", label: labels.dateManufacture, type: "date" },
	{ key: "last_test_date", label: labels.lastTest, type: "date" },
	{ key: "capacity", label: labels.capacity, type: "number", placeholder: "L" },
	{ key: "tare_weight", label: labels.tare, type: "number" },
	{ key: "max_gross_weight", label: labels.maxGross, type: "number" },
]
const tankHas = (key) => String(tank[key] ?? "").trim() !== ""
const tankFilled = computed(() => TANK_FIELDS.filter((f) => tankHas(f.key)).length)
const tankOptions = ref({ container_type: [], equipment_type: [], size: [] })
const tanggal = ref(new Date().toISOString().slice(0, 10))
const tankStatus = ref("")
const remarks = ref("")
const reffDoc = ref("")
const referredVoucher = ref("")
const truckNo = ref("")
const driver = ref("")
const driverPhone = ref("")
const emkl = ref("")
const shipper = ref("")
const cargo = ref("")
const cargos = ref([])
const bookingCode = ref("")
const result = ref(null)
const savedOk = ref(false)
const suppressSave = ref(false)
let saveTimer = null

const rows = ref([])
// Kelengkapan tank — one reactive row per master slot (see TankFittings.vue). Built from
// the masters, then filled in from the draft by applyDraftToRows.
const fittings = ref([])
const damageCodes = ref([])
const repairCodes = ref([])

const bulkPhotos = ref([])
// A "foto cepat" keeps its Foto Cepat spot even after Admin sorts it into a checklist item
// on the Sortir screen — sorting is just categorisation, the photo still belongs here. This
// maps each bulk photo URL → the checklist item it was sorted into ("" = not yet sorted), so
// buildPhotos re-sends that assignment and a save never un-sorts it.
const bulkMeta = ref({})
// Keterangan per FOTO, dikunci pada url-nya — bukan pada posisinya di array, karena baris
// bisa dihapus di tengah. Tinggal terpisah dari `bulkPhotos` dengan alasan yang sama seperti
// `bulkMeta`: yang dikirim ke server dirakit di buildPhotos, dan bentuk `photos` di form
// (deretan url) tidak ikut berubah — checklist, lightbox dan autosave membacanya apa adanya.
const photoNotes = ref({})
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

// --- batch: judul, penghitung waktu, salin, dan status kiriman ----------------
// Semua yang ada di sini hanya hidup selama beberapa EIR dibuka bersama; satu EIR yang
// dibuka sendirian melewatinya tanpa satu pun elemen tambahan di layar.
const batchMode = computed(() => inBatch(props.inspection))

// "Masuk · FG01 · Coner" — arah, tank, pemiliknya. Nomor EIR-nya tidak ikut ke judul: ia
// ada di kartu Voucher Referensi dan di layar Mulai, dan header ini harus tetap terbaca
// sekali lirik di atas tank yang sedang dipegang.
const headerTitle = computed(() =>
	[labels.eirBadgeIn, header.value?.container_no, header.value?.principal].filter(Boolean).join(" · ")
)

// Baris identitas di layar Mulai: pemilik, ke mana tank ini masuk, dan — kalau batch ini
// memang satu bon — bahwa datanya sudah diisi di tank sebelumnya.
const identityLine = computed(() => {
	const parts = [header.value?.principal]
	if (header.value?.depot) parts.push(`${labels.eirBadgeIn.toLowerCase()} ${labels.depot.toLowerCase()} ${header.value.depot}`)
	return parts.filter(Boolean).join(" · ")
})

// Titik nol penghitung waktu di header. Nol = belum dimulai (chip "Belum mulai").
const startedMs = computed(() => (workStartedOn.value ? startMs(props.inspection, workStartedOn.value) : 0))

const saveStatus = computed(() => {
	if (saveRes.loading) return labels.eirSavingShort
	if (saveError.value) return saveError.value
	if (savedOk.value) return labels.eirSavedShort
	return labels.eirAutosaveShort
})

// Anggota batch lain yang belum dikirim — yang membuat tombol kirim berbunyi
// "& tutup batch" begitu daftar ini kosong.
const unsentOthers = computed(() =>
	batchMode.value ? batch.names.filter((n) => n !== props.inspection && !batch.sent[n]) : []
)

const fittingsFilled = computed(() => fittings.value.filter((r) => String(r.value ?? "").trim()).length)
const fittingsBlank = computed(() => fittings.value.length - fittingsFilled.value)
const damageCount = computed(() => rows.value.filter(rowHasFinding).length)
const photoCount = computed(
	() => bulkPhotos.value.length + rows.value.reduce((n, r) => n + (r.photos?.length || 0), 0)
)

// Kartu "Status batch" di langkah terakhir: tiga keadaan — sudah dikirim, yang sedang
// dipegang, dan yang belum disentuh.
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
				line: `${labels.eirBatchReadyToSend} · ${damageCount.value} ${labels.eirReviewDamage}`,
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

// Apa yang terjadi SETELAH tombol kirim — pertanyaan terakhir sebelum menekannya.
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
		damages: damageCount.value,
		photos: photoCount.value,
		minutes: startedMs.value ? Math.max(1, Math.round((Date.now() - startedMs.value) / 60000)) : 0,
	})
}

const mastersRes = cachedResource({
	url: "container_depot.ess.inspections.eir_masters",
	method: "GET",
	auto: true,
	onSuccess(data) {
		damageCodes.value = data.damage_codes || []
		repairCodes.value = data.repair_codes || []
		cargos.value = data.cargos || []
		tankOptions.value = { container_type: [], equipment_type: [], size: [], ...(data.tank_options || {}) }
		rows.value = (data.checklist || []).map((i) =>
			reactive({ ...i, damage_code: ACCEPTABLE_DAMAGE, repair_code: NO_ACTION_REPAIR, remarks: "", photos: [], uploading: false, photoErr: "", added: false })
		)
		fittings.value = (data.fittings || []).map((f) => reactive({ ...f, value: "", baseline: "", otherMode: false }))
		if (header.value) applyDraftToRows(header.value)
	},
})

// The read-only block: what this EIR was handed rather than what the surveyor writes. Depo
// sits here too — it comes from the bon's booking, not off the tank. Owner and container
// number are the screen title, and Last Cargo is the Cargo picker below; neither repeats.
const voucherCells = computed(() => [
	// Nomor EIR-nya duduk di sini sejak header form dipersempit jadi judul + penghitung
	// waktu: ia satu-satunya cara mencocokkan layar ini dengan lembar kertas di tangan.
	{ label: labels.eir, value: eirCode.value, mono: true },
	{ label: labels.bookingCode, value: bookingCode.value, mono: true },
	{ label: labels.referredVoucher, value: referredVoucher.value, mono: true },
	{ label: labels.depot, value: header.value?.depot },
	{ label: labels.emkl, value: emkl.value },
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
		// Mendarat di langkah tempat tank ini ditinggalkan (0 untuk yang belum pernah dibuka).
		step.value = getStep(props.inspection)
		// Dicatat juga saat langkahnya kebetulan 0: tanpa ini watcher di bawah tidak pernah
		// menyala, dan baris worklist kehilangan "Draft 1/4" untuk EIR yang baru dimulai.
		if (data.work_started_on) setStep(props.inspection, step.value)
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
		emkl.value = data.emkl || ""
		shipper.value = data.shipper || ""
		cargo.value = data.cargo || data.last_cargo || ""
		bookingCode.value = data.booking_code || ""
		Object.keys(tank).forEach((k) => {
			tank[k] = data[k] ?? ""
		})
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
		// Jam LOKAL, bukan ISO/UTC: cap ini dibaca manusia di header ("Dimulai 09:41") dan
		// dipakai menghitung durasi. Yang ditulis UTC membuat handset di Jakarta melaporkan
		// pemeriksaan yang mulai tujuh jam lalu.
		workStartedOn.value = localStamp()
		markStarted(inspection.value)
		setStep(props.inspection, 0)
		step.value = 0
	} catch (e) {
		toast.error(e?.message || labels.error)
	}
}

function localStamp() {
	const d = new Date()
	const p = (n) => String(n).padStart(2, "0")
	return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

// Langkah terakhir tiap EIR diingat di luar komponen ini: berpindah tank di dalam batch
// membongkar form dan memasangnya lagi, dan mendarat di langkah 1 setiap kali adalah cara
// tercepat kehilangan tempat pada tank yang baru setengah jalan.
watch(step, (s) => setStep(props.inspection, s))

function goStep(n) {
	step.value = Math.min(STEPS.length - 1, Math.max(0, n))
	window.scrollTo({ top: 0, behavior: "smooth" })
}

// "Simpan draft" di langkah pertama: satu simpanan paksa, lalu keluar. Autosave sudah
// berjalan sendiri — yang dibeli tombol ini adalah kepastian sebelum layar ditinggalkan.
function saveAndExit() {
	doSave(false)
	emit("back")
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
	const notes = {}
	;(data.photos || []).forEach((p) => {
		const code = p.item_code
		if (p.caption) notes[p.photo] = p.caption
		if (code && lineMap[code]) {
			;(photoMap[code] = photoMap[code] || []).push(p.photo)
		} else {
			bulk.push(p.photo)
			meta[p.photo] = code || ""
		}
	})
	bulkPhotos.value = bulk
	bulkMeta.value = meta
	photoNotes.value = notes
	applyDraftToFittings(data)
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

// Kelengkapan: the server sends back only the slots that carry a value (plus, on an
// EIR-Out, the EIR-In baseline). Every other slot resets to blank — a box nobody filled
// must read as "not recorded", not keep whatever the previous draft happened to show.
function applyDraftToFittings(data) {
	const saved = {}
	;(data.fittings || []).forEach((f) => {
		if (f.fitting_item) saved[f.fitting_item] = f
	})
	fittings.value.forEach((r) => {
		const f = saved[r.fitting_item]
		r.value = (f && f.value) || ""
		r.baseline = (f && f.baseline) || ""
		// A saved value the master no longer offers is a write-in ("Other ..." on paper):
		// keep the text box open so it stays visible instead of silently vanishing.
		r.otherMode = r.value_type === "Choice" && Boolean(r.value) && !(r.options || []).includes(r.value)
	})
}

// Only the boxes that were actually filled travel. Unlike the checklist there is no
// "opened but empty" state to preserve — a blank box carries no fact.
function buildFittings() {
	return fittings.value
		.filter((r) => String(r.value ?? "").trim())
		.map((r) => ({ fitting_item: r.fitting_item, value: String(r.value).trim() }))
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
	// One note map for both buckets: a photo keeps what was typed about it whether it hangs
	// on a damage card or in Foto Cepat, and Admin sorting it later moves it between the two.
	const note = (url) => (photoNotes.value[url] || "").trim()
	const perItem = rows.value.flatMap((r) =>
		(r.photos || []).map((url) => ({ item_code: r.item_code, photo: url, caption: note(url) }))
	)
	// Keep each foto cepat's sorted item_code (bulkMeta) so a save preserves Admin's sorting.
	const bulk = bulkPhotos.value.map((url) => ({
		item_code: bulkMeta.value[url] || "",
		photo: url,
		caption: note(url),
	}))
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
	await addBulkPhotos(files)
}

// The in-app viewfinder: shutter -> here -> upload, with no "pakai foto ini?" in between
// (see utils/camera.js for why the phone's camera app is not used). It hands over one shot
// at a time and keeps the viewfinder up, so this is called once per photo.
const bulkCamInput = ref(null)
function openCameraOrFallback() {
	return shootOrFallback(bulkCamInput, (file) => addBulkPhotos([file]))
}

// Each photo shows itself in the grid while it goes up (utils/photoQueue), so the shutter
// is answered by the picture rather than by an empty grid for the length of a 3G upload.
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
		// Per photo, not per batch: one picture that cannot be stored must not take the
		// other three down with it.
		for (const f of files) {
			const id = photoQueue.add(f)
			try {
				const url = await uploadFile(f)
				last = url
				bulkPhotos.value.push(url)
				bulkMeta.value[url] = "" // freshly taken → not sorted into a checklist item yet
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

// Satu pintu tulis untuk peta keterangan, dipakai kartu checklist lewat `@note`. Kosong
// berarti kuncinya dibuang: keterangan yatim akan ikut terkirim ke server tanpa ada fotonya
// di layar, dan menempel pada foto berikutnya yang kebetulan ber-url sama.
function setPhotoNote({ url, value }) {
	if (value) photoNotes.value[url] = value
	else delete photoNotes.value[url]
}

function removeBulkPhoto(idx) {
	const [url] = bulkPhotos.value.splice(idx, 1)
	if (url) {
		delete bulkMeta.value[url]
		delete photoNotes.value[url]
	}
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
		// The two follow-up flags are deliberately NOT sent. The PWA has no opt-out for
		// either one, and the server no longer clears a box that is not due — a hand-ticked
		// box is now honoured on submit — so asking for both on every save would file a
		// Cleaning Order for every clean tank and an empty M&R for every undamaged one.
		// Omitted, eir.save_eir leaves them alone and Inspection.sync_followup_flags ticks
		// each one the moment its evidence appears (tank turns Empty Dirty, first finding
		// lands), which is exactly what this field operator's screen means by them.

		// Sent as arrays, not JSON strings: `send` has to be able to walk the payload to
		// find the `local:` photo references and swap them for real file_urls.
		lines: buildLines(),
		photos: buildPhotos(),
		// No photo references in here, so it can go up as a plain JSON blob like `tank`.
		fittings: JSON.stringify(buildFittings()),
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
		noteSent()
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

watch([tanggal, tankStatus, cargo, remarks, reffDoc, signatureUrl], scheduleSave)
watch(tank, scheduleSave, { deep: true })
watch(rows, scheduleSave, { deep: true })
watch(fittings, scheduleSave, { deep: true })
watch(bulkPhotos, scheduleSave, { deep: true })
// Sendiri, karena keterangan hidup di luar `bulkPhotos`: tanpa ini satu-satunya jalan
// menyimpannya adalah menyentuh sesuatu yang lain di form.
watch(photoNotes, scheduleSave, { deep: true })

onMounted(() => {
	openRes.submit({ inspection: props.inspection })
})
</script>
