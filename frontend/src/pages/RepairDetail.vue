<template>
	<!-- Tata letak = detail Jadwal Survey: kepala (kembali + status), kartu info yang sama
	     dengan barisnya di daftar, tanggal, siapa yang membuat & mengerjakan — lalu isi M&R-nya
	     sendiri. Halaman yang sama sebelum dan sesudah Mulai: apa pekerjaannya (tank, temuan
	     EIR, yang disetujui, spec tank) tidak bergantung pada tombol itu; hanya aksi di bawah
	     yang berubah. -->
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<DetailHeader :title="kind.workTitle" :chip="orderChip" @back="goBack" />

		<SkeletonDetail v-if="detailPending" :cells="6" :sections="3" />

		<!-- Gagal dimuat dan tidak ada salinan cache — inline, bukan toast yang menghilang. -->
		<section v-else-if="detailFailed" class="oak-card space-y-3 p-6 text-center">
			<span class="oak-icon-tile mx-auto h-12 w-12 bg-red-50 text-red-500">
				<Icon name="alert-triangle" :size="24" />
			</span>
			<p class="text-sm text-gray-600">{{ detailError }}</p>
			<div class="flex gap-2">
				<button class="oak-btn oak-btn-secondary flex-1" @click="goBack">{{ labels.mrBack }}</button>
				<button class="oak-btn oak-btn-primary flex-1" @click="retryDetail">{{ labels.retry }}</button>
			</div>
		</section>

		<template v-else-if="order">
			<!-- Rekan yang menyentuhnya terakhir — di atas kartu, sebelum apa pun diisi. -->
			<EditedBy :by="order.updated_by" :name="order.updated_by_name" :at="order.updated_on" />

			<section class="oak-card space-y-3 p-4">
				<RepairOrderInfo :o="order" />
				<div class="grid grid-cols-2 gap-2 border-t border-gray-100 pt-3">
					<div class="min-w-0">
						<p class="text-[11px] text-gray-400">{{ labels.mrPlanDate }}</p>
						<p class="truncate text-sm font-bold text-gray-900">{{ fmtDate(order.plan_date) }}</p>
					</div>
					<div class="min-w-0">
						<p class="text-[11px] text-gray-400">{{ labels.leakCreated }}</p>
						<p class="truncate text-sm font-bold text-gray-900">{{ fmtDateTime(order.creation) }}</p>
					</div>
				</div>
				<div class="space-y-1 border-t border-gray-100 pt-3 text-xs">
					<p class="flex gap-2">
						<span class="w-24 shrink-0 text-gray-400">{{ labels.svCreatedBy }}</span>
						<span class="min-w-0 font-semibold text-gray-700">{{ order.created_by_name || "—" }}</span>
					</p>
					<p class="flex gap-2">
						<span class="w-24 shrink-0 text-gray-400">{{ labels.svWorkedBy }}</span>
						<span class="min-w-0 font-semibold" :class="workedBy ? 'text-gray-700' : 'text-gray-400'">
							{{ workedBy || labels.svNotStarted }}
						</span>
					</p>
				</div>

				<!-- Siapa yang meloloskan pekerjaan ini, dan catatannya. -->
				<div v-if="approval" class="flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-gray-100 pt-3">
					<span class="oak-chip" :class="approval.tone">
						<Icon :name="approval.icon" :size="12" />{{ approval.label }}
					</span>
					<span class="truncate text-[11px] text-gray-400">{{ approval.note }}</span>
				</div>

				<!-- Setelah berjalan: kapan mulai, dan berapa bukti yang sudah masuk. -->
				<div v-if="isInProgress" class="flex flex-wrap gap-1.5 border-t border-gray-100 pt-3">
					<span class="oak-chip" :class="photoProgress.done >= photoProgress.total ? 'bg-leaf-100 text-leaf-800' : 'bg-amber-100 text-amber-800'">
						<Icon name="camera" :size="12" />{{ photoProgress.label }}
					</span>
					<span v-if="runLine" class="oak-chip bg-gray-100 text-gray-600">
						<Icon name="clock" :size="12" />{{ runLine }}
					</span>
				</div>
			</section>

			<!-- Diajukan Review: pekerjaan lapangan selesai, Desk yang memeriksa. Tim masih boleh
			     menariknya kembali untuk diperbaiki — belum ada yang keluar gudang sejak approval. -->
			<section v-if="isInReview" class="oak-card space-y-2 border-sky-200 bg-sky-50 p-3">
				<p class="text-sm font-semibold text-sky-800">{{ labels.mrWithdrawReviewHint }}</p>
				<button class="oak-btn oak-btn-secondary w-full" :disabled="withdrawRes.loading" @click="withdrawReview">
					<Icon v-if="withdrawRes.loading" name="loader" :size="16" class="animate-spin" />
					<span v-else>{{ labels.mrWithdrawReview }}</span>
				</button>
			</section>

			<!-- Order di luar eksekusi yang dibuka lewat deep-link — dikelola di ERP. -->
			<section v-else-if="!isPending && !isInProgress" class="oak-card border-amber-200 bg-amber-50 p-3">
				<p class="text-sm font-semibold text-amber-800">{{ labels.mrExecErpBanner }}</p>
			</section>

			<!-- Yang disetujui. Baca saja sebelum Mulai (dan saat review): estimasinya milik owner. -->
			<section v-if="!isInProgress" class="oak-card space-y-2 p-4">
				<div class="flex items-center justify-between gap-2">
					<p class="oak-section-title">{{ labels.mrExecPartsTitle }}</p>
					<span class="text-[11px] text-gray-400">{{ itemsCountText }}</span>
				</div>
				<p v-if="!photoGroups.length" class="py-2 text-center text-sm text-gray-400">{{ labels.mrNoUsed }}</p>
				<div v-for="g in photoGroups" :key="g.key" class="space-y-2 rounded-xl border border-gray-100 p-3">
					<div class="flex items-start justify-between gap-2">
						<div class="min-w-0">
							<p class="truncate font-semibold text-gray-900">{{ g.label }}</p>
							<p class="text-xs text-gray-500">{{ lineFacts(g.line) }}</p>
							<p v-if="g.line.remark" class="text-xs text-gray-400">{{ g.line.remark }}</p>
						</div>
						<span class="oak-chip shrink-0" :class="g.photos.length ? 'bg-leaf-100 text-leaf-800' : 'bg-gray-100 text-gray-500'">
							{{ labels.mrPhotoCount.replace("{n}", g.photos.length) }}
						</span>
					</div>
					<!-- Bukti yang sudah dikirim (order di review) — lihat saja. -->
					<div v-if="g.photos.length" class="grid grid-cols-4 gap-1.5">
						<button
							v-for="(ph, pi) in g.photos"
							:key="ph.photo"
							type="button"
							class="oak-press aspect-square"
							@click="openLightbox(g.photos.map((x) => ({ src: photoSrc(x.photo), caption: x.caption })), pi)"
						>
							<img :src="photoSrc(ph.photo)" class="h-full w-full rounded-lg border border-gray-200 object-cover" />
						</button>
					</div>
				</div>
			</section>

			<!-- FORM KERJA — satu kartu per baris yang disetujui: apa pekerjaannya, buktinya,
			     keterangannya. Dua tabel di server (estimasi beku, bukti dikumpulkan di tengah
			     perbaikan); satu layar di HP. -->
			<template v-if="isInProgress">
				<section v-for="g in photoGroups" :key="g.key" class="oak-card space-y-3 p-4">
					<div class="flex items-start justify-between gap-2">
						<div class="min-w-0">
							<p class="truncate font-bold text-gray-900">{{ g.label }}</p>
							<p class="text-xs text-gray-500">{{ lineFacts(g.line) }}</p>
							<p v-if="g.line.remark" class="text-xs text-gray-400">{{ g.line.remark }}</p>
						</div>
						<span class="oak-chip shrink-0" :class="g.photos.length ? 'bg-leaf-100 text-leaf-800' : 'bg-gray-100 text-gray-500'">
							<Icon v-if="g.photos.length" name="check" :size="12" />
							{{ labels.mrPhotoCount.replace("{n}", g.photos.length) }}
						</span>
					</div>

					<!-- Dua per baris, keterangan di bawah masing-masing — kotak selebar thumbnail
					     64px tidak bisa diketik di HP. -->
					<div class="grid grid-cols-2 items-start gap-2">
						<div v-for="(ph, pi) in g.photos" :key="ph.photo" class="space-y-1">
							<div class="relative aspect-square">
								<button
									type="button"
									class="oak-press h-full w-full"
									@click="openLightbox(g.photos.map((x) => ({ src: photoSrc(x.photo), caption: x.caption })), pi)"
								>
									<img :src="photoSrc(ph.photo)" class="h-full w-full rounded-lg border border-gray-200 object-cover" />
								</button>
								<button
									type="button"
									class="absolute right-1 top-1 flex h-8 w-8 items-center justify-center rounded-full bg-black/70 text-white shadow active:bg-black"
									:aria-label="labels.mrRemove"
									@click="removePhoto(ph)"
								>
									<Icon name="x" :size="16" />
								</button>
								<PhotoMark :photo="ph.photo" />
							</div>
							<input
								v-model="ph.caption"
								type="text"
								class="oak-input px-2 py-1.5 text-xs"
								:placeholder="labels.mrPhotoCaption"
								@input="scheduleSave"
							/>
						</div>
						<!-- Bentuk sel yang sama dengan foto yang sudah naik, supaya grid tidak loncat. -->
						<PhotoTile v-for="it in queueFor(g.key).items" :key="it.id" :item="it" tile="aspect-square w-full" />
					</div>

					<div class="flex w-full gap-2">
						<button
							type="button"
							class="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-dashed border-brand-300 bg-brand-50 py-2.5 text-sm font-medium text-brand-600 active:bg-brand-100"
							:disabled="g.uploading"
							@click="openCameraOrFallback(g)"
						>
							<Icon v-if="g.uploading" name="loader" :size="16" class="animate-spin" />
							<template v-else><Icon name="camera" :size="16" /> {{ labels.photoCamera }}</template>
						</button>
						<label class="flex flex-1 cursor-pointer items-center justify-center gap-1.5 rounded-lg border border-dashed border-brand-300 bg-brand-50 py-2.5 text-sm font-medium text-brand-600 active:bg-brand-100">
							<input
								type="file"
								accept="image/*"
								multiple
								class="hidden"
								:disabled="g.uploading"
								@change="onPickPhotos(g, $event)"
							/>
							<Icon v-if="g.uploading" name="loader" :size="16" class="animate-spin" />
							<template v-else><Icon name="image" :size="16" /> {{ labels.photoGallery }}</template>
						</label>
					</div>
				</section>
				<p v-if="!photoGroups.length" class="oak-card py-6 text-center text-sm text-gray-400">{{ labels.mrNoUsed }}</p>
				<p v-if="photoErr" class="text-xs text-red-600">{{ photoErr }}</p>
			</template>

			<!-- Temuan EIR. Terbuka sebelum Mulai, dilipat begitu form kerja tampil. -->
			<section v-if="(order.damages || []).length" class="oak-card space-y-3 p-4">
				<button type="button" class="flex w-full items-center justify-between gap-2 text-left" @click="damagesOpen = !damagesOpen">
					<p class="oak-section-title">{{ labels.mrDamagesTitle }}</p>
					<span class="flex shrink-0 items-center gap-1 text-[11px] text-gray-400">
						{{ labels.mrFindingsCount.replace("{n}", order.damages.length) }}
						<Icon :name="damagesOpen ? 'chevron-up' : 'chevron-down'" :size="14" />
					</span>
				</button>
				<div v-if="damagesOpen" class="space-y-2">
					<MrDamageCard v-for="(d, i) in order.damages" :key="i" :damage="d" />
				</div>
			</section>

			<!-- Spec tank, langsung dari EIR. -->
			<section class="oak-card p-4">
				<div class="mb-2 flex items-center justify-between gap-2">
					<p class="oak-section-title">{{ labels.mrTankDetails }}</p>
					<span v-if="order.inspection" class="shrink-0 text-[11px] text-gray-400">{{ labels.mrTankFromEir }}</span>
				</div>
				<p class="mb-2 truncate text-xs text-gray-500">{{ orderSubtitle }}</p>
				<dl class="grid grid-cols-2 gap-x-3 gap-y-3 text-sm">
					<div v-for="cell in headerCells" :key="cell.label" class="min-w-0">
						<dt class="text-[11px] uppercase tracking-wide text-gray-400">{{ cell.label }}</dt>
						<dd class="truncate font-semibold text-gray-800">{{ cell.value || "—" }}</dd>
					</div>
					<!-- Satu-satunya sel yang bisa ditulis: tanggal uji tank (milik master), hanya
					     di order uji berkala. -->
					<LastTestField
						v-if="order.job_type === 'Periodic Test'"
						v-model="order.last_test_date"
						:container="order.container"
					/>
				</dl>
			</section>

			<!-- Catatan umum (baca saja — Admin Ops yang menulis). -->
			<section v-if="order.remarks" class="oak-card p-4">
				<p class="oak-section-title mb-1">{{ labels.mrRemarks }}</p>
				<p class="whitespace-pre-line text-sm text-gray-700">{{ order.remarks }}</p>
			</section>

			<!-- BELUM MULAI: satu aksi, dan apa yang dicatatnya. -->
			<template v-if="isPending">
				<button class="oak-btn oak-btn-primary w-full py-3 text-base" @click="startCurrent">
					<Icon name="play" :size="18" /> {{ labels.mrStartFull }}
				</button>
				<p class="text-center text-xs text-gray-400">{{ labels.mrStartAuto }}</p>
			</template>

			<!-- SUDAH MULAI: serahkan ke Desk. Ini TIDAK menutup order. -->
			<template v-else-if="isInProgress">
				<p class="flex items-center justify-center gap-1.5 text-xs">
					<span v-if="saveRes.loading" class="text-gray-400">{{ labels.savingDraft }}</span>
					<span v-else-if="savedOk" class="inline-flex items-center gap-1 text-leaf-600">
						<Icon name="check" :size="13" /> {{ labels.draftSaved }}
					</span>
					<span v-else class="text-gray-400">{{ labels.mrSubmitAutosave }}</span>
				</p>
				<button class="oak-btn oak-btn-primary w-full py-3" :disabled="submitting" @click="confirmSubmit">
					<Icon v-if="submitting" name="loader" :size="18" class="animate-spin" />
					<span v-else>{{ labels.mrSubmitReview }}</span>
				</button>
				<p class="text-center text-xs text-gray-400">{{ labels.mrSubmitReviewHint }}</p>
			</template>
		</template>

		<!-- Satu fallback kamera tersembunyi untuk seluruh halaman; `fallbackGroup` ingat baris
		     mana yang meminta. Lihat utils/camera.js. -->
		<input ref="camInput" type="file" accept="image/*" capture="environment" multiple class="hidden" @change="onFallbackPick($event)" />
	</div>
