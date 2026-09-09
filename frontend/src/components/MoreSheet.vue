<template>
	<teleport to="body">
		<div
			v-if="open"
			class="fixed inset-0 z-40 animate-fade-in bg-gray-900/40 backdrop-blur-[1px]"
			@click="close"
		></div>
		<section
			v-if="open"
			class="fixed inset-x-0 bottom-0 z-50 max-h-[86vh] animate-slide-up overflow-y-auto rounded-t-3xl bg-paper pb-safe-bottom shadow-soft"
			role="dialog"
			aria-modal="true"
		>
			<!-- The grab handle is the only affordance that says this pulls down; the sheet
			     covers the bottom bar it opened from, so without it there is nothing on screen
			     that looks dismissible. -->
			<button class="w-full pb-1 pt-2.5" :aria-label="labels.moreClose" @click="close">
				<span class="mx-auto block h-1 w-10 rounded-full bg-gray-300"></span>
			</button>

			<div class="space-y-5 px-4 pb-6 pt-2">
				<!-- Who this handset is logged in as. First thing in the sheet because a depot
				     phone changes hands between shifts, and the account is what everything below
				     it (menus, branch scope, notifications) hangs off. -->
				<router-link
					to="/profile"
					class="oak-card oak-press flex items-center gap-3 p-3"
					@click="close"
				>
					<img
						v-if="photoUrl"
						:src="photoUrl"
						alt=""
						class="h-11 w-11 shrink-0 rounded-full object-cover"
					/>
					<span
						v-else
						class="oak-icon-tile h-11 w-11 rounded-full bg-brand-50 text-sm font-extrabold text-brand-700"
					>
						{{ initials }}
					</span>
					<span class="min-w-0 flex-1">
						<span class="block truncate font-bold text-gray-900">{{ fullName }}</span>
						<span class="block truncate text-xs text-gray-500">{{ accountLine }}</span>
					</span>
					<span class="shrink-0 text-xs font-semibold text-brand-600">{{ labels.profileTitle }}</span>
				</router-link>

				<!-- Every module this account holds that the bottom bar had no room for. The bar
				     shows the few screens a shift is spent inside; this is the rest of the app,
				     and it is the only way to reach them without typing a URL. -->
				<div v-if="modules.length || editTabs">
					<div class="mb-2 flex items-center justify-between gap-2 px-1">
						<p class="text-xs font-semibold uppercase tracking-wide text-gray-400">
							{{ editTabs ? labels.navTabsTitle : labels.moreModules }}
						</p>
						<!-- Pengaturannya tinggal di sini, bukan di Profil: sheet inilah yang
						     dibuka justru pada saat modul yang dicari TIDAK ada di bar — momen
						     paling wajar untuk memindahkannya ke sana. -->
						<button
							v-if="!editTabs"
							class="oak-btn oak-btn-ghost px-2 py-1 text-xs"
							@click="startEditTabs"
						>
							<Icon name="sliders" :size="14" /> {{ labels.navTabsEdit }}
						</button>
						<span v-else class="text-[11px] font-bold" :class="draft.length ? 'text-brand-600' : 'text-gray-400'">
							{{ draft.length }}/{{ MAX_TABS }}
						</span>
					</div>

					<p v-if="editTabs" class="mb-3 px-1 text-[11px] leading-snug text-gray-500">
						{{ labels.navTabsHint }}
					</p>

					<!-- Mode pilih memakai grid yang SAMA, dan menampilkan seluruh modul akun ini —
					     termasuk yang sedang jadi tab. Kalau yang sudah terpasang disembunyikan
					     (seperti di mode biasa), tidak ada cara melepasnya lagi. Dua cabang, bukan
					     satu <component :is>: yang satu menavigasi, yang satu mencentang, dan
					     keduanya tidak berbagi apa pun selain tampilannya. -->
					<div class="grid grid-cols-4 gap-x-2 gap-y-4">
						<template v-if="editTabs">
							<button
								v-for="m in allModules"
								:key="m.key"
								type="button"
								class="oak-press flex flex-col items-center gap-1.5"
								:aria-pressed="draft.includes(m.key)"
								@click="toggleTab(m.key)"
							>
								<span class="relative">
									<span
										class="oak-icon-tile h-14 w-14 transition"
										:class="[m.tone, draft.includes(m.key) ? 'ring-2 ring-brand-500' : 'opacity-45']"
									>
										<Icon :name="m.icon" :size="22" />
									</span>
									<span
										v-if="draft.includes(m.key)"
										class="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-brand-600 text-white shadow"
									>
										<Icon name="check" :size="12" />
									</span>
								</span>
								<span
									class="text-center text-[11px] font-semibold leading-tight"
									:class="draft.includes(m.key) ? 'text-brand-700' : 'text-gray-500'"
								>
									{{ m.title }}
								</span>
							</button>
						</template>
						<router-link
							v-for="m in modules"
							v-else
							:key="m.to"
							:to="m.to"
							class="oak-press flex flex-col items-center gap-1.5"
							@click="close"
						>
							<span class="oak-icon-tile h-14 w-14" :class="m.tone">
								<Icon :name="m.icon" :size="22" />
							</span>
							<span class="text-center text-[11px] font-semibold leading-tight text-gray-600">
								{{ m.title }}
							</span>
						</router-link>
					</div>

					<div v-if="editTabs" class="mt-4 flex items-center gap-2">
						<button class="oak-btn oak-btn-secondary flex-1 py-2.5" @click="editTabs = false">
							{{ labels.navTabsCancel }}
						</button>
						<button class="oak-btn oak-btn-ghost shrink-0 px-3 py-2.5 text-xs" @click="resetDraft">
							{{ labels.navTabsReset }}
						</button>
						<button class="oak-btn oak-btn-primary flex-1 py-2.5" @click="saveTabs">
							{{ labels.navTabsSave }}
						</button>
					</div>
				</div>

				<!-- Terang / gelap / ikut HP. It sits in the sheet rather than on Profil because
				     it is the one setting an operator changes situationally — walking out of a
				     dim warehouse into daylight — and it must not be three taps deep. -->
				<div>
					<p class="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-gray-400">
						{{ labels.moreTheme }}
					</p>
					<div class="grid grid-cols-3 gap-2">
						<button
							v-for="opt in themeOptions"
							:key="opt.mode"
							class="oak-toggle flex items-center justify-center gap-1.5"
							:class="theme.mode === opt.mode ? 'oak-toggle-on' : 'oak-toggle-off'"
							@click="setTheme(opt.mode)"
						>
							<Icon :name="opt.icon" :size="15" />{{ opt.label }}
						</button>
					</div>
					<p v-if="theme.mode === 'system'" class="mt-1.5 px-1 text-[11px] text-gray-400">
						{{ labels.themeSystemHint }}
					</p>
				</div>

				<div>
					<p class="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-gray-400">
						{{ labels.moreAccount }}
					</p>
					<div class="oak-card divide-y divide-gray-100 overflow-hidden">
						<router-link
							to="/profile#akses"
							class="flex items-center gap-3 px-3.5 py-3 transition active:bg-gray-50"
							@click="close"
						>
							<span class="oak-icon-tile h-9 w-9 bg-gray-100 text-gray-500">
								<Icon name="users" :size="17" />
							</span>
							<span class="min-w-0 flex-1">
								<span class="block text-sm font-semibold text-gray-800">{{ labels.moreRoles }}</span>
								<span class="block truncate text-xs text-gray-500">{{ rolesLine }}</span>
							</span>
							<Icon name="chevron-right" :size="16" class="shrink-0 text-gray-300" />
						</router-link>

						<!-- Jalan pulang ke ERPNext untuk akun yang memegang keduanya. Tag <a> biasa,
						     bukan router-link: /desk aplikasi yang berbeda sama sekali. -->
						<a
							v-if="menu.deskAccess"
							href="/desk"
							class="flex items-center gap-3 px-3.5 py-3 transition active:bg-gray-50"
						>
							<span class="oak-icon-tile h-9 w-9 bg-brand-50 text-brand-600">
								<Icon name="external-link" :size="17" />
							</span>
							<span class="min-w-0 flex-1">
								<span class="block text-sm font-semibold text-gray-800">{{ labels.openDesk }}</span>
								<span class="block truncate text-xs text-gray-500">{{ labels.moreDeskHint }}</span>
							</span>
							<Icon name="chevron-right" :size="16" class="shrink-0 text-gray-300" />
						</a>

						<router-link
							to="/profile#pengaturan"
							class="flex items-center gap-3 px-3.5 py-3 transition active:bg-gray-50"
							@click="close"
						>
							<span class="oak-icon-tile h-9 w-9 bg-gray-100 text-gray-500">
								<Icon name="settings" :size="17" />
							</span>
							<span class="min-w-0 flex-1">
								<span class="block text-sm font-semibold text-gray-800">{{ labels.moreSettings }}</span>
								<span class="block truncate text-xs text-gray-500">{{ labels.moreSettingsHint }}</span>
							</span>
							<Icon name="chevron-right" :size="16" class="shrink-0 text-gray-300" />
						</router-link>

						<button
							class="flex w-full items-center gap-3 px-3.5 py-3 text-left transition active:bg-gray-50"
							@click="logout"
						>
							<span class="oak-icon-tile h-9 w-9 bg-red-50 text-red-600">
								<Icon name="log-out" :size="17" />
							</span>
							<span class="flex-1 text-sm font-semibold text-red-600">{{ labels.logout }}</span>
						</button>
					</div>
				</div>

				<p class="text-center text-[11px] text-gray-400">{{ footer }}</p>
			</div>
		</section>
	</teleport>
