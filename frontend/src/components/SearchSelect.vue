<template>
	<div ref="root" class="relative">
		<!-- Trigger: looks like an oak-input, shows the selected label or the placeholder. -->
		<button ref="trigger" type="button" class="oak-input flex w-full items-center justify-between gap-2 text-left disabled:cursor-not-allowed disabled:opacity-60" :class="triggerClass" :disabled="disabled" @click="toggle">
			<span :class="selectedLabel ? 'text-gray-900' : 'text-gray-400'" class="truncate">
				{{ selectedLabel || placeholder }}
			</span>
			<Icon name="chevron-down" :size="16" class="shrink-0 text-gray-400 transition-transform" :class="{ 'rotate-180': open }" />
		</button>

		<!-- Dropdown teleported to <body> and fixed-positioned so it is never clipped by a
		     scrolling/overflow-hidden ancestor (e.g. the checklist scroller). -->
		<Teleport to="body">
			<div
				v-if="open"
				ref="panel"
				class="flex flex-col overflow-hidden rounded-xl border border-gray-200 bg-white shadow-card"
				:style="panelStyle"
			>
				<div class="border-b border-gray-100 p-2">
					<div class="relative">
						<span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400"><Icon name="search" :size="15" /></span>
						<input
							ref="searchInput"
							v-model="query"
							type="text"
							:placeholder="searchPlaceholder"
							class="oak-input py-2 pl-8 text-sm"
							@keydown.down.prevent="move(1)"
							@keydown.up.prevent="move(-1)"
							@keydown.enter.prevent="pickHighlighted"
							@keydown.esc.prevent="close"
						/>
					</div>
				</div>
				<ul class="min-h-0 flex-1 overflow-y-auto overscroll-contain py-1">
					<li>
						<button type="button" class="flex w-full items-center px-3 py-2 text-left text-sm text-gray-400 hover:bg-gray-50" @click="pick(null, '')">
							— {{ clearLabel || placeholder }} —
						</button>
					</li>
					<template v-for="row in view" :key="row.key">
						<li v-if="row.type === 'group'" class="sticky top-0 bg-gray-50/95 px-3 py-1 text-[11px] font-bold uppercase tracking-wide text-gray-500 backdrop-blur">
							{{ row.label }}
						</li>
						<li v-else>
							<button
								type="button"
								class="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-gray-50"
								:class="[row.index === highlight ? 'bg-brand-50' : '', valueOf(row.opt) === modelValue ? 'font-semibold text-brand-600' : 'text-gray-700']"
								@click="pick(row.opt)"
								@mousemove="highlight = row.index"
							>
								<span class="truncate">{{ labelOf(row.opt) }}</span>
								<Icon v-if="valueOf(row.opt) === modelValue" name="check" :size="15" class="shrink-0 text-brand-600" />
							</button>
						</li>
					</template>
					<li v-if="!filtered.length" class="px-3 py-3 text-center text-sm text-gray-400">{{ emptyLabel }}</li>
				</ul>
			</div>
		</Teleport>
	</div>
</template>

<script setup>
// Lightweight searchable select (Select2-style) — pure Vue, no external dependency.
// Options may be plain strings OR objects; pass optionValue/optionLabel for objects, and
// groupBy to render section headers. The panel teleports to <body> so it works inside any
// overflow container. Global listeners are attached only while open.
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue"
import Icon from "@/components/Icon.vue"

const props = defineProps({
	modelValue: { type: [String, Number], default: "" },
	options: { type: Array, default: () => [] },
	optionValue: { type: Function, default: null }, // (opt) => value ; default: opt.value | opt
	optionLabel: { type: Function, default: null }, // (opt) => label ; default: opt.label | opt
	groupBy: { type: Function, default: null }, // (opt) => group name (optional)
	placeholder: { type: String, default: "Pilih…" },
	searchPlaceholder: { type: String, default: "Cari…" },
	clearLabel: { type: String, default: "" },
	emptyLabel: { type: String, default: "Tidak ada hasil." },
	triggerClass: { type: String, default: "" },
	disabled: { type: Boolean, default: false },
})
const emit = defineEmits(["update:modelValue"])

