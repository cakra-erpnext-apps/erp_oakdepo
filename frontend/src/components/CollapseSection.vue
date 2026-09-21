<template>
	<!-- Satu bagian daftar yang bisa dibuka-tutup. Kepalanya selalu terlihat — judul,
	     jumlah, dan panah — jadi operator tahu bagian itu ADA dan berisi berapa tanpa
	     harus membukanya. Yang tertutup tidak ikut memanjangkan halaman, dan di layar HP
	     itulah bedanya antara empat daftar yang terbaca dan satu gulungan panjang. -->
	<section class="oak-section">
		<button
			type="button"
			class="flex w-full items-center gap-2 text-left"
			:aria-expanded="open"
			@click="emit('update:open', !open)"
		>
			<Icon :name="icon" :size="16" :class="tone" />
			<p class="oak-section-title min-w-0 flex-1 truncate">{{ title }}</p>
			<span class="oak-chip shrink-0" :class="count ? chip : 'bg-gray-100 text-gray-400'">{{ count }}</span>
			<Icon
				name="chevron-down"
				:size="18"
				class="shrink-0 text-gray-400 transition-transform"
				:class="open ? 'rotate-180' : ''"
			/>
		</button>
		<div v-if="open" class="mt-3 space-y-3">
			<slot />
		</div>
	</section>
</template>

<script setup>
import Icon from "@/components/Icon.vue"

defineProps({
	title: { type: String, required: true },
	icon: { type: String, default: "list" },
	tone: { type: String, default: "text-gray-400" },
	chip: { type: String, default: "bg-gray-100 text-gray-500" },
	count: { type: Number, default: 0 },
	open: { type: Boolean, default: false },
})
const emit = defineEmits(["update:open"])
</script>
