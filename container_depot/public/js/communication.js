// Email → Order.
//
// An incoming email (Communication, medium Email, Received) is the reference behind the two
// things a customer books by mail — tanks coming in or going out — and it almost never names
// one tank. Both become a Container Booking; the direction is what tells them apart (the
// outbound half used to raise a Gate Out Plan, a separate notice that authorised nothing).
// So "Buat Order" opens a dialog, not a form: the email body stays on screen on the left
// while the container list is built on the
// right in the same grid shape Container Booking uses (Container picker + the tank's last
// cargo), filled from the mail, from an .xlsx, or by pasting a block straight out of Excel.
// Every row is a real Container master: a number with none is reported, never carried along
// as loose text — a tank the depot has no record of is how a typo becomes a phantom.
//
// Both orders hold their tanks in a child table, so submitting always means the same thing:
// one fresh, UNSAVED form with a row per container. Nothing is written; you save it.
//
// See container_depot/mail_to_order.py for everything the server does here.

const ORDER_TYPES = [
	{ key: "Booking", doctype: "Container Booking", label: __("Booking (Tank In)") },
	{ key: "Gate Out", doctype: "Container Booking", label: __("Gate Out (Tank Out)") },
];

// Extra dialog fields per order type, and which of them the order's *child rows* make
// mandatory — asking once here beats typing the same date into twenty grid rows, and a
// row-mandatory field left blank would only block the save later.
// The outbound type does NOT offer a Direction picker: choosing "Gate Out" IS the choice.
const TYPE_FIELDS = {
	"Booking": ["direction", "reff_doc", "estimation_date"],
	// The outbound half also asks who surveys the tanks and when — one answer for the whole
	// mail, copied onto every row and still editable per tank on the booking form.
	"Gate Out": ["reff_doc", "estimation_date", "survey_date", "surveyor"],
};
const ROW_REQUIRED = { "Booking": ["estimation_date"], "Gate Out": ["estimation_date"] };
const ALL_TYPE_FIELDS = [
	"direction", "reff_doc", "estimation_date", "survey_date", "surveyor",
];

function type_by_key(key) {
	return ORDER_TYPES.find((t) => t.key === key);
}

// Same normalisation the server does (mail_to_order._normalise) — kept here only to match
// a grid row back to the row the server answered about.
function normalise_no(value) {
	return String(value || "").replace(/[\s-]+/g, "").toUpperCase();
}

// --- the email, readable while you work ------------------------------------------
// Rendered from the doc already in memory (no extra fetch). Scripts and styles are
// stripped: a customer's mail is untrusted HTML and this renders inside the desk.
//
// The styles ship with this file rather than the app stylesheet: they are what makes the
// dialog legible at all, and a browser holding a cached .css must not be able to strip
// them off. Injected once per session, keyed by id.
const MAIL_STYLE_ID = "oak-mail-style";

