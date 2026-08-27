"""Kelengkapan tank (fittings) as printed on the OAK EIR sheet — the fill-in boxes.

These are NOT defects. They are the tank's own equipment recorded at every gate: how many
straps came in, what the manlid seal is made of, the steam pipe bore. The damage checklist
answers "what is broken"; this answers "what is fitted, and how much of it". The two live in
separate tables on ``Inspection`` for exactly that reason — the same split as ``out_seals``.

One entry per INPUT BOX, not per item: the paper form gives Airline Valve four boxes
(type, pcs, inch, cap pcs), so it contributes four rows that share an ``item_label``. That
keeps the model flat — no per-item schema — while still printing back as one line per item.

``printed_no`` is the number the box carries on the paper sheet, so a surveyor holding the
form can match it. Consumed by the v0_82 seeding patch.

(fitting_code, compartment, printed_no, item_label, slot_label, value_type, options, uom, sequence)
"""

NUMBER = "Number"
CHOICE = "Choice"

FITTINGS = [
	# --- Bottom Discharge Compartment -------------------------------------------------
	('BDC-09-IN',    'Bottom Discharge', '9',  'Steam Pipe',           'IN',    NUMBER, '',                              'inch',  1),
	('BDC-09-OUT',   'Bottom Discharge', '9',  'Steam Pipe',           'OUT',   NUMBER, '',                              'inch',  2),
	('BDC-11-DEG',   'Bottom Discharge', '11', 'Thermometer',          '',      NUMBER, '',                              '°C', 3),
	('BDC-07-TYPE',  'Bottom Discharge', '7',  'Btm Dis Connection',   'Tipe',  CHOICE, 'Flange\nBSP\nOther',            '',      4),
	('BDC-07-CAP',   'Bottom Discharge', '7',  'Btm Dis Connection',   'Cap',   NUMBER, '',                              'pcs',   5),
	# --- Top Discharge Compartment ----------------------------------------------------
	('TDC-02-PCS',   'Top Discharge',    '2',  'Top Dis Blind Flange', '',      NUMBER, '',                              'pcs',   6),
	('TDC-02-BOLT',  'Top Discharge',    '2',  'Top Dis Blind Flange', 'Bolts', NUMBER, '',                              'bolts', 7),
	('TDC-08-TYPE',  'Top Discharge',    '8',  'Airline Valve',        'Tipe',  CHOICE, 'Bttrfly\nBall',                 '',      8),
	('TDC-08-PCS',   'Top Discharge',    '8',  'Airline Valve',        '',      NUMBER, '',                              'pcs',   9),
	('TDC-08-INCH',  'Top Discharge',    '8',  'Airline Valve',        'Ukuran', NUMBER, '',                             'inch',  10),
	('TDC-08-CAP',   'Top Discharge',    '8',  'Airline Valve',        'Cap',   NUMBER, '',                              'pcs',   11),
	# --- Manlid Compartment -----------------------------------------------------------
	('MLC-02-TYPE',  'Manlid',           '2',  'Manlid Cover',         'Tipe',  CHOICE, 'FV\nPRL\nOther',                '',      12),
	('MLC-02-BOLT',  'Manlid',           '2',  'Manlid Cover',         'Bolts', NUMBER, '',                              'bolts', 13),
	('MLC-03-TYPE',  'Manlid',           '3',  'Manlid Cover Locking', 'Tipe',  CHOICE, 'Swingbolt\nBolt',               '',      14),
	('MLC-03-PCS',   'Manlid',           '3',  'Manlid Cover Locking', '',      NUMBER, '',                              'pcs',   15),
	('MLC-08-PCS',   'Manlid',           '8',  'Calibration Chart',    '',      NUMBER, '',                              'pcs',   16),
	('MLC-09-TYPE',  'Manlid',           '9',  'Manlid Seal',          'Tipe',  CHOICE, 'PTFE\nSWR\nSupertanktyt\nOther', '',     17),
	# --- Side Compartment -------------------------------------------------------------
	('SID-01-L',     'Side',             '1',  'PVC 3 Way',            'LEFT',  NUMBER, '',                              'pcs',   18),
	('SID-01-R',     'Side',             '1',  'PVC 3 Way',            'RIGHT', NUMBER, '',                              'pcs',   19),
	('SID-02-L',     'Side',             '2',  'Drain Hose',           'LEFT',  NUMBER, '',                              'pcs',   20),
	('SID-02-R',     'Side',             '2',  'Drain Hose',           'RIGHT', NUMBER, '',                              'pcs',   21),
	('SID-03-PCS',   'Side',             '3',  'Strap',                '',      NUMBER, '',                              'pcs',   22),
	('SID-04-LONG',  'Side',             '4',  'Walkways',             'LONG',  NUMBER, '',                              'pcs',   23),
	('SID-04-SHORT', 'Side',             '4',  'Walkways',             'SHORT', NUMBER, '',                              'pcs',   24),
]
