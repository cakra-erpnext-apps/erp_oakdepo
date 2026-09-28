import { labels } from "@/utils/labels"
import { pill, tone } from "@/utils/statusPill"

// Chip satu Leak Check, sama dengan leak_check_list.js: belum dicek, atau hasilnya (aman / bocor).
export function leakChip(o) {
	if (o.status === "Open") return pill("ready")
	return o.has_leak
		? { label: labels.leakFlag, cls: tone("red") }
		: { label: labels.leakSafe, cls: tone("green") }
}
