<template>
	<!-- Diam kalau yang terakhir menyentuhnya adalah pemakai layar ini sendiri: form
	     menyimpan otomatis tiap beberapa detik, dan baris "diubah oleh saya" yang muncul
	     terus-menerus akan dibaca sebagai hiasan lalu diabaikan — termasuk pada saat ia
	     akhirnya menyebut nama orang lain. -->
	<p
		v-if="show"
		class="flex items-center gap-1.5 rounded-lg bg-amber-50 px-2.5 py-1.5 text-[11px] text-amber-800"
	>
		<Icon name="user" :size="12" class="shrink-0" />
		<span class="min-w-0 truncate">
			{{ labels.orderEditedBy.replace("{name}", name || by) }}
			<span v-if="at" class="opacity-70">· {{ since(at) }}</span>
		</span>
	</p>
</template>

<script setup>
// Siapa yang terakhir mengubah order ini.
//
// Sejak pagar klaim dicabut (2026-09-10) satu order boleh dipegang bergantian: ia tidak lagi
// hilang dari worklist rekan, dan dua HP boleh membuka form yang sama. Servernya memang
// mencatat semuanya — `modified_by` plus satu baris Version tiap simpan, terbaca di timeline
// Desk — tapi catatan yang hanya ada di Desk tidak menolong orang yang sedang berdiri di
// samping tangki. Baris ini adalah catatan itu, dibawa ke layar tempat kejadiannya.
//
// Amber, bukan abu-abu: ini bukan metadata: isian yang muncul di form ini ditulis orang lain,
// dan itu hal yang harus terbaca sebelum ditimpa.
import { computed } from "vue"
import { session } from "@/data/session"
import { labels } from "@/utils/labels"
import { since } from "@/utils/surveyStatus"
import Icon from "@/components/Icon.vue"

const props = defineProps({
	by: { type: String, default: "" }, // login-nya, untuk membandingkan dengan pemakai layar
	name: { type: String, default: "" }, // nama yang dibaca orang
	at: { type: String, default: "" }, // kapan (waktu server)
})
const show = computed(() => !!props.by && props.by !== session.user)
</script>
