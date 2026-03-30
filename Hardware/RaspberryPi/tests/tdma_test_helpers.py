def make_samples(count, offset=0.0):
    rows = []
    for index in range(count):
        base = offset + index * 0.1
        rows.append(
            {
                "ax": base,
                "ay": base + 0.1,
                "az": 9.8 + base,
                "gx": base + 0.2,
                "gy": base + 0.3,
                "gz": base + 0.4,
            }
        )
    return rows
