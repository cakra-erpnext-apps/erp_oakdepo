<template>
	<!-- Every date picker in the PWA reads HARI-BULAN-TAHUN (user, 2026-10-07). A native
	     <input type="date"> draws its text in the phone's own locale and cannot be told
	     otherwise, so it sits invisible over a box that prints DD-MM-YYYY: the tap still
	     opens the phone's own calendar, and the value stays ISO (YYYY-MM-DD) for the server. -->
	<div
		class="oak-input relative flex items-center focus-within:border-brand-500 focus-within:ring-2 focus-within:ring-brand-500/25"
		:class="[attrs.class, disabled ? 'bg-gray-50 text-gray-400' : '']"
	>
		<span :class="value ? '' : 'text-gray-400'">{{ value ? dmy(value) : labels.datePlaceholder }}</span>
		<input
			v-bind="{ ...attrs, class: undefined }"
			type="date"
			:value="value"
			:min="min"
			:max="max"
			:disabled="disabled"
			class="absolute inset-0 h-full w-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
			@click="open"
			@input="set($event.target.value)"
			@change="set($event.target.value)"
		/>
	</div>
</template>

<script setup>
import { computed, useAttrs } from "vue"
import { labels } from "@/utils/labels"

defineOptions({ inheritAttrs: false })
const props = defineProps({
	modelValue: { type: String, default: "" },
	min: { type: String, default: undefined },
	max: { type: String, default: undefined },
	disabled: { type: Boolean, default: false },
})
const emit = defineEmits(["update:modelValue"])
const attrs = useAttrs()

// A datetime from the server arrives as "YYYY-MM-DD hh:mm:ss"; the picker takes the day.
const value = computed(() => String(props.modelValue || "").slice(0, 10))

const dmy = (iso) => iso.split("-").reverse().join("-")

function set(v) {
	if (v !== value.value) emit("update:modelValue", v)
}

// Desktop browsers open the calendar only from their own (invisible) icon; a click anywhere
// on the box should do it, as a tap does on a phone.
function open(e) {
	try {
		e.target.showPicker?.()
	} catch {
		/* already open, or not allowed outside a user gesture */
	}
}
</script>