</template>

<script setup>
import { computed, nextTick, reactive, ref, watch } from "vue"
import { createResource } from "frappe-ui"
import { useRoute, useRouter } from "vue-router"
import { isLocalRef, photoSrc, send, uploadPhoto } from "@/data/send"
import { cachedResource } from "@/data/cache"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
import { openLightbox } from "@/utils/lightbox"
import { shootOrFallback } from "@/utils/camera"
import { confirm } from "@/utils/confirm"
import { clockOf, fmtStamp, mrChip } from "@/utils/mrStatus"
import { fmtDate, fmtDateTime } from "@/utils/surveyStatus"
import { usePhotoQueue } from "@/utils/photoQueue"
import EditedBy from "@/components/EditedBy.vue"
import Icon from "@/components/Icon.vue"
import LastTestField from "@/components/LastTestField.vue"
import MrDamageCard from "@/components/MrDamageCard.vue"
import PhotoMark from "@/components/PhotoMark.vue"
import PhotoTile from "@/components/PhotoTile.vue"
import SkeletonDetail from "@/components/SkeletonDetail.vue"
import RepairOrderInfo from "@/components/RepairOrderInfo.vue"
import DetailHeader from "@/components/list/DetailHeader.vue"


const route = useRoute()
const router = useRouter()

