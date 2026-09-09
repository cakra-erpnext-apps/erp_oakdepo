<template>
	<!-- Bar batch: satu-satunya hal di layar yang tahu ada pekerjaan lain selain tank yang
	     sedang dibuka. Menempel di bawah app bar, dan tingginya diumumkan sebagai
	     --oak-nav-h supaya header form parkir di bawahnya, bukan di atasnya (lihat
	     .oak-subheader-stacked di main.css). -->
	<div ref="bar" class="oak-subheader -mx-4 bg-brand-100 px-1.5 py-1.5 text-brand-900">
		<div class="flex items-center gap-1">
			<!-- ◀ / ▶ dibuat selebar dan setinggi jempol (56 × 48), berpermukaan sendiri.
			     Sebelumnya keduanya cuma 36 px di tepi bar sementara judul di tengah
			     mengambil SISA lebar layar sebagai area sentuh — jadi setiap pindah tank
			     berakhir membuka sheet daftar batch. -->
			<button
				class="oak-press flex h-12 w-14 shrink-0 items-center justify-center rounded-xl bg-brand-900/5 text-brand-900/80 active:bg-brand-900/10 disabled:opacity-30"
				:aria-label="labels.eirNavPrev"
				:disabled="queue.length < 2"
				@click="emit('prev')"
			>
				<Icon name="chevron-left" :size="22" />
			</button>

			<!-- Pembungkus ini TIDAK bisa ditekan, dan itu gunanya: ia menyisakan jarak mati
			     di kiri-kanan judul supaya jempol yang meleset dari panah mendarat di ruang
			     kosong, bukan di sheet. Yang bisa ditekan hanya tombol judul selebar isinya. -->
			<div class="flex min-w-0 flex-1 justify-center px-2">
				<!-- Judulnya sebuah tombol: daftar isi batch tidak punya tempat lain untuk
				     hidup, dan nomor tank adalah hal yang paling sering ditatap di layar ini. -->
				<!-- max-w-[62%] bukan hiasan: tanpa batas ini judul melar mengikuti panjang nomor
				     bon dan memakan lagi ruang mati yang baru saja dibuat. Nomor bon-nya boleh
				     terpotong — versi lengkapnya ada di kepala sheet dan di kartu Voucher
				     Referensi satu langkah di bawah. -->
				<button class="oak-press min-w-0 max-w-[62%] rounded-lg px-2 py-1 text-center" @click="emit('open')">
					<span class="block truncate font-mono text-sm font-extrabold leading-tight">
						{{ active?.container_no || active?.container || "—" }}
					</span>
					<span class="block truncate text-[11px] leading-tight text-brand-900/70">
						{{ labels.eirBadge }} {{ activeIndex + 1 }} {{ labels.eirBatchOf }} {{ queue.length }}
						<template v-if="voucher"> · {{ labels.eirBatchWord }} {{ voucher }}</template>
					</span>
				</button>
			</div>

			<button
				class="oak-press flex h-12 w-14 shrink-0 items-center justify-center rounded-xl bg-brand-900/5 text-brand-900/80 active:bg-brand-900/10 disabled:opacity-30"
				:aria-label="labels.eirNavNext"
				:disabled="queue.length < 2"
				@click="emit('next')"
			>
				<Icon name="chevron-right" :size="22" />
			</button>
		</div>

		<!-- Satu setrip per EIR: hijau sudah dikirim, oranye sedang/pernah dikerjakan, abu
		     belum disentuh. Menjawab "tinggal berapa lagi" tanpa membuka apa pun. Keluar dari
		     tombol judul supaya area sentuhnya tidak ikut melebar — ini penanda, bukan kontrol. -->
		<div class="mt-1 flex items-center justify-center gap-1">
			<span
				v-for="(r, i) in queue"
				:key="r.name"
				class="h-1 w-5 rounded-full"
				:class="[dashTone(r), i === activeIndex ? 'opacity-100' : 'opacity-60']"
			></span>
		</div>
	</div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"

const props = defineProps({
	// Baris worklist anggota batch, urut seperti di sheet. `sent` diisi pemanggil dari
	// catatan kiriman batch — baris yang sudah dikirim sudah tidak ada di worklist.
	queue: { type: Array, default: () => [] },
	activeIndex: { type: Number, default: 0 },
	voucher: { type: String, default: "" },
})
const emit = defineEmits(["prev", "next", "open"])

const active = computed(() => props.queue[props.activeIndex] || null)

function dashTone(r) {
	if (r.sent) return "bg-leaf-500"
	if (r.work_started_on) return "bg-brand-500"
	return "bg-brand-900/25"
}

// Tinggi bar ini diumumkan ke seluruh halaman (lihat komentar di template). Nol saat bar
// hilang, bukan "tidak diset", supaya header form kembali rapat ke app bar seketika.
const bar = ref(null)
let ro = null
function publish(px) {
	document.documentElement.style.setProperty("--oak-nav-h", `${px}px`)
}
watch(
	bar,
	(el) => {
		ro?.disconnect()
		ro = null
		if (!el || typeof ResizeObserver === "undefined") {
			publish(0)
			return
		}
		ro = new ResizeObserver(([entry]) => {
			const h = entry.borderBoxSize?.[0]?.blockSize ?? entry.target.getBoundingClientRect().height
			publish(Math.round(h))
		})
		ro.observe(el)
	},
	{ flush: "post" }
)
onBeforeUnmount(() => {
	ro?.disconnect()
	publish(0)
})
</script>
