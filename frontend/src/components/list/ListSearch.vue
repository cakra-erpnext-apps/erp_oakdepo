<template>
	<div class="relative">
		<Icon name="search" :size="18" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
		<input
			:value="modelValue"
			type="search"
			class="oak-input pl-10 pr-10"
			:placeholder="placeholder"
			autocorrect="off"
			spellcheck="false"
			@input="onInput"
		/>
		<button
			v-if="modelValue"
			class="oak-press absolute right-2 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full text-gray-400"
			:aria-label="labels.tplCancel"
			@click="emit('update:modelValue', ''); emit('search')"
		>
			<Icon name="x" :size="16" />
		</button>
	</div>
</template>

<script setup>
import { onBeforeUnmount } from "vue"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"

defineProps({ modelValue: { type: String, default: "" }, placeholder: { type: String, default: "" } })
const emit = defineEmits(["update:modelValue", "search"])

// Debounced: a tank number typed a character at a time is one query, not twelve.
let timer = null
function onInput(e) {
	emit("update:modelValue", e.target.value)
	clearTimeout(timer)
	timer = setTimeout(() => emit("search"), 300)
}
onBeforeUnmount(() => clearTimeout(timer))
</script>