// M&R atau Periodic Test — satu halaman, dua menu (router.js meta; server: mr_scope.py).
const kind = route.meta.jobType === "Periodic Test"
	? { base: "/periodic", workTitle: labels.ptWorkTitle }
	: { base: "/mr", workTitle: labels.mrWorkTitle }

// ?o=<name> (daftar, notifikasi, Riwayat "Tarik & Perbaiki") atau :name kalau kelak punya rute sendiri.
const orderName = computed(() => route.params.name || route.query.o || "")

const order = ref(null)
const used = ref([])
// Album bukti order ini, datar. Pengelompokan per baris ada di view.
const workPhotos = ref([])
const photoErr = ref("")
const savedOk = ref(false) // auto-save terakhir berhasil
const suppressSave = ref(false) // bisukan auto-save saat detail sedang dimuat

// "Pending" = sudah diserahkan Admin Ops, belum dipegang; tekan pertama tim adalah Mulai.
const isPending = computed(() => order.value?.status === "Pending")
const isInProgress = computed(() => order.value?.status === "In Progress")
const isInReview = computed(() => order.value?.status === "Pending Review")
// Hanya baris yang disetujui yang relevan untuk tim lapangan.
const repairLines = computed(() => used.value.filter((u) => u.decision !== "Rejected"))

