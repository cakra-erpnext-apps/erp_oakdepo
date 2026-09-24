// Countdown bar before maintenance — sent by container_depot.maintenance.announce over
// realtime to every Desk user, so whoever is mid-form has time to Save before the update
// takes the site down. Fixed on top of everything; the maintenance page replaces it.
//
// Bound on app_ready: frappe.realtime has no socket until desk.js has initialised it, and
// .on() before that is silently dropped.
frappe.provide('container_depot');

container_depot.maintenance_countdown = function ({ seconds = 30, message = '' } = {}) {
	const end = Date.now() + seconds * 1000;
	let $bar = $('#oak-maintenance');
	if (!$bar.length) {
		$bar = $('<div id="oak-maintenance" role="alert" aria-live="assertive"></div>')
			.css({
				position: 'fixed', top: 0, left: 0, right: 0, zIndex: 2000, padding: '10px 16px',
				background: 'var(--red-600, #dc2626)', color: '#fff', textAlign: 'center', fontWeight: 600,
			})
			.appendTo('body');
	}
	clearInterval(container_depot._maintenance_timer);
	const tick = () => {
		const left = Math.max(0, Math.ceil((end - Date.now()) / 1000));
		$bar.text(
			left
				? __('{0} Maintenance dimulai dalam {1} detik.', [message, left])
				: __('Maintenance sedang berjalan. Halaman akan kembali setelah selesai.')
		);
		if (!left) clearInterval(container_depot._maintenance_timer);
	};
	tick();
	container_depot._maintenance_timer = setInterval(tick, 1000);
};

$(document).on('app_ready', () => {
	frappe.realtime.on('oak_maintenance', container_depot.maintenance_countdown);
	// Reloaded mid-countdown: the server still knows how long is left (maintenance.boot).
	if (frappe.boot.oak_maintenance && frappe.boot.oak_maintenance.seconds) {
		container_depot.maintenance_countdown(frappe.boot.oak_maintenance);
	}
});
