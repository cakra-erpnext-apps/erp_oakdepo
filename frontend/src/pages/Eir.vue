<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<!-- =================== FORM (In or Out) =================== -->
		<template v-if="activeInspection && activeType">
			<!-- Bar batch: hanya muncul kalau memang ada lebih dari satu EIR yang dibuka
			     bersama. Ia yang mengumumkan --oak-nav-h, jadi header form di bawahnya
			     otomatis turun satu bar (lihat EirBatchBar.vue). -->
			<EirBatchBar
				v-if="batchRows.length > 1 && activeIndex !== -1"
				:queue="batchRows"
				:active-index="activeIndex"
				:tanks="activeTanks"
				@prev="goRel(-1)"
				@next="goRel(1)"
				@open="sheetOpen = true"
			/>
			<component
				:is="activeType === 'EIR-Out' ? EirOutForm : EirInForm"
				:key="activeInspection + activeType"
				:inspection="activeInspection"
				@back="onBack"
				@submitted="onSubmitted"
			/>
			<EirBatchSheet
				:open="sheetOpen"
				:rows="batchRows"
				:active-name="activeInspection || ''"
				:tanks="activeTanks"
				@close="sheetOpen = false"
				@leave="clearBatch"
				@pick="goItem"
			/>
		</template>
		<!-- ?e= without ?t= (hand-typed / shared link): the worklist is still resolving
		     which direction this EIR is. Rendering the wrong form would call the wrong
		     endpoint, so wait rather than guess. -->
		<div v-else-if="activeInspection" class="oak-section space-y-2">
			<div class="oak-skeleton h-6 w-1/2 rounded-md"></div>
			<div class="oak-skeleton h-24 rounded-xl"></div>
		</div>

		<!-- =================== BATCH SELESAI =================== -->
		<!-- Bon yang seluruh tanknya sudah dikirim. Bukan sekadar toast: sebuah batch adalah
		     satu truk yang selesai dilayani, dan operator berhak melihat ringkasannya sekali
		     — apa yang terkirim, berapa temuannya, berapa lama — sebelum daftar kembali
		     penuh dengan pekerjaan berikutnya. -->
		<template v-else-if="batchDone">
			<section class="space-y-4 py-6 text-center">
				<span class="oak-icon-tile mx-auto h-16 w-16 rounded-full bg-leaf-100 text-leaf-600">
					<Icon name="check" :size="32" />
				</span>
				<div>
					<h1 class="text-lg font-extrabold tracking-tight">
						{{ labels.eirBatchDoneTitle }} · {{ sentSummary.length }} {{ labels.eirBatchDoneSent }}
					</h1>
					<p v-if="batch.voucher" class="mt-0.5 font-mono text-xs text-gray-500">{{ batch.voucher }}</p>
				</div>

				<ul class="oak-card divide-y divide-gray-100 overflow-hidden text-left">
					<li v-for="r in sentSummary" :key="r.name" class="flex items-center gap-3 px-4 py-3">
						<span class="oak-icon-tile h-7 w-7 bg-leaf-100 text-leaf-700"><Icon name="check" :size="15" /></span>
						<span class="min-w-0 flex-1">
							<span class="block truncate font-mono text-sm font-bold text-gray-900">{{ r.container_no }}</span>
							<span class="block truncate text-[11px] text-gray-500">{{ doneLine(r) }}</span>
						</span>
						<span class="oak-chip shrink-0 bg-sky-100 text-sky-700">{{ labels.eirStatusPendingReview }}</span>
					</li>
				</ul>

				<p class="px-2 text-xs text-gray-400">{{ labels.eirBatchDoneNote }}</p>
			</section>

			<div class="oak-footer -mx-4 space-y-2 border-t border-gray-200/80 bg-gray-50/95 px-4 py-3 backdrop-blur">
				<button class="oak-btn oak-btn-primary w-full py-3" @click="finishBatch(false)">
					{{ labels.eirBatchDoneBack }}
				</button>
				<button class="oak-btn oak-btn-secondary w-full py-2.5" @click="finishBatch(true)">
					{{ labels.eirBatchDoneNew }}
				</button>
			</div>
		</template>

		<!-- =================== WORKLIST + LANDING =================== -->
		<template v-else>
			<div class="flex flex-wrap items-center justify-between gap-2">
				<div class="flex items-center gap-2">
					<span class="oak-icon-tile h-9 w-9 bg-leaf-50 text-leaf-600"><Icon name="search-check" :size="20" /></span>
					<div class="min-w-0">
						<h1 class="text-lg font-extrabold leading-tight tracking-tight">{{ labels.eirTitle }}</h1>
						<p class="truncate text-xs text-gray-500">{{ labels.eirCombinedSubtitle }}</p>
					</div>
				</div>
				<!-- Sedang memilih batch: satu-satunya jalan keluar berada di tempat yang sama
				     dengan pintu masuknya. Sortir & Riwayat menepi — keduanya membawa operator
				     ke layar lain, yang berarti pilihan yang sedang disusun hilang. -->
				<button
					v-if="selectMode"
					class="oak-btn oak-btn-secondary border-brand-300 px-3 py-2 text-brand-700"
					@click="toggleSelectMode"
				>
					<Icon name="x" :size="16" /> {{ labels.eirSelectCancel }}
				</button>
				<div v-else class="flex items-center gap-2">
					<!-- "Pilih" duduk di kepala halaman, bukan di kepala satu bagian: batch boleh
					     mencampur tank yang sedang dikerjakan dengan yang belum disentuh, dan
					     keduanya kini hidup di bagian yang berbeda. -->
					<button class="oak-btn oak-btn-secondary px-3 py-2" @click="toggleSelectMode">
						<Icon name="check-square" :size="16" /> {{ labels.eirSelect }}
					</button>
					<router-link to="/eir/sort" class="oak-btn oak-btn-secondary px-3 py-2">
						<Icon name="layers" :size="16" /> {{ labels.eirSortOpen }}
					</router-link>
					<router-link to="/eir/history" class="oak-btn oak-btn-secondary px-3 py-2">
						<Icon name="clock" :size="16" /> {{ labels.eirHistory }}
					</router-link>
				</div>
			</div>

			<!-- Batch yang sedang terbuka. Tanpa baris ini batch adalah pekerjaan yang tidak
			     terlihat di mana pun begitu operator menekan Kembali dari form: daftarnya
			     kembali seperti semula, tidak ada jalan pulang selain memilih ulang, dan
			     satu-satunya kesimpulan yang masuk akal adalah "batch-nya tidak tersimpan".
			     Ia memang tersimpan — yang hilang cuma pintunya.

			     Yang dipajang nomor tank-nya, bukan nomor bon: "Batch ORD-BKR-2026-00020"
			     tidak memberi tahu siapa pun tank mana yang ada di dalamnya, dan nomor tank
			     itulah yang tertulis di badan tangki dan di kertas yang dipegang sopir. -->
			<div
				v-if="openBatchRows.length > 1 && !selectMode"
				class="flex items-center gap-3 rounded-xl border border-brand-200 bg-brand-50 p-3"
			>
				<span class="oak-icon-tile h-9 w-9 shrink-0 bg-brand-100 text-brand-700">
					<Icon name="layers" :size="18" />
				</span>
				<div class="min-w-0 flex-1">
					<p class="truncate text-sm font-bold text-gray-900">
						{{ labels.eirBatchTitle }} · <span class="font-mono">{{ openBatchTanks }}</span>
					</p>
					<p class="truncate text-[11px] text-gray-500">{{ openBatchLine }}</p>
				</div>
				<button class="oak-btn oak-btn-ghost shrink-0 px-2 py-2 text-xs" @click="clearBatch">
					{{ labels.eirBatchExit }}
				</button>
				<button v-if="resumeRow" class="oak-btn oak-btn-primary shrink-0 px-3 py-2 text-xs" @click="goItem(resumeRow)">
					{{ labels.eirBatchResume }}
				</button>
			</div>

			<!-- SATU kotak cari dan SATU saringan arah untuk keempat bagian di bawah. Dulu
			     keduanya hanya menyaring daftar pending, sementara bagian di bawahnya tetap
			     memajang apa saja — jadi mencari satu nomor tank tetap berarti membacanya
			     sendiri di daftar Selesai. Pencariannya dikirim ke server untuk keempat
			     daftar; arah disaring di sini karena tiap baris sudah membawa jenisnya. -->
			<div v-if="!selectMode" class="flex items-center gap-2">
				<div class="relative min-w-0 flex-1">
					<Icon name="search" :size="16" class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
					<input
						v-model.trim="search"
						type="text"
						:placeholder="labels.eirPendingSearch"
						class="oak-input pl-8 uppercase"
						@input="onSearchInput"
					/>
				</div>
				<!-- Masuk / Keluar: pekerjaan yang berbeda (tank datang vs pergi), sering
				     dikerjakan berkelompok. -->
				<div class="flex shrink-0 rounded-lg border border-gray-200 bg-gray-50 p-0.5">
					<button
						v-for="f in DIR_FILTERS"
						:key="f.key"
						class="rounded-md px-2.5 py-1.5 text-[11px] font-bold transition"
						:class="dirFilter === f.key ? 'bg-paper text-brand-700 shadow-sm' : 'text-gray-500'"
						@click="dirFilter = f.key"
					>
						{{ f.label }}
					</button>
				</div>
			</div>

			<p v-if="fetchError" class="flex items-center gap-1.5 text-sm text-red-600">
				<Icon name="alert-circle" :size="15" /> {{ fetchError }}
			</p>

			<!-- Dua bagian untuk pekerjaan yang belum lepas tangan: yang sudah dipegang
			     seseorang, dan yang belum disentuh siapa pun. Markupnya satu, dirender dua
			     kali — barisnya memang sama, yang berbeda cuma isi dan judulnya. -->
			<CollapseSection
				v-for="s in pendingSections"
				:key="s.key"
				:title="s.title"
				:icon="s.icon"
				:tone="s.tone"
				:chip="s.chip"
				:count="s.rows.length"
				:open="openSections[s.key]"
				@update:open="openSections[s.key] = $event"
			>
				<div v-if="selectMode && s.rows.length" class="flex justify-end">
					<button class="oak-btn oak-btn-accent px-3 py-1.5 text-xs" @click="selectAll(s.rows)">
						{{ labels.eirBatchSelectAll }}
					</button>
				</div>

				<ul v-if="loadingPending && !pendingItems.length" class="space-y-2">
					<li v-for="n in 3" :key="n" class="oak-skeleton h-14 rounded-xl"></li>
				</ul>
				<div v-else-if="!s.rows.length" class="flex flex-col items-center gap-1 py-4 text-center">
					<span class="oak-icon-tile h-11 w-11 bg-gray-100 text-gray-300"><Icon name="inbox" :size="22" /></span>
					<p class="text-sm font-semibold text-gray-500">{{ emptyFor(s) }}</p>
					<!-- Kalimat kedua hanya untuk kosong yang sebenar-benarnya: kalau daftarnya
					     kosong karena saringan, "dibuat otomatis dari bon" menjawab pertanyaan
					     yang tidak sedang ditanya. -->
					<p v-if="!pendingItems.length" class="text-xs text-gray-400">{{ labels.eirPendingEmptyHint }}</p>
				</div>
				<!-- Every draft is listed; the scroller reveals about 5 rows and the rest
				     scroll. Rows are no longer a fixed 60px: the EIR number moved onto the row
				     (see below), so the height follows the content instead of clipping it. -->
				<div v-else class="max-h-[340px] overflow-y-auto overscroll-contain">
					<ul class="divide-y divide-gray-100">
						<li v-for="r in s.rows" :key="r.name">
							<button class="flex min-h-[64px] w-full items-center gap-3 py-2 text-left" @click="rowClick(r)">
								<!-- Select-mode tick box (replaces navigation while picking a batch). -->
								<span
									v-if="selectMode"
									class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border"
									:class="selected.has(r.name) ? 'border-brand-500 bg-brand-500 text-white' : 'border-gray-300'"
								>
									<Icon v-if="selected.has(r.name)" name="check" :size="14" />
								</span>
								<span v-else class="oak-icon-tile h-9 w-9 shrink-0" :class="r._type === 'EIR-Out' ? 'bg-brand-50 text-brand-600' : 'bg-amber-50 text-amber-600'">
									<Icon :name="r._type === 'EIR-Out' ? 'log-out' : 'search-check'" :size="16" />
								</span>
								<div class="min-w-0 flex-1">
									<!-- Nomor tank memiliki barisnya sendiri, nomor EIR-nya menepi ke
									     kanan: keduanya identitas, tapi yang di-scan mata cuma yang
									     kiri — dan nomor EIR yang dulu tidak ada di baris ini adalah
									     satu-satunya cara mencocokkan layar dengan kertas. -->
									<div class="flex items-baseline justify-between gap-2">
										<p class="truncate font-bold text-gray-900">{{ r.container_no || r.container }}</p>
										<span class="shrink-0 font-mono text-[10px] text-gray-400">{{ r.inspection_id || r.name }}</span>
									</div>
									<!-- Pemilik · status · bon. Nomor bon ikut ke baris ini karena dialah
									     yang menentukan tank mana yang layak dikerjakan bersama: batch
									     dipilih dengan mata, dari daftar ini. -->
									<p class="truncate text-[11px] text-gray-500">
										{{ [r.container_principal, r.tank_status, r.referred_voucher].filter(Boolean).join(" · ") || "—" }}
									</p>
									<!-- Baris chip: arah, sejauh mana sudah dikerjakan, kapan tank ini
									     ditunggu keluar, dan — kalau bonnya membawa lebih dari satu tank
									     — bahwa membukanya berarti membuka satu batch. -->
									<p class="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
										<span
											class="oak-chip shrink-0"
											:class="r._type === 'EIR-Out' ? 'bg-brand-100 text-brand-700' : 'bg-leaf-100 text-leaf-800'"
										>
											<Icon :name="r._type === 'EIR-Out' ? 'arrow-up-right' : 'arrow-down-left'" :size="11" />
											{{ r._type === 'EIR-Out' ? labels.eirBadgeOut : labels.eirBadgeIn }}
										</span>
										<span class="oak-chip shrink-0" :class="progressChip(r).tone">{{ progressChip(r).label }}</span>
										<span v-if="bonSize(r) > 1" class="oak-chip shrink-0 bg-brand-100 text-brand-700">
											<Icon name="layers" :size="11" />
											{{ labels.eirBatchTitle }} {{ bonSize(r) }}
										</span>
										<LiftOnBadge :survey="r.target_survey_on" :target="r.target_lift_on" :urgent="r.target_urgent_on" />
									</p>
									<!-- Siapa yang sudah di dalamnya. EIR yang sudah ditekan "Mulai"
									     tetap ada di daftar semua orang (dulu ia hilang dari daftar
									     rekan), jadi baris inilah yang membedakan "boleh dilanjutkan
									     bergantian" dari "dua orang mengisi tangki yang sama tanpa
									     saling tahu". -->
									<p
										v-if="r.started_by_name"
										class="mt-1 flex items-center gap-1 truncate text-[11px] text-gray-400"
									>
										<Icon name="user" :size="11" class="shrink-0" />
										{{ labels.eirWorkedBy.replace("{name}", r.started_by_name) }}
									</p>
								</div>
							</button>
						</li>
					</ul>
				</div>
			</CollapseSection>

			<!-- Satu bon, beberapa tank: data rujukan (kode booking, EMKL, truk, sopir) sama
			     untuk semuanya, dan itulah yang membuat batch layak dibuka. Banner ini muncul
			     hanya kalau yang dicentang memang satu bon — kalau campur, tidak ada yang
			     boleh dijanjikan "diisi sekali untuk semua". -->
			<div
				v-if="selectMode && selected.size > 1 && sharedVoucher"
				class="flex items-start gap-2 rounded-xl border border-blue-200 bg-blue-50 p-3 text-blue-800"
			>
				<Icon name="info" :size="16" class="mt-0.5 shrink-0" />
				<div class="min-w-0 text-[11px] leading-snug">
					<p class="font-bold">{{ labels.eirBatchVoucherTitle.replace("{n}", selected.size) }}</p>
					<p class="truncate opacity-80">
						<span class="font-mono">{{ sharedVoucher }}</span> · {{ labels.eirBatchVoucherHint }}
					</p>
				</div>
			</div>

			<!-- Sent for review (Pending Review) — field operator submitted, awaiting Admin
			     Ops's Desk Submit. Read-only detail, same as the completed list. -->
			<CollapseSection
				:title="labels.eirReviewList"
				icon="clock"
				tone="text-sky-500"
				chip="bg-sky-100 text-sky-700"
				:count="reviewRows.length"
				:open="openSections.review"
				@update:open="openSections.review = $event"
			>
				<ul v-if="reviewRes.loading && !reviewRows.length" class="space-y-2">
					<li v-for="n in 2" :key="n" class="oak-skeleton h-12 rounded-xl"></li>
				</ul>
				<p v-else-if="!reviewRows.length" class="py-2 text-center text-sm text-gray-400">{{ labels.eirReviewEmpty }}</p>
				<ul v-else class="divide-y divide-gray-100">
					<li v-for="r in reviewRows" :key="r.name">
						<button type="button" class="oak-press flex w-full items-center gap-3 py-2.5 text-left" @click="goCompleted(r)">
							<!-- Inisial orangnya, bukan ikon jam yang sama di setiap baris. Daftar
							     ini branch-scoped: barisnya bisa milik siapa saja, dan "punya siapa
							     yang ini" adalah hal pertama yang ditanya sebelum menariknya
							     kembali. Jatuh balik ke ikon kalau EIR-nya belum berpemilik. -->
							<span class="oak-icon-tile h-9 w-9 shrink-0 bg-sky-50 text-[11px] font-extrabold text-sky-700">
								<template v-if="initials(r.inspector_name)">{{ initials(r.inspector_name) }}</template>
								<Icon v-else name="clock" :size="16" />
							</span>
							<div class="min-w-0 flex-1">
								<div class="flex items-baseline justify-between gap-2">
									<p class="truncate font-bold text-gray-900">{{ r.container_no || r.container }}</p>
									<span class="shrink-0 font-mono text-[10px] text-gray-400">{{ r.inspection_id || r.name }}</span>
								</div>
								<p class="truncate text-[11px] text-gray-500">
									{{ [r.container_principal, r.inspection_type, r.tank_status].filter(Boolean).join(" · ") }}
								</p>
								<p class="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
									<span class="oak-chip shrink-0 bg-sky-100 text-sky-800">{{ labels.eirStatusPendingReview }}</span>
									<LiftOnBadge :survey="r.target_survey_on" :target="r.target_lift_on" :urgent="r.target_urgent_on" />
								</p>
								<!-- Sudah berapa lama menunggu, dan pada siapa. Sebuah antrean review
								     tanpa umur tidak bisa dibedakan mana yang baru masuk dan mana yang
								     tertinggal sejak kemarin. -->
								<p v-if="r.inspector_name || r.modified" class="mt-1 flex items-center gap-1 truncate text-[11px] text-gray-400">
									<Icon name="clock" :size="11" class="shrink-0" />
									{{ [since(r.modified), r.inspector_name].filter(Boolean).join(" · ") }}
								</p>
							</div>
							<Icon name="chevron-right" :size="16" class="shrink-0 text-gray-300" />
						</button>
					</li>
				</ul>
			</CollapseSection>

			<!-- Completed (submitted) EIRs — In & Out -->
			<CollapseSection
				:title="labels.eirCompleteList"
				icon="check-circle"
				tone="text-leaf-600"
				chip="bg-leaf-100 text-leaf-800"
				:count="doneRows.length"
				:open="openSections.done"
				@update:open="openSections.done = $event"
			>
				<ul v-if="doneRes.loading && !doneRows.length" class="space-y-2">
					<li v-for="n in 3" :key="n" class="oak-skeleton h-12 rounded-xl"></li>
				</ul>
				<p v-else-if="!doneRows.length" class="py-2 text-center text-sm text-gray-400">{{ labels.eirCompleteEmpty }}</p>
				<ul v-else class="divide-y divide-gray-100">
					<li v-for="r in doneRows" :key="r.name">
						<button type="button" class="oak-press flex w-full items-center gap-3 py-2.5 text-left" @click="goCompleted(r)">
							<span class="oak-icon-tile h-9 w-9 shrink-0" :class="r.inspection_type === 'EIR-Out' ? 'bg-brand-50 text-brand-600' : 'bg-leaf-50 text-leaf-600'">
								<Icon :name="r.inspection_type === 'EIR-Out' ? 'arrow-up-right' : 'arrow-down-left'" :size="16" />
							</span>
							<div class="min-w-0 flex-1">
								<div class="flex items-baseline justify-between gap-2">
									<p class="truncate font-bold text-gray-900">{{ r.container_no || r.container }}</p>
									<span class="shrink-0 font-mono text-[10px] text-gray-400">{{ r.inspection_id || r.name }}</span>
								</div>
								<p class="truncate text-[11px] text-gray-500">
									{{ [r.container_principal, r.inspection_type, r.tank_status].filter(Boolean).join(" · ") }}
								</p>
								<p v-if="r.inspector_name || r.modified" class="mt-0.5 flex items-center gap-1 truncate text-[11px] text-gray-400">
									<Icon name="clock" :size="11" class="shrink-0" />
									{{ [since(r.modified), r.inspector_name].filter(Boolean).join(" · ") }}
								</p>
							</div>
							<span v-if="r.revision_requested" class="oak-chip shrink-0 bg-orange-100 text-orange-800">{{ labels.eirStatusRevision }}</span>
							<span class="oak-chip shrink-0" :class="r.inspection_type === 'EIR-Out' ? 'bg-brand-100 text-brand-700' : 'bg-leaf-100 text-leaf-800'">
								<Icon :name="r.inspection_type === 'EIR-Out' ? 'arrow-up-right' : 'arrow-down-left'" :size="11" />
								{{ r.inspection_type === 'EIR-Out' ? labels.eirBadgeOut : labels.eirBadgeIn }}
							</span>
							<Icon name="chevron-right" :size="16" class="shrink-0 text-gray-300" />
						</button>
					</li>
				</ul>
				<router-link to="/eir/history" class="oak-link block text-center text-sm">{{ labels.eirListMore }}</router-link>
			</CollapseSection>

			<!-- Aksi utama mode pilih, menempel di bawah: daftar pending bisa panjang, dan
			     tombol yang ikut ter-scroll ke luar layar memaksa operator naik-turun untuk
			     memastikan pilihannya sudah lengkap. -->
			<div
				v-if="selectMode && selected.size"
				class="oak-footer -mx-4 border-t border-gray-200/80 bg-gray-50/95 px-4 py-3 backdrop-blur"
			>
				<button class="oak-btn oak-btn-primary w-full py-3" @click="openBatchNow">
					{{ labels.eirBatchOpenBtn }} · {{ selected.size }} {{ labels.eirBadge }}
				</button>
				<p class="mt-1.5 text-center text-[11px] text-gray-400">{{ labels.eirBatchOpenHint }}</p>
			</div>
		</template>
	</div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { labels } from "@/utils/labels"
