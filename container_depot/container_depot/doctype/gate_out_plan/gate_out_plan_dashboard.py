"""Connections tab on Gate Out Plan — what the notice actually turned into.

The plan itself authorises nothing: it says which tanks a customer will collect and when,
so the depot can prioritise their cleaning / M&R. What lets a tank out is a **Container
Booking (Tank Out / Lift On)**, raised from the plan and carrying its ``gate_out_plan``
back-link. Listing them here answers the question a half-collected plan raises — "has
anyone booked these tanks yet, and under which booking?" — including the ordinary case of
one plan collected over several visits, i.e. several bookings.
"""


def get_data():
	return {
		"fieldname": "gate_out_plan",
		"transactions": [
			{"label": "Gate Out", "items": ["Container Booking"]},
		],
	}