const orderChip = computed(() => {
	if (!order.value) return null
	const c = mrChip(order.value.status)
	return { label: c.label, cls: c.tone }
})
const workedBy = computed(() => order.value?.started_by_name || order.value?.technician || "")

// Grup mana yang sedang mengunggah — satu per satu cukup, dan flag-nya tidak menempel di
// baris foto (yang dikirim apa adanya ke server).
const uploading = ref(null)

// Satu antrean per grup, supaya foto tampil di bawah barisnya sendiri selama naik. Di luar
// `photoGroups` (computed — apa pun yang ditulis ke objeknya hilang di recompute berikutnya).
const queues = new Map()
function queueFor(key) {
	if (!queues.has(key)) queues.set(key, usePhotoQueue())
	return queues.get(key)
}

// Satu grup per baris yang disetujui. Foto milik grup yang BARIS-nya ia sebut; cadangan `item`
// menangkap foto yang dilampirkan dari Desk, tempat manusia memilih item tanpa melihat id baris.
const photoGroups = computed(() =>
	repairLines.value.map((u) => ({
		key: u.name || u.item,
		line: u,
		label: u.item_name || u.item,
		uploading: uploading.value === (u.name || u.item),
		photos: workPhotos.value.filter((p) => (p.used_item ? p.used_item === u.name : p.item === u.item)),
	}))
)