import { since } from "@/utils/surveyStatus"
import Icon from "@/components/Icon.vue"
import LiftOnBadge from "@/components/LiftOnBadge.vue"
import EirBatchBar from "@/components/EirBatchBar.vue"
import EirBatchSheet from "@/components/EirBatchSheet.vue"
import CollapseSection from "@/components/CollapseSection.vue"
import { cachedResource } from "@/data/cache"
import { keepScrollForNextNavigation } from "@/router"
import EirInForm from "@/pages/EirInForm.vue"
import EirOutForm from "@/pages/EirOutForm.vue"
import {
	STEP_COUNT,
	batch,
	getStep,
	hasPending,
	hasStep,
	leaveBatch,
	openBatch,
	sentRows,
	tankNo,
} from "@/utils/eirBatch"

const route = useRoute()
const router = useRouter()

// "Budi Santoso" -> "BS". Dipakai sebagai penanda baris, bukan sebagai identitas: nama
// lengkapnya tetap tertulis di baris waktu tepat di bawahnya, jadi inisial yang bertabrakan
// antar dua orang tidak menyesatkan siapa pun — ia cuma membuat baris milik orang yang sama
// terlihat berkelompok saat daftar di-scroll.
function initials(name) {
	const parts = String(name || "").trim().split(/\s+/).filter(Boolean)
	if (!parts.length) return ""
	return (parts[0][0] + (parts[1]?.[0] || "")).toUpperCase()
}

