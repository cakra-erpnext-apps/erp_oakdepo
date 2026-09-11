<template>
	<div class="mx-auto w-full max-w-lg space-y-3 md:max-w-2xl">
		<div class="flex items-center gap-2">
			<button
				class="oak-press flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-gray-500"
				:aria-label="labels.surveyPosBack"
				@click="goBack"
			>
				<Icon name="chevron-left" :size="22" />
			</button>
			<h1 class="min-w-0 flex-1 truncate text-lg font-extrabold tracking-tight text-gray-900">
				{{ labels.tankDetailTitle }}
			</h1>
			<span v-if="tank" class="oak-chip shrink-0" :class="chipClass(tank.status)">
				{{ statusLabel(tank.status) }}
			</span>
		</div>

		<!-- Dua langkah dalam satu batang. Layar ini dipakai dua tim yang masing-masing hanya
		     memegang satu langkah, dan tanpa batang ini keduanya harus menebak apakah giliran
		     mereka sudah tiba — dari status yang bahasanya milik dokumen, bukan milik yard. -->
		<div v-if="tank" class="flex items-center gap-2 px-1">
			<span class="shrink-0 text-[11px] font-semibold" :class="stepDone(1) ? 'text-leaf-600' : 'text-brand-600'">
				{{ labels.stepLowering }}
			</span>
			<span class="h-1 flex-1 rounded-full" :class="stepDone(1) ? 'bg-leaf-500' : 'bg-brand-500'"></span>
			<span class="h-1 flex-1 rounded-full" :class="stepDone(2) ? 'bg-leaf-500' : stepDone(1) ? 'bg-brand-500' : 'bg-gray-200'"></span>
			<span class="shrink-0 text-[11px] font-semibold" :class="stepDone(2) ? 'text-leaf-600' : stepDone(1) ? 'text-brand-600' : 'text-gray-400'">
				{{ labels.stepSurvey }}
			</span>
		</div>

		<SkeletonDetail v-if="pending" :cells="4" :sections="3" />

		<section v-else-if="failed" class="oak-card space-y-3 p-6 text-center">
			<span class="oak-icon-tile mx-auto h-12 w-12 bg-red-50 text-red-500">
				<Icon name="alert-triangle" :size="24" />
			</span>
			<p class="text-sm text-gray-600">{{ error }}</p>
			<div class="flex gap-2">
				<button class="oak-btn oak-btn-secondary min-h-[48px] flex-1" @click="goBack">{{ labels.surveyPosBack }}</button>
				<button class="oak-btn oak-btn-primary min-h-[48px] flex-1" @click="load">{{ labels.retry }}</button>
			</div>
		</section>

		<template v-else-if="tank">
			<!-- Identitas: dibaca sambil berdiri di samping tank, jadi nomornya besar dan yang
			     lain satu baris. -->
			<section class="oak-card space-y-2 p-4">
				<div class="flex items-start justify-between gap-3">
					<p class="min-w-0 truncate font-mono text-xl font-extrabold tracking-tight text-gray-900">
						{{ tank.container_no || tank.container || labels.monitorNoNumber }}
					</p>
					<p class="shrink-0 font-mono text-[11px] text-gray-400">{{ tank.survey_order }}</p>
				</div>
				<p class="truncate text-xs text-gray-500">{{ identityLine }}</p>
			</section>

			<!-- Spanduk keadaan. Warnanya yang menjawab lebih dulu dari kalimatnya: merah =
			     tenggatnya sudah dekat dan tank masih di atas. -->
			<div v-if="banner" class="flex gap-2 rounded-xl border p-3" :class="banner.box">
				<Icon :name="banner.icon" :size="16" class="mt-0.5 shrink-0" :class="banner.tint" />
				<div class="min-w-0">
					<p class="text-xs font-bold" :class="banner.tint">{{ banner.title }}</p>
					<p class="mt-0.5 text-[11px] leading-relaxed" :class="banner.body">{{ banner.text }}</p>
				</div>
			</div>

			<!-- LANGKAH 1 — tandai lowered -->
			<section v-if="canLower" class="oak-card space-y-3 border-brand-300 p-4">
				<p class="text-sm font-extrabold text-gray-900">{{ labels.tankMarkLowered }}</p>

				<!-- Kotak letak hanya muncul untuk tank yang belum pernah didata. Untuk yang
				     sudah, "sudah turun" tidak mengubah letaknya, dan kotak terisi otomatis
				     mengundang konfirmasi ulang atas posisi yang tidak ada yang mengeceknya. -->
				<div v-if="!tank.located">
					<label class="oak-label">{{ labels.tankPosNewLabel }}</label>
					<textarea
						v-model.trim="form.location_note"
						rows="2"
						class="oak-input"
						:placeholder="labels.posLocationHint"
					></textarea>
					<p class="mt-1 text-[11px] text-amber-700">{{ labels.tankPosUnlocatedHint }}</p>
				</div>

				<div>
					<label class="oak-label">
						{{ labels.tankLoweringNote }} <span class="font-normal text-gray-400">{{ labels.tankPosOptional }}</span>
					</label>
					<textarea
						v-model.trim="form.lowering_note"
						rows="2"
						class="oak-input"
						:placeholder="labels.tankLoweringNoteHint"
					></textarea>
				</div>

				<div>
					<label class="oak-label">
						{{ labels.tankLoweringPhotos }} <span class="font-normal text-gray-400">{{ labels.tankPosOptional }}</span>
					</label>
					<div class="grid grid-cols-3 gap-2">
						<div v-for="(url, i) in photos" :key="i" class="relative aspect-square">
							<img :src="photoSrc(url)" class="h-full w-full rounded-lg border border-gray-200 object-cover" />
							<button
								type="button"
								class="absolute right-1 top-1 flex h-8 w-8 items-center justify-center rounded-full bg-black/70 text-white"
								:aria-label="labels.tplCancel"
								@click="photos.splice(i, 1)"
							>
								<Icon name="x" :size="16" />
							</button>
						</div>
						<PhotoTile v-for="it in photoQueue.items" :key="it.id" :item="it" tile="aspect-square w-full" />
						<input ref="camInput" type="file" accept="image/*" capture="environment" multiple class="hidden" @change="onPhotos" />
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
						<label class="flex aspect-square cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed border-brand-300 bg-brand-50 text-brand-600 active:bg-brand-100">
							<Icon name="image" :size="22" />
							<span class="text-xs font-medium">{{ labels.photoGallery }}</span>
							<input type="file" accept="image/*" multiple class="hidden" :disabled="photoUploading" @change="onPhotos" />
						</label>
					</div>
				</div>

				<p v-if="lowerError" class="text-xs text-red-600">{{ lowerError }}</p>
				<button
					class="oak-btn oak-btn-primary min-h-[52px] w-full text-base"
					:disabled="lowering"
					@click="markLowered"
				>
					{{ lowering ? "…" : labels.tankMarkLowered }}
				</button>
				<p class="text-center text-[11px] text-gray-400">{{ labels.tankAutoStamp }}</p>
			</section>

			<!-- Foto lowering yang sudah ada — patokan visual buat yang datang berikutnya. -->
			<section v-if="!canLower && latestPhotos.length" class="oak-card space-y-2 p-4">
				<div class="flex items-baseline justify-between gap-2">
					<p class="text-sm font-extrabold text-gray-900">{{ labels.tankLoweringPhotos }}</p>
					<p class="shrink-0 text-[11px] text-gray-400">{{ latestPhotos.length }} {{ labels.tankPosPhotoCount }}</p>
				</div>
				<div class="grid grid-cols-3 gap-2">
					<img
						v-for="(url, i) in latestPhotos"
						:key="i"
						:src="photoSrc(url)"
						class="aspect-square w-full rounded-lg border border-gray-200 object-cover"
						@click="openLightbox(latestPhotos.map(photoSrc), i)"
					/>
				</div>
			</section>

			<!-- LANGKAH 2 — lakukan survey -->
			<section v-if="canFinish" class="oak-card space-y-3 border-brand-300 p-4">
				<p class="text-sm font-extrabold text-gray-900">{{ labels.tankDoSurvey }}</p>
				<div>
					<label class="oak-label">
						{{ labels.tankSurveyNote }} <span class="font-normal text-gray-400">{{ labels.tankPosOptional }}</span>
					</label>
					<textarea v-model.trim="form.notes" rows="2" class="oak-input" :placeholder="labels.tankSurveyNoteHint"></textarea>
				</div>
				<p v-if="finishError" class="text-xs text-red-600">{{ finishError }}</p>
				<button
					class="oak-btn oak-btn-primary min-h-[52px] w-full text-base"
					:disabled="finishing"
					@click="finishSurvey"
				>
					{{ finishing ? "…" : labels.tankFinishSurvey }}
				</button>
				<p class="text-center text-[11px] text-gray-400">{{ labels.tankFinishHint }}</p>
			</section>

			<!-- Hasil — hanya setelah survey ditutup. -->
			<section v-if="tank.status === DONE" class="oak-card space-y-2 p-4">
				<p class="text-sm font-extrabold text-gray-900">{{ labels.tankResult }}</p>
				<div class="flex items-baseline justify-between gap-2 border-t border-gray-100 pt-2">
					<span class="text-xs text-gray-500">{{ labels.tankDraftEirOut }}</span>
					<span class="truncate font-mono text-sm font-bold text-gray-900">{{ tank.eir_out || "—" }}</span>
				</div>
				<div v-if="tank.survey_notes" class="border-t border-gray-100 pt-2">
					<p class="text-xs text-gray-500">{{ labels.tankSurveyNote }}</p>
					<p class="mt-0.5 whitespace-pre-line text-sm text-gray-800">{{ tank.survey_notes }}</p>
				</div>
			</section>

			<!-- Riwayat update — dirakit dari stempel di baris tank-nya sendiri. -->
			<section v-if="timeline.length" class="oak-card overflow-hidden">
				<div class="flex items-baseline justify-between gap-2 px-4 pb-2 pt-3">
					<p class="text-sm font-extrabold text-gray-900">{{ labels.tankUpdates }}</p>
					<p class="text-xs text-gray-400">{{ timeline.length }}</p>
				</div>
				<ol class="space-y-3 px-4 pb-4 pt-1">
					<li v-for="(e, i) in timeline" :key="i" class="relative flex gap-3">
						<span v-if="i < timeline.length - 1" class="absolute left-[5px] top-3 h-full w-px bg-gray-200"></span>
						<span class="relative mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full" :class="eventTone(e.key)"></span>
						<div class="min-w-0 flex-1">
							<p class="truncate text-xs font-bold text-gray-900">{{ eventTitle(e) }}</p>
							<p class="truncate text-[11px] text-gray-400">{{ eventMeta(e) }}</p>
							<p v-if="e.note" class="mt-0.5 whitespace-pre-line text-[11px] text-gray-500">{{ e.note }}</p>
						</div>
					</li>
				</ol>
			</section>

			<!-- Batalkan — undo yang dipunya alur ini sebagai ganti langkah review. Tanpa
			     peninjau di belakang kru lapangan, pilihannya cuma catatan salah yang tidak bisa
			     dibetulkan siapa pun. -->
			<section v-if="canReopen" class="oak-card space-y-2 border-red-200 p-4">
				<p class="text-sm font-extrabold text-red-600">{{ labels.tankUndo }}</p>
				<div v-if="tank.status === DONE" class="flex items-center gap-3 border-t border-gray-100 pt-2">
					<div class="min-w-0 flex-1">
						<p class="text-sm font-bold text-gray-900">{{ labels.posReopenSurvey }}</p>
						<p class="text-[11px] leading-relaxed text-gray-500">{{ labels.posReopenSurveyHint }}</p>
					</div>
					<button class="oak-btn oak-btn-secondary min-h-[44px] shrink-0 px-4 text-xs" @click="ask('survey')">
						{{ labels.tankUndoPick }}
					</button>
				</div>
				<div class="flex items-center gap-3 border-t border-gray-100 pt-2">
					<div class="min-w-0 flex-1">
						<p class="text-sm font-bold text-gray-900">{{ labels.posReopenLowering }}</p>
						<p class="text-[11px] leading-relaxed text-gray-500">{{ labels.posReopenLoweringHint }}</p>
					</div>
					<button class="oak-btn oak-btn-secondary min-h-[44px] shrink-0 px-4 text-xs" @click="ask('lowering')">
						{{ labels.tankUndoPick }}
					</button>
				</div>
			</section>
		</template>

		<!-- Konfirmasi kembalikan. Bukan confirm() umum: yang harus terbaca sebelum menekan
		     adalah AKIBATNYA — status tank mundur, dan draft EIR-Out yang sudah terbit ikut
		     dibatalkan. Sebuah dialog yang cuma bertanya "yakin?" menyembunyikan itu. -->
		<teleport to="body">
			<div v-if="asking" class="fixed inset-0 z-40 animate-fade-in bg-gray-900/50" @click="asking = null"></div>
			<section
				v-if="asking"
				class="fixed inset-x-4 bottom-6 z-50 animate-slide-up rounded-2xl bg-paper p-4 shadow-soft"
				role="dialog"
				aria-modal="true"
			>
				<p class="text-base font-extrabold text-gray-900">{{ askTitle }}</p>
				<p class="mt-1 text-xs leading-relaxed text-gray-600">{{ askBody }}</p>
				<label class="oak-label mt-3">{{ labels.posReopenReason }}</label>
				<textarea v-model.trim="reopenNote" rows="2" class="oak-input" :placeholder="labels.posReopenReasonHint"></textarea>
				<div v-if="asking === 'lowering' && tank?.eir_out" class="mt-2 flex items-baseline justify-between border-t border-gray-100 pt-2">
					<span class="text-xs text-gray-500">{{ labels.tankDraftEirOut }}</span>
					<span class="font-mono text-sm font-bold text-gray-900">{{ tank.eir_out }}</span>
				</div>
				<button
					class="oak-btn oak-btn-secondary mt-3 min-h-[52px] w-full border-red-200 text-red-600"
					:disabled="reopening"
					@click="confirmReopen"
				>
					{{ reopening ? "…" : labels.posReopenSend }}
				</button>
				<button class="oak-btn oak-btn-secondary mt-2 min-h-[52px] w-full" @click="asking = null">
					{{ labels.confirmCancel }}
				</button>
			</section>
		</teleport>
	</div>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
