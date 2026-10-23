import math
from collections import Counter
from datetime import timedelta

from release import CHANGE_TYPES, change_type

MAX_CHART_POINTS = 20
MAX_TABLE_ROWS = 100


def review_blocks(release, text):
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
    if release.included:
        blocks += [
            change_mix_chart(release.included, release.previous_tag),
            merge_activity_chart(release.included, release.previous_tag),
        ]
    if release.changes:
        blocks.append(changes_table(release))
    return blocks


def change_mix_chart(changes, since_tag):
    counts = Counter(change_type(change) for change in changes)
    types = [name for name in CHANGE_TYPES if counts[name]]
    return {
        "type": "data_visualization",
        "title": f"Changes since {since_tag}"[:50],
        "chart": {
            "type": "bar",
            "series": [{"name": "Changes", "data": [{"label": name, "value": counts[name]} for name in types]}],
            "axis_config": {"categories": types, "x_label": "Type", "y_label": "Changes"},
        },
    }


def merge_activity_chart(changes, since_tag):
    merged = sorted(change.merged_at for change in changes)
    start = merged[0].replace(hour=0, minute=0, second=0, microsecond=0)
    span_days = (merged[-1] - start).days + 1
    weeks_per_bucket = max(1, math.ceil(span_days / (7 * MAX_CHART_POINTS)))
    bucket = timedelta(weeks=weeks_per_bucket)
    bucket_starts = [start + bucket * i for i in range(math.ceil(span_days / bucket.days))]
    show_year = merged[0].year != merged[-1].year
    labels = [f"{day:%b} {day.day}" + (f" {day.year}" if show_year else "") for day in bucket_starts]
    data = [
        {"label": label, "value": sum(1 for merged_at in merged if merged_at < bucket_start + bucket)}
        for label, bucket_start in zip(labels, bucket_starts)
    ]
    return {
        "type": "data_visualization",
        "title": f"Merged since {since_tag}"[:50],
        "chart": {
            "type": "area",
            "series": [{"name": "Changes", "data": data}],
            "axis_config": {
                "categories": labels,
                "x_label": "Week of" if weeks_per_bucket == 1 else f"{weeks_per_bucket} weeks starting",
                "y_label": "Changes merged (running total)",
            },
        },
    }


def changes_table(release):
    changes = release.changes[:MAX_TABLE_ROWS]
    caption = f"{len(release.included)} of {len(release.changes)} changes included in {release.version}"
    if len(changes) < len(release.changes):
        caption += f", showing the first {len(changes)}"
    header = [raw_text("Change"), raw_text("Author"), raw_text("Merged"), raw_text("Type"), raw_text("Review")]
    return {
        "type": "data_table",
        "caption": caption,
        "page_size": 10,
        "rows": [header] + [review_row(change, change.url in release.excluded) for change in changes],
    }


def change_cells(change, excluded=False):
    title = {"type": "link", "url": change.url, "text": change.title}
    if excluded:
        title["style"] = {"strike": True}
    return [
        rich_text(title),
        rich_text({"type": "link", "url": change.author_url, "text": f"@{change.author}"})
        if change.author_url
        else raw_text(change.author),
        date_cell(change.merged_at),
        raw_text(change_type(change)),
    ]


def review_row(change, excluded):
    return change_cells(change, excluded) + [
        {
            "type": "action_cell",
            "element": {
                "type": "button",
                "text": {"type": "plain_text", "text": "Include" if excluded else "Exclude"},
                "action_id": "toggle_change",
                "value": change.url,
            },
            "fallback": raw_text("Excluded" if excluded else "Included"),
        },
    ]


def date_cell(moment, with_year=False):
    text = f"{moment:%b} {moment.day}" + (f", {moment.year}" if with_year else "")
    return {"type": "raw_number", "value": int(moment.timestamp()), "text": text}


def number_cell(value):
    return {"type": "raw_number", "value": value, "text": str(value)}


def rich_text(*elements):
    return {"type": "rich_text", "elements": [{"type": "rich_text_section", "elements": list(elements)}]}


def raw_text(text):
    return {"type": "raw_text", "text": text}