// One EIR menu for both directions. The worklist below merges pending EIR-In and EIR-Out
// (each row badged by type); tapping opens the matching form component.
//
// The open EIR lives in the URL (?e=<name>&t=in|out) — same contract as CleaningOrder's
// ?o= — so a refresh restores the form instead of dropping back to the worklist. The
// direction rides along because the two forms hit different endpoints, so it must
// survive the reload too.
const activeInspection = computed(() => route.query.e || null)
const activeType = computed(() => {
	if (route.query.t === "out") return "EIR-Out"
	if (route.query.t === "in") return "EIR-In"
	// No ?t (hand-typed / shared link): recover the direction from the worklist rather
	// than guessing. Null until it loads — the template shows a skeleton meanwhile.
	return pendingItems.value.find((r) => r.name === route.query.e)?._type || null
})

const search = ref("")
const inItems = ref([])
const outItems = ref([])

// Pending EIR-In (auto-created per container when an Order Bongkar is submitted).
const inRes = cachedResource({
	url: "container_depot.ess.inspections.eir_pending",
	method: "GET",
	makeParams: () => ({ search: search.value || undefined, page_length: 50 }),
	auto: true,
	onSuccess: (data) => (inItems.value = (data.items || []).map((x) => ({ ...x, _type: "EIR-In" }))),
})
// Pending EIR-Out (auto-created per container when an Order Muat is submitted).
const outRes = cachedResource({
	url: "container_depot.ess.inspections.eir_out_pending",
	method: "GET",
	makeParams: () => ({ search: search.value || undefined, page_length: 50 }),
	auto: true,
	onSuccess: (data) => (outItems.value = (data.items || []).map((x) => ({ ...x, _type: "EIR-Out" }))),
})