import { confirm } from "@/utils/confirm"
import { menu } from "@/data/menu"
import Icon from "@/components/Icon.vue"
import SkeletonDetail from "@/components/SkeletonDetail.vue"
import { cachedResource } from "@/data/cache"
import { send } from "@/data/send"
import { openLightbox } from "@/utils/lightbox"
import { uploadPhoto, photoSrc } from "@/data/send"
import { usePhotoQueue } from "@/utils/photoQueue"
import { shootOrFallback } from "@/utils/camera"
import PhotoTile from "@/components/PhotoTile.vue"
import {
	DONE,
	LOWERED,
	WAITING,
	chipClass,
	fmtDate,
	fmtDateTime,
	stamp,
	statusLabel,
} from "@/utils/surveyStatus"

const route = useRoute()
const router = useRouter()

const tank = ref(null)
const pending = ref(true)
const failed = ref(false)
const error = ref("")

const form = reactive({ location_note: "", lowering_note: "", notes: "" })

// The pictures of the position shown at the top. Only the newest reading's — the older ones
// belong to the Letak Tank screen, not to a surveyor asking where to walk.
const latestPhotos = computed(() => tank.value?.position_photos || [])
const timeline = computed(() => tank.value?.timeline || [])

function fill(tpl, vars) {
	return Object.entries(vars).reduce((s, [k, v]) => s.replace(`{${k}}`, v), tpl)
}

