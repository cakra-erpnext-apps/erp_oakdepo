<template>
	<div class="space-y-3">
		<!-- Daftar ini milik depot, bukan milik yang membukanya. Dikatakan di muka, sekali,
		     supaya tidak ada yang menghapus baris orang lain sambil mengira itu preferensinya
		     sendiri. -->
		<div class="flex gap-2 rounded-xl border border-blue-200 bg-blue-50 p-3">
			<Icon name="info" :size="16" class="mt-0.5 shrink-0 text-blue-600" />
			<div class="min-w-0">
				<p class="text-xs font-bold text-blue-900">{{ labels.tplSharedTitle }}</p>
				<p class="mt-0.5 text-[11px] leading-relaxed text-blue-800">
					{{ fill(labels.tplSharedHint, { depot: depotName || "—" }) }}
				</p>
			</div>
		</div>

		<!-- Tambah -->
		<section class="oak-card space-y-2 p-4">
			<p class="text-sm font-extrabold text-gray-900">{{ labels.tplAdd }}</p>
			<div class="flex gap-2">
				<input
					v-model.trim="draft"
					class="oak-input min-h-[48px] flex-1"
					:placeholder="labels.tplAddPlaceholder"
					maxlength="60"
					@keydown.enter="add()"
				/>
				<button class="oak-btn oak-btn-primary min-h-[48px] shrink-0 px-5" :disabled="!draft || busy" @click="add()">
					{{ labels.tplAddBtn }}
				</button>
			</div>
		</section>

		<!-- Daftar -->
		<section class="space-y-1.5">
			<div class="flex items-baseline justify-between gap-2 px-1">
				<p class="text-xs font-bold text-gray-500">{{ labels.tplList }} · {{ items.length }}</p>
				<p v-if="items.length > 1" class="truncate text-[11px] text-gray-400">{{ labels.tplReorderHint }}</p>
			</div>

			<div v-if="res.loading && !items.length" class="oak-card space-y-3 p-4">
				<div class="oak-skeleton h-4 w-2/3"></div>
				<div class="oak-skeleton h-4 w-1/2"></div>
			</div>
			<p v-else-if="!items.length" class="oak-card p-4 text-xs text-gray-500">{{ labels.tplEmpty }}</p>

			<ul v-else class="oak-card divide-y divide-gray-100 overflow-hidden">
				<li v-for="(t, i) in items" :key="t.name" class="px-2 py-2">
					<div v-if="editing === t.name" class="flex items-center gap-2">
						<input v-model.trim="editDraft" class="oak-input min-h-[44px] min-w-0 flex-1" maxlength="60" @keydown.enter="commitRename(t)" />
						<button class="oak-btn oak-btn-primary min-h-[44px] shrink-0 px-3" :disabled="busy" @click="commitRename(t)">
							<Icon name="check" :size="16" />
						</button>
						<button class="oak-btn oak-btn-secondary min-h-[44px] shrink-0 px-3" @click="editing = ''">
							<Icon name="x" :size="16" />
						</button>
					</div>

					<div v-else class="flex items-center gap-1">
						<!-- Urutan diubah dengan dua tombol, bukan diseret. Drag-and-drop HTML
						     tidak berjalan sama sekali di browser sentuh — pegangan geser di HP
						     adalah kontrol yang terlihat bisa dipakai dan tidak melakukan apa pun.
						     Dua panah bekerja di mana saja, dan tiap ketukannya satu langkah yang
						     bisa dibatalkan dengan ketukan sebaliknya. -->
						<div class="flex shrink-0 flex-col">
							<button
								class="oak-press flex h-6 w-9 items-center justify-center rounded-t-lg text-gray-400 disabled:opacity-25"
								:disabled="i === 0 || busy"
								:aria-label="labels.tplMoveUp"
								@click="move(i, -1)"
							>
								<Icon name="chevron-up" :size="15" />
							</button>
							<button
								class="oak-press flex h-6 w-9 items-center justify-center rounded-b-lg text-gray-400 disabled:opacity-25"
								:disabled="i === items.length - 1 || busy"
								:aria-label="labels.tplMoveDown"
								@click="move(i, 1)"
							>
								<Icon name="chevron-down" :size="15" />
							</button>
						</div>

						<div class="min-w-0 flex-1 py-1">
							<p class="truncate font-mono text-sm font-bold" :class="t.used ? 'text-gray-900' : 'text-gray-400'">
								{{ t.label }}
							</p>
							<p class="truncate text-[11px] text-gray-400">{{ usageLine(t) }}</p>
						</div>

						<button
							class="oak-press flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-gray-400"
							:aria-label="labels.tplRename"
							@click="startRename(t)"
						>
							<Icon name="edit-2" :size="16" />
						</button>
						<button
							class="oak-press flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-red-400"
							:aria-label="labels.tplDelete"
							@click="askDelete(t)"
						>
							<Icon name="trash-2" :size="16" />
						</button>
					</div>
				</li>
			</ul>
		</section>

		<!-- Yang sudah terbukti dipakai tapi belum terdaftar. Ini yang menjaga daftar di atas
		     tidak menua: sebuah bay baru dibuka, semua orang mengetiknya dengan tangan, dan
		     tidak ada yang merasa punya urusan membuka layar ini untuk mendaftarkannya. -->
		<section v-if="suggestions.length" class="space-y-1.5">
			<div class="flex items-baseline justify-between gap-2 px-1">
				<p class="text-xs font-bold text-gray-500">{{ labels.tplSuggestTitle }}</p>
				<p class="truncate text-[11px] text-gray-400">{{ labels.tplSuggestNote }}</p>
			</div>
			<ul class="oak-card divide-y divide-gray-100 overflow-hidden">
				<li v-for="sg in suggestions" :key="sg.label" class="flex min-h-[60px] items-center gap-2 px-4 py-3">
					<div class="min-w-0 flex-1">
						<p class="truncate font-mono text-sm font-bold text-gray-900">{{ sg.label }}</p>
						<p class="truncate text-[11px] text-gray-400">{{ fill(labels.tplSuggestTyped, { n: sg.typed }) }}</p>
					</div>
					<button class="oak-btn oak-btn-secondary min-h-[44px] shrink-0 px-4 text-xs" :disabled="busy" @click="add(sg.label)">
						{{ labels.tplSuggestMake }}
					</button>
				</li>
			</ul>
		</section>

		<!-- Konfirmasi hapus -->
		<teleport to="body">
			<div v-if="pendingDelete" class="fixed inset-0 z-[60] animate-fade-in bg-gray-900/50" @click="pendingDelete = null"></div>
			<section
				v-if="pendingDelete"
				class="fixed inset-x-4 bottom-6 z-[61] animate-slide-up rounded-2xl bg-paper p-4 shadow-soft"
				role="dialog"
				aria-modal="true"
			>
				<p class="text-base font-extrabold text-gray-900">
					{{ fill(labels.tplDeleteAsk, { label: pendingDelete.label }) }}
				</p>
				<p class="mt-1 text-xs leading-relaxed text-gray-600">
					{{ fill(labels.tplDeleteBody, { depot: depotName || "—", label: pendingDelete.label }) }}
				</p>
				<div v-if="usage !== null" class="mt-3 flex items-baseline justify-between border-t border-gray-100 pt-3">
					<span class="text-xs text-gray-500">{{ labels.tplDeleteInUse }}</span>
					<span class="text-sm font-extrabold" :class="usage ? 'text-amber-700' : 'text-gray-400'">
						{{ fill(labels.tplDeleteTanks, { n: usage }) }}
					</span>
				</div>
				<button
					class="oak-btn oak-btn-secondary mt-3 min-h-[52px] w-full border-red-200 text-red-600"
					:disabled="busy"
					@click="confirmDelete"
				>
					{{ labels.tplDelete }}
				</button>
				<button class="oak-btn oak-btn-secondary mt-2 min-h-[52px] w-full" @click="pendingDelete = null">
					{{ labels.tplCancel }}
				</button>
			</section>
		</teleport>
	</div>