// --- batch: memilih, membuka, berpindah ---------------------------------------
// "Pilih" mencentang beberapa EIR pending; "Buka batch" menyerahkannya ke utils/eirBatch,
// yang memegang urutan, langkah, papan salin, dan catatan kiriman sampai batch ditutup.
// Tidak perlu Mulai dan tidak perlu submit untuk berpindah antar anggotanya — setiap
// perubahan sudah tersimpan otomatis.
const selectMode = ref(false)
const selected = reactive(new Set())
const sheetOpen = ref(false)
const batchDone = ref(false)
const autoAdvanceTo = ref(null) // EIR berikutnya yang dibuka setelah sebuah submit

// Anggota batch dengan barisnya masing-masing. Yang sudah dikirim tidak ada lagi di
// worklist, jadi barisnya dirakit dari catatan kiriman — bar dan sheet tetap harus bisa
// menunjukkan tank itu ada dan sudah beres.
const batchRows = computed(() =>
	batch.names
		.map((n) => {
			const sent = batch.sent[n]
			const row = pendingItems.value.find((r) => r.name === n)
			if (row) return { ...row, sent }
			return sent ? { name: n, container_no: sent.container_no || tankNo(n), sent } : null
		})
		.filter(Boolean)
)
const activeIndex = computed(() => batchRows.value.findIndex((r) => r.name === activeInspection.value))
// Batch yang masih terbuka saat operator berdiri di daftar — bahan banner "lanjutkan".
const openBatchRows = computed(() =>
	activeInspection.value || batchDone.value || !hasPending() ? [] : batchRows.value
)
const resumeRow = computed(() => openBatchRows.value.find((r) => !r.sent && r._type) || null)
// Isi batch dalam bahasa yang dipakai di lapangan: nomor tank, bukan nomor dokumen.
const openBatchTanks = computed(() => tanksOf(openBatchRows.value))
const activeTanks = computed(() => tanksOf(batchRows.value))
function tanksOf(rows) {
	return rows.map((r) => r.container_no || r.container || tankNo(r.name)).filter(Boolean).join(", ")
}

