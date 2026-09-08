<template>
	<div class="mx-auto w-full max-w-lg space-y-5 md:max-w-2xl">
		<!-- Sapaan — siapa yang login, hari apa, dan berapa peran yang dipegang. Tanggal
		     dan shift ada di sini karena handset depot dipakai bergantian antar shift: baris
		     ini yang menjawab "HP ini sedang login sebagai siapa" tanpa membuka Profil. -->
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
			<section v-if="todayTiles.length || summaryRes.loading">
				<div class="mb-2 flex items-end justify-between px-1">
					<p class="oak-eyebrow">{{ labels.homeToday }}</p>
					<router-link v-if="menu.has('monitor')" to="/monitor" class="oak-link text-xs">
						{{ labels.homeTodayMonitor }}
					</router-link>
				</div>
				<div v-if="summaryRes.loading && !summary" class="grid grid-cols-2 gap-3">
					<div v-for="i in 4" :key="i" class="oak-card h-[86px] p-3.5">
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
import { computed, onMounted, ref } from "vue"
import { useRouter } from "vue-router"
import { session } from "@/data/session"
import { userContext } from "@/data/context"
import { cachedResource } from "@/data/cache"
import { fetchMenu, menu } from "@/data/menu"
import { GROUP_OPS, GROUP_YARD, modulesFor } from "@/data/modules"
import { labels } from "@/utils/labels"
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

// --- Sapaan: tanggal + shift ------------------------------------------------------
// Shift dibaca dari jam dinding, bukan dari roster: tidak ada doctype yang menyimpan
// jadwal shift, dan yang dibutuhkan baris ini cuma menyebut waktu kerja yang sedang
// berjalan supaya operator tahu HP ini menyapa hari yang benar.
const todayLine = computed(() => {
	const now = new Date()
	const date = new Intl.DateTimeFormat("id-ID", {
		weekday: "long",
		day: "numeric",
		month: "short",
		year: "numeric",
	}).format(now)
	const h = now.getHours()
	const shift = h < 12 ? labels.homeShiftMorning : h < 18 ? labels.homeShiftDay : labels.homeShiftNight
	return `${date} · ${shift}`
})

// --- Kotak cari -> Gate ------------------------------------------------------------
const query = ref("")
function goSearch() {
	const q = query.value.trim()
	if (!q) return
	router.push({ path: "/gate", query: { q } })
	query.value = ""
}

// --- Ringkasan beranda -------------------------------------------------------------
// Satu GET untuk kartu "Hari ini" + antrean "Menunggu Anda" (ess/home.py). Lewat
// cachedResource, jadi di titik mati sinyal beranda masih menampilkan angka terakhir
// alih-alih layar kosong — sama seperti setiap worklist di app ini.
const summaryRes = cachedResource({
	url: "container_depot.ess.home.get_home_summary",
	method: "GET",
	auto: true,
})
const summary = computed(() => summaryRes.data || null)

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

const todayTiles = computed(() => {
	const t = summary.value?.today
	if (!t) return []
	const out = []
	if (t.gate_in !== undefined) {
		out.push({
			key: "gateIn",
			icon: "log-in",
			text: "text-brand-500",
			label: labels.homeTileGateIn,
			value: t.gate_in,
			to: "/gate/history",
			...sub(t.eir_open, labels.homeTileGateInSub),
		})
		out.push({
			key: "gateOut",
			icon: "log-out",
			text: "text-leaf-500",
			label: labels.homeTileGateOut,
			value: t.gate_out,
			to: "/gate/history",
			...sub(t.booking_out, labels.homeTileGateOutSub),
		})
	}
	if (t.eir_review !== undefined) {
		const age = ageText(t.eir_review_age)
		out.push({
			key: "eirReview",
			icon: "clipboard",
			text: "text-amber-500",
			label: labels.homeTileEirReview,
			value: t.eir_review,
			to: "/eir",
			sub: t.eir_review ? (age ? fill(labels.homeTileEirReviewSub, { age }) : null) : labels.homeTileClear,
			subTone: t.eir_review ? "text-amber-600" : "text-gray-400",
		})
	}
	if (t.cleaning_open !== undefined) {
		out.push({
			key: "cleaning",
			icon: "droplet",
			text: "text-leaf-500",
			label: labels.homeTileCleaning,
			value: t.cleaning_open,
			to: "/cleaning",
			...sub(t.cleaning_idle, labels.homeTileCleaningSub),
		})
	}
	return out
})

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
	unlocated: { icon: "map-pin", tone: "bg-gray-100 text-gray-500", to: "/tank-position", many: labels.waitUnlocatedMany },
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
