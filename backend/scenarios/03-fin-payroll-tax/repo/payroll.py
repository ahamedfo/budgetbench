BRACKETS = [(0, 0.10), (11000, 0.12), (44725, 0.22), (95375, 0.24)]

def tax(income):
    owed = 0.0
    prev = 0
    for floor, rate in BRACKETS:
        if income > floor:  # bug: should be >= for the boundary band
            owed += (min(income, floor) - prev) * rate
            prev = floor
    return round(owed, 2)