const openBatchLine = computed(() => {
	const rows = openBatchRows.value
	const sent = rows.filter((r) => r.sent).length
	const parts = [`${rows.length} ${labels.eirBadge}`]
	if (sent) parts.push(`${sent} ${labels.eirBatchSentWord.toLowerCase()}`)
	parts.push(`${rows.length - sent} ${labels.eirBatchTodoWord.toLowerCase()}`)
	return parts.join(" · ")
})
const sentSummary = computed(() => sentRows())

const loadingPending = computed(() => inRes.loading || outRes.loading)
const fetchError = computed(() => {
	const e = inRes.error || outRes.error
	return e ? e.messages?.[0] || e.message : null
})

// Merge both queues, in the same three tiers the server sorts every worklist by
// (container_depot.container_depot.worklist): the customer's lift-on date first, then the
// inspection already in this surveyor's hands, then the rest newest-first.
//
// Re-sorted here at all only because this screen is the one that MERGES two server lists —
// EIR-In and EIR-Out arrive separately, each already ordered, and concatenating them would
// otherwise put every outbound tank below every inbound one. Sorting by anything other than
// the server's own rule is what used to happen here, and it quietly dropped gate-out
// priority off the one screen that most needed it.
const pendingItems = computed(() => {
	const all = [...inItems.value, ...outItems.value]
	const NO_DATE = "9999-12-31" // sorts after every real date, same as the server's sentinel
	// Tanggal survey dulu, baru rencana pickup — cermin `worklist.priority_date`. Kalau
	// keduanya berselisih, layar ini yang salah: server yang memutuskan urutan.
	const due = (r) => String(r.target_survey_on || r.target_lift_on || NO_DATE)
	// ...dan di atas keduanya tanda mendesak — tier 0 di `worklist.sort_by_priority`, diurut
	// memakai tanggal mendesaknya sendiri persis seperti server.
	const urgent = (r) => (r.target_urgent_on ? String(r.target_urgent_on) : "")
	all.sort((a, b) => {
		const flag = Number(!urgent(a)) - Number(!urgent(b))
		if (flag) return flag
		if (urgent(a) && urgent(b)) {
			const u = urgent(a).localeCompare(urgent(b))
			if (u) return u
		}
		const lift = due(a).localeCompare(due(b))
		if (lift) return lift
		const started = Number(!!b.work_started_on) - Number(!!a.work_started_on)
		return started || String(b.creation || "").localeCompare(String(a.creation || ""))
	})
	return all
})

