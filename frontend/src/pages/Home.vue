<template>
	<div class="mx-auto w-full max-w-lg space-y-5 md:max-w-2xl">
		<!-- Sapaan — siapa yang login, hari apa, dan berapa peran yang dipegang. Tanggalnya
		     ada di sini karena handset depot dipakai bergantian antar shift: baris ini yang
		     menjawab "HP ini sedang login sebagai siapa" tanpa membuka Profil. -->
		<section class="oak-card animate-slide-up p-4">
			<div class="flex items-start justify-between gap-3">
				<div class="min-w-0">
					<p class="text-sm text-gray-500">{{ labels.greeting }},</p>
					<p class="truncate text-xl font-extrabold tracking-tight text-gray-900">
						{{ displayUser }}
					</p>
					<p class="mt-0.5 truncate text-xs text-gray-500">{{ todayLine }}</p>
				</div>
				<!-- Jumlahnya, bukan daftarnya: sepuluh chip peran memakan setengah layar dan
				     tidak ada yang membacanya. Rinciannya satu ketukan jauhnya, di Profil. -->
				<router-link
					v-if="roles.length"
					to="/profile"
					class="oak-chip oak-press shrink-0 bg-gray-100 text-gray-600"
				>
					<Icon name="users" :size="12" />{{ fill(labels.homeRoles, { n: roles.length }) }}
				</router-link>
			</div>
		</section>

		<!-- Kotak cari. Bukan pencarian global — apa pun yang diketik operator dari beranda
		     (kode booking, kode order, nomor tank) berujung di layar Gate, jadi kotak ini
		     mengoper kodenya ke sana dan hasilnya muncul di Gate lengkap dengan tombol
		     lanjutannya. Hanya untuk akun yang boleh membuka Gate. -->
		<form v-if="menu.has('gate')" class="flex gap-2" @submit.prevent="goSearch">
			<div class="relative flex-1">
				<Icon
					name="search"
					:size="18"
					class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
				/>
				<input
					v-model.trim="query"
					type="search"
					autocapitalize="characters"
					autocorrect="off"
					autocomplete="off"
					spellcheck="false"
					enterkeyhint="search"
					:placeholder="labels.homeSearchPlaceholder"
					class="oak-input h-11 pl-10 pr-3"
				/>
			</div>
			<!-- Tombol cari muncul begitu ada yang diketik. Enter / tombol "cari" di keyboard
			     sudah mengirim form ini, tapi di ponsel tombol itu tidak selalu terlihat sebagai
			     jalan keluar — jadi sediakan yang bisa ditekan, seperti di layar Gate. -->
			<button
				v-if="query"
				type="submit"
				class="oak-btn oak-btn-primary h-11 w-11 shrink-0 px-0"
				:aria-label="labels.homeSearchAria"
			>
				<Icon name="search" :size="18" />
			</button>
			<router-link
				to="/gate?scan=1"
				class="oak-btn oak-btn-secondary h-11 w-11 shrink-0 px-0"
				:aria-label="labels.homeScanAria"
			>
				<Icon name="maximize" :size="18" />
			</router-link>
		</form>

		<!-- Akun tanpa menu sama sekali: staf kantor, atau akun lapangan yang rolenya belum
		     diberikan. /depot memang terbuka untuk siapa pun yang punya sesi, jadi katakan
		     kenapa kosong daripada menampilkan halaman kosong yang terlihat rusak. -->
		<section v-if="menu.isEmpty" class="oak-card p-6 text-center">
			<span class="oak-icon-tile mx-auto h-12 w-12 bg-gray-100 text-gray-400">
				<Icon name="lock" :size="24" />
			</span>
			<p class="mt-3 font-bold text-gray-900">{{ labels.menuEmptyTitle }}</p>
			<p class="mt-1 text-sm text-gray-500">{{ labels.menuEmptyBody }}</p>
			<template v-if="menu.deskAccess">
				<a href="/desk" class="oak-btn oak-btn-primary mt-4">
					<Icon name="external-link" :size="16" />
					{{ labels.openDesk }}
				</a>
				<p class="mt-2 text-xs text-gray-400">{{ labels.openDeskHint }}</p>
			</template>
		</section>

		<template v-else>
			<!-- "Hari ini" — angka besar = yang sudah terjadi, sub-teks = sisa pekerjaan yang
			     menempel padanya. Sub-teks itulah alasan kartu ini ada; angka besarnya sendiri
			     tidak menyuruh siapa pun berbuat apa-apa. -->
			<section v-if="todayTiles.length || summaryRes.loading || editTiles">
				<div class="mb-2 flex items-end justify-between gap-2 px-1">
					<p class="oak-eyebrow">{{ editTiles ? labels.homeTilesTitle : labels.homeToday }}</p>
					<div class="flex shrink-0 items-center gap-3">
						<span
							v-if="editTiles"
							class="text-[11px] font-bold"
							:class="tileDraft.length ? 'text-brand-600' : 'text-gray-400'"
						>
							{{ tileDraft.length }}/{{ MAX_TILES }}
						</span>
						<template v-else>
							<!-- "Atur" hanya berarti sesuatu kalau memang ada yang bisa ditukar:
							     akun dengan satu kartu tidak punya pilihan untuk dibuat. -->
							<button v-if="availableTiles.length > 1" class="oak-link text-xs" @click="startEditTiles">
								{{ labels.homeTilesEdit }}
							</button>
							<router-link v-if="menu.has('monitor')" to="/monitor" class="oak-link text-xs">
								{{ labels.homeTodayMonitor }}
							</router-link>
						</template>
					</div>
				</div>

				<!-- Mode atur: SELURUH kartu yang boleh dilihat akun ini, dengan angkanya yang
				     sebenarnya (server diminta menghitung semuanya selama panel ini terbuka).
				     Memilih kartu tanpa melihat angkanya berarti memilih nama, dan nama tidak
				     memberitahu siapa pun angka mana yang penting buat pekerjaannya. -->
				<template v-if="editTiles">
					<p class="mb-2 px-1 text-[11px] leading-snug text-gray-500">{{ labels.homeTilesHint }}</p>
					<div class="grid grid-cols-2 gap-3">
						<button
							v-for="c in availableTiles"
							:key="c.key"
							type="button"
							class="oak-card oak-press relative p-3.5 text-left transition"
							:class="tileDraft.includes(c.key) ? 'border-brand-300 ring-2 ring-brand-500' : 'opacity-55'"
							:aria-pressed="tileDraft.includes(c.key)"
							@click="toggleTile(c.key)"
						>
							<p class="flex items-center gap-1.5 text-[11px] font-semibold text-gray-500">
								<Icon :name="c.icon" :size="13" :class="c.text" />
								<span class="truncate">{{ c.label }}</span>
							</p>
							<p class="mt-0.5 text-2xl font-extrabold leading-tight text-gray-900">{{ tileValue(c) }}</p>
							<span
								v-if="tileDraft.includes(c.key)"
								class="absolute right-2 top-2 flex h-5 w-5 items-center justify-center rounded-full bg-brand-600 text-white shadow"
							>
								<Icon name="check" :size="12" />
							</span>
						</button>
					</div>
					<div class="mt-3 flex items-center gap-2">
						<button class="oak-btn oak-btn-secondary flex-1 py-2.5" @click="editTiles = false">
							{{ labels.navTabsCancel }}
						</button>
						<button class="oak-btn oak-btn-ghost shrink-0 px-3 py-2.5 text-xs" @click="resetTilesToDefault">
							{{ labels.navTabsReset }}
						</button>
						<button class="oak-btn oak-btn-primary flex-1 py-2.5" @click="saveTiles">
							{{ labels.navTabsSave }}
						</button>
					</div>
				</template>

				<template v-else>
					<div v-if="summaryRes.loading && !summary" class="grid grid-cols-2 gap-3">
						<div v-for="i in tileKeys.length || 4" :key="i" class="oak-card h-[86px] p-3.5">
							<div class="oak-skeleton h-3 w-20"></div>
							<div class="oak-skeleton mt-2 h-6 w-10"></div>
							<div class="oak-skeleton mt-2 h-3 w-16"></div>
						</div>
					</div>
					<div v-else class="grid grid-cols-2 gap-3">
						<router-link
							v-for="t in todayTiles"
							:key="t.key"
							:to="t.to"
							class="oak-card oak-press p-3.5"
						>
							<p class="flex items-center gap-1.5 text-[11px] font-semibold text-gray-500">
								<Icon :name="t.icon" :size="13" :class="t.text" />
								<span class="truncate">{{ t.label }}</span>
							</p>
							<p class="mt-0.5 text-2xl font-extrabold leading-tight text-gray-900">{{ t.value }}</p>
							<p v-if="t.sub" class="truncate text-[11px] font-semibold" :class="t.subTone">
								{{ t.sub }}
							</p>
						</router-link>
					</div>
				</template>
			</section>

			<!-- "Menunggu Anda" — antrean yang sudah menunggu, tertua di atas. Umurnya yang
			     dipajang di kanan, bukan jumlahnya: tiga cleaning order yang baru dibuat
			     semenit lalu bukan masalah, satu yang menganggur sejak awal shift iya. -->
			<section v-if="summary">
				<div class="mb-2 flex items-end justify-between px-1">
					<p class="oak-eyebrow">{{ labels.homeWaiting }}</p>
					<p v-if="waiting.length" class="text-xs text-gray-400">
						{{ fill(labels.homeWaitingCount, { n: waiting.length }) }}
					</p>
				</div>
				<!-- Kosong tetap ditampilkan, tidak disembunyikan: "tidak ada yang menunggu"
				     adalah jawaban yang dicari operator di awal shift, dan bagian yang hilang
				     begitu saja terbaca seperti data yang belum termuat. -->
				<p v-if="!waiting.length" class="oak-card px-3.5 py-3 text-sm text-gray-400">
					{{ labels.homeWaitingEmpty }}
				</p>
				<div v-else class="oak-card divide-y divide-gray-100 overflow-hidden">
					<router-link
						v-for="w in waiting"
						:key="w.key"
						:to="w.to"
						class="flex items-center gap-3 px-3.5 py-3 transition active:bg-gray-50"
					>
						<span class="oak-icon-tile h-9 w-9" :class="w.tone">
							<Icon :name="w.icon" :size="17" />
						</span>
						<p class="min-w-0 flex-1 text-sm font-semibold text-gray-800">{{ w.text }}</p>
						<span v-if="w.ageText" class="shrink-0 text-[11px] text-gray-400">{{ w.ageText }}</span>
						<Icon name="chevron-right" :size="16" class="shrink-0 text-gray-300" />
					</router-link>
				</div>
			</section>

			<!-- Pintasan menu. Dua kelompok, bukan enam: yang dikerjakan per dokumen
			     (Operasional) dan yang dikerjakan per tank di lapangan (Yard). -->
			<section v-for="g in menuGroups" :key="g.title">
				<p class="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-gray-400">
					{{ g.title }}
				</p>
				<div class="grid grid-cols-4 gap-x-2 gap-y-4">
					<router-link
						v-for="m in g.items"
						:key="m.to"
						:to="m.to"
						class="oak-press flex flex-col items-center gap-1.5"
					>
						<span class="oak-icon-tile h-14 w-14" :class="m.tone">
							<Icon :name="m.icon" :size="22" />
						</span>
						<span class="text-center text-[11px] font-semibold leading-tight text-gray-600">
							{{ m.title }}
						</span>
					</router-link>
				</div>
			</section>

			<!-- Riwayat — satu chip per menu utama yang boleh dibuka akun ini. Chip, bukan
			     kartu: ini jalan ke belakang, dan tidak boleh memakan ruang sebanyak pekerjaan
			     yang sedang berjalan. -->
			<section v-if="history.length">
				<p class="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-gray-400">
					{{ labels.homeGroupHistory }}
				</p>
				<div class="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1">
					<router-link
						v-for="h in history"
						:key="h.to"
						:to="h.to"
						class="oak-card oak-press flex shrink-0 items-center gap-1.5 px-3 py-2 text-xs font-semibold text-gray-600"
					>
						<Icon :name="h.icon" :size="14" class="text-gray-400" />{{ h.title }}
					</router-link>
				</div>
			</section>
		</template>
	</div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue"
