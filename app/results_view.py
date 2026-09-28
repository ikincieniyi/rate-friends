"""Read-only presentation data for the results page."""

import math


def radar_chart(averages):
    # Numbered axes keep even long category names readable in the adjacent list.
    if not 3 <= len(averages) <= 10:
        return None

    center, radius = 180, 118
    angles = [2 * math.pi * i / len(averages) - math.pi / 2 for i in range(len(averages))]

    def point(angle, distance):
        return (round(center + math.cos(angle) * distance, 3),
                round(center + math.sin(angle) * distance, 3))

    def points_text(points):
        return " ".join(f"{x},{y}" for x, y in points)

    # The center is 1 and the outer ring is 10; use unrounded averages.
    dots = [point(angle, radius * (average - 1) / 9) for angle, average in zip(angles, averages)]
    return {
        "axes": [point(angle, radius) for angle in angles],
        "labels": [point(angle, radius + 30) for angle in angles],
        "rings": [
            {"value": value,
             "points": points_text([point(angle, radius * (value - 1) / 9) for angle in angles]),
             "label_y": round(center - radius * (value - 1) / 9 + 4, 3)}
            for value in (2, 4, 6, 8, 10)
        ],
        "points": points_text(dots),
        "dots": dots,
    }


def result_cards(rows):
    grouped = {}
    for row in rows:
        average = row["score_sum"] / row["vote_count"]
        grouped.setdefault(row["person"], []).append({
            "category": row["category"],
            "average": average,
            "label": f"{average:.2f}",
            "bar_width": average * 10,
        })
    return [
        {"person": person, "items": items,
         "radar": radar_chart([item["average"] for item in items])}
        for person, items in grouped.items()
    ]
