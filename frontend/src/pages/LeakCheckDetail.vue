<template>
	<!-- Tata letak = detail Jadwal Survey: kepala, kartu info yang sama dengan barisnya di
	     daftar, lalu isinya — form foto kalau masih Open, galeri kalau sudah selesai. -->
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<DetailHeader :title="labels.leakDetailTitle" :chip="doc ? leakChip(doc) : null" @back="goBack" />

		<SkeletonDetail v-if="pending" :cells="2" :sections="2" />

		<section v-else-if="failed" class="oak-card space-y-3 p-6 text-center">
			<span class="oak-icon-tile mx-auto h-12 w-12 bg-red-50 text-red-500">
				<Icon name="alert-triangle" :size="24" />
			</span>
			<p class="text-sm text-gray-600">{{ error }}</p>
			<div class="flex gap-2">
				<button class="oak-btn oak-btn-secondary flex-1" @click="goBack">{{ labels.surveyPosBack }}</button>
				<button class="oak-btn oak-btn-primary flex-1" @click="load">{{ labels.retry }}</button>
			</div>
		</section>

		<template v-else-if="doc">
			<section class="oak-card space-y-3 p-4">
				<LeakCheckInfo :o="doc" />
				<div class="grid grid-cols-2 gap-2 border-t border-gray-100 pt-3">
					<div class="min-w-0">
						<p class="text-[11px] text-gray-400">{{ labels.leakCreated }}</p>
						<p class="truncate text-sm font-bold text-gray-900">{{ fmtDateTime(doc.creation) }}</p>
					</div>
					<div class="min-w-0">
						<p class="text-[11px] text-gray-400">{{ labels.leakChecked }}</p>
						<p class="truncate text-sm font-bold text-gray-900">{{ doc.recorded_on ? fmtDateTime(doc.recorded_on) : "—" }}</p>
					</div>
				</div>
				<p v-if="doc.recorded_by" class="flex gap-2 border-t border-gray-100 pt-3 text-xs">
					<span class="w-24 shrink-0 text-gray-400">{{ labels.leakCheckedBy }}</span>
					<span class="min-w-0 font-semibold text-gray-700">{{ doc.recorded_by }}</span>
				</p>
			</section>

			<!-- Masih Open: isi di sini. -->
			<template v-if="doc.can_edit">
				<LeakPhotoForm :form="form" />
				<div class="oak-footer">
					<button
						class="oak-btn oak-btn-primary min-h-[52px] w-full text-base"
						:disabled="!canSave || saving"
						@click="save"
					>
						{{ saving ? "…" : labels.leakSave }}
					</button>
				</div>
			</template>

			<!-- Sudah selesai: hasilnya, baca saja (koreksi lewat Desk). -->
			<template v-else>
				<section class="oak-card space-y-2 p-4">
					<p class="text-sm font-extrabold text-gray-900">
						{{ labels.leakPhotos }} <span class="text-gray-400">{{ doc.photos.length }}</span>
					</p>
					<div class="grid grid-cols-2 items-start gap-2 sm:grid-cols-3">
						<button v-for="(p, i) in doc.photos" :key="p.photo" type="button" class="space-y-1 text-left" @click="openLightbox(slides, i)">
							<img
								:src="photoSrc(p.photo)"
								class="aspect-square w-full rounded-lg border-2 object-cover"
								:class="p.is_leak ? 'border-red-500' : 'border-gray-200'"
							/>
							<span v-if="p.is_leak" class="oak-chip bg-red-100 text-red-700">{{ labels.leakFlag }}</span>
							<span v-if="p.caption" class="block truncate text-xs text-gray-600">{{ p.caption }}</span>
						</button>
					</div>
				</section>
				<section class="oak-card space-y-1 p-4">
					<p class="text-sm font-extrabold text-gray-900">{{ labels.leakRemarks }}</p>
					<p class="whitespace-pre-line text-sm" :class="doc.remarks ? 'text-gray-700' : 'text-gray-400'">
						{{ doc.remarks || labels.leakNoRemarks }}
					</p>
				</section>
			</template>
		</template>
	</div>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { labels } from "@/utils/labels"
import { cachedResource } from "@/data/cache"
import { send, photoSrc } from "@/data/send"
import { toast } from "@/utils/toast"
import { openLightbox } from "@/utils/lightbox"
import { fmtDateTime } from "@/utils/surveyStatus"
import { leakChip } from "@/utils/leakStatus"
import Icon from "@/components/Icon.vue"
import SkeletonDetail from "@/components/SkeletonDetail.vue"
import DetailHeader from "@/components/list/DetailHeader.vue"
import LeakCheckInfo from "@/components/LeakCheckInfo.vue"
import LeakPhotoForm from "@/components/LeakPhotoForm.vue"

const route = useRoute()
const router = useRouter()

const doc = ref(null)
const pending = ref(false)
const failed = ref(false)
const error = ref("")
const form = reactive({ photos: [], remarks: "", uploading: false })
const saving = ref(false)
const canSave = computed(() => form.photos.length > 0 && !form.uploading)
const slides = computed(() => (doc.value?.photos || []).map((p) => ({ src: photoSrc(p.photo), caption: p.caption })))

const res = cachedResource({
	url: "container_depot.ess.leak_check.leak_detail",
	method: "GET",
	onSuccess(data) {
		pending.value = false
		failed.value = false
		doc.value = data
		form.photos = []
		form.remarks = data?.remarks || ""
	},
	// Inline, never a toast — same as the survey detail: a toast leaves a blank screen.
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
watch(() => route.params.name, (n) => n && load(), { immediate: true })

async function save() {
	if (!canSave.value || saving.value) return
	saving.value = true
	try {
		await send({
			url: "container_depot.ess.leak_check.leak_record",
			payload: {
				name: doc.value.name,
				remarks: form.remarks.trim() || undefined,
				photos: form.photos.map((p) => ({ photo: p.photo, caption: p.caption.trim(), is_leak: p.is_leak ? 1 : 0 })),
			},
		})
		toast.success(labels.leakSaved, { title: doc.value.container_no })
		load()
	} catch (e) {
		toast.error(e?.message || labels.error)
	} finally {
		saving.value = false
	}
}

function goBack() {
	if (window.history.length > 1) router.back()
	else router.push("/leak-check")
}
</script>