</template>

<script setup>
import { computed, ref, watch } from "vue"
import { cachedResource } from "@/data/cache"
import { send } from "@/data/send"
import { labels } from "@/utils/labels"
import { since } from "@/utils/surveyStatus"
import { toast } from "@/utils/toast"
import { useDismissOnBack } from "@/utils/backstack"
import Icon from "@/components/Icon.vue"

const props = defineProps({
	depot: { type: String, default: "" },
	// Panel ini hidup di dua tempat: halaman tersendiri, dan sheet di atas form. Yang kedua
	// baru memuat isinya saat dibuka — sebuah sheet tertutup tidak perlu membayar satu GET.
	active: { type: Boolean, default: true },
})
const emit = defineEmits(["changed"])

const res = cachedResource({
	url: "container_depot.ess.container_position.position_templates",
	method: "GET",
	makeParams: () => ({ depot: props.depot || "" }),
})
// Urutan disimpan lokal selagi diubah, supaya baris berpindah seketika dan tidak menunggu
// server menjawab dulu — di sinyal yard itu jeda yang terasa seperti tombol yang rusak.
const items = ref([])
watch(
	() => res.data,
	(d) => {
		if (d?.items) items.value = [...d.items]
	},
	{ immediate: true }
)
watch(
	() => [props.active, props.depot],
	([on]) => on && res.reload(),
	{ immediate: true }
)

