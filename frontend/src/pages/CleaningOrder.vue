<template>
	<!-- /cleaning = daftar; /cleaning?o=<name> = satu order. Alamat detailnya sengaja tetap
	     query, bukan path: notifikasi (notification_routes._cleaning) dan tautan lama sudah
	     menunjuk ke sana. -->
	<CleaningDetail v-if="route.query.o" />
	<CleaningList v-else />
</template>

<script setup>
import { useRoute } from "vue-router"
import CleaningDetail from "@/pages/CleaningDetail.vue"
import CleaningList from "@/pages/CleaningList.vue"

const route = useRoute()
</script>