// Arah EIR (masuk / keluar) — saringan halaman, bukan saringan satu daftar: ia dipakai
// keempat bagian di bawah. Pencariannya sendiri dikirim ke server (lihat makeParams di
// tiap resource), jadi kotak cari dan pil arah ini bersama-sama menyaring SATU daftar
// yang kebetulan digambar dalam empat bagian.
const dirFilter = ref("all")
const DIR_FILTERS = computed(() => [
	{ key: "all", label: labels.eirFilterAll },
	{ key: "EIR-In", label: labels.eirBadgeIn },
	{ key: "EIR-Out", label: labels.eirBadgeOut },
])
const byDir = (rows, typeKey) =>
	dirFilter.value === "all" ? rows : rows.filter((r) => r[typeKey] === dirFilter.value)

const visiblePending = computed(() => byDir(pendingItems.value, "_type"))
const reviewRows = computed(() => byDir(reviewItems.value, "inspection_type"))
const doneRows = computed(() => byDir(doneItems.value, "inspection_type"))

// Empat bagian, masing-masing bisa ditutup: pekerjaan yang sedang dipegang seseorang,
// yang belum disentuh, yang sudah dikirim ke Adm Ops, dan yang sudah selesai. Sebelumnya
// ketiganya berdesakan di satu halaman yang tidak bisa dipendekkan, dan bagian "sedang
// dikerjakan" tidak ada sama sekali — ia tercampur di antrean "menunggu dikerjakan",
// tempat yang persis salah untuk tank yang sudah ada orangnya.
const pendingSections = computed(() => {
	const rows = visiblePending.value
	return [
		{
			key: "doing", title: labels.sectionDoing, icon: "play-circle",
			tone: "text-brand-500", chip: "bg-brand-100 text-brand-700",
			rows: rows.filter((r) => r.work_started_on), empty: labels.eirFilterEmptyStarted,
		},
		{
			key: "todo", title: labels.sectionTodo, icon: "search-check",
			tone: "text-amber-500", chip: "bg-amber-100 text-amber-800",
			rows: rows.filter((r) => !r.work_started_on), empty: labels.eirFilterEmptyNotStarted,
		},
	]
})

