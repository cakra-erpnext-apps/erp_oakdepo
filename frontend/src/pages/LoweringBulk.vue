<template>
	<div class="mx-auto w-full max-w-lg space-y-3 md:max-w-2xl">
		<div class="flex items-center gap-2">
			<button
				class="oak-press flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-gray-500"
				:aria-label="labels.backBtn"
				@click="goBack"
			>
				<Icon name="chevron-left" :size="22" />
			</button>
			<h1 class="min-w-0 flex-1 truncate text-lg font-extrabold tracking-tight text-gray-900">
				{{ labels.bulkLowTitle }}
			</h1>
			<span v-if="picked.length" class="oak-chip shrink-0 bg-brand-100 text-brand-700">
				{{ picked.length }} {{ labels.bulkTankWord }}
			</span>
		</div>

		<!-- Sudah tersimpan: layar berhenti jadi form dan jadi jawaban. -->
		<section v-if="done" class="oak-card border-leaf-300 p-5 text-center">
			<span class="oak-icon-tile mx-auto h-12 w-12 bg-leaf-500 text-white"><Icon name="check" :size="24" /></span>
			<p class="mt-2 text-base font-extrabold text-gray-900">
				{{ fill(labels.bulkLowDone, { n: done.done.length }) }}
			</p>
			<p class="mt-0.5 text-xs text-gray-500">{{ labels.bulkLowDoneHint }}</p>
			<p v-if="done.failed.length" class="mt-2 text-xs font-bold text-red-600">
				{{ fill(labels.bulkLowPartial, { n: done.failed.length }) }}
			</p>
			<div class="mt-3 flex gap-2">
				<button class="oak-btn oak-btn-primary min-h-[48px] flex-1" @click="goBack">{{ labels.bulkLowBack }}</button>
				<router-link to="/survey-orders" class="oak-btn oak-btn-secondary min-h-[48px] flex-1">
					{{ labels.bulkLowOpenSurvey }}
				</router-link>
			</div>
		</section>

		<template v-else>
			<div class="flex gap-2 rounded-xl border border-blue-200 bg-blue-50 p-3">
				<Icon name="info" :size="16" class="mt-0.5 shrink-0 text-blue-600" />
				<div class="min-w-0">
					<p class="text-xs font-bold text-blue-900">{{ labels.bulkLowIntro }}</p>
					<p class="mt-0.5 text-[11px] text-blue-800">{{ labels.bulkLowIntroHint }}</p>
				</div>
			</div>

			<!-- Tank yang dipilih. Semua sudah dibawa dari papan; di sini hanya bisa dikurangi,
			     karena yang belum terpilih tidak ada di layar sebelumnya untuk dipilih. -->
			<section class="oak-card overflow-hidden">
				<div class="flex items-center justify-between gap-2 px-4 pb-2 pt-3">
					<p class="text-sm font-extrabold text-gray-900">
						{{ labels.bulkLowPicked }}
						<span class="text-gray-400">{{ picked.length }} {{ labels.eirBatchOf }} {{ initial }}</span>
					</p>
				</div>
				<p v-if="!picked.length" class="px-4 pb-4 text-xs text-gray-500">{{ labels.bulkEmpty }}</p>
				<ul v-else class="divide-y divide-gray-100 border-t border-gray-100">
					<li v-for="t in picked" :key="t.name" class="flex min-h-[60px] items-center gap-3 px-4 py-3">
						<span class="oak-icon-tile h-7 w-7 shrink-0 bg-brand-500 text-white">
							<Icon name="check" :size="14" />
						</span>
						<div class="min-w-0 flex-1">
							<p class="truncate font-mono text-sm font-bold text-gray-900">
								{{ t.container_no || t.container }}
							</p>
							<p class="truncate text-[11px] text-gray-500">{{ line(t) }}</p>
						</div>
						<button
							class="oak-press flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-gray-400"
							:aria-label="labels.tplCancel"
							@click="drop(t.name)"
						>
							<Icon name="x" :size="17" />
						</button>
					</li>
				</ul>
			</section>

			<!-- Tank yang letaknya belum pernah didata tidak bisa ditandai lowered: "sudah turun"
			     sendirian meninggalkan surveyor tanpa tempat untuk berjalan. Dikatakan DI SINI,
			     bukan sebagai kegagalan setelah tombol ditekan. -->
			<div v-if="unlocated.length" class="flex gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3">
				<Icon name="alert-triangle" :size="16" class="mt-0.5 shrink-0 text-amber-600" />
				<div class="min-w-0">
					<p class="text-xs font-bold text-amber-900">{{ fill(labels.bulkLowNeedPos, { n: unlocated.length }) }}</p>
					<p class="mt-0.5 text-[11px] text-amber-800">{{ labels.bulkLowNeedPosHint }}</p>
				</div>
			</div>

			<section class="oak-card space-y-2 p-4">
				<div class="flex items-baseline justify-between gap-2">
					<p class="text-sm font-extrabold text-gray-900">{{ labels.tankLoweringNote }}</p>
					<p class="shrink-0 text-[11px] text-gray-400">{{ labels.bulkLowNoteAll }} · {{ labels.tankPosOptional }}</p>
				</div>
				<textarea v-model.trim="note" rows="2" class="oak-input" :placeholder="labels.tankLoweringNoteHint"></textarea>
			</section>

			<div class="oak-footer space-y-1">
				<button
					class="oak-btn oak-btn-primary min-h-[52px] w-full text-base"
					:disabled="!picked.length || saving"
					@click="save"
				>
					{{ saving ? "…" : fill(labels.bulkLowSave, { n: picked.length }) }}
				</button>
				<p class="text-center text-[11px] text-gray-400">{{ labels.bulkLowHint }}</p>
			</div>
		</template>
	</div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue"
