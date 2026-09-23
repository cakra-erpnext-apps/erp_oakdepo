<template>
	<div class="flex items-center gap-2">
		<button
			class="oak-press flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-gray-500"
			:aria-label="labels.surveyPosBack"
			@click="emit('back')"
		>
			<Icon name="chevron-left" :size="22" />
		</button>
		<h1 class="min-w-0 flex-1 truncate text-lg font-extrabold tracking-tight text-gray-900">{{ title }}</h1>
		<span v-if="chip" class="oak-chip shrink-0" :class="chip.cls">{{ chip.label }}</span>
	</div>
</template>

<script setup>
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"

defineProps({
	title: { type: String, required: true },
	chip: { type: Object, default: null }, // { label, cls }
})
const emit = defineEmits(["back"])
</script>
