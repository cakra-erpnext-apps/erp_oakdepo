<template>
	<!-- One field of the Gate bon form, in whichever shape its definition asks for. Pulled
	     out of GateEntry when the form grew a second home: the required fields sit on the
	     step-2 pane and the optional ones inside the "Detail tambahan" disclosure, and two
	     copies of this v-if chain would drift the moment one of them gained a field type. -->
	<SearchSelect
		v-if="field.type === 'select'"
		:model-value="modelValue"
		:options="field.options"
		:option-value="field.optionValue || null"
		:option-label="field.optionLabel || null"
		:group-by="field.groupBy || null"
		:empty-label="field.emptyLabel"
		:placeholder="labels.selectPlaceholder"
		:search-placeholder="labels.selectSearch"
		@update:model-value="emit('update:modelValue', $event)"
	/>
	<textarea
		v-else-if="field.type === 'textarea'"
		:value="modelValue"
		rows="2"
		class="oak-input"
		@input="emit('update:modelValue', $event.target.value.trim())"
	></textarea>
	<template v-else-if="field.type === 'datalist'">
		<input
			:value="modelValue"
			:list="`dl-${field.key}`"
			class="oak-input"
			autocomplete="off"
			@input="emit('update:modelValue', $event.target.value.trim())"
		/>
		<datalist :id="`dl-${field.key}`">
			<option v-for="o in field.options" :key="o" :value="o" />
		</datalist>
	</template>
	<input
		v-else
		:value="modelValue"
		:type="field.inputType || 'text'"
		class="oak-input"
		@input="emit('update:modelValue', $event.target.value.trim())"
	/>
</template>

<script setup>
import SearchSelect from "@/components/SearchSelect.vue"
import { labels } from "@/utils/labels"

defineProps({
	field: { type: Object, required: true },
	modelValue: { type: [String, Number], default: "" },
})
const emit = defineEmits(["update:modelValue"])
</script>
