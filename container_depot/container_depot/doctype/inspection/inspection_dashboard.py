"""Connections tab on an EIR — what this inspection produced, and what points back at it.

Three groups, because they answer different questions:

* **Pekerjaan Depo** — the orders the EIR raised on submit: a Cleaning Order for a dirty
  tank, an M&R for an indication of damage, and any Periodic Test Order later filed against
  it. All three carry ``inspection``, so they are found by the standard fieldname.
* **Gate** — the gate record whose ``eir_reference`` is this EIR. An EIR-Out submit IS the
  departure (``gate.mark_gate_out``), so this is where the visit was closed.
* **EIR** — the EIR-Out that used this EIR-In as its comparison baseline
  (``reference_eir_in``). Reads the other way on an EIR-Out: nothing lists it here, its
  baseline sits in the internal link below.

``internal_links`` are the documents THIS EIR points at (a field on the form), not documents
pointing at it. The bon is deliberately absent: ``referred_voucher`` is a Dynamic Link, and
naming a fixed doctype for it would draw a link to Order Bongkar for an EIR that actually
refers to an Order Muat.
"""


def get_data():
	return {
		"fieldname": "inspection",
		"non_standard_fieldnames": {
			"Gate Entry": "eir_reference",
			"Inspection": "reference_eir_in",
		},
		"internal_links": {
			"Container": "container",
			"Container Booking": "container_booking",
		},
		"transactions": [
			{"label": "Pekerjaan Depo", "items": ["Cleaning Order", "Repair Order", "Periodic Test Order"]},
			{"label": "Gate", "items": ["Gate Entry"]},
			{"label": "EIR", "items": ["Inspection"]},
			{"label": "Tank & Booking", "items": ["Container", "Container Booking"]},
		],
	}