// Satu baris identitas: prinsipal, letak, surveyor, hari pickup. Yang kosong dibuang, bukan
// diganti tanda hubung — sebuah master yang setengah lengkap tidak perlu tampil sebagai
// deretan garis.
const identityLine = computed(() => {
	const t = tank.value
	if (!t) return ""
	const sch = t.schedule || {}
	return [
		t.principal,
		t.located ? `posisi ${t.location_note}` : labels.tankPosUnlocated,
		sch.surveyor ? `surveyor ${sch.surveyor}` : null,
		sch.plan_date ? `${labels.lowPickup} ${fmtDate(sch.plan_date)}` : null,
	]
		.filter(Boolean)
		.join(" · ")
})

// Batang dua langkah: 1 = lowering, 2 = survey.
function stepDone(n) {
	const st = tank.value?.status
	if (n === 1) return st === LOWERED || st === DONE
	return st === DONE
}

// Spanduk keadaan. Merah hanya untuk yang benar-benar mendesak DAN masih di atas — kalau
// setiap tank merah, tidak ada tank yang merah.
const banner = computed(() => {
	const t = tank.value
	if (!t) return null
	if (t.status === WAITING) {
		if (t.urgent) {
			return {
				box: "border-red-200 bg-red-50",
				tint: "text-red-700",
				body: "text-red-900",
				icon: "alert-circle",
				title: fill(labels.tankUrgentTitle, { t: dueWord(t) }),
				text: labels.tankUrgentBody,
			}
		}
		return {
			box: "border-amber-200 bg-amber-50",
			tint: "text-amber-800",
			body: "text-amber-900",
			icon: "arrow-down",
			title: labels.tankNotDownTitle,
			text: labels.tankNotDownBody,
		}
	}
	if (t.status === LOWERED) {
		return {
			box: "border-leaf-200 bg-leaf-50",
			tint: "text-leaf-700",
			body: "text-leaf-900",
			icon: "check-circle",
			title: labels.tankReadyTitle,
			text: fill(labels.tankReadyBody, { t: stamp(t.lowered_on) }),
		}
	}
	if (t.status === DONE) {
		return {
			box: "border-leaf-200 bg-leaf-50",
			tint: "text-leaf-700",
			body: "text-leaf-900",
			icon: "check-circle",
			title: labels.tankSurveyDone,
			text: [stamp(t.surveyed_on), t.surveyed_by].filter(Boolean).join(" · "),
		}
	}
	return null
})

