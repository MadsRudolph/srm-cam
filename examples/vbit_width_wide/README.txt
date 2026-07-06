V-bit width card - read with a multimeter (see vbit_width.py).
Rows top->bottom (mm): 1.50 1.25 1.00 0.80 0.60 0.45 0.30 0.20
Narrowest row that still beeps = upper bound on the overcut past
the configured bit width. Actual cut width = bit_diameter + the
bracket between the widest dead row and the narrowest live row.
Everything beeps and the thinnest looks fat -> cut is undersized.
