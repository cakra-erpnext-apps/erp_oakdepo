import { pill } from "@/utils/statusPill"

// Chip satu Cleaning Order, sama dengan cleaning_order_list.js di Desk — teksnya ikut, supaya
// tetap terbaca walau warnanya pudar di bawah matahari.
const CHIPS = {
	Pending: pill("ready"),
	In_Progress: pill("doing"),
	"Pending Review": pill("review"),
	Completed: pill("done"),
	Cancelled: pill("cancelled"),
}
// Service Setup: Admin Ops belum memilih metode — draf-nya order cuci.
const DRAFT = pill("draft")
export function cleaningChip(o) {
	return CHIPS[o?.status] || DRAFT
}