import { useRouter } from "vue-router"
import { session } from "@/data/session"
import { userContext } from "@/data/context"
import { cachedResource } from "@/data/cache"
import { fetchMenu, menu } from "@/data/menu"
import { GROUP_OPS, GROUP_YARD, modulesFor } from "@/data/modules"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
import {
	DEFAULT_TILES,
	MAX_TILES,
	pickedTiles,
	resetTiles,
	setTiles,
} from "@/utils/homeTiles"
import Icon from "@/components/Icon.vue"

const router = useRouter()

onMounted(() => {
	// Confirms the logged-in user server-side and carries the name + depot roles the
	// greeting shows, in the one call /profile already makes.
	if (session.isLoggedIn && !userContext.data) userContext.reload()
	// Which menus this account may open. Cached after the first call, so the router
	// guard and this page share one request.
	fetchMenu()
})

const ctx = computed(() => userContext.data || null)
const displayUser = computed(() => ctx.value?.full_name || session.user || "—")
// Peran depot saja — server sudah membuang All / Guest / Desk User dan role ERPNext yang
// ikut menempel (ess.context.depot_roles).
const roles = computed(() => ctx.value?.depot_roles || [])

// `{n}` / `{ref}` / `{age}` — pola isian yang sama dipakai di seluruh labels.js.
function fill(tpl, vars) {
	return Object.entries(vars).reduce((s, [k, v]) => s.replace(`{${k}}`, v), tpl)
}

