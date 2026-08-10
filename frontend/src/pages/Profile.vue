<template>
	<div class="mx-auto w-full max-w-lg space-y-5 md:max-w-2xl">
		<!-- Identity hero — same shape as Home's greeting card so the two read as one app -->
		<section class="oak-card relative overflow-hidden animate-slide-up">
			<div class="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-brand-500 to-leaf-500"></div>
			<img
				:src="emblem"
				alt=""
				class="pointer-events-none absolute -right-6 -top-4 h-32 w-32 opacity-[0.06]"
			/>
			<div class="relative z-10 flex items-center gap-4 p-5">
				<span
					class="oak-icon-tile h-14 w-14 shrink-0 bg-brand-50 text-lg font-extrabold text-brand-700"
				>
					{{ initials }}
				</span>
				<div class="min-w-0 flex-1">
					<p class="oak-eyebrow">{{ labels.loggedInAs }}</p>
					<p class="mt-1 truncate text-xl font-extrabold tracking-tight text-gray-900">
						{{ fullName }}
					</p>
					<p class="mt-0.5 truncate text-sm text-gray-500">{{ email }}</p>
				</div>
			</div>
		</section>

		<!-- Branch scope — the same "empty selection means all branches" convention the
		     backend uses (user_branch.get_user_branches), spelled out rather than shown
		     as a blank list, which would read as "no access". -->
		<section class="space-y-2">
			<p class="oak-eyebrow flex items-center gap-1.5 px-1">
				<Icon name="map-pin" :size="14" /> {{ labels.profileBranchTitle }}
			</p>
			<div class="oak-card p-4">
				<p v-if="ctx?.all_branches" class="text-sm font-semibold text-gray-700">
					{{ labels.profileBranchAll }}
				</p>
				<div v-else-if="branches.length" class="flex flex-wrap gap-1.5">
					<span v-for="b in branches" :key="b" class="oak-chip bg-brand-50 text-brand-700">
						{{ b }}
					</span>
				</div>
				<div v-else class="oak-skeleton h-5 w-32 rounded"></div>
			</div>
		</section>

		<!-- Which menus this account may open. Straight off the same menu keys the bottom
		     bar and Home filter on, so what it lists is exactly what is reachable. -->
		<section class="space-y-2">
			<p class="oak-eyebrow flex items-center gap-1.5 px-1">
				<Icon name="grid" :size="14" /> {{ labels.profileAccessTitle }}
			</p>
			<div class="oak-card p-4">
				<div v-if="accessLabels.length" class="flex flex-wrap gap-1.5">
					<span v-for="m in accessLabels" :key="m" class="oak-chip bg-leaf-50 text-leaf-700">
						{{ m }}
					</span>
				</div>
				<p v-else-if="menu.ready" class="text-sm text-gray-400">{{ labels.profileAccessEmpty }}</p>
				<div v-else class="oak-skeleton h-5 w-40 rounded"></div>
				<p class="mt-2 text-xs text-gray-400">{{ labels.profileAccessHint }}</p>
			</div>
		</section>

		<!-- Roles, depot ones first: an account carries Frappe's automatic All/Guest/Desk
		     User too, and leading with those buries the one line that explains the access
		     above. -->
		<section class="space-y-2">
			<p class="oak-eyebrow flex items-center gap-1.5 px-1">
				<Icon name="shield" :size="14" /> {{ labels.profileRolesTitle }}
			</p>
			<div class="oak-card p-4">
				<div v-if="roles.length" class="flex flex-wrap gap-1.5">
					<span
						v-for="r in roles"
						:key="r.name"
						class="oak-chip"
						:class="r.builtin ? 'bg-gray-100 text-gray-500' : 'bg-amber-50 text-amber-700'"
					>
						{{ r.name }}
					</span>
				</div>
				<p v-else class="text-sm text-gray-400">{{ labels.profileRolesEmpty }}</p>
			</div>
		</section>

		<!-- Ubah password — collapsed by default, same tap-to-expand card Home uses for its
		     summary. A password form sitting open is visual weight on a page people mostly
		     open to check their access. -->
		<section class="space-y-2">
			<button
				type="button"
				@click="pwOpen = !pwOpen"
				:aria-expanded="pwOpen"
				class="oak-card oak-press flex w-full items-center gap-3 p-4 text-left"
			>
				<span class="oak-icon-tile h-10 w-10 bg-gray-100 text-gray-500">
					<Icon name="lock" :size="20" />
				</span>
				<div class="min-w-0 flex-1">
					<p class="font-bold text-gray-900">{{ labels.pwTitle }}</p>
					<p class="mt-0.5 text-xs text-gray-500">{{ labels.pwHint }}</p>
				</div>
				<Icon
					name="chevron-down"
					:size="20"
					class="shrink-0 text-gray-400 transition-transform duration-200"
					:class="pwOpen ? 'rotate-180' : ''"
				/>
			</button>

			<form v-if="pwOpen" class="oak-card space-y-3 p-4" @submit.prevent="submitPassword">
				<div>
					<label class="oak-label" for="pw-old">{{ labels.pwOld }}</label>
					<input
						id="pw-old"
						v-model="pwOld"
						class="oak-input"
						:type="pwReveal ? 'text' : 'password'"
						autocomplete="current-password"
					/>
				</div>
				<div>
					<label class="oak-label" for="pw-new">{{ labels.pwNew }}</label>
					<input
						id="pw-new"
						v-model="pwNew"
						class="oak-input"
						:type="pwReveal ? 'text' : 'password'"
						autocomplete="new-password"
					/>
				</div>
				<div>
					<label class="oak-label" for="pw-confirm">{{ labels.pwConfirm }}</label>
					<input
						id="pw-confirm"
						v-model="pwConfirm"
						class="oak-input"
						:type="pwReveal ? 'text' : 'password'"
						autocomplete="new-password"
					/>
				</div>
				<label class="flex items-center gap-2 text-sm text-gray-600">
					<input v-model="pwReveal" type="checkbox" class="h-4 w-4 rounded border-gray-300" />
					{{ labels.pwShow }}
				</label>
				<p v-if="pwError" class="text-sm font-medium text-red-600">{{ pwError }}</p>
				<button type="submit" class="oak-btn oak-btn-primary w-full" :disabled="pwSaving">
					<Icon name="check" :size="16" />
					{{ pwSaving ? labels.pwSaving : labels.pwSubmit }}
				</button>
			</form>
		</section>

		<!-- Actions. "Buka Desk" is a plain <a> — /desk is a different app, not a route. -->
		<section class="space-y-2">
			<a v-if="menu.deskAccess" href="/desk" class="oak-btn oak-btn-secondary w-full">
				<Icon name="external-link" :size="16" />
				{{ labels.openDesk }}
			</a>
			<button type="button" class="oak-btn oak-btn-ghost w-full text-gray-500" @click="session.logout()">
				<Icon name="log-out" :size="16" />
				{{ labels.logout }}
			</button>
		</section>
	</div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue"
