"""Add the Survey and Periodic Test service menus on sites that already ran v0_34.

Every flow whose item picker is scoped by a price list must declare WHICH items it offers
through a Depot Service Menu — otherwise the filter lives in code where no operator can see
or change it. Survey Order and Periodic Test Order were the two that didn't, so their pickers
offered the whole catalogue.

The groups they need already exist (``Survey Fee`` holds the class-certification items,
``Testing Charges`` the 2.5yr / 5yr / leak tests); this only files them under a menu. Runs the
same add-only seeder as v0_34, so it also repairs the Cleaning / Maintenance menus that patch
left empty on sites built from the placeholder taxonomy.
"""

from __future__ import annotations


def execute():
	from container_depot.operations.service_menu import seed_default_menus

	print(f"[container_depot] seed_survey_and_periodic_menus: {seed_default_menus()} menu(s) created/updated.")