// --- Sapaan: tanggal + jam ----------------------------------------------------------
// Sempat ada "Shift pagi/siang/malam" di sini, ditebak dari jam HP. Dihapus: depot tidak
// menyimpan jadwal shift di mana pun, jadi angka 12 dan 18 itu tebakan yang ikut zona waktu
// handset — tulisan yang terlihat resmi padahal tidak dijamin siapa-siapa. Jamnya sendiri
// tidak mengaku tahu apa-apa selain jam, jadi itu yang tinggal.
//
// Dan jam itu HARUS berdetak. Beranda adalah layar yang ditinggal terbuka berjam-jam di
// handset yang dipakai bergantian; jam yang beku sejak layar dibuka bukan cuma basi, ia
// berbohong dengan meyakinkan. Setengah menit sekali sudah cukup halus untuk tampilan
// jam-menit dan tetap murah — satu penulisan ref, tanpa permintaan ke server.
const now = ref(new Date())
let clock = null
onMounted(() => {
	clock = setInterval(() => (now.value = new Date()), 30_000)
})
onUnmounted(() => clearInterval(clock))

const todayLine = computed(() => {
	const d = new Intl.DateTimeFormat("id-ID", {
		weekday: "long",
		day: "numeric",
		month: "short",
		year: "numeric",
	}).format(now.value)
	const t = new Intl.DateTimeFormat("id-ID", {
		hour: "2-digit",
		minute: "2-digit",
	}).format(now.value)
	return `${d} · ${t}`
})