import { session } from "@/data/session"
import { userContext } from "@/data/context"
import { fetchMenu, menu } from "@/data/menu"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
import Icon from "@/components/Icon.vue"
import emblem from "@/assets/oak-emblem.png"

onMounted(() => {
	if (!userContext.data) userContext.reload()
	fetchMenu()
})

const ctx = computed(() => userContext.data || null)
const email = computed(() => ctx.value?.user || session.user || "—")
const fullName = computed(() => ctx.value?.full_name || email.value)
const branches = computed(() => ctx.value?.branches || [])

const initials = computed(() => {
	const parts = String(fullName.value).trim().split(/\s+/).filter(Boolean)
	if (!parts.length) return "?"
	return (parts[0][0] + (parts[1]?.[0] || "")).toUpperCase()
})

// Roles Frappe attaches to every session; they say nothing about depot access, so they
// sort last and stay grey.
const BUILTIN_ROLES = new Set(["All", "Guest", "Desk User"])
const roles = computed(() =>
	[...(ctx.value?.roles || [])]
		.map((name) => ({ name, builtin: BUILTIN_ROLES.has(name) }))
		.sort((a, b) => a.builtin - b.builtin || a.name.localeCompare(b.name))
)

// Menu key -> the same title its Home tile uses, so one menu is never named two ways.
const MENU_LABELS = {
	gate: labels.gate,
	readyOut: labels.readyOutTitle,
	eir: labels.eir,
	cleaning: labels.cleaningTitle,
	mr: labels.mrTitleFull,
	periodicTest: labels.ptTitleFull,
	monitor: labels.monitorTitle,
	surveyPos: labels.surveyPosTitle,
	posFix: labels.posFixTitle,
}
const accessLabels = computed(() => menu.keys.map((k) => MENU_LABELS[k] || k))

