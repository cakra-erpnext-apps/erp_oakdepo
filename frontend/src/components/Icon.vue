<template>
	<!-- Lucide, from the SAME sprite the Desk sidebar draws (frappe/public/icons/lucide.svg),
	     so a menu reads with one icon on both surfaces. Symbols carry paths only; stroke
	     comes from here, so colour follows `text-*`. -->
	<span class="inline-flex shrink-0 items-center justify-center">
		<svg
			:width="size"
			:height="size"
			fill="none"
			stroke="currentColor"
			:stroke-width="stroke"
			stroke-linecap="round"
			stroke-linejoin="round"
			aria-hidden="true"
		>
			<use :href="`${LUCIDE_SPRITE}#icon-${lucideName}`" />
		</svg>
	</span>
</template>

<script>
// Served by Frappe; the service worker keeps a copy for offline (service-worker.js).
export const LUCIDE_SPRITE = "/assets/frappe/icons/lucide.svg"

// Feather names still used across the app -> their Lucide names. Lucide renamed these;
// everything else kept its feather name.
const RENAMED = {
	"alert-circle": "circle-alert",
	"alert-triangle": "triangle-alert",
	"arrow-down-circle": "circle-arrow-down",
	"check-circle": "circle-check",
	"check-square": "square-check",
	"x-circle": "circle-x",
	"help-circle": "circle-help",
	"play-circle": "circle-play",
	"edit-2": "pencil",
	"edit-3": "pen-line",
	grid: "layout-grid",
	home: "house",
	"more-horizontal": "ellipsis",
	sliders: "sliders-horizontal",
	tool: "wrench",
}
</script>

<script setup>
import { computed } from "vue"

const props = defineProps({
	name: { type: String, required: true },
	size: { type: [Number, String], default: 20 },
	stroke: { type: [Number, String], default: 2 },
})

const lucideName = computed(() => RENAMED[props.name] || props.name)
</script>