// --- Kotak cari -> Gate ------------------------------------------------------------
const query = ref("")
function goSearch() {
	const q = query.value.trim()
	if (!q) return
	router.push({ path: "/gate", query: { q } })
	query.value = ""
}


function ageText(min) {
	if (min === null || min === undefined) return ""
	if (min < 1) return labels.ageNow
	if (min < 60) return fill(labels.ageMinutes, { n: min })
	if (min < 60 * 24) return fill(labels.ageHours, { n: Math.floor(min / 60) })
	return fill(labels.ageDays, { n: Math.floor(min / (60 * 24)) })
}

// Sub-teks kartu: sisa pekerjaan bila ada, "beres semua" bila nol, dan TIDAK ADA bila
// angkanya memang tidak dikirim server (menu yang bersangkutan tidak dipegang akun ini).
function sub(count, tpl) {
	if (count === undefined || count === null) return { sub: null, subTone: "" }
	if (!count) return { sub: labels.homeTileClear, subTone: "text-gray-400" }
	return { sub: fill(tpl, { n: count }), subTone: "text-brand-600" }
}

// Katalog kartu "Hari ini" — satu-dua per menu, semuanya tersedia untuk dipilih. `menu`
// adalah kunci permission yang menjaganya (sama dengan yang dipakai bar bawah), `value`
// membaca angka yang dikirim ess/home.py, dan `sub` kalimat kecil di bawahnya: sisa
// pekerjaan yang menempel pada angka besar itu. Sub-teks itulah alasan kartunya ada —
// angka besarnya sendiri tidak menyuruh siapa pun berbuat apa-apa.
//
// Urutan di sini adalah urutan yang tampil di pengaturan, dan sengaja mengikuti urutan
// modul di data/modules.js supaya operator menemukannya di tempat yang sama.
const TILE_CATALOG = [
	{
		key: "gateIn", menu: "gate", icon: "log-in", text: "text-brand-500",
		label: labels.homeTileGateIn, to: "/gate/history",
		value: (t) => t.gate_in, sub: (t) => sub(t.eir_open, labels.homeTileGateInSub),
	},
	{
		key: "gateOut", menu: "gate", icon: "log-out", text: "text-leaf-500",
		label: labels.homeTileGateOut, to: "/gate/history",
		value: (t) => t.gate_out, sub: (t) => sub(t.booking_out, labels.homeTileGateOutSub),
	},
	{
		key: "eirOpen", menu: "eir", icon: "clipboard", text: "text-brand-500",
		label: labels.homeTileEirOpen, to: "/eir",
		value: (t) => t.eir_open, sub: (t) => sub(t.eir_out, labels.homeTileEirOpenSub),
	},
	{
		key: "eirReview", menu: "eir", icon: "clipboard", text: "text-amber-500",
		label: labels.homeTileEirReview, to: "/eir",
		value: (t) => t.eir_review,
		// Umur yang tertua, bukan jumlahnya: satu EIR yang menunggu sejak awal shift lebih
		// mendesak daripada tiga yang baru dikirim semenit lalu.
		sub: (t) => {
			const age = ageText(t.eir_review_age)
			return {
				sub: t.eir_review ? (age ? fill(labels.homeTileEirReviewSub, { age }) : null) : labels.homeTileClear,
				subTone: t.eir_review ? "text-amber-600" : "text-gray-400",
			}
		},
	},
	{
		key: "cleaning", menu: "cleaning", icon: "droplet", text: "text-leaf-500",
		label: labels.homeTileCleaning, to: "/cleaning",
		value: (t) => t.cleaning_open, sub: (t) => sub(t.cleaning_idle, labels.homeTileCleaningSub),
	},
	{
		key: "mr", menu: "mr", icon: "tool", text: "text-amber-500",
		label: labels.homeTileMr, to: "/mr",
		value: (t) => t.mr_open, sub: (t) => sub(t.mr_approval, labels.homeTileMrSub),
	},
	{
		key: "monitor", menu: "monitor", icon: "grid", text: "text-brand-500",
		label: labels.homeTileMonitor, to: "/monitor",
		value: (t) => t.depot_total, sub: () => ({ sub: labels.homeTileMonitorSub, subTone: "text-gray-400" }),
	},
	{
		key: "schedule", menu: "schedule", icon: "calendar", text: "text-brand-500",
		label: labels.homeTileSchedule, to: "/schedule",
		value: (t) => t.schedule_today, sub: (t) => sub(t.schedule_open, labels.homeTileScheduleSub),
	},
	{
		key: "survey", menu: "surveyList", icon: "list", text: "text-brand-500",
		label: labels.homeTileSurvey, to: "/survey-orders",
		value: (t) => t.survey_today, sub: () => ({ sub: null, subTone: "" }),
	},
	{
		key: "lowering", menu: "posFix", icon: "arrow-down-circle", text: "text-leaf-500",
		label: labels.homeTileLowering, to: "/position-fix",
		value: (t) => t.lowering, sub: (t) => sub(t.lowering, labels.homeTileLoweringSub),
	},
	{
		key: "unlocated", menu: "tankPos", icon: "map-pin", text: "text-amber-500",
		label: labels.homeTileUnlocated, to: "/tank-position",
		value: (t) => t.unlocated, sub: (t) => sub(t.unlocated, labels.homeTileUnlocatedSub),
	},
]

