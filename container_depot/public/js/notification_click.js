// Desk notification bell: check access before following the link.
//
// Frappe already routes a notification to its document — `get_item_link` builds
// `/app/<doctype>/<name>` from the log's document_type/document_name. What it does not do is
// ask first, so a recipient who cannot read that document lands on the form's "Insufficient
// Permission" page. That is safe — the server refused, which is the point — but it reads as a
// broken notification, and leaves the operator unable to tell whether the record was deleted,
// was never theirs, or the app is simply broken.
//
// So the click is intercepted, the same resolver the PWA bell uses is asked, and we either
// follow the link or say plainly why not. Note it asks about DESK access (document read),
// not the PWA menu — a Desk user with no field role has every right to open the form.
//
// FAIL-OPEN, ON PURPOSE. This hangs off Frappe's own markup
// (`a.notification-item[data-name]`), and core markup changes between versions. If the
// selector stops matching, or the call fails, the click proceeds exactly as it does today —
// into Frappe's permission handling. This listener is a courtesy on top of a check that is
// already enforced server-side. It is not the check, and it must never become the reason a
// working link stops working.

(function () {
	// Capture phase: Frappe binds its own handler on the row, and navigation has to be
	// stoppable before that runs.
	document.addEventListener(
		"click",
		function (e) {
			const link = e.target?.closest?.("a.notification-item[data-name]");
			if (!link) return;
			// "Mark as read" is a button inside the row, not a navigation.
			if (e.target.closest(".mark-as-read")) return;
			// Our own replay of this click — let it through untouched.
			if (link.dataset.depotChecked === "1") return;

			const logName = link.getAttribute("data-name");
			const href = link.getAttribute("href");
			if (!logName || !href || href === "#") return;

			e.preventDefault();
			e.stopPropagation();

			frappe
				.call({
					method: "container_depot.ess.notifications.open_target",
					args: { name: logName },
					// A refusal is an answer we render ourselves, not an error dialog.
					freeze: false,
				})
				.then((r) => {
					const res = r?.message || {};
					if (res.desk_allowed === false) {
						frappe.msgprint({
							title: __("Tidak bisa dibuka"),
							message: res.desk_message || __("Anda tidak punya izin membuka dokumen ini."),
							indicator: "orange",
						});
						return;
					}
					follow(link);
				})
				.catch(function () {
					// The check itself failed. Do not punish the operator for that: send them
					// where they were going and let the server's own permission layer answer.
					follow(link);
				});
		},
		true
	);

	// Replay the click so Frappe's own row handling still runs — mark as read, close the
	// panel, route through the SPA router rather than a full page load.
	function follow(link) {
		link.dataset.depotChecked = "1";
		try {
			link.click();
		} finally {
			delete link.dataset.depotChecked;
		}
	}
})();