import { useRouter } from "vue-router"
import { send } from "@/data/send"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
import { takeLoweringPreselect } from "@/utils/positionPick"
import Icon from "@/components/Icon.vue"

const router = useRouter()

const picked = ref([])
const initial = ref(0)
const note = ref("")
const saving = ref(false)
const done = ref(null)

const unlocated = computed(() => picked.value.filter((t) => !t.located))

function fill(tpl, vars) {
	return Object.entries(vars).reduce((s, [k, v]) => s.replace(`{${k}}`, v), tpl)
}
function line(t) {
	return [t.principal, t.located ? t.location_note : labels.tankPosUnlocated].filter(Boolean).join(" · ")
}
function drop(name) {
	picked.value = picked.value.filter((t) => t.name !== name)
}

async function save() {
	if (!picked.value.length || saving.value) return
	saving.value = true
	try {
		const res = await send({
			url: "container_depot.ess.tank_survey.survey_lowered_many",
			payload: {
				names: JSON.stringify(picked.value.map((t) => t.name)),
				note: note.value || undefined,
			},
		})
		// Gagal sebagian dilaporkan apa adanya, dan yang berhasil TETAP tercatat: membuang
		// empat pencatatan yang benar karena tank kelima belum punya letak berarti membuang
		// pekerjaan yang sudah dilakukan.
		done.value = { done: res?.done || [], failed: res?.failed || [] }
		if (res?.failed?.length) toast.error(fill(labels.bulkLowPartial, { n: res.failed.length }))
	} catch (e) {
		toast.error(e?.message || labels.error)
	} finally {
		saving.value = false
	}
}

function goBack() {
	if (window.history.length > 1) router.back()
	else router.push("/position-fix")
}

onMounted(() => {
	picked.value = takeLoweringPreselect()
	initial.value = picked.value.length
	// Dibuka langsung tanpa melewati papan (refresh, atau tautan yang disalin): tidak ada yang
	// bisa ditandai, jadi kembalikan ke tempat pilihannya dibuat daripada memajang layar kosong.
	if (!picked.value.length) router.replace("/position-fix")
})
</script>
