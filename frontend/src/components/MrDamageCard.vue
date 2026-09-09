<template>
	<div class="flex gap-3 rounded-xl border border-gray-100 p-3">
		<!-- Foto duluan, teks belakangan. Temuan kerusakan dibaca dengan mata: operator
		     mencocokkan gambar di layar dengan penyok yang ada di depannya, lalu baru membaca
		     kodenya untuk memastikan. Kalau tidak ada fotonya, kotaknya tetap ada supaya
		     barisan temuan tidak bergeser-geser. -->
		<button
			v-if="photos.length"
			type="button"
			class="oak-press h-16 w-16 shrink-0"
			@click="openLightbox(photos, 0)"
		>
			<img :src="photos[0]" class="h-full w-full rounded-lg border border-gray-200 object-cover" />
			<span
				v-if="photos.length > 1"
				class="-mt-5 ml-auto mr-1 block w-fit rounded bg-black/60 px-1 text-[10px] font-semibold text-white"
			>+{{ photos.length - 1 }}</span>
		</button>
		<span
			v-else
			class="flex h-16 w-16 shrink-0 items-center justify-center rounded-lg border border-dashed border-gray-200 text-[10px] text-gray-300"
		>
			<Icon name="image" :size="18" />
		</span>

		<div class="min-w-0 flex-1 space-y-1.5">
			<p class="truncate font-semibold text-gray-900">{{ damage.component || damage.area || "—" }}</p>
			<div class="flex flex-wrap gap-1.5 text-[11px]">
				<span v-if="damage.area && damage.component" class="oak-chip bg-gray-100 text-gray-600">
					{{ labels.mrLocation }} {{ damage.area }}
				</span>
				<span v-if="damage.damage_code" class="oak-chip bg-red-50 text-red-700">
					{{ labels.mrCodeDamage }} {{ damage.damage_code }}<span v-if="damage.damage_desc"> · {{ damage.damage_desc }}</span>
				</span>
				<span v-if="damage.repair_code" class="oak-chip bg-blue-50 text-blue-700">
					{{ labels.mrCodeRepair }} {{ damage.repair_code }}<span v-if="damage.repair_desc"> · {{ damage.repair_desc }}</span>
				</span>
			</div>
			<p v-if="damage.damage_description" class="text-sm text-gray-600">{{ damage.damage_description }}</p>
		</div>
	</div>
</template>

<script setup>
// Satu temuan kerusakan yang disalin dari EIR — read-only di mana pun ia muncul.
//
// Satu komponen, bukan tiga salinan: kartu ini dibaca di layar order (sebelum mulai), di
// bawah lipatan "Temuan EIR" pada form kerja, dan di Riwayat. Markupnya memang pernah
// disalin dua kali dan langsung berselisih — yang satu punya foto, yang lain tidak.
import { computed } from "vue"

import { labels } from "@/utils/labels"
import { openLightbox } from "@/utils/lightbox"
import Icon from "@/components/Icon.vue"

const props = defineProps({
	// Satu baris `damages[]` dari `mr_order_detail`.
	damage: { type: Object, required: true },
})

const photos = computed(() => props.damage.photos || [])
</script>