// Empat angka tank yang dicari di tengah perbaikan.
const headerCells = computed(() => {
	const h = order.value || {}
	return [
		{ label: labels.cleaningCapacity, value: h.capacity },
		{ label: labels.mrTareMgw, value: [h.tare, h.mgw].filter(Boolean).join(" / ") },
		{ label: labels.cleaningPrevCargo, value: h.previous_cargo },
		{ label: labels.cleaningMfgDate, value: fmtMonthYear(h.date_of_manufacture) },
	]
})

// "Mar 2019" — tahun buat tank dibaca sebagai vintage, bukan hari.
function fmtMonthYear(v) {
	if (!v) return ""
	const d = new Date(String(v).slice(0, 10) + "T00:00:00")
	return Number.isNaN(d.getTime())
		? String(v).slice(0, 7)
		: d.toLocaleDateString("id-ID", { month: "short", year: "numeric" })
}

// Jenis tank, muatan terakhir, dan EIR asalnya — prinsipal & nomor tank sudah di kartu info.
const orderSubtitle = computed(() => {
	const o = order.value || {}
	return [
		o.tank_type,
		o.previous_cargo ? labels.mrExFmt.replace("{cargo}", o.previous_cargo) : "",
		o.inspection ? labels.mrFromEir.replace("{ref}", o.inspection) : "",
	]
		.filter(Boolean)
		.join(" · ")
})

// Siapa yang meloloskan pekerjaan. Estimasi yang ditolak memakai bentuk yang sama supaya
// alasannya tidak tersembunyi di balik perubahan warna.
const approval = computed(() => {
	const o = order.value
	if (!o || !o.decided_on) return null
	const rejected = o.status === "Rejected"
	return {
		label: rejected ? labels.mrRejectedBanner : [labels.mrFlowApproved, o.decided_by_name].filter(Boolean).join(" "),
		tone: rejected ? "bg-red-100 text-red-700" : "bg-leaf-100 text-leaf-800",
		icon: rejected ? "x-circle" : "check-circle",
		note: [o.owner_note, fmtStamp(o.decided_on)].filter(Boolean).join(" · "),
	}
})

// Dihitung dalam BARIS yang punya minimal satu foto, bukan jumlah foto.
const photoProgress = computed(() => {
	const total = photoGroups.value.length
	const done = photoGroups.value.filter((g) => g.photos.length).length
	return { done, total, label: labels.mrProgressChip.replace("{done}", done).replace("{total}", total) }
})