</template>

<script setup>
import { computed, ref, watch } from "vue"
import { session } from "@/data/session"
import { userContext } from "@/data/context"
import { menu } from "@/data/menu"
import { MODULES, modulesFor } from "@/data/modules"
import { MAX_TABS, pickedTabs, resetTabs, setTabs } from "@/utils/navTabs"
import { toast } from "@/utils/toast"
import { useDismissOnBack } from "@/utils/backstack"
import { setTheme, theme } from "@/utils/theme"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"

const props = defineProps({
	open: { type: Boolean, default: false },
	// Menu keys already shown as tabs in the bottom bar — those are not repeated here.
	exclude: { type: Array, default: () => [] },
})
const emit = defineEmits(["close"])

function close() {
	emit("close")
}
// Back is the only dismiss a handset has, and it must close the sheet rather than leave the
// page underneath it.
useDismissOnBack(
	computed(() => props.open),
	close
)

const ctx = computed(() => userContext.data || null)
const email = computed(() => ctx.value?.user || session.user || "—")
const fullName = computed(() => ctx.value?.full_name || email.value)
const photoUrl = computed(() => ctx.value?.user_image || "")
const roles = computed(() => ctx.value?.depot_roles || [])

const initials = computed(() => {
	const parts = String(fullName.value).trim().split(/\s+/).filter(Boolean)
	if (!parts.length) return "?"
	return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase()
})