function ensure_mail_style() {
	if (document.getElementById(MAIL_STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = MAIL_STYLE_ID;
	// The body is rendered on a forced LIGHT card, in both desk themes. Customer mail
	// carries its own inline colours written for a white background — black text, dark
	// signatures, transparent PNG logos — so painting it on the dark theme's surface is
	// what made it unreadable. Its own palette is left untouched; only the paper is fixed.
	style.textContent = `
		.oak-mail-body {
			color-scheme: light;
			background-color: #ffffff;
			color: #1f272e;
			max-height: min(55vh, 520px);
			overflow: auto;
			overflow-wrap: anywhere;
			padding: 12px;
			border: 1px solid var(--border-color);
			border-radius: var(--border-radius);
		}
		.oak-mail-body img { max-width: 100%; height: auto; }
		.oak-mail-body table { max-width: 100%; }
		.oak-mail-empty { color: #6c7680; }

		/*
		 * The same paper for the email on the Communication form itself, which renders the
		 * customer's HTML in the read-only editor and had the identical dark-mode problem.
		 * Only the read view: while the mail is still editable it stays a desk field.
		 */
		.oak-mail-form [data-fieldname="content"] .ql-editor.read-mode {
			color-scheme: light;
			background-color: #ffffff;
			color: #1f272e;
			padding: 12px;
			border: 1px solid var(--border-color);
			border-radius: var(--border-radius);
			overflow-wrap: anywhere;
		}
		.oak-mail-form [data-fieldname="content"] .ql-editor.read-mode img { max-width: 100%; height: auto; }
	`;
	document.head.appendChild(style);
}

function email_preview_html(doc) {
	const esc = frappe.utils.escape_html;
	const body = frappe.dom.remove_script_and_style(doc.content || "");
	const when = doc.communication_date ? frappe.datetime.str_to_user(doc.communication_date) : "";
	return `
		<div class="oak-mail">
			<div class="bold">${esc(doc.subject || __("(tanpa subjek)"))}</div>
			<div class="text-muted small mb-2">${esc(doc.sender || "-")}${when ? " · " + esc(when) : ""}</div>
			<div class="oak-mail-body">${
				body || `<span class="oak-mail-empty">${__("Email ini tidak punya isi.")}</span>`
			}</div>
		</div>`;
}

// --- what the container list adds up to -------------------------------------------
// Per-row state is shown in the grid's own Status column; this is the sentence under it.
function summary_line(rows, type) {
	const n = rows.length;
	if (!n) return __("Isi minimal satu nomor container.");
	return __("{0} container → 1 form {1} ({0} baris), belum disimpan.", [n, __(type.doctype)]);
}

// Two different complaints, said separately because the fix differs: a row the booking's
// own direction gate refuses (a Tank Out that cannot leave, a Tank In already in the
// depot), and a number from the mail or a file that has no master to become a row at all.
function notice_html(rows, missing) {
	const esc = frappe.utils.escape_html;
	const blocked = rows.filter((r) => r.blocked).length;
	const lines = [];
	if (blocked) {
		lines.push(
			`<div class="text-danger small">${__(
				"{0} container tidak bisa dipakai untuk arah ini — lihat kolom Status.",
				[blocked]
			)}</div>`
		);
	}
	if (missing.length) {
		lines.push(`
			<div class="text-danger small">${__("{0} nomor belum ada di master Container:", [missing.length])}
				${missing.map(esc).join(", ")}</div>
			<div class="text-muted small">${__(
				"Buat masternya dulu — bisa lewat \"+ Create New\" di kolom Container — lalu barisnya ikut menyusul sendiri."
			)}</div>`);
	}
	return lines.length ? `${lines.join("")}<div class="mb-2"></div>` : "";
}

function primary_label(type) {
	return __("Buka Form {0}", [__(type.doctype)]);
}

// --- opening the prefilled (unsaved) form -----------------------------------------
function open_prefilled(res) {
	frappe.model.with_doctype(res.doctype, () => {
		const doc = frappe.model.get_new_doc(res.doctype);
		Object.assign(doc, res.values || {});
		if (res.table) {
			for (const values of res.table.rows) {
				const row = frappe.model.add_child(doc, res.table.doctype, res.table.fieldname);
				Object.assign(row, values);
			}
		}
		frappe.set_route("Form", res.doctype, doc.name);
	});
}

// --- the dialog -------------------------------------------------------------------
function open_order_dialog(frm, preset_key) {
	ensure_mail_style();

	// The grid's model. A dialog grid (no frm) reads and writes this array in place, so it
	// is the one copy of the container list — everything below pushes into it and refreshes.
	const grid_rows = [];
	let resolved = [];
	// Numbers seen in the mail / an imported file that have no master yet — tracked so the
	// notice under the grid stays true, and so the row appears by itself once one is made.
	let missing = [];

	// The grid's columns, held by reference: Last Cargo is only a booking line's own field,
	// so it is editable there and read-only context everywhere else, and `onchange` is what
	// re-resolves the list (a column's onchange fires for every row, see
	// frappe/form/grid_row.js). Declared before the dialog because both need them.
	const grid_columns = [
		{
			fieldname: "container",
			fieldtype: "Link",
			options: "Container",
			label: __("Container"),
			in_list_view: 1,
			columns: 5,
			onchange: () => debounced_resolve(),
			// Scoped to the Tank Owner picked in the header: one owner's fleet is a list you
			// can pick from, the whole depot's is not. A Tank Out is narrowed further to
			// tanks that are physically here (container_status.PRESENT) — it can only take
			// out what is in the yard. Whether one of those is actually free to leave is the
			// server's call, not a Link filter: readiness is the absence of open work.
			get_query: () => {
				const filters = {};
				const principal = dialog.get_value("principal");
				if (principal) filters.principal = principal;
				if (current_type().key === "Booking" && dialog.get_value("direction") === "Tank Out") {
					filters.status = ["in", ["In_Depot", "Available"]];
				}
				return Object.keys(filters).length ? { filters } : {};
			},
		},
		{
			fieldname: "cargo",
			fieldtype: "Link",
			options: "Cargo",
			label: __("Last Cargo"),
			in_list_view: 1,
			columns: 3,
		},
		{
			fieldname: "status_label",
			fieldtype: "Data",
			label: __("Status"),
			read_only: 1,
			in_list_view: 1,
			columns: 2,
		},
	];
	const cargo_column = grid_columns.find((f) => f.fieldname === "cargo");

	const dialog = new frappe.ui.Dialog({
		title: __("Buat Order dari Email"),
		size: "extra-large",
		fields: [
			{ fieldtype: "HTML", fieldname: "email_preview" },
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Select",
				fieldname: "order_type",
				label: __("Tipe Order"),
				reqd: 1,
				default: preset_key,
				options: ORDER_TYPES.filter((t) => frappe.model.can_create(t.doctype)).map((t) => ({
					value: t.key,
					label: t.label,
				})),
			},
			{
				fieldtype: "Select",
				fieldname: "direction",
				label: __("Arah"),
				options: ["Tank In", "Tank Out"],
				default: "Tank In",
			},
			{
				fieldtype: "Link",
				fieldname: "principal",
				options: "Customer",
				label: __("Principal / Tank Owner"),
				description: __("Menyaring pilihan container di grid."),
				onchange: () => grid.refresh(),
			},
			{
				fieldtype: "Data",
				fieldname: "reff_doc",
				label: __("No. Dokumen"),
				description: __("Nomor dokumen pelanggan yang tertulis di email (opsional)."),
			},
			{ fieldtype: "Date", fieldname: "estimation_date", label: __("Tanggal Rencana") },
			{ fieldtype: "Date", fieldname: "survey_date", label: __("Survey Date") },
			{
				fieldtype: "Link",
				fieldname: "surveyor",
				label: __("Surveyor"),
				options: "Customer",
				get_query: () => ({ filters: { is_surveyor: 1 } }),
			},
			{
				fieldtype: "Table",
				fieldname: "containers",
				label: __("Containers"),
				editable_grid: 1,
				data: grid_rows,
				get_data: () => grid_rows,
				fields: grid_columns,
			},
			{ fieldtype: "HTML", fieldname: "containers_status" },
		],
	});

	const grid = dialog.fields_dict.containers.grid;
	dialog.fields_dict.email_preview.$wrapper.html(email_preview_html(frm.doc));

	function current_type() {
		return type_by_key(dialog.get_value("order_type")) || type_by_key(preset_key);
	}

	function paint() {
		const type = current_type();
		// A field the child rows make mandatory is only mandatory once there ARE rows —
		// opening a blank form from an email must not be gated behind a date.
		for (const field of ROW_REQUIRED[type.key] || []) {
			dialog.set_df_property(field, "reqd", resolved.length ? 1 : 0);
		}
		dialog.fields_dict.containers_status.$wrapper.html(
			`${notice_html(resolved, missing)}<div class="text-muted small">${summary_line(resolved, type)}</div>`
		);
		dialog.set_primary_action(primary_label(type), (values) => submit(values));
	}

	function sync_type() {
		const type = current_type();
		const shown = TYPE_FIELDS[type.key] || [];
		for (const field of ALL_TYPE_FIELDS) {
			// reqd is checked even on a hidden field, so a field going out of view has to
			// drop its mandatory flag with it (paint() puts it back when it applies).
			dialog.set_df_property(field, "hidden", shown.includes(field) ? 0 : 1);
			dialog.set_df_property(field, "reqd", 0);
		}
		// Only a booking line carries its own cargo (Container Booking Item.cargo). Elsewhere
		// the column still says what the tank last held — worth knowing when reading a
		// cleaning request — but editing it would write nowhere, so it is read-only.
		// The grid reads these very objects (docfields === df.fields) but caches the column
		// layout, so that cache goes with the change.
		cargo_column.read_only = type.key === "Booking" ? 0 : 1;
		grid.visible_columns = undefined;
		grid.refresh();
		resolve_grid();
	}

	// Ask the server about every row, then write the answer back into the grid: the picked
	// Container fills in the number, a recognised number fills in the Container link, and
	// the Status column says what the master knows. One call for the whole list.
	function resolve_grid() {
		// The tracked missing numbers ride along: whoever creates one of those masters (here
		// via "+ Create New", or in another tab) gets it added on the next resolve instead of
		// having to remember it.
		const numbers = [
			...grid_rows.map((r) => normalise_no(r.container_no || r.container)).filter(Boolean),
			...missing,
		];
		if (!numbers.length) {
			resolved = [];
			paint();
			return;
		}
		frappe.call({
			method: "container_depot.container_depot.mail_to_order.resolve_containers",
			args: {
				containers: numbers,
				order_type: current_type().key,
				direction: dialog.get_value("direction"),
			},
		}).then((r) => {
			const info = {};
			(r.message || []).forEach((row) => (info[row.container_no] = row));

			const arrived = missing.filter((n) => info[n] && info[n].known);
			missing = missing.filter((n) => !(info[n] && info[n].known));
			for (const n of arrived) {
				grid_rows.push({
					idx: grid_rows.length + 1,
					__islocal: true,
					container: info[n].container,
					cargo: info[n].last_cargo,
				});
			}

			resolved = [];
			for (const row of grid_rows) {
				const hit = info[normalise_no(row.container_no || row.container)];
				if (!hit) {
					row.status_label = "";
					continue;
				}
				// container_no is not a column any more, but it stays on the row: it is what the
				// server keys off, and a Container renamed away from its number would not
				// resolve from the link name alone.
				row.container_no = hit.container_no;
				// The master's last cargo is the starting point; a value already on the row
				// (picked here or imported) is the operator's and is left alone.
				if (!row.cargo && hit.last_cargo) row.cargo = hit.last_cargo;
				row.status_label = hit.blocked || __(hit.status || "terdaftar");
				resolved.push(hit);
			}
			grid.refresh();
			paint();
		});
	}


	// Track numbers that have no master yet (from the mail scan or a file) so they are
	// visible instead of quietly missing.
	function note_missing(numbers) {
		for (const number of numbers) {
			if (number && !missing.includes(number)) missing.push(number);
		}
	}

	const debounced_resolve = frappe.utils.debounce(resolve_grid, 400);
	dialog.fields_dict.order_type.df.onchange = sync_type;
	dialog.fields_dict.direction.df.onchange = resolve_grid;

	// Add rows, skipping numbers already listed. Excel and the mail scan both land here.
	function add_rows(rows, { replace } = {}) {
		if (replace) grid_rows.length = 0;
		const seen = new Set(grid_rows.map((r) => normalise_no(r.container_no || r.container)));
		let added = 0, skipped = 0;
		for (const row of rows) {
			const key = normalise_no(row.container || row.container_no);
			if (!key || seen.has(key)) {
				skipped++;
				continue;
			}
			seen.add(key);
			grid_rows.push({ idx: grid_rows.length + 1, __islocal: true, ...row });
			added++;
		}
		grid.refresh();
		resolve_grid();
		return { added, skipped };
	}

	// Run once when the dialog opens: the numbers the mail itself names are the list the
	// operator would otherwise retype. Only the ones with a master can become rows; the
	// others are named in the notice under the grid.
	function scan_email() {
		frappe.call({
			method: "container_depot.container_depot.mail_to_order.scan_email_containers",
			args: { communication: frm.doc.name },
		}).then((r) => {
			const found = r.message || [];
			// One owner across the mail's tanks is the owner of the job — seeded here so the
			// Container picker is scoped from the start. Mixed owners are left for the operator.
			const owners = [...new Set(found.map((d) => d.principal).filter(Boolean))];
			if (owners.length === 1 && !dialog.get_value("principal")) {
				dialog.set_value("principal", owners[0]);
			}
			note_missing(found.filter((d) => !d.container).map((d) => d.container_no));
			add_rows(
				found
					.filter((d) => d.container)
					.map((d) => ({ container: d.container, cargo: d.last_cargo }))
			);
		});
	}

	// Both buttons sit in the grid footer next to Add Row, the same place Container Booking
	// puts its own import. A block copied out of Excel can also just be pasted onto the
	// grid; that is Frappe's own table paste.
	function add_grid_buttons() {
		// window.open, not frappe.call: this streams a file back, not JSON, and the session
		// cookie rides along so the GET is authenticated.
		grid.add_custom_button(__("Download Template"), () =>
			window.open(
				"/api/method/container_depot.container_depot.mail_to_order.download_container_template"
			)
		);
		grid.add_custom_button(__("Import Excel"), () => {
			const importer = new frappe.ui.Dialog({
				title: __("Import Container dari Excel"),
				fields: [
					{
						fieldtype: "HTML",
						fieldname: "hint",
						options: `<p class="text-muted small">${__(
							"Kolom: Container, Last Cargo (opsional). Baris header dilewati. Pakai Download Template kalau belum punya filenya."
						)}</p>`,
					},
					// Asked here and not only in the header, because a file bypasses the grid's
					// Container picker: imported rows never pass the owner filter the picker
					// applies, so without this the import is the one door another principal's
					// tank can walk through. Answering it first turns that into a named,
					// refused row. Editing it writes straight back to the header, so the two
					// cannot drift — and the header's own onchange rescopes the picker.
					{
						fieldtype: "Link",
						fieldname: "principal",
						options: "Customer",
						label: __("Principal / Tank Owner"),
						reqd: 1,
						default: dialog.get_value("principal") || "",
						description: __("Container milik principal lain dilewati."),
						onchange() {
							const picked = this.get_value();
							if (picked && picked !== dialog.get_value("principal")) {
								dialog.set_value("principal", picked);
							}
						},
					},
					{ fieldtype: "Attach", fieldname: "file", label: __("File Excel (.xlsx)"), reqd: 1 },
					{ fieldtype: "Check", fieldname: "replace", label: __("Ganti baris yang ada") },
				],
				primary_action_label: __("Import"),
				primary_action(values) {
					frappe.call({
						method: "container_depot.container_depot.mail_to_order.parse_container_file",
						args: { file_url: values.file, principal: values.principal },
						freeze: true,
						freeze_message: __("Membaca file…"),
					}).then((r) => {
						const res = r.message || {};
						const rows = res.rows || [];
						const unknown = res.skipped || [];
						note_missing(unknown);
						const counts = add_rows(rows, { replace: values.replace });
						importer.hide();
						report_import(unknown, res.errors || [], counts, res.refused || []);
					});
				},
			});
			importer.show();
		});
	}

	// An import creates no master, ever: an unknown tank comes in as a bare number (the
	// grid's Status column then says what becomes of it), a tank the master says belongs to
	// another principal is dropped, and an unknown cargo is dropped rather than invented —
	// Cargo drives the cleaning method and its price, so a spreadsheet typo must not be able
	// to mint one.
	//
	// All three are listed here in a report that stays on screen. A toast is fine for "12
	// rows added"; it is not how you tell someone that eight of their cargo cells are wrong.
	function report_import(unknown, errors, counts, refused) {
		const esc = frappe.utils.escape_html;
		const summary = `${__("{0} baris ditambahkan.", [counts.added])}${
			counts.skipped ? " " + __("{0} dilewati (duplikat).", [counts.skipped]) : ""
		}`;
		refused = refused || [];
		if (!unknown.length && !errors.length && !refused.length) {
			frappe.show_alert({ message: summary, indicator: counts.added ? "green" : "orange" });
			return;
		}
		const blocks = [`<div>${summary}</div>`];
		if (unknown.length) {
			blocks.push(`
				<div class="bold mt-3">${__("Dilewati — belum ada di master Container")} (${unknown.length})</div>
				<div class="text-muted small">${__(
					"Nomornya dicatat di bawah grid. Buat masternya dulu, barisnya ikut menyusul sendiri."
				)}</div>
				<div>${unknown.map(esc).join(", ")}</div>`);
		}
		if (refused.length) {
			blocks.push(`
				<div class="bold mt-3">${__("Dilewati — milik principal lain")} (${refused.length})</div>
				<div class="text-muted small">${__(
					"Ganti Principal / Tank Owner lalu import ulang, atau buat order terpisah untuk pemilik itu."
				)}</div>
				<ul>${refused.map((e) => `<li>${esc(e)}</li>`).join("")}</ul>`);
		}
		if (errors.length) {
			blocks.push(`
				<div class="bold mt-3">${__("Cargo tidak dikenal")} (${errors.length})</div>
				<div class="text-muted small">${__(
					"Cargo-nya dikosongkan, containernya tetap masuk. Isi manual di grid, atau tambahkan cargonya di master lalu import ulang."
				)}</div>
				<ul>${errors.map((e) => `<li>${esc(e)}</li>`).join("")}</ul>`);
		}
		frappe.msgprint({ title: __("Hasil Import"), indicator: "orange", message: blocks.join("") });
	}

	function options_from(values) {
		return {
			principal: values.principal,
			direction: values.direction,
			reff_doc: values.reff_doc,
			estimation_date: values.estimation_date,
			survey_date: values.survey_date,
			surveyor: values.surveyor,
		};
	}

	function submit(values) {
		const type = current_type();
		// Stop here rather than open a form that cannot be saved: these are the booking's own
		// direction gates (container_booking._find_status_mismatches), reported where the row
		// can still be fixed.
		const blocked = resolved.filter((r) => r.blocked);
		if (blocked.length) {
			const esc = frappe.utils.escape_html;
			frappe.msgprint({
				title: __("Container Belum Siap"),
				indicator: "red",
				message:
					`<div>${__("Perbaiki baris berikut dulu:")}</div><ul>` +
					blocked
						.map((r) => `<li><b>${esc(r.container_no)}</b> — ${esc(r.blocked)}</li>`)
						.join("") +
					"</ul>",
			});
			return;
		}
		// Straight from the grid: the server takes the rows as they are, cargo included,
		// and does its own resolving/de-duplicating.
		const containers = grid_rows
			.filter((r) => r.container)
			.map((r) => ({
				container_no: r.container_no,
				container: r.container,
				cargo: r.cargo,
			}));
		frappe.call({
			method: "container_depot.container_depot.mail_to_order.get_order_prefill",
			args: {
				communication: frm.doc.name,
				order_type: type.key,
				containers,
				options: options_from(values),
			},
			freeze: true,
			freeze_message: __("Menyiapkan order…"),
		}).then((r) => {
			if (!r.message) return;
			dialog.hide();
			open_prefilled(r.message);
		});
	}

	dialog.show();
	add_grid_buttons();
	sync_type();
	// Start from what the email itself says, so nobody retypes ten tank numbers.
	scan_email();
}

// --- Orders made from this email -------------------------------------------------
// The `reff_email` link was only readable from the order side, so the email itself could
// not say whether it had already been turned into work. This lists them at the top of the
// email — newest first, with the state each one is in — and each row routes to the order.
//
// Shown even when there is nothing yet: "belum ada order" is the answer an operator opens
// the email to get, and a card that only exists sometimes is a card nobody looks for.
//
// Rendered as a dashboard section with the standard `custom` class: the form's refresh
// wipes those before running this handler, so re-adding here can never stack up.
const LINKED_SECTION = "custom oak-email-orders";

function order_row(o) {
	const esc = frappe.utils.escape_html;
	const subtitle = [__(o.doctype), o.subtitle].filter(Boolean).map(esc).join(" · ");
	// get_form_link builds the desk's own route, so the link survives wherever the desk is
	// mounted — and being a real <a>, it can also be opened in a new tab.
	const link = frappe.utils.get_form_link(o.doctype, o.name, true, esc(o.name));
	return `
		<div class="flex justify-between align-center py-2 border-bottom">
			<div class="ellipsis">
				<div class="bold">${link}</div>
				<div class="text-muted small ellipsis">${subtitle}</div>
			</div>
			${o.state ? `<span class="indicator-pill blue no-indicator-dot">${esc(__(o.state))}</span>` : ""}
		</div>`;
}

function empty_row() {
	return `<div class="text-muted py-2">${__("Belum ada order dari email ini. Pakai tombol Buat Order di atas.")}</div>`;
}

function show_linked_orders(frm) {
	const shown_for = frm.doc.name;
	frappe.call({
		method: "container_depot.container_depot.mail_to_order.linked_orders",
		args: { communication: frm.doc.name },
	}).then((r) => {
		// Stale guard: the reply can land after the form has moved to another email, and the
		// section belongs to the one it was asked for.
		if (frm.doc.name !== shown_for) return;
		const orders = r.message || [];
		frm.dashboard.parent.find(".oak-email-orders").remove();
		frm.dashboard.add_section(
			orders.length ? orders.map(order_row).join("") : empty_row(),
			__("Order dari Email Ini"),
			LINKED_SECTION
		);
	});
}

frappe.ui.form.on("Communication", {
	refresh(frm) {
		// Only incoming emails are an order reference.
		const is_incoming_email =
			frm.doc.communication_type === "Communication" &&
			frm.doc.communication_medium === "Email" &&
			frm.doc.sent_or_received === "Received";
		if (!is_incoming_email || frm.is_new()) return;

		// Read the mail on light paper in either desk theme — the sender's own colours are
		// written for a white background (see ensure_mail_style).
		ensure_mail_style();
		frm.$wrapper.addClass("oak-mail-form");

		show_linked_orders(frm);

		for (const t of ORDER_TYPES) {
			if (!frappe.model.can_create(t.doctype)) continue;
			frm.add_custom_button(t.label, () => open_order_dialog(frm, t.key), __("Buat Order"));
		}
	},
});