function dueWord(t) {
	const d = t.days_to
	if (d === null || d === undefined) return "—"
	if (d < 0) return `lewat ${-d} hari`
	if (d === 0) return "hari ini"
	if (d === 1) return "besok"
	return `${d} hari lagi`
}

// Kalimat tiap kejadian riwayat.
const EVENT = {
	scheduled: { label: () => labels.evScheduled, tone: "bg-leaf-500" },
	lowered: { label: () => labels.evLowered, tone: "bg-brand-500" },
	surveyed: { label: () => labels.evSurveyed, tone: "bg-leaf-500" },
	eir_out: { label: () => labels.evEirOut, tone: "bg-blue-500" },
	reopened: { label: () => labels.evReopened, tone: "bg-amber-500" },
}
function eventTitle(e) {
	return EVENT[e.key]?.label() || e.key
}
function eventTone(key) {
	return EVENT[key]?.tone || "bg-gray-300"
}
function eventMeta(e) {
	const parts = []
	if (e.at) parts.push(fmtDateTime(e.at))
	if (e.by) parts.push(e.by)
	if (e.ref) parts.push(e.key === "scheduled" ? fill(labels.evScheduledFrom, { ref: e.ref }) : e.ref)
	return parts.join(" · ")
}

// ---- foto lowering ----
// Foto TANPA letak baru tetap tersimpan sebagai bacaan posisi memakai letak yang berlaku
// (tank_survey.mark_lowered) — kalau tidak, jepretan operator hilang tanpa pesan apa pun.
const photos = ref([])
const photoUploading = ref(false)
const photoQueue = usePhotoQueue()
const camInput = ref(null)
function openCameraOrFallback() {
	return shootOrFallback(camInput, (file) => addPhotos([file]))
}
async function onPhotos(e) {
	const files = Array.from(e.target.files || [])
	e.target.value = ""
	await addPhotos(files)
}
async function addPhotos(files) {
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
				last = await uploadPhoto(f)
				photos.value.push(last)
				photoQueue.done(id)
			} catch {
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

const res = cachedResource({
	url: "container_depot.ess.tank_survey.survey_tank_detail",
	method: "GET",
	onSuccess(data) {
		pending.value = false
		failed.value = false
		tank.value = data
		// Blank on purpose when the tank already has a location: this box means "the tank moved
		// to HERE", and pre-filling it with the old place invites a re-confirmation of a
		// position nobody re-checked.
		form.location_note = ""
		form.lowering_note = data.lowering_note || ""
		form.notes = data.survey_notes || ""
	},
	onError(err) {
		pending.value = false
		failed.value = true
		error.value = err?.messages?.[0] || err?.message || labels.error
	},
})

function load() {
	pending.value = true
	failed.value = false
	res.submit({ name: route.params.name })
}
watch(() => route.params.name, load, { immediate: true })

// ---- what this user may press ----
//
// Both gates are also enforced server-side (ess/tank_survey.py). These only keep the
// screen honest: a button that would answer 403 is worse than no button.
const canLower = computed(
	() => tank.value?.status === WAITING && (menu.has("posFix") || menu.has("surveyPos"))
)
const canFinish = computed(() => tank.value?.status === LOWERED && menu.has("surveyPos"))
const canReopen = computed(
	() => tank.value && [LOWERED, DONE].includes(tank.value.status) && (menu.has("posFix") || menu.has("surveyPos"))
)

// ---- step 1: tandai lowered ----
const lowering = ref(false)
const lowerError = ref("")

async function markLowered() {
	if (lowering.value || !tank.value) return
	// Optional — unless nobody has ever located this tank. A tank that has just been put down
	// by definition has a position to record, and "sudah turun" with no place leaves the
	// surveyor nowhere to walk.
	if (!tank.value.located && !form.location_note) {
		lowerError.value = labels.posLocationRequired
		return
	}
	if (!(await confirm({
		title: labels.posLoweredConfirmYes,
		message: labels.posLoweredConfirmMsg,
		confirmLabel: labels.posLoweredConfirmYes,
		cancelLabel: labels.confirmCancel,
	}))) return

	lowering.value = true
	lowerError.value = ""
	try {
		await send({
			url: "container_depot.ess.tank_survey.survey_lowered",
			payload: {
				name: tank.value.name,
				location_note: form.location_note || undefined,
				note: form.lowering_note || undefined,
				photos: photos.value.length ? photos.value : undefined,
			},
		})
		toast.success(labels.posLoweredDone, { title: tank.value.name })
		photos.value = []
		load()
	} catch (e) {
		lowerError.value = e?.message || labels.error
		toast.error(lowerError.value)
	} finally {
		lowering.value = false
	}
}

// ---- step 2: selesai survey ----
const finishing = ref(false)
const finishError = ref("")
async function finishSurvey() {
	if (finishing.value || !tank.value) return
	if (!(await confirm({
		title: labels.surveyFinishConfirmTitle,
		message: labels.surveyFinishEirHint,
		confirmLabel: labels.surveyFinishConfirmYes,
		cancelLabel: labels.confirmCancel,
	}))) return

	finishing.value = true
	finishError.value = ""
	const d = tank.value
	try {
		await send({
			url: "container_depot.ess.tank_survey.survey_finish",
			payload: {
				name: d.name,
				notes: form.notes || undefined,
			},
		})
		toast.success(labels.surveyFinishDone, { title: d.name })
		load()
	} catch (e) {
		finishError.value = e?.message || labels.error
		toast.error(finishError.value)
	} finally {
		finishing.value = false
	}
}

// ---- undo ----
// Dialognya sendiri, bukan confirm() umum: yang harus terbaca sebelum menekan adalah
// AKIBATNYA — status tank mundur, dan draft EIR-Out yang sudah terbit ikut dibatalkan.
const reopenNote = ref("")
const reopening = ref(false)
const asking = ref(null)

const askTitle = computed(() =>
	asking.value === "survey" ? labels.posReopenSurvey : labels.posReopenLoweringAsk
)
const askBody = computed(() =>
	asking.value === "survey" ? labels.posReopenSurveyHint : labels.posReopenLoweringBody
)

function ask(which) {
	asking.value = which
	reopenNote.value = ""
}

async function confirmReopen() {
	if (reopening.value || !tank.value || !asking.value) return
	reopening.value = true
	try {
		await send({
			url:
				asking.value === "survey"
					? "container_depot.ess.tank_survey.survey_reopen_survey"
					: "container_depot.ess.tank_survey.survey_reopen_lowering",
			payload: { name: tank.value.name, note: reopenNote.value || undefined },
		})
		toast.success(labels.posReopenDone, { title: tank.value.name })
		asking.value = null
		reopenNote.value = ""
		load()
	} catch (e) {
		toast.error(e?.message || labels.error)
	} finally {
		reopening.value = false
	}
}

function goBack() {
	if (window.history.length > 1) router.back()
	else router.push("/survey-orders")
}
</script>
