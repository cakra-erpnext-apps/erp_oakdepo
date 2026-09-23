<template>
	<!-- Leak Check manual — tank yang tidak punya order dari bon (mis. sudah di depo sebelum
	     fitur ini ada). Order dari bon dibuka lewat daftar /leak-check. -->
	<div class="mx-auto w-full max-w-lg space-y-3 md:max-w-2xl">
		<DetailHeader :title="labels.leakManualTitle" @back="goBack" />

		<section class="oak-card space-y-2 p-4">
			<p class="text-sm font-extrabold text-gray-900">{{ labels.leakPickTank }}</p>
			<div v-if="tank" class="flex items-center gap-3">
				<p class="min-w-0 flex-1 truncate font-mono text-base font-extrabold text-gray-900">
					{{ tank.container_no || tank.name }}
				</p>
				<button class="oak-btn oak-btn-secondary shrink-0 px-3 py-1.5 text-xs" @click="tank = null">
					{{ labels.leakChange }}
				</button>
			</div>
			<template v-else>
				<ListSearch v-model="query" :placeholder="labels.tankPosSearch" @search="searchRes.reload()" />
				<ul v-if="results.length" class="divide-y divide-gray-100">
					<li v-for="r in results" :key="r.name">
						<button
							type="button"
							class="flex w-full items-center gap-2 py-2.5 text-left transition active:bg-gray-50"
							@click="pick(r)"
						>
							<span class="min-w-0 flex-1 truncate font-mono text-sm font-bold text-gray-900">{{ r.container_no || r.name }}</span>
							<span class="shrink-0 truncate text-[11px] text-gray-500">{{ r.principal }}</span>
						</button>
					</li>
				</ul>
				<p v-else-if="query.trim() && !searchRes.loading" class="text-xs text-gray-400">{{ labels.tankPosEmpty }}</p>
			</template>
		</section>

		<LeakPhotoForm :form="form" />

		<div class="oak-footer">
			<button
				class="oak-btn oak-btn-primary min-h-[52px] w-full text-base"
				:disabled="!canSave || saving"
				@click="save"
			>
				{{ saving ? "…" : labels.leakSave }}
			</button>
		</div>
	</div>
</template>

<script setup>
import { computed, reactive, ref } from "vue"
import { useRouter } from "vue-router"
import { cachedResource } from "@/data/cache"
import { send } from "@/data/send"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
import DetailHeader from "@/components/list/DetailHeader.vue"
import ListSearch from "@/components/list/ListSearch.vue"
import LeakPhotoForm from "@/components/LeakPhotoForm.vue"

const router = useRouter()
const tank = ref(null)
const form = reactive({ photos: [], remarks: "", uploading: false })
const saving = ref(false)
const canSave = computed(() => !!tank.value && form.photos.length > 0 && !form.uploading)

const query = ref("")
const searchRes = cachedResource({
	url: "container_depot.ess.leak_check.leak_tank_search",
	method: "GET",
	makeParams: () => ({ search: query.value || "", page_length: 8 }),
})
const results = computed(() => (query.value.trim() ? searchRes.data?.items || [] : []))
function pick(r) {
	tank.value = r
	query.value = ""
}

async function save() {
	if (!canSave.value || saving.value) return
	saving.value = true
	try {
		const res = await send({
			url: "container_depot.ess.leak_check.leak_record",
			payload: {
				container: tank.value.name,
				remarks: form.remarks.trim() || undefined,
				photos: form.photos.map((p) => ({ photo: p.photo, caption: p.caption.trim(), is_leak: p.is_leak ? 1 : 0 })),
			},
		})
		toast.success(labels.leakSaved, { title: tank.value.container_no || tank.value.name })
		const name = res?.message?.name
		router.replace(name ? `/leak-check/${name}` : "/leak-check")
	} catch (e) {
		toast.error(e?.message || labels.error)
	} finally {
		saving.value = false
	}
}

function goBack() {
	if (window.history.length > 1) router.back()
	else router.push("/leak-check")
}
</script>
