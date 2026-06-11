def total(items, customer):
    t = 0
    for i in items:
        t = t + i['price'] * i['qty']
    if customer['tier'] == 'gold':
        if t > 500:
            t = t * 0.85
        else:
            t = t * 0.9
    elif customer['tier'] == 'silver':
        if t > 500:
            t = t * 0.92
    return round(t, 2)
