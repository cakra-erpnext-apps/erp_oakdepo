<template>
	<transition name="lb">
		<div
			v-if="lightbox.open"
			class="fixed inset-0 z-[60] flex flex-col bg-black/90 backdrop-blur-sm"
			role="dialog"
			aria-modal="true"
			@click="closeLightbox"
		>
			<!-- Top bar: counter + close -->
			<div class="flex items-center justify-between p-3 pt-[max(0.75rem,env(safe-area-inset-top))] text-white">
				<span
					v-if="lightbox.images.length > 1"
					class="rounded-full bg-white/10 px-3 py-1 text-sm font-medium tabular-nums"
				>
					{{ lightbox.index + 1 }} / {{ lightbox.images.length }}
				</span>
				<span v-else></span>
				<button
					type="button"
					class="rounded-full bg-white/10 p-2 transition hover:bg-white/20"
					aria-label="Tutup"
					@click.stop="closeLightbox"
				>
					<Icon name="x" :size="22" />
				</button>
			</div>

			<!-- Image stage -->
			<div class="relative flex flex-1 items-center justify-center overflow-hidden px-2 pb-[max(1rem,env(safe-area-inset-bottom))]">
				<button
					v-if="lightbox.images.length > 1"
					type="button"
					class="absolute left-1 top-1/2 -translate-y-1/2 rounded-full bg-white/10 p-2 text-white transition hover:bg-white/20"
					aria-label="Sebelumnya"
					@click.stop="prevImage"
				>
					<Icon name="chevron-left" :size="26" />
				</button>

				<img
					:src="current"
					alt=""
					class="max-h-full max-w-full select-none rounded-lg object-contain shadow-2xl"
					@click.stop
				/>

				<button
					v-if="lightbox.images.length > 1"
					type="button"
					class="absolute right-1 top-1/2 -translate-y-1/2 rounded-full bg-white/10 p-2 text-white transition hover:bg-white/20"
					aria-label="Berikutnya"
					@click.stop="nextImage"
				>
					<Icon name="chevron-right" :size="26" />
				</button>
			</div>
		</div>
	</transition>
</template>

<script setup>
import { computed, onMounted, onUnmounted, watch } from "vue"
import { lightbox, closeLightbox, nextImage, prevImage } from "@/utils/lightbox"
import { useDismissOnBack } from "@/utils/backstack"
import Icon from "@/components/Icon.vue"

const current = computed(() => lightbox.images[lightbox.index] || "")

// Escape closes the viewer on a desktop; on a phone that key does not exist and Back is the
// only dismiss there is. Without this it closed the page underneath instead.
useDismissOnBack(
	() => lightbox.open,
	() => closeLightbox()
)

function onKey(e) {
	if (!lightbox.open) return
	if (e.key === "Escape") closeLightbox()
	else if (e.key === "ArrowRight") nextImage()
	else if (e.key === "ArrowLeft") prevImage()
}

// Lock background scroll while the viewer is open.
watch(
	() => lightbox.open,
	(open) => {
		document.body.style.overflow = open ? "hidden" : ""
	}
)

onMounted(() => window.addEventListener("keydown", onKey))
onUnmounted(() => {
	window.removeEventListener("keydown", onKey)
	document.body.style.overflow = ""
})
</script>

<style scoped>
.lb-enter-active,
.lb-leave-active {
	transition: opacity 0.2s ease;
}
.lb-enter-from,
.lb-leave-to {
	opacity: 0;
}
</style>
