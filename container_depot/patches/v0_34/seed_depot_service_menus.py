"""Seed the default Depot Service Menus.

A menu is a named filter over Item Groups, so an item picker can be scoped with ~zero
per-item setup. The mapping used to live here, but it named the placeholder groups from
patches.v0_11.seed_item_groups while live sites had replaced those with the customer's real
rate-card groups — so this patch quietly created Cleaning / Maintenance menus with ZERO
groups. The mapping now lives next to the code that reads it
(``container_depot/service_menu.DEFAULT_MENU_GROUPS``), which is also where the menus added later
(Survey / Periodic Test) are declared, so seeder and reader can no longer drift apart.

Kept as a patch so the migration history stays intact; it just delegates now.
"""

from __future__ import annotations


def execute():
	from container_depot.container_depot.service_menu import DEFAULT_MENU_GROUPS, seed_default_menus

	touched = seed_default_menus()
	print(
		f"[container_depot] seed_depot_service_menus: {len(DEFAULT_MENU_GROUPS)} default menu(s), "
		f"{touched} created/updated."
	)