// Kartu yang boleh dilihat akun ini. Permission tetap yang berkuasa: pilihan operator hanya
// menentukan urutan dan jumlah, tidak pernah membuka kartu yang menunya tidak dipegang.
const availableTiles = computed(() => TILE_CATALOG.filter((c) => menu.has(c.menu)))

// Kunci kartu yang aktif — pilihan operator, atau empat bawaan kalau ia belum pernah
// memilih. Inilah yang dikirim ke server sebagai `tiles`, jadi yang tidak tampil tidak
// pernah dihitung.
const tileKeys = computed(() => {
	const picked = pickedTiles(session.user) || DEFAULT_TILES
	const allowed = new Set(availableTiles.value.map((c) => c.key))
	return picked.filter((k) => allowed.has(k)).slice(0, MAX_TILES)
})

// Panel "atur kartu". Disunting sebagai draft supaya "Batal" benar-benar membatalkan, dan
// supaya beranda tidak memuat ulang angkanya setiap satu ikon diketuk. Dideklarasikan DI
// ATAS resource di bawah: `auto: true` menembakkan GET pertamanya saat resource dibuat, dan
// makeParams-nya membaca keduanya.
const editTiles = ref(false)
const tileDraft = ref([])

// Angka mana yang diminta ke server. Selama panel atur terbuka: semuanya, supaya tiap kartu
// bisa dipilih sambil melihat angkanya. Selebihnya: hanya yang tampil.
const wantedTiles = computed(() =>
	editTiles.value ? availableTiles.value.map((c) => c.key) : tileKeys.value
)