const depotName = computed(() => res.data?.depot || props.depot)
const suggestions = computed(() => res.data?.suggestions || [])

const draft = ref("")
const busy = ref(false)

function fill(tpl, vars) {
	return Object.entries(vars).reduce((s, [k, v]) => s.replace(`{${k}}`, v), tpl)
}
function usageLine(t) {
	if (!t.used) return labels.tplNeverUsed
	const parts = [fill(labels.tplUsed, { n: t.used })]
	if (t.last_used) parts.push(fill(labels.tplLastUsed, { t: since(t.last_used).toLowerCase() }))
	return parts.join(" · ")
}

async function call(url, payload) {
	busy.value = true
	try {
		await send({ url, payload })
		res.reload()
		emit("changed")
		return true
	} catch (e) {
		toast.error(e.message || String(e))
		return false
	} finally {
		busy.value = false
	}
}

async function add(label) {
	const text = (label || draft.value || "").trim()
	if (!text) return
	const ok = await call("container_depot.ess.container_position.position_template_add", {
		depot: depotName.value,
		label: text,
	})
	if (ok && !label) draft.value = ""
}

// --- ganti nama ---
const editing = ref("")
const editDraft = ref("")
function startRename(t) {
	editing.value = t.name
	editDraft.value = t.label
}
async function commitRename(t) {
	if (!editDraft.value || editDraft.value === t.label) {
		editing.value = ""
		return
	}
	if (
		await call("container_depot.ess.container_position.position_template_rename", {
			name: t.name,
			label: editDraft.value,
		})
	) {
		editing.value = ""
	}
}

// --- urutkan ---
function move(i, delta) {
	const j = i + delta
	if (j < 0 || j >= items.value.length) return
	const list = [...items.value]
	;[list[i], list[j]] = [list[j], list[i]]
	items.value = list
	// Yang dikirim daftar UTUH, bukan "pindahkan yang ini ke urutan tiga": dua orang yang
	// menggeser bersamaan lewat perintah relatif bisa menghasilkan urutan yang tidak pernah
	// dilihat keduanya.
	call("container_depot.ess.container_position.position_template_reorder", {
		depot: depotName.value,
		names: JSON.stringify(list.map((t) => t.name)),
	})
}

// --- hapus ---
const pendingDelete = ref(null)
const usage = ref(null)
const usageRes = cachedResource({
	url: "container_depot.ess.container_position.position_template_usage",
	method: "GET",
	makeParams: () => ({ name: pendingDelete.value?.name || "" }),
	onSuccess: (d) => (usage.value = d.tanks ?? null),
})
function askDelete(t) {
	pendingDelete.value = t
	usage.value = null
	usageRes.reload()
}
useDismissOnBack(
	computed(() => Boolean(pendingDelete.value)),
	() => (pendingDelete.value = null)
)
async function confirmDelete() {
	const t = pendingDelete.value
	if (!t) return
	if (await call("container_depot.ess.container_position.position_template_delete", { name: t.name })) {
		pendingDelete.value = null
	}
}
</script>
