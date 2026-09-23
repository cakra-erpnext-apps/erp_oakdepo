<template>
	<!-- Angka yang bisa dipencet = filter status. Dihitung TANPA filter yang sedang berlaku
	     (server), supaya pil tetap bisa dipakai berpindah saat pencarian mempersempit. -->
	<div class="grid gap-1.5" :style="{ gridTemplateColumns: `repeat(${pills.length}, minmax(0, 1fr))` }">
		<button
			v-for="p in pills"
			:key="p.key || 'all'"
			class="oak-press flex min-h-[68px] flex-col items-center justify-center rounded-xl border px-1 py-2 transition"
			:class="modelValue === p.key ? 'border-brand-500 bg-brand-500/10' : 'border-gray-200 bg-paper'"
			:aria-pressed="modelValue === p.key"
			@click="emit('update:modelValue', modelValue === p.key ? '' : p.key)"
		>
			<span class="text-lg font-extrabold leading-none" :class="modelValue === p.key ? 'text-brand-700' : p.tone">
				{{ p.count }}
			</span>
			<span class="mt-1 truncate text-[11px] font-semibold" :class="modelValue === p.key ? 'text-brand-700' : 'text-gray-500'">
				{{ p.label }}
			</span>
		</button>
	</div>
</template>

<script setup>
defineProps({
	pills: { type: Array, required: true }, // [{ key, label, count, tone }] — key "" = semua
	modelValue: { type: String, default: "" },
})
const emit = defineEmits(["update:modelValue"])
</script>
