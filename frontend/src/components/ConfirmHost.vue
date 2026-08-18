<template>
	<transition name="cf">
		<div
			v-if="confirmState.open"
			class="fixed inset-0 z-[70] flex items-end justify-center bg-black/50 p-4 backdrop-blur-sm sm:items-center"
			role="dialog"
			aria-modal="true"
			@click="cancel"
		>
			<div class="oak-card w-full max-w-sm space-y-4 p-5" @click.stop>
				<div class="space-y-1.5">
					<p class="text-base font-extrabold tracking-tight text-gray-900">{{ confirmState.title }}</p>
					<p v-if="confirmState.message" class="text-sm leading-snug text-gray-600">{{ confirmState.message }}</p>
				</div>
				<div class="flex gap-2">
					<button class="oak-btn oak-btn-secondary flex-1 py-2.5" @click="cancel">
						{{ confirmState.cancelLabel }}
					</button>
					<button
						class="oak-btn flex-1 py-2.5"
						:class="confirmState.danger ? 'bg-red-600 text-white hover:bg-red-700' : 'oak-btn-primary'"
						@click="ok"
					>
						{{ confirmState.confirmLabel }}
					</button>
				</div>
			</div>
		</div>
	</transition>
</template>

<script setup>
import { onMounted, onUnmounted } from "vue"
import { confirmState, resolveConfirm } from "@/utils/confirm"
import { useDismissOnBack } from "@/utils/backstack"

function cancel() {
	resolveConfirm(false)
}
// Back is the phone's Escape: dismiss the sheet as a "no", never as "leave the screen".
// The promise has to settle either way or whatever awaited the confirm hangs forever.
useDismissOnBack(
	() => confirmState.open,
	() => cancel()
)
function ok() {
	resolveConfirm(true)
}
function onKey(e) {
	if (confirmState.open && e.key === "Escape") cancel()
}
onMounted(() => window.addEventListener("keydown", onKey))
onUnmounted(() => window.removeEventListener("keydown", onKey))
</script>

<style scoped>
.cf-enter-active,
.cf-leave-active {
	transition: opacity 0.18s ease;
}
.cf-enter-from,
.cf-leave-to {
	opacity: 0;
}
</style>