// Yang terbuka saat halaman dibuka: pekerjaan yang belum lepas tangan. Review dan Selesai
// tertutup — keduanya bacaan, bukan antrean, dan kepalanya sudah menyebut jumlahnya.
const openSections = reactive({ doing: true, todo: true, review: false, done: false })

// ?s=doing|todo|review|done — dikirim kartu Beranda ("EIR review" mendarat di bagian
// review-nya, terbuka sendiri, sisanya tertutup). Tanpa ini kartu itu cuma membuka halaman
// EIR dan operator harus mencari sendiri daftar yang angkanya barusan ia tekan.
onMounted(() => {
	const want = String(route.query.s || "")
	// hasOwnProperty, bukan `in`: `?s=toString` lolos dari `in` dan akan menutup keempat
	// bagian sekaligus.
	if (!Object.prototype.hasOwnProperty.call(openSections, want)) return
	Object.keys(openSections).forEach((k) => (openSections[k] = k === want))
})

/** Kalimat kosong satu bagian — yang menyebut saringan arah kalau memang itu penyebabnya. */
function emptyFor(s) {
	if (pendingItems.value.length) {
		if (dirFilter.value === "EIR-In") return labels.eirFilterEmptyIn
		if (dirFilter.value === "EIR-Out") return labels.eirFilterEmptyOut
	}
	return s.empty
}

// Sejauh mana satu EIR sudah dikerjakan. Langkahnya hanya dicetak untuk EIR yang memang
// pernah dibuka di sesi ini — "Draft 1/4" untuk tank yang dimulai rekan kemarin adalah
// tebakan, dan tebakan di worklist dibaca sebagai fakta.
function progressChip(r) {
	if (!r.work_started_on) return { label: labels.eirBatchNotStarted, tone: "bg-gray-100 text-gray-500" }
	if (hasStep(r.name))
		return {
			label: `${labels.eirDraftStep} ${getStep(r.name) + 1}/${STEP_COUNT}`,
			tone: "bg-brand-100 text-brand-700",
		}
	return { label: labels.eirChipStarted, tone: "bg-amber-100 text-amber-800" }
}

// Bon yang sama untuk semua yang dicentang — atau kosong kalau campur.
const sharedVoucher = computed(() => {
	const vouchers = new Set(
		pendingItems.value.filter((r) => selected.has(r.name)).map((r) => r.referred_voucher || "")
	)
	return vouchers.size === 1 ? [...vouchers][0] : ""
})

let searchTimer = null
function onSearchInput() {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(reloadLists, 300)
}
// Satu kotak cari untuk empat daftar — jadi satu ketikan menyegarkan keempatnya.
function reloadLists() {
	inRes.reload()
	outRes.reload()
	reviewRes.reload()
	doneRes.reload()
}

// Landing "recently submitted" — the caller's own latest completed EIRs (In & Out),
// newest first (no date filter). Tapping one opens its read-only detail (+ revision).
const LANDING_LIMIT = 5
const doneItems = ref([])
const doneRes = cachedResource({
	url: "container_depot.ess.inspections.eir_history",
	method: "GET",
	makeParams: () => ({ docstatus: 1, page_length: LANDING_LIMIT, search: search.value || undefined }),
	auto: true,
	onSuccess: (data) => (doneItems.value = data.items || []),
})

// "Diajukan Review" — the caller's own EIRs sent for review (Pending Review, still
// docstatus 0), awaiting Admin Ops's Desk Submit. Read-only, opened like a completed one.
const reviewItems = ref([])
const reviewRes = cachedResource({
	url: "container_depot.ess.inspections.eir_pending_review",
	method: "GET",
	makeParams: () => ({ page_length: 20, search: search.value || undefined }),
	auto: true,
	onSuccess: (data) => (reviewItems.value = data.items || []),
})

function goItem(r) {
	router.push({ query: { e: r.name, t: r._type === "EIR-Out" ? "out" : "in" } })
}
// Completed EIRs are read-only: open the History detail (which carries the revision button).
function goCompleted(r) {
	router.push({ path: "/eir/history", query: { open: r.name } })
}
// Prev/next within the batch — keep the scroll position so moving between EIRs lands
// on the SAME section (e.g. the photos) instead of jumping back to the top. The next form
// re-mounts (collapsing height), so we re-apply the saved offset over a few frames until the
// page is tall enough to reach it again.
function goRel(delta) {
	// Yang sudah dikirim dilewati: ia masih anggota batch (dan masih punya setrip di bar),
	// tapi tidak ada lagi yang bisa dikerjakan di sana.
	const queue = batchRows.value.filter((r) => !r.sent)
	if (queue.length < 2) return
	const i = queue.findIndex((r) => r.name === activeInspection.value)
	// Wrap around: Next on the last EIR loops back to the first (and Prev on the first to
	// the last), so you can keep cycling the batch without hitting a dead end.
	const target = queue[(Math.max(0, i) + delta + queue.length) % queue.length]
	if (!target || target.name === activeInspection.value) return
	keepScrollForNextNavigation()
	restoreScrollTo(window.scrollY)
	goItem(target)
}
function restoreScrollTo(y) {
	if (y <= 0) return
	let tries = 0
	const tick = () => {
		const maxY = document.documentElement.scrollHeight - window.innerHeight
		if (maxY >= y - 2 || tries >= 90) {
			window.scrollTo(0, Math.min(y, Math.max(0, maxY)))
			// One late re-apply catches images/thumbnails that settle after first paint.
			if (tries < 90) setTimeout(() => window.scrollTo(0, Math.min(y, Math.max(0, document.documentElement.scrollHeight - window.innerHeight))), 250)
			return
		}
		tries++
		requestAnimationFrame(tick)
	}
	requestAnimationFrame(tick)
}