const accountLine = computed(() => {
	const n = roles.value.length
	return n ? `${email.value} · ${labels.homeRoles.replace("{n}", n)}` : email.value
})

// Two names and a count, not ten chips: an SPV holds every depot role, and the row exists to
// confirm the account, not to enumerate it. The full list is on Profil.
const rolesLine = computed(() => {
	const r = roles.value
	if (!r.length) return labels.profileAccessEmpty
	const shown = r.slice(0, 2).join(", ")
	const rest = r.length - 2
	return rest > 0 ? `${shown}, ${labels.moreRolesRest.replace("{n}", rest)}` : shown
})

const themeOptions = [
	{ mode: "system", icon: "smartphone", label: labels.themeSystem },
	{ mode: "light", icon: "sun", label: labels.themeLight },
	{ mode: "dark", icon: "moon", label: labels.themeDark },
]

const modules = computed(() =>
	modulesFor(
		Object.keys(MODULES).filter((k) => !props.exclude.includes(k)),
		menu
	)
)

// --- Atur tab bawah -----------------------------------------------------------
// Yang dipilih hanya tiga slot tengah; Beranda dan Lainnya tidak pernah ikut daftar ini
// (lihat utils/navTabs.js). Pilihannya disunting sebagai draft supaya "Batal" benar-benar
// membatalkan — bar tidak berubah di belakang sheet setiap kali sebuah ikon diketuk.
const editTabs = ref(false)
const draft = ref([])
const allModules = computed(() => modulesFor(Object.keys(MODULES), menu))

function startEditTabs() {
	// Titik awalnya adalah bar yang sedang terlihat: `exclude` justru berisi kunci tab yang
	// sedang dipasang, jadi tidak perlu menebak apa pun.
	// Disalin, bukan dipakai langsung: draft harus bisa diubah tanpa menyentuh yang tersimpan.
	draft.value = [...(pickedTabs(session.user) || props.exclude.slice(0, MAX_TABS))]
	editTabs.value = true
}

function toggleTab(key) {
	const i = draft.value.indexOf(key)
	if (i !== -1) {
		draft.value = draft.value.filter((k) => k !== key)
		return
	}
	// Penuh: yang paling lama dipilih keluar, bukan ketukannya yang ditolak diam-diam.
	// Menolak tanpa penjelasan membuat layar terasa rusak; menggeser membuatnya terasa
	// seperti tiga kantong yang bisa diisi bergantian.
	draft.value = [...draft.value, key].slice(-MAX_TABS)
}

function resetDraft() {
	resetTabs(session.user)
	editTabs.value = false
	toast.success(labels.navTabsResetDone)
}

function saveTabs() {
	setTabs(session.user, draft.value)
	editTabs.value = false
	toast.success(labels.navTabsSaved)
}

// Sheet ditutup dengan mode pilih masih menyala → buka lagi harus bersih, bukan setengah
// jalan di draft kemarin.
watch(
	() => props.open,
	(open) => {
		if (!open) editTabs.value = false
	}
)

// Back keluar dari mode pilih dulu, baru menutup sheet. Didaftarkan BELAKANGAN dari
// dismisser sheet-nya, jadi ia yang di atas tumpukan selama mode pilih menyala — satu
// gesture, satu lapisan, sama seperti lapisan lain di aplikasi ini (utils/backstack.js).
useDismissOnBack(
	computed(() => props.open && editTabs.value),
	() => (editTabs.value = false)
)

// No version string: the app has no release number worth printing (package.json is 0.0.0),
// and a made-up one is worse than none. The host is the part that actually helps support —
// it says which site this handset is talking to.
const footer = `${labels.appName} · ${window.location.host}`

function logout() {
	close()
	session.logout()
}
</script>