// "mulai 15:33 · teknisi Rudi"
const runLine = computed(() => {
	const o = order.value || {}
	const who = o.started_by_name || o.technician
	return [
		o.start_date ? labels.mrStartedAt.replace("{time}", clockOf(o.start_date)) : "",
		who ? labels.mrTechnicianShort.replace("{name}", who) : "",
	]
		.filter(Boolean)
		.join(" · ")
})

const itemsCountText = computed(() => labels.mrItemsN.replace("{n}", photoGroups.value.length))

// Qty, gudang asal part, dan stok di rak.
function lineFacts(line) {
	return [
		`${labels.mrQty} ${line.quantity}`,
		line.warehouse || "",
		line.on_hand != null ? `${labels.mrOnHand} ${line.on_hand}` : "",
	]
		.filter(Boolean)
		.join(" · ")
}

// Dilipat di form kerja, terbuka pada job yang belum dimulai.
const damagesOpen = ref(true)

// Status fetch dilacak eksplisit, bukan diturunkan dari `order` — turunan itu berkedip.
const detailPending = ref(false)
const detailFailed = ref(false)
const detailError = ref("")

const detailRes = cachedResource({
	url: "container_depot.ess.repairs.mr_order_detail",
	method: "GET",
	onSuccess(data) {
		detailPending.value = false
		detailFailed.value = false
		// Bisukan auto-save selama album diisi dari order yang dimuat — kalau tidak, membuka
		// job langsung mengirim balik apa yang baru dibacanya.
		suppressSave.value = true
		savedOk.value = false
		order.value = data
		damagesOpen.value = data.status !== "In Progress"
		used.value = (data.used_items || []).map((u) => reactive({ ...u, decision: u.decision || "Pending" }))
		workPhotos.value = (data.work_photos || []).map((p) => ({ ...p }))
		photoErr.value = ""
		nextTick(() => {
			suppressSave.value = false
		})
	},
	onError(err) {
		detailPending.value = false
		detailFailed.value = true
		detailError.value = err?.messages?.[0] || err?.message || labels.error
	},
})

function fetchDetail(name) {
	detailPending.value = true
	detailFailed.value = false
	detailRes.fetch({ repair_order: name })
}
function retryDetail() {
	if (orderName.value) fetchDetail(orderName.value)
}
watch(orderName, (n) => n && order.value?.name !== n && fetchDetail(n), { immediate: true })

// --- mulai (Pending -> In Progress) ------------------------------------------
// Status dibalik lokal, tidak di-fetch ulang: menunggu respons membuat "Mulai" mustahil di
// titik tanpa sinyal, dan mengunci teknisi dari sisa form.
async function startCurrent() {
	if (!order.value) return
	try {
		await send({ url: "container_depot.ess.repairs.mr_start", payload: { repair_order: order.value.name } })
		toast.success(labels.mrStarted)
		order.value = { ...order.value, status: "In Progress" }
	} catch (e) {
		toast.error(e?.message || labels.error)
	}
}

// --- tarik dari review (Pending Review -> In Progress) ------------------------
const withdrawRes = createResource({
	url: "container_depot.ess.repairs.mr_withdraw_review",
	method: "POST",
	onSuccess: () => {
		toast.success(labels.mrWithdrawReviewDone)
		fetchDetail(order.value.name)
	},
	onError: (e) => toast.error(e?.messages?.[0] || e?.message || labels.error),
})
function withdrawReview() {
	withdrawRes.submit({ repair_order: order.value.name })
}

// --- foto bukti ----------------------------------------------------------------
// Foto naik begitu diambil dan album langsung disimpan, jadi HP yang mati di tengah
// perbaikan tidak kehilangan apa pun. Ref `local:` (upload gagal) tidak ikut auto-save;
// submit yang membawanya lewat `send`, yang menukarnya dengan file_url sungguhan.
async function onPickPhotos(group, event) {
	const files = Array.from(event.target.files || [])
	event.target.value = "" // boleh memilih berkas yang sama lagi
	await addPhotos(group, files)
}

// Viewfinder dalam aplikasi: rana -> unggah, tanpa layar konfirmasi aplikasi kamera.
const camInput = ref(null)
let fallbackGroup = null
function openCameraOrFallback(group) {
	fallbackGroup = group
	return shootOrFallback(camInput, (file) => addPhotos(group, [file]))
}

