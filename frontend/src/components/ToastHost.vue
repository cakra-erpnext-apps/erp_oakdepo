<template>
	<div
		class="pointer-events-none fixed inset-x-0 top-[max(0.75rem,env(safe-area-inset-top))] z-50 flex flex-col items-center px-4"
	>
		<transition-group name="toast" tag="div" class="flex w-full max-w-sm flex-col gap-2">
			<div
				v-for="t in toasts"
				:key="t.id"
				class="pointer-events-auto flex items-start gap-2.5 rounded-xl border px-3.5 py-2.5 shadow-lg backdrop-blur"
				:class="toneClass(t.type)"
				role="status"
				@click="dismiss(t.id)"
			>
				<Icon :name="toneIcon(t.type)" :size="18" class="mt-0.5 shrink-0" />
				<div class="min-w-0 flex-1">
					<p v-if="t.title" class="text-sm font-bold leading-snug">{{ t.title }}</p>
					<p class="text-sm leading-snug">{{ t.message }}</p>
				</div>
				<Icon name="x" :size="15" class="mt-0.5 shrink-0 opacity-40" />
			</div>
		</transition-group>
	</div>
</template>

<script setup>
import { toasts, dismiss } from "@/utils/toast"
import Icon from "@/components/Icon.vue"

function toneClass(type) {
	switch (type) {
		case "success":
			return "border-leaf-200 bg-leaf-50/95 text-leaf-800"
		case "error":
			return "border-red-200 bg-red-50/95 text-red-700"
		default:
			return "border-gray-200 bg-white/95 text-gray-800"
	}
}
function toneIcon(type) {
	switch (type) {
		case "success":
			return "check-circle"
		case "error":
			return "alert-circle"
		default:
			return "info"
	}
}
</script>

<style scoped>
.toast-enter-active,
.toast-leave-active {
	transition: all 0.25s ease;
}
.toast-enter-from {
	opacity: 0;
	transform: translateY(-12px) scale(0.97);
}
.toast-leave-to {
	opacity: 0;
	transform: translateY(-8px) scale(0.97);
}
.toast-move {
	transition: transform 0.25s ease;
}
</style>