const root = ref(null)
const trigger = ref(null)
const panel = ref(null)
const searchInput = ref(null)
const open = ref(false)
const query = ref("")
const highlight = ref(-1)
const panelStyle = ref({})

function valueOf(o) {
	if (props.optionValue) return props.optionValue(o)
	return o && typeof o === "object" ? o.value : o
}
function labelOf(o) {
	if (props.optionLabel) return props.optionLabel(o)
	return o && typeof o === "object" ? o.label : o
}

const selectedLabel = computed(() => {
	if (props.modelValue === "" || props.modelValue == null) return ""
	const found = props.options.find((o) => valueOf(o) === props.modelValue)
	return found != null ? labelOf(found) : String(props.modelValue)
})

const filtered = computed(() => {
	const q = query.value.trim().toLowerCase()
	if (!q) return props.options
	return props.options.filter((o) => String(labelOf(o)).toLowerCase().includes(q))
})

// Rows to render: option rows carry a flat `index` (for keyboard nav); group headers are
// inserted when groupBy is set and the group changes.
const view = computed(() => {
	const out = []
	let lastGroup = null
	filtered.value.forEach((opt, index) => {
		if (props.groupBy) {
			const g = props.groupBy(opt)
			if (g !== lastGroup) {
				out.push({ type: "group", label: g, key: `g:${g}:${index}` })
				lastGroup = g
			}
		}
		out.push({ type: "option", opt, index, key: `o:${valueOf(opt)}:${index}` })
	})
	return out
})

watch(filtered, () => {
	highlight.value = filtered.value.length ? 0 : -1
})

function positionPanel() {
	const el = trigger.value
	if (!el) return
	const r = el.getBoundingClientRect()
	const vw = window.innerWidth
	const vh = window.innerHeight
	const width = Math.max(r.width, 240)
	let left = r.left
	if (left + width > vw - 8) left = Math.max(8, vw - 8 - width)
	const below = vh - r.bottom
	const above = r.top
	const useAbove = below < 300 && above > below
	const maxHeight = Math.max(160, Math.min(320, (useAbove ? above : below) - 12))
	panelStyle.value = {
		position: "fixed",
		left: `${left}px`,
		width: `${width}px`,
		maxHeight: `${maxHeight}px`,
		zIndex: 60,
		...(useAbove ? { bottom: `${vh - r.top + 4}px` } : { top: `${r.bottom + 4}px` }),
	}
}

function toggle() {
	if (props.disabled) return
	open.value ? close() : openPanel()
}
function openPanel() {
	open.value = true
	query.value = ""
	nextTick(() => {
		positionPanel()
		searchInput.value?.focus()
	})
	document.addEventListener("click", onDocClick, true)
	window.addEventListener("scroll", positionPanel, true)
	window.addEventListener("resize", positionPanel)
}
function close() {
	open.value = false
	document.removeEventListener("click", onDocClick, true)
	window.removeEventListener("scroll", positionPanel, true)
	window.removeEventListener("resize", positionPanel)
}
function pick(opt, raw) {
	emit("update:modelValue", opt === null ? raw ?? "" : valueOf(opt))
	close()
}
function move(dir) {
	if (!filtered.value.length) return
	highlight.value = (highlight.value + dir + filtered.value.length) % filtered.value.length
}
function pickHighlighted() {
	if (highlight.value >= 0 && highlight.value < filtered.value.length) pick(filtered.value[highlight.value])
}

// Close when clicking outside both the trigger and the (teleported) panel.
function onDocClick(e) {
	if (!open.value) return
	const inTrigger = root.value && root.value.contains(e.target)
	const inPanel = panel.value && panel.value.contains(e.target)
	if (!inTrigger && !inPanel) close()
}

onBeforeUnmount(close)
</script>
