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
				<!-- Tap the avatar to replace it. A separate "ganti foto" button would be one
				     more thing on a screen people open to check their access; the picture is
				     the affordance, with the camera badge saying so. -->
				<button
					type="button"
					class="oak-press relative h-14 w-14 shrink-0 rounded-2xl"
					:disabled="photoBusy"
					:aria-label="labels.profilePhotoChange"
					@click="photoInput?.click()"
				>
					<img
						v-if="photoUrl"
						:src="photoUrl"
						alt=""
						class="h-14 w-14 rounded-2xl object-cover"
					/>
					<span
						v-else
						class="oak-icon-tile h-14 w-14 bg-brand-50 text-lg font-extrabold text-brand-700"
					>
						{{ initials }}
					</span>
					<span
						class="absolute -bottom-1 -right-1 flex h-6 w-6 items-center justify-center rounded-full border-2 border-white bg-brand-500 text-white"
					>
						<Icon :name="photoBusy ? 'loader' : 'camera'" :size="12" :class="photoBusy ? 'animate-spin' : ''" />
					</span>
				</button>
				<input
					ref="photoInput"
					type="file"
					accept="image/jpeg,image/png,image/webp"
					class="hidden"
					@change="onPhotoPick"
				/>
				<div class="min-w-0 flex-1">
					<p class="oak-eyebrow">{{ labels.loggedInAs }}</p>
					<p class="mt-1 truncate text-xl font-extrabold tracking-tight text-gray-900">
						{{ fullName }}
					</p>
					<p class="mt-0.5 truncate text-sm text-gray-500">{{ email }}</p>
					<button
						v-if="photoUrl"
						type="button"
						class="mt-1 text-xs font-semibold text-gray-400 hover:text-gray-600"
						:disabled="photoBusy"
						@click="removePhoto"
					>
						{{ labels.profilePhotoRemove }}
					</button>
				</div>
			</div>
			<p v-if="photoErr" class="relative z-10 px-5 pb-4 text-xs font-medium text-red-600">
				{{ photoErr }}
			</p>
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

		<!-- The role list used to sit here. It was removed 2026-08-11: an account also carries
		     Frappe's automatic All / Guest / Desk User, so the section spent most of its space
		     on names that say nothing about depot access — and the section above it already
		     answers the question an operator actually opens this screen with ("what can I
		     open?"), in menu names rather than role names. -->

		<!-- Notifikasi HP — the only place a browser may ask for permission is a real tap,
		     so this cannot be turned on for the operator automatically. -->
		<section class="space-y-2">
			<p class="oak-eyebrow flex items-center gap-1.5 px-1">
				<Icon name="bell" :size="14" /> {{ labels.pushTitle }}
			</p>
			<div class="oak-card p-4">
				<div class="flex items-center gap-3">
					<span
						class="oak-icon-tile h-10 w-10 shrink-0"
						:class="push.subscribed ? 'bg-leaf-50 text-leaf-600' : 'bg-gray-100 text-gray-400'"
					>
						<Icon :name="push.subscribed ? 'bell' : 'bell-off'" :size="20" />
					</span>
					<div class="min-w-0 flex-1">
						<p class="text-sm font-semibold text-gray-900">
							{{ push.subscribed ? labels.pushActive : labels.pushInactive }}
						</p>
						<p class="mt-0.5 text-xs text-gray-500">{{ labels.pushHint }}</p>
					</div>
					<button
						type="button"
						class="oak-btn shrink-0"
						:class="push.subscribed ? 'oak-btn-ghost text-gray-500' : 'oak-btn-primary'"
						:disabled="push.busy || !push.supported"
						@click="togglePush"
					>
						{{ push.busy ? labels.pushWorking : push.subscribed ? labels.pushDisable : labels.pushEnable }}
					</button>
				</div>
				<p v-if="pushNote" class="mt-3 text-xs font-medium text-amber-700">{{ pushNote }}</p>
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
				<!-- One eye per field rather than one switch for the form: the point of
				     revealing is to check what you just typed, and that should not mean
				     putting the old password on screen at the same time. -->
				<div v-for="f in pwFields" :key="f.id">
					<label class="oak-label" :for="f.id">{{ f.label }}</label>
					<div class="relative">
						<input
							:id="f.id"
							v-model="f.model.value"
							class="oak-input pr-11"
							:type="f.reveal.value ? 'text' : 'password'"
							:autocomplete="f.autocomplete"
						/>
						<button
							type="button"
							class="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-gray-400 transition-colors hover:text-gray-600"
							:aria-label="f.reveal.value ? labels.pwHide : labels.pwShow"
							:aria-pressed="f.reveal.value"
							@click="f.reveal.value = !f.reveal.value"
						>
							<Icon :name="f.reveal.value ? 'eye-off' : 'eye'" :size="18" />
						</button>
					</div>
				</div>
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
import { disablePush, enablePush, push, refreshPushState } from "@/data/push"
import { isIos, isStandalone } from "@/utils/install"
import { labels, passwordFeedbackLabel } from "@/utils/labels"
import { compressPhoto } from "@/utils/photo"
import { toast } from "@/utils/toast"
import Icon from "@/components/Icon.vue"
import emblem from "@/assets/oak-emblem.png"

onMounted(() => {
	if (!userContext.data) userContext.reload()
	fetchMenu()
	refreshPushState()
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

// --- Foto profil ------------------------------------------------------------
// The avatar is optional and the initials are the fallback, so nothing here blocks the rest
// of the screen: a failed upload leaves the old picture on display and puts one line of red
// under the card.
const photoInput = ref(null)
const photoBusy = ref(false)
const photoErr = ref("")
const photoUrl = computed(() => ctx.value?.user_image || "")

async function postPhoto(path, body) {
	const res = await fetch(`/api/method/container_depot.ess.profile.${path}`, {
		method: "POST",
		headers: { Accept: "application/json", "X-Frappe-CSRF-Token": window.csrf_token || "" },
		...(body ? { body } : {}),
	})
	if (!res.ok) throw new Error(String(res.status))
	// Re-read the context rather than patching it locally: user_image is what the rest of
	// the app reads, and one source keeps a stale URL from surviving a failed write.
	await userContext.reload()
}

async function onPhotoPick(event) {
	const file = event.target.files?.[0]
	event.target.value = "" // so picking the same file twice still fires
	if (!file) return
	photoErr.value = ""
	photoBusy.value = true
	try {
		// Same shrink the EIR photos get. It never throws — a frame it cannot decode is
		// passed through, and the server rejects it by format there instead.
		const fd = new FormData()
		fd.append("file", await compressPhoto(file), file.name)
		await postPhoto("set_profile_photo", fd)
		toast.success(labels.profilePhotoSaved)
	} catch (e) {
		photoErr.value = labels.profilePhotoFailed
	} finally {
		photoBusy.value = false
	}
}

async function removePhoto() {
	photoErr.value = ""
	photoBusy.value = true
	try {
		await postPhoto("remove_profile_photo")
		toast.success(labels.profilePhotoRemoved)
	} catch (e) {
		photoErr.value = labels.profilePhotoFailed
	} finally {
		photoBusy.value = false
	}
}

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

// --- Notifikasi HP ----------------------------------------------------------
// Three different "off" states read the same to the operator but need different advice:
// a browser that cannot do push at all, a permission the OS already refused (which we
// cannot re-prompt — only the site settings can undo it), and a server with no VAPID
// keys. Saying "gagal" to all three sends people to the wrong fix.
const pushNote = computed(() => {
	if (!push.supported) return labels.pushUnsupported
	if (push.permission === "denied") return labels.pushDenied
	if (push.error === "server-off") return labels.pushServerOff
	if (push.error === "denied") return labels.pushDenied
	if (push.error) return labels.pushFailed
	if (!push.subscribed && isIos() && !isStandalone()) return labels.pushIosHint
	return ""
})

async function togglePush() {
	if (push.subscribed) {
		if (await disablePush()) toast.success(labels.pushDisabled)
		return
	}
	if (await enablePush()) toast.success(labels.pushEnabled)
}

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
const pwSaving = ref(false)
const pwError = ref("")

// Passed to the template as refs so the eye toggle and the value live on the same row —
// `f.model.value` in the markup is the price of not writing the same block three times.
const pwFields = [
	{ id: "pw-old", label: labels.pwOld, model: pwOld, reveal: ref(false), autocomplete: "current-password" },
	{ id: "pw-new", label: labels.pwNew, model: pwNew, reveal: ref(false), autocomplete: "new-password" },
	{ id: "pw-confirm", label: labels.pwConfirm, model: pwConfirm, reveal: ref(false), autocomplete: "new-password" },
]

function resetPasswordForm() {
	pwFields.forEach((f) => {
		f.model.value = ""
		f.reveal.value = false
	})
	pwError.value = ""
}

// Frappe reports a weak password as `_server_messages` — a JSON array of JSON strings —
// whose payload is HTML: an optional warning <div> plus a <ul> of suggestions
// (user.handle_password_test_fail). Each item is pulled out separately so it can be
// looked up in the Indonesian map; joining first would leave one blob nothing matches.
// Anything with no translation passes through in English rather than being dropped.
// Selector covers `div` as well as `li`: the warning ships as
// `<div class="alert alert-warning">`, but frappe sanitises the attributes off it before
// it reaches `_server_messages`, so matching on the class finds nothing.
function htmlToLines(html) {
	const doc = new DOMParser().parseFromString(String(html || ""), "text/html")
	const items = [...doc.querySelectorAll("div, li, p")]
		.map((el) => el.textContent.trim())
		.filter(Boolean)
	if (items.length) return [...new Set(items)]
	const plain = doc.body.textContent.trim()
	return plain ? [plain] : []
}

async function readFrappeError(res) {
	let body = null
	try {
		body = await res.json()
	} catch (e) {
		return res.status === 401 ? labels.pwWrongOld : labels.pwFailed
	}
	let lines = []
	try {
		lines = JSON.parse(body?._server_messages || "[]").flatMap((m) => {
			let msg = m
			try {
				msg = JSON.parse(m).message
			} catch (e) {
				/* plain string */
			}
			return htmlToLines(msg)
		})
	} catch (e) {
		/* fall through to the status-based fallbacks */
	}
	if (lines.length) {
		return [labels.pwRequirements + ":", ...lines.map(passwordFeedbackLabel)].join(" ")
	}
	if (res.status === 401) return labels.pwWrongOld
	// `message` carries frappe's short reason ("Incorrect password"); `exception` is a
	// python class path, which is never worth showing to a yard operator.
	return body?.message ? passwordFeedbackLabel(body.message) : labels.pwFailed
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
