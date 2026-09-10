<template>
	<div class="space-y-2">
		<textarea
			:value="modelValue"
			rows="2"
			class="oak-input"
			:placeholder="labels.posLocationHint"
			@input="emit('update:modelValue', $event.target.value)"
		></textarea>

		<div class="flex items-baseline justify-between gap-2">
			<p class="truncate text-[11px] text-gray-400">
				{{ fill(labels.tankPosTemplateFor, { depot: depot || "—" }) }}
			</p>
			<!-- Membuka SHEET, bukan halaman lain. Pindah halaman dari sini berarti form yang
			     sedang diisi dibongkar: posisi yang sudah diketik, catatan, dan foto yang sudah
			     naik semuanya hilang — dan yang menekan "Kelola template" justru sedang di
			     tengah mengisi form, karena di situlah ia menyadari template-nya kurang. -->
			<button
				v-if="depot"
				type="button"
				class="oak-press -my-1 shrink-0 rounded-lg px-2 py-1.5 text-xs font-bold text-brand-600"
				@click="sheet = true"
			>
				{{ labels.tankPosManageTemplates }}
			</button>
		</div>

		<div class="flex flex-wrap gap-1.5">
			<button
				v-for="t in templates"
				:key="t.name"
				type="button"
				class="oak-press min-h-[38px] rounded-full border px-3 font-mono text-xs font-bold transition"
				:class="isActive(t.label)
					? 'border-brand-500 bg-brand-500/10 text-brand-700'
					: 'border-gray-200 bg-paper text-gray-600'"
				@click="emit('update:modelValue', t.label)"
			>
				{{ t.label }}
			</button>

			<!-- Menawarkan menyimpan APA YANG BARU SAJA DIKETIK, di tempat ia diketik. Layar
			     pengaturan yang harus dibuka sendiri tidak pernah dibuka: yang tahu bahwa bay
			     ini akan dipakai lagi besok adalah orang yang sedang mengetiknya sekarang. -->
			<button
				v-if="canSave"
				type="button"
				class="oak-press min-h-[38px] rounded-full border border-dashed border-brand-400 px-3 text-xs font-bold text-brand-600 transition disabled:opacity-50"
				:disabled="saving"
				@click="saveTemplate"
			>
				{{ saving ? "…" : fill(labels.tankPosTemplateSaveAs, { label: trimmed }) }}
			</button>
		</div>

		<p class="text-[11px] text-gray-400">{{ labels.tankPosTemplateFree }}</p>

		<teleport to="body">
			<div v-if="sheet" class="fixed inset-0 z-40 animate-fade-in bg-gray-900/40 backdrop-blur-[1px]" @click="closeSheet"></div>
			<section
				v-if="sheet"
				class="fixed inset-x-0 bottom-0 z-50 flex max-h-[88vh] flex-col rounded-t-3xl bg-paper pb-safe-bottom shadow-soft animate-slide-up"
				role="dialog"
				aria-modal="true"
			>
				<button class="w-full pb-1 pt-2.5" :aria-label="labels.moreClose" @click="closeSheet">
					<span class="mx-auto block h-1 w-10 rounded-full bg-gray-300"></span>
				</button>
				<div class="flex items-center gap-2 px-4 pb-2">
					<h2 class="min-w-0 flex-1 truncate text-base font-extrabold text-gray-900">{{ labels.tplTitle }}</h2>
					<span class="oak-chip shrink-0 bg-gray-100 font-mono text-gray-600">{{ depot }}</span>
				</div>
				<div class="min-h-0 flex-1 overflow-y-auto px-4 pb-3">
					<PositionTemplatePanel :depot="depot" :active="sheet" @changed="res.reload()" />
				</div>
				<!-- Jalan pulangnya disebut apa adanya: yang ditinggalkan sebentar adalah form,
				     dan form itu masih utuh di belakang sheet ini. -->
				<div class="border-t border-gray-100 px-4 pb-4 pt-3">
					<button class="oak-btn oak-btn-primary min-h-[52px] w-full" @click="closeSheet">
						{{ labels.tplBackToForm }}
					</button>
				</div>
			</section>
		</teleport>
	</div>
</template>

<script setup>
import { computed, ref, watch } from "vue"
import { cachedResource } from "@/data/cache"
import { send } from "@/data/send"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
import { useDismissOnBack } from "@/utils/backstack"
import PositionTemplatePanel from "@/components/PositionTemplatePanel.vue"

const props = defineProps({
	modelValue: { type: String, default: "" },
	// Depot tank yang sedang dicatat. Template milik depot, jadi tanpa ini daftarnya akan
	// menawarkan bay dari yard lain — nama yang benar di tempat yang salah.
	depot: { type: String, default: "" },
})
const emit = defineEmits(["update:modelValue"])

const res = cachedResource({
	url: "container_depot.ess.container_position.position_templates",
	method: "GET",
	makeParams: () => ({ depot: props.depot || "" }),
})
const templates = computed(() => res.data?.items || [])

watch(
	() => props.depot,
	(v) => v && res.reload(),
	{ immediate: true }
)

const trimmed = computed(() => (props.modelValue || "").trim())
const isActive = (label) => label.toLowerCase() === trimmed.value.toLowerCase()
const canSave = computed(
	() => Boolean(props.depot) && trimmed.value.length > 0 && !templates.value.some((t) => isActive(t.label))
)

const saving = ref(false)
async function saveTemplate() {
	if (saving.value) return
	saving.value = true
	try {
		await send({
			url: "container_depot.ess.container_position.position_template_add",
			payload: { depot: props.depot, label: trimmed.value },
		})
		res.reload()
	} catch (e) {
		toast.error(e.message || String(e))
	} finally {
		saving.value = false
	}
}

// Sheet kelola template. Tombol Back HP menutup sheet lebih dulu, bukan meninggalkan form —
// urutan yang sama dengan yang dilihat mata (utils/backstack).
const sheet = ref(false)
function closeSheet() {
	sheet.value = false
	res.reload() // template yang baru ditambah harus langsung muncul sebagai chip
}
useDismissOnBack(sheet, closeSheet)

function fill(tpl, vars) {
	return Object.entries(vars).reduce((s, [k, v]) => s.replace(`{${k}}`, v), tpl)
}
</script>
