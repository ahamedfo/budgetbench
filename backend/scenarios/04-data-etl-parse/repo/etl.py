def load(path):
    rows = []
    for line in open(path):
        parts = line.strip().split(',')  # bug: breaks on quoted commas
        rows.append({'name': parts[0], 'amount': parts[1]})  # bug: amount stays str
    return rows
