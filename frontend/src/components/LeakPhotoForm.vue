<template>
	<!-- Foto: tiap foto punya deskripsi (opsional) + tanda bocor (default tidak). `form` diubah
	     di tempat: { photos: [{ photo, caption, is_leak }], remarks, uploading }. -->
	<section class="oak-card space-y-2 p-4">
		<div class="flex items-baseline justify-between gap-2">
			<p class="text-sm font-extrabold text-gray-900">{{ labels.leakPhotos }}</p>
			<p class="shrink-0 text-[11px] text-gray-400">{{ labels.leakPhotosReq }}</p>
		</div>
		<div class="grid grid-cols-2 items-start gap-2 sm:grid-cols-3">
			<div v-for="(p, i) in form.photos" :key="p.photo" class="space-y-1">
				<div class="relative aspect-square">
					<img
						:src="photoSrc(p.photo)"
						class="h-full w-full rounded-lg border-2 object-cover"
						:class="p.is_leak ? 'border-red-500' : 'border-gray-200'"
						@click="openLightbox(form.photos.map((x) => ({ src: photoSrc(x.photo), caption: x.caption })), i)"
					/>
					<button
						type="button"
						class="absolute right-1 top-1 flex h-8 w-8 items-center justify-center rounded-full bg-black/70 text-white"
						:aria-label="labels.tplCancel"
						@click="form.photos.splice(i, 1)"
					>
						<Icon name="x" :size="16" />
					</button>
				</div>
				<input v-model="p.caption" type="text" class="oak-input px-2 py-1.5 text-xs" :placeholder="labels.photoCaption" />
				<label class="flex min-h-[36px] items-center gap-2 text-xs font-semibold" :class="p.is_leak ? 'text-red-600' : 'text-gray-600'">
					<input v-model="p.is_leak" type="checkbox" class="h-4 w-4" />
					{{ labels.leakFlag }}
				</label>
			</div>
			<PhotoTile v-for="it in photoQueue.items" :key="it.id" :item="it" tile="aspect-square w-full" />
			<input ref="camInput" type="file" accept="image/*" capture="environment" multiple class="hidden" @change="onPhotos" />
			<button
				type="button"
				class="flex aspect-square flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed border-brand-300 bg-brand-50 text-brand-600 active:bg-brand-100"
				:disabled="form.uploading"
				@click="openCameraOrFallback"
			>
				<Icon v-if="form.uploading" name="loader" :size="22" class="animate-spin" />
				<template v-else>
					<Icon name="camera" :size="22" />
					<span class="text-xs font-medium">{{ labels.photoCamera }}</span>
				</template>
			</button>
			<label class="flex aspect-square cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed border-brand-300 bg-brand-50 text-brand-600 active:bg-brand-100">
				<Icon name="image" :size="22" />
				<span class="text-xs font-medium">{{ labels.photoGallery }}</span>
				<input type="file" accept="image/*" multiple class="hidden" :disabled="form.uploading" @change="onPhotos" />
			</label>
		</div>
	</section>

	<!-- Remark umum, terpisah dari deskripsi per foto. -->
	<section class="oak-card space-y-2 p-4">
		<p class="text-sm font-extrabold text-gray-900">{{ labels.leakRemarks }}</p>
		<textarea v-model="form.remarks" rows="3" class="oak-input text-sm" :placeholder="labels.leakRemarksHint" />
	</section>
</template>

<script setup>
import { ref } from "vue"
import { uploadPhoto, photoSrc } from "@/data/send"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
import { openLightbox } from "@/utils/lightbox"
import { usePhotoQueue } from "@/utils/photoQueue"
import { shootOrFallback } from "@/utils/camera"
import Icon from "@/components/Icon.vue"
import PhotoTile from "@/components/PhotoTile.vue"

const props = defineProps({ form: { type: Object, required: true } })

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
	// `last` dibaca viewfinder kamera (utils/camera.js) untuk menandai jepretan gagal.
	let last = false
	photoQueue.clearFailed()
	props.form.uploading = true
	try {
		for (const f of files) {
			const id = photoQueue.add(f)
			try {
				last = await uploadPhoto(f)
				props.form.photos.push({ photo: last, caption: "", is_leak: false })
				photoQueue.done(id)
			} catch {
				last = false
				toast.error(labels.error)
				photoQueue.fail(id)
			}
		}
	} finally {
		props.form.uploading = false
	}
	return last
}
</script>