// --- Ubah password ----------------------------------------------------------
// Posts to Frappe's own `update_password` rather than a wrapper of ours. That one
// endpoint already carries the password-strength policy, the `logout_on_password_reset`
// system setting and `last_password_reset_date`; re-implementing it here would be three
// chances to get security-relevant behaviour subtly wrong.
//
// It derives the account from `frappe.session.user` whenever `key` is absent, so a caller
// can only ever change their OWN password — and `old_password` is mandatory in that path
// (`_get_user_for_update_password` raises AuthenticationError on a wrong one). It also
// re-issues the session cookie on success, so the user is not kicked out of the PWA.
const pwOpen = ref(false)
const pwOld = ref("")
const pwNew = ref("")
const pwConfirm = ref("")
const pwReveal = ref(false)
const pwSaving = ref(false)
const pwError = ref("")

function resetPasswordForm() {
	pwOld.value = ""
	pwNew.value = ""
	pwConfirm.value = ""
	pwReveal.value = false
	pwError.value = ""
}

// Frappe reports validation failures (weak password, wrong old password) as
// `_server_messages` — a JSON array of JSON strings — and hard errors as `exception`.
// Anything unrecognised falls back to a generic line rather than dumping a traceback.
async function readFrappeError(res) {
	let body = null
	try {
		body = await res.json()
	} catch (e) {
		return res.status === 401 ? labels.pwWrongOld : labels.pwFailed
	}
	try {
		const msgs = JSON.parse(body?._server_messages || "[]").map((m) => {
			try {
				return JSON.parse(m).message
			} catch (e) {
				return m
			}
		})
		const text = msgs.filter(Boolean).join(" ")
		if (text) return text.replace(/<[^>]*>/g, "")
	} catch (e) {
		/* fall through */
	}
	if (res.status === 401) return labels.pwWrongOld
	return body?.exception || labels.pwFailed
}

async function submitPassword() {
	pwError.value = ""
	if (!pwOld.value || !pwNew.value || !pwConfirm.value) {
		pwError.value = labels.pwIncomplete
		return
	}
	if (pwNew.value !== pwConfirm.value) {
		pwError.value = labels.pwMismatch
		return
	}
	if (pwNew.value === pwOld.value) {
		pwError.value = labels.pwSame
		return
	}
	pwSaving.value = true
	try {
		const res = await fetch("/api/method/frappe.core.doctype.user.user.update_password", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Accept: "application/json",
				"X-Frappe-CSRF-Token": window.csrf_token || "",
			},
			body: JSON.stringify({
				old_password: pwOld.value,
				new_password: pwNew.value,
				logout_all_sessions: 0,
			}),
		})
		if (!res.ok) {
			pwError.value = await readFrappeError(res)
			return
		}
		resetPasswordForm()
		pwOpen.value = false
		toast.success(labels.pwSuccess)
	} catch (e) {
		pwError.value = labels.pwFailed
	} finally {
		pwSaving.value = false
	}
}
</script>