// Tank lain di bon yang sama dan masih harus dikerjakan — termasuk tank ini sendiri.
// Satu bon = satu truk (gate menerbitkannya untuk maksimal dua tank), jadi himpunan
// inilah batch-nya: tidak ada yang perlu dipilih untuk membuatnya ada.
function bonMates(r) {
	if (!r.referred_voucher) return [r]
	return pendingItems.value.filter((x) => x.referred_voucher === r.referred_voucher)
}
// Berapa tank yang dibawa tiap bon — dihitung sekali per daftar, bukan sekali per baris:
// chip "Batch 2" di bawah menanyakannya untuk setiap baris yang digambar.
const bonCount = computed(() => {
	const m = {}
	pendingItems.value.forEach((r) => {
		if (r.referred_voucher) m[r.referred_voucher] = (m[r.referred_voucher] || 0) + 1
	})
	return m
})
function bonSize(r) {
	return (r.referred_voucher && bonCount.value[r.referred_voucher]) || 1
}

// Worklist tap: select in batch mode, otherwise open the EIR.
function rowClick(r) {
	if (selectMode.value) {
		if (selected.has(r.name)) selected.delete(r.name)
		else selected.add(r.name)
		return
	}
	// Menekan anggota batch yang sedang terbuka = melanjutkan batch itu, bukan
	// membubarkannya.
	if (batch.names.includes(r.name)) {
		goItem(r)
		return
	}
	// Tank di luar batch: batch lama ditutup dan bon tank ini yang menggantikannya —
	// otomatis, kalau bonnya memang membawa lebih dari satu tank. Batch tidak lagi harus
	// disusun dengan tangan, dan karena langkah/kiriman tiap EIR tersimpan per EIR (lihat
	// utils/eirBatch), berpindah bolak-balik antar bon tidak menghapus kemajuan mana pun.
	const mates = bonMates(r)
	if (mates.length > 1) {
		openBatch(
			mates.map((m) => ({ name: m.name, container_no: m.container_no || m.container })),
			r.referred_voucher || ""
		)
	} else {
		leaveBatch()
	}
	goItem(r)
}
function toggleSelectMode() {
	selectMode.value = !selectMode.value
	selected.clear()
}
/** "Pilih semua" satu bagian — bukan seluruh halaman: bagian itulah yang sedang dilihat. */
function selectAll(rows) {
	rows.forEach((r) => selected.add(r.name))
}

// Buka EIR yang dicentang sebagai satu batch, urut seperti di worklist, lalu mendarat di
// yang pertama. Tidak ada Mulai dan tidak ada submit di sini: keduanya milik tiap EIR.
function openBatchNow() {
	const members = pendingItems.value.filter((r) => selected.has(r.name))
	if (!members.length) return
	openBatch(
		members.map((r) => ({ name: r.name, container_no: r.container_no || r.container })),
		sharedVoucher.value
	)
	selectMode.value = false
	selected.clear()
	goItem(members[0])
}
// Keluar dari batch (dari sheet) dan kembali ke daftar.
function clearBatch() {
	sheetOpen.value = false
	leaveBatch()
	if (route.query.e) router.push({ query: {} })
}
// Tombol di layar batch selesai: tutup batch, lalu diam di daftar atau langsung memilih
// batch berikutnya (truk berikutnya biasanya sudah menunggu).
function finishBatch(pickAnother) {
	leaveBatch()
	batchDone.value = false
	selectMode.value = pickAnother
	selected.clear()
	reloadLists()
}

function onBack() {
	// After a submit the child emits `submitted` (which queued the next EIR) then `back`.
	const next = autoAdvanceTo.value
	autoAdvanceTo.value = null
	if (next) {
		goItem(next) // lanjut ke anggota batch berikutnya
		reloadLists()
		return
	}
	// Batch yang seluruh anggotanya sudah terkirim berhenti di layar penutupnya, bukan di
	// worklist: itu satu-satunya tempat ringkasan truk tadi masih ada.
	if (batch.names.length && !hasPending()) batchDone.value = true
	if (route.query.e) router.push({ query: {} })
	reloadLists()
}
function onSubmitted(name) {
	// Anggota berikutnya yang belum dikirim — dihitung SEBELUM daftar disegarkan (form sudah
	// mencatat kiriman ini ke batch, jadi ia sendiri sudah tidak masuk hitungan).
	const queue = batchRows.value.filter((r) => !r.sent && r.name !== name)
	autoAdvanceTo.value = queue[0] || null
}

// Nomor batch berganti (batch baru dibuka) — layar penutup yang lama tidak boleh tertinggal.
watch(
	() => batch.names.join(","),
	() => (batchDone.value = false)
)

function doneLine(r) {
	const parts = [
		`${r.damages || 0} ${labels.eirReviewDamage}`,
		`${r.photos || 0} ${labels.eirReviewPhotos}`,
	]
	if (r.minutes) parts.push(`${r.minutes} ${labels.eirMinutes}`)
	return parts.join(" · ")
}
</script>