// --- Ringkasan beranda -------------------------------------------------------------
// Satu GET untuk kartu "Hari ini" + antrean "Menunggu Anda" (ess/home.py). Lewat
// cachedResource, jadi di titik mati sinyal beranda masih menampilkan angka terakhir
// alih-alih layar kosong — sama seperti setiap worklist di app ini.
const summaryRes = cachedResource({
	url: "container_depot.ess.home.get_home_summary",
	method: "GET",
	// Kartu yang dipilih operator ikut ke server: yang tidak tampil tidak dihitung sama
	// sekali (lihat _wanted_tiles di ess/home.py). Ia juga jadi bagian kunci cache, jadi
	// mengubah pilihan tidak menampilkan angka milik susunan yang lama.
	makeParams: () => ({ tiles: wantedTiles.value.join(",") || undefined }),
	auto: true,
})
const summary = computed(() => summaryRes.data || null)

const todayTiles = computed(() => {
	const t = summary.value?.today
	if (!t) return []
	return tileKeys.value
		.map((key) => {
			const c = availableTiles.value.find((x) => x.key === key)
			if (!c) return null
			const value = c.value(t)
			// Angka yang tidak dikirim server = kartu yang tidak boleh digambar. Terjadi
			// sesaat setelah pilihan berubah, sebelum GET berikutnya mendarat.
			if (value === undefined) return null
			return { key: c.key, icon: c.icon, text: c.text, label: c.label, to: c.to, value, ...c.sub(t) }
		})
		.filter(Boolean)
})

// --- Atur kartu ---------------------------------------------------------------------
function startEditTiles() {
	tileDraft.value = [...tileKeys.value]
	editTiles.value = true
}
function toggleTile(key) {
	if (tileDraft.value.includes(key)) {
		tileDraft.value = tileDraft.value.filter((k) => k !== key)
		return
	}
	// Penuh: yang paling lama dipilih keluar, bukan ketukannya yang ditolak diam-diam.
	tileDraft.value = [...tileDraft.value, key].slice(-MAX_TILES)
}
function saveTiles() {
	setTiles(session.user, tileDraft.value)
	editTiles.value = false
	toast.success(labels.homeTilesSaved)
}
function resetTilesToDefault() {
	resetTiles(session.user)
	editTiles.value = false
	toast.success(labels.homeTilesResetDone)
}

watch(wantedTiles, (now, before) => {
	if (now.join(",") !== (before || []).join(",")) summaryRes.reload()
})

/** Angka satu kartu di panel atur — "—" selagi GET yang lebih lengkap belum mendarat. */
function tileValue(c) {
	const t = summary.value?.today
	const v = t ? c.value(t) : undefined
	return v === undefined || v === null ? "—" : v
}

