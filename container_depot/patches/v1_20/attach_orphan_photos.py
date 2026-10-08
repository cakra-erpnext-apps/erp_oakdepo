import frappe

from container_depot.container_depot.tank_survey import home_interior_photos
from container_depot.files import backfill


def execute():
	"""Foto yang terlanjur yatim (privat tanpa tuan → 403 untuk semua kecuali pengunggahnya)
	ditempelkan ke dokumennya, sama seperti Foto per Item di EIR: foto interior survey ke EIR-Out
	tanknya, foto Leak Check dan Container Position ke dokumennya sendiri. Aman diulang."""
	tanks = frappe.get_all("Survey Order Photo", filters={"survey_tank": ["is", "set"]}, pluck="survey_tank", distinct=True)
	attached = sum(home_interior_photos(t) for t in tanks)
	attached += backfill(("Leak Check", "Container Position", "Survey Order"))
	frappe.logger().info(f"attach_orphan_photos: {attached} file ditempelkan")
