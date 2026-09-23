import { labels } from "@/utils/labels"

// Chip satu Leak Check: belum dicek, atau hasilnya (aman / bocor).
export function leakChip(o) {
	if (o.status === "Open") return { label: labels.leakStatOpen, cls: "bg-amber-100 text-amber-800" }
	return o.has_leak
		? { label: labels.leakFlag, cls: "bg-red-100 text-red-700" }
		: { label: labels.leakSafe, cls: "bg-leaf-100 text-leaf-700" }
}