// Satu entri per kunci antrean yang dikirim ess/home.py. Kalimatnya dua versi: yang
// menyebut tank (antrean berisi satu) dan yang menyebut jumlah — server hanya mengirim
// `ref` ketika antreannya memang tinggal satu.
const WAIT = {
	eirReview: { icon: "clipboard", tone: "bg-amber-50 text-amber-600", to: "/eir", one: labels.waitEirReviewOne, many: labels.waitEirReviewMany },
	eirOpen: { icon: "clipboard", tone: "bg-brand-50 text-brand-600", to: "/eir", one: labels.waitEirOpenOne, many: labels.waitEirOpenMany },
	eirOut: { icon: "log-out", tone: "bg-brand-50 text-brand-600", to: "/eir", many: labels.waitEirOutMany },
	cleaningIdle: { icon: "droplet", tone: "bg-leaf-50 text-leaf-600", to: "/cleaning", one: labels.waitCleaningIdleOne, many: labels.waitCleaningIdleMany },
	mrApproval: { icon: "tool", tone: "bg-amber-50 text-amber-600", to: "/mr", one: labels.waitMrApprovalOne, many: labels.waitMrApprovalMany },
	bookingGate: { icon: "log-in", tone: "bg-brand-50 text-brand-600", to: "/gate", one: labels.waitBookingGateOne, many: labels.waitBookingGateMany },
	lowering: { icon: "arrow-down-circle", tone: "bg-leaf-50 text-leaf-600", to: "/position-fix", many: labels.waitLoweringMany },
	surveyReady: { icon: "list", tone: "bg-leaf-50 text-leaf-600", to: "/survey-orders", many: labels.waitSurveyReadyMany },
	// Bukan "tank tanpa letak" (itu ratusan dan tidak ada tenggatnya) — hanya yang surveinya
	// sudah dijadwalkan. Warnanya ikut keluarga yard, bukan abu: ini pekerjaan, bukan catatan.
	positionOrder: { icon: "map-pin", tone: "bg-leaf-50 text-leaf-600", to: "/tank-position", many: labels.waitPositionOrderMany },
	cleaningReview: { icon: "droplet", tone: "bg-sky-50 text-sky-600", to: "/cleaning", one: labels.waitCleaningReviewOne, many: labels.waitCleaningReviewMany },
	mrReview: { icon: "tool", tone: "bg-sky-50 text-sky-600", to: "/mr", one: labels.waitMrReviewOne, many: labels.waitMrReviewMany },
	// Warna amber, bukan biru: yang lain menunggu giliran, yang ini sudah lewat waktunya.
	scheduleOverdue: { icon: "calendar", tone: "bg-amber-50 text-amber-600", to: "/schedule", many: labels.waitScheduleOverdueMany },
}
const waiting = computed(() =>
	(summary.value?.waiting || [])
		.map((w) => {
			const def = WAIT[w.key]
			if (!def) return null // kunci baru dari server yang belum punya kalimat di sini
			const tpl = w.ref && def.one ? def.one : def.many
			return {
				key: w.key,
				icon: def.icon,
				tone: def.tone,
				to: def.to,
				text: fill(tpl, { n: w.count, ref: w.ref || "" }),
				ageText: ageText(w.age),
			}
		})
		.filter(Boolean)
)

// --- Pintasan menu -----------------------------------------------------------------
// Katalog modul bersama (data/modules.js): bar bawah dan sheet "Lainnya" menggambar dari
// daftar yang sama, jadi tidak ada modul yang hilang dari salah satu permukaan saja.
const allMenuGroups = [
	{ title: labels.homeGroupOps, keys: GROUP_OPS },
	// Letak Tank duduk di Yard, bukan di Survey: ia SATU-SATUNYA yang menulis lokasi terkini
	// di master Container, dipakai kapan saja tanpa perlu ada job — dan justru itu yang
	// membuat Survey Order bisa mempercayainya.
	{ title: labels.homeGroupYard, keys: GROUP_YARD },
]

// Buang tile yang tidak boleh dibuka akun ini, lalu buang kelompok yang jadi kosong —
// judul di atas grid kosong terbaca seperti bug loading.
const menuGroups = computed(() =>
	allMenuGroups
		.map((g) => ({ ...g, items: modulesFor(g.keys, menu) }))
		.filter((g) => g.items.length)
)

// Riwayat menumpang kunci menu utamanya, jadi akun yang tidak boleh membuka M&R juga
// tidak bisa menelusuri riwayat M&R.
const allHistory = [
	{ key: "gate", to: "/gate/history", icon: "log-in", title: labels.navGate },
	{ key: "eir", to: "/eir/history", icon: "clipboard", title: labels.navEir },
	{ key: "cleaning", to: "/cleaning/history", icon: "droplet", title: labels.navCleaning },
	{ key: "mr", to: "/mr/history", icon: "tool", title: labels.navMr },
	// Satu-satunya Riwayat dengan dua pemilik: ia memuat kedua sisi alur survey posisi.
	{ keys: ["surveyList", "surveyPos", "posFix"], to: "/survey-orders/history", icon: "map-pin", title: labels.navSurveyList },
	{ key: "monitor", to: "/monitor/history", icon: "activity", title: labels.navMonitor },
]
const history = computed(() =>
	allHistory.filter((h) => (h.keys || [h.key]).some((k) => menu.has(k)))
)
</script>
