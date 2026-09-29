<template>
	<!-- Info satu order — sama persis di kartu besar, di baris ringkas, dan di kepala detail.
	     Yang dicocokkan dengan kertas (Reff Doc, Prinsipal, Shipper, EMKL) di atas dan tebal;
	     nomor sistem paling bawah, kecil: dibaca hanya saat mencocokkan ke Desk.
	     Tidak ada yang dipotong (…): di HP, nomor tank dan Reff Doc justru yang dicari, jadi
	     baris turun ke bawah. Tiap potongan `whitespace-nowrap` supaya nomor tidak patah di
	     tengah; patahnya di pemisah " · ". Judul panjang tanpa spasi (Reff Doc) boleh patah
	     di mana saja. -->
	<span class="block min-w-0">
		<!-- Slot di kanan judul (chip status) — di baris judul saja, supaya baris-baris di
		     bawahnya dapat lebar penuh. -->
		<span class="flex items-start justify-between gap-2">
			<span class="min-w-0 font-mono text-sm font-extrabold text-gray-900 [overflow-wrap:anywhere]">{{ title }}</span>
			<slot />
		</span>
		<span class="block text-xs leading-snug">
			<span :class="principal ? 'font-semibold text-gray-700' : 'text-amber-600'">
				{{ principal || labels.svNoPrincipal }}
			</span>
			<span class="text-gray-500"><template v-for="m in meta.filter(Boolean)" :key="m"> · <span class="whitespace-nowrap">{{ m }}</span></template></span>
		</span>
		<span v-for="x in parties.filter((p) => p.v)" :key="x.k" class="block text-xs leading-snug">
			<span class="text-gray-400">{{ x.k }}</span> <span class="font-semibold text-gray-700">{{ x.v }}</span>
		</span>
		<span v-if="ids.filter(Boolean).length" class="mt-0.5 block text-[11px] leading-snug tabular-nums text-gray-400">
			<template v-for="(id, i) in ids.filter(Boolean)" :key="id"><template v-if="i"> · </template><span class="whitespace-nowrap">{{ id }}</span></template>
		</span>
	</span>
</template>

<script setup>
import { labels } from "@/utils/labels"

defineProps({
	title: { type: String, required: true },
	principal: { type: String, default: "" },
	meta: { type: Array, default: () => [] }, // teks setelah prinsipal
	parties: { type: Array, default: () => [] }, // [{ k, v }]
	ids: { type: Array, default: () => [] }, // nomor sistem
})
</script>
