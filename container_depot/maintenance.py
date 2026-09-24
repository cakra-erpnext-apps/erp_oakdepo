"""Heads-up before maintenance: every open screen counts down so people can save first.

Run by ``scripts/prod-update.sh`` / ``staging-update.sh`` right before the maintenance page
goes up, then the script waits the same number of seconds::

    bench --site <site> execute container_depot.maintenance.announce --kwargs '{"seconds": 30}'

Two roads, because the two front ends listen differently:
  * Desk — Frappe realtime, broadcast to the site room (every logged-in System User);
    ``public/js/maintenance_notice.js`` draws the countdown bar.
  * PWA  — it holds no socket, so a Web Push to every subscribed device. The OS shows it as
    a notification (the app may be closed), and the service worker hands it to an open app,
    which draws its own countdown (``MaintenanceBanner.vue``).

The deadline is also kept in the cache, so a screen that reloads (or opens) mid-countdown
asks :func:`status` and picks it up again: the Desk reads it from boot, the PWA on load and
every few seconds — the PWA has no socket, and a phone without push would otherwise never know.
Every device counts down from the ``seconds`` left as the SERVER sees it, never from a
timestamp compared to its own clock: a phone's clock can be minutes off.
"""

from __future__ import annotations

import time

import frappe

CACHE_KEY = "oak_maintenance"
DEFAULT_MESSAGE = "Sistem akan maintenance. Simpan pekerjaan Anda sekarang."


def announce(seconds: int = 30, message: str | None = None) -> dict:
	from container_depot.ess import push

	seconds = int(seconds)
	message = message or DEFAULT_MESSAGE
	# ponytail: expires just after the countdown — past that the maintenance page answers.
	frappe.cache.set_value(CACHE_KEY, {"until": time.time() + seconds, "message": message}, expires_in_sec=seconds + 10)
	frappe.publish_realtime("oak_maintenance", {"seconds": seconds, "message": message}, after_commit=False)

	# Sent here, not queued: the queue workers are the next thing the update restarts.
	users = frappe.get_all(push.SUBSCRIPTION_DOCTYPE, filters={"enabled": 1}, pluck="user", distinct=True)
	sent = push.deliver(
		users,
		title="Maintenance dalam {0} detik".format(seconds),
		body=message,
		tag="oak-maintenance",
		extra={"seconds": seconds},
	) if users else 0
	return {"desk": "broadcast", "pwa_devices": sent}


@frappe.whitelist(allow_guest=True)
def status() -> dict:
	"""``{"seconds": left, "message": ...}`` while a countdown runs, else ``{}``. A cache read."""
	state = frappe.cache.get_value(CACHE_KEY)
	left = int(state["until"] - time.time()) if state else 0
	return {"seconds": left, "message": state["message"]} if left > 0 else {}


def boot(bootinfo):
	bootinfo.oak_maintenance = status()