async function onFallbackPick(event) {
	const files = Array.from(event.target.files || [])
	event.target.value = ""
	const group = fallbackGroup
	fallbackGroup = null
	if (group) await addPhotos(group, files)
}

async function addPhotos(group, files) {
	if (!files.length) return false
	// `last` adalah jawaban untuk viewfinder (lihat utils/camera.js): kegagalan yang ditelan di
	// sini akan tampil sebagai "terkirim" pada foto yang tidak ke mana-mana.
	let last = false
	const queue = queueFor(group.key)
	queue.clearFailed()
	photoErr.value = ""
	uploading.value = group.key
	try {
		// Per foto: satu gambar yang gagal tidak boleh menyeret yang lain.
		for (const f of files) {
			const id = queue.add(f)
			try {
				last = await uploadPhoto(f)
				workPhotos.value.push({
					photo: last,
					// BARIS untuk presisi (item yang sama bisa dua kali), ITEM untuk manusia.
					used_item: group.line.name || null,
					item: group.line.item,
					caption: "",
				})
				queue.done(id)
			} catch (e) {
				last = false
				photoErr.value = labels.mrPhotoError
				queue.fail(id)
			}
		}
		scheduleSave()
	} finally {
		uploading.value = null
	}
	return last
}

function removePhoto(row) {
	const i = workPhotos.value.indexOf(row)
	if (i >= 0) workPhotos.value.splice(i, 1)
	scheduleSave()
}

const saveRes = createResource({
	url: "container_depot.ess.repairs.mr_order_save",
	method: "POST",
	onSuccess() {
		savedOk.value = true
		flushPendingSave()
	},
	// Auto-save yang tidak sampai server tidak layak toast merah; yang DITOLAK server harus terlihat.
	onError(err) {
		if (err?.response) photoErr.value = err?.messages?.[0] || err?.message || labels.error
		flushPendingSave()
	},
})

// Tidak pernah dua save sekaligus: masing-masing mengganti seluruh album, jadi respons lama
// yang datang belakangan akan memulihkan foto yang sudah dihapus.
let saveTimer = null
let resaveWanted = false

function flushPendingSave() {
	if (!resaveWanted) return
	resaveWanted = false
	scheduleSave()
}

function scheduleSave() {
	if (!order.value || suppressSave.value) return
	savedOk.value = false
	if (saveTimer) clearTimeout(saveTimer)
	saveTimer = setTimeout(() => {
		saveTimer = null
		if (saveRes.loading) {
			resaveWanted = true
			return
		}
		saveRes.fetch({
			repair_order: order.value.name,
			work_photos: JSON.stringify(workPhotos.value.filter((p) => !isLocalRef(p.photo))),
		})
	}, 700)
}

// --- kirim untuk review (In Progress -> Pending Review) -------------------------
// Serah terima, bukan penutupan: Desk yang memeriksa dan menutup. `send` menambahkan
// request_id supaya kiriman ulang tidak jadi dua sign-off (ess/idempotency.py).
const submitting = ref(false)

async function confirmSubmit() {
	const ok = await confirm({
		message: labels.mrSubmitReviewHint,
		confirmLabel: labels.mrSubmitReview,
		cancelLabel: labels.confirmCancel,
	})
	if (ok) submitForReview()
}

async function submitForReview() {
	if (!order.value || submitting.value) return
	submitting.value = true
	const o = order.value
	try {
		if (saveTimer) {
			clearTimeout(saveTimer)
			saveTimer = null
		}
		await send({
			url: "container_depot.ess.repairs.mr_order_save",
			payload: {
				repair_order: o.name,
				// Array, bukan string JSON: `send` harus menelusuri payload untuk menukar ref `local:`.
				work_photos: workPhotos.value,
				submit: 1,
			},
		})
		toast.success(labels.mrSubmittedReview, { title: o.repair_order_id || o.name })
		goBack()
	} catch (e) {
		toast.error(e?.message || labels.error)
	} finally {
		submitting.value = false
	}
}

// Kembali sungguhan kalau layar ini dibuka dari daftar (entri riwayatnya ikut terbuang);
// dari notifikasi/deep link tidak ada entri untuk di-pop, jadi ganti ke daftar.
function goBack() {
	if (saveTimer) {
		clearTimeout(saveTimer)
		saveTimer = null
	}
	suppressSave.value = true
	if (window.history.state?.back) router.back()
	else router.replace({ path: kind.base })
}
</script>
