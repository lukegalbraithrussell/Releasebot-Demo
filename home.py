from blocks import change_cells, change_mix_chart, date_cell, merge_activity_chart, number_cell, raw_text, rich_text
from release import next_minor_version

MAX_RECENT_CHANGES = 100


def loading_view():
    return home([section("Checking GitHub for the latest SDK releases…")])


def error_view(error):
    return home(
        [
            section(f":warning: Couldn't load SDK releases from GitHub. {error}"),
            {"type": "actions", "elements": [button("Try again", "home_refresh")]},
        ]
    )


def overview_view(statuses, loaded_at, error=None):
    warning = [context(f":warning: Couldn't refresh. {error} Showing data from {loaded_at:%b %-d, %-I:%M %p}.")] if error else []
    return home(
        [
            {"type": "header", "text": {"type": "plain_text", "text": "SDK releases"}},
            context(
                "Changes merged since each SDK's last release. "
                f"`node-slack-sdk` packages release separately; *View* it for each package. Updated {loaded_at:%b %-d, %-I:%M %p}."
            ),
            *warning,
            {"type": "actions", "elements": [button("Refresh", "home_refresh")]},
            *status_blocks(statuses, "Changes since last release", "SDK"),
        ]
    )


def packages_view(status):
    return home(
        [
            {"type": "actions", "elements": [button("← All SDKs", "home_back")]},
            {"type": "header", "text": {"type": "plain_text", "text": f"{status.sdk.name} packages"}},
            section(
                f"*{status.change_count}* unreleased changes across {len(status.packages)} packages. "
                "Each package counts the changes under its own directory since its own last release, "
                "so a change that touches two packages appears in both."
            ),
            *status_blocks(status.packages, "Changes since each package's release", "Package"),
        ]
    )


def status_blocks(statuses, chart_title, name_label):
    statuses = sorted(statuses, key=lambda status: status.change_count, reverse=True)
    pending = [status for status in statuses if status.change_count]
    chart = [pending_changes_chart(pending, chart_title, name_label)] if pending else []
    return chart + [sdk_table(statuses, name_label)]


def pending_changes_chart(statuses, title, name_label):
    names = [status.sdk.name for status in statuses]
    return {
        "type": "data_visualization",
        "title": title,
        "chart": {
            "type": "bar",
            "series": [
                {"name": "Changes", "data": [{"label": status.sdk.name, "value": status.change_count} for status in statuses]}
            ],
            "axis_config": {"categories": names, "x_label": name_label, "y_label": "Changes"},
        },
    }


def sdk_table(statuses, name_label):
    header = [raw_text(text) for text in [name_label, "Last release", "Released", "Days since", "Changes since", "Details"]]
    rows = [
        [
            rich_text(link(status.sdk.url, status.sdk.name)),
            rich_text(link(status.release_url, status.tag)),
            date_cell(status.released_at, with_year=True),
            number_cell(status.days_since),
            number_cell(status.change_count),
            {
                "type": "action_cell",
                "element": button("View", "view_sdk", status.sdk.name),
                "fallback": raw_text(status.sdk.name),
            },
        ]
        for status in statuses
    ]
    return {"type": "data_table", "caption": f"{name_label} release status", "page_size": 20, "rows": [header] + rows}


def detail_view(status):
    if status.packages:
        return packages_view(status)
    if status.sdk.package:
        actions = [button("← node-slack-sdk packages", "view_sdk", "node-slack-sdk")]
    else:
        actions = [button("← All SDKs", "home_back"), button("Cut release", "cut_release_from_home", status.sdk.name, style="primary")]
    blocks = [
        {"type": "actions", "elements": actions},
        {"type": "header", "text": {"type": "plain_text", "text": f"{status.sdk.name} since {status.tag}"[:150]}},
        section(
            f"*{status.change_count}* changes merged since <{status.release_url}|{status.tag}>, "
            f"released {status.released_at:%b %-d, %Y} ({status.days_since} days ago). "
            f"<{status.compare_url}|Compare on GitHub>"
        ),
    ]
    if not status.changes:
        return home(blocks)
    if len(status.changes) < status.change_count:
        blocks.append(section(f"_Charts cover the first {len(status.changes)} changes._"))
    recent = list(reversed(status.changes))[:MAX_RECENT_CHANGES]
    header = [raw_text(text) for text in ["Change", "Author", "Merged", "Type"]]
    blocks += [
        change_mix_chart(status.changes, status.tag),
        merge_activity_chart(status.changes, status.tag),
        {
            "type": "data_table",
            "caption": f"Most recent {len(recent)} changes",
            "page_size": 10,
            "rows": [header] + [change_cells(change) for change in recent],
        },
    ]
    return home(blocks)


def cut_release_modal(status):
    return {
        "type": "modal",
        "callback_id": "cut_release",
        "private_metadata": status.sdk.repo,
        "title": {"type": "plain_text", "text": "Cut a release"},
        "submit": {"type": "plain_text", "text": "Cut release"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            section(
                f"Cut *{status.sdk.repo}* with the {status.change_count} changes merged since `{status.tag}`. "
                "ReleaseBot posts a card in the channel you pick and opens a code channel for the review."
            ),
            {
                "type": "input",
                "block_id": "version",
                "label": {"type": "plain_text", "text": "Version"},
                "element": {"type": "plain_text_input", "action_id": "value", "initial_value": next_minor_version(status.tag)},
            },
            {
                "type": "input",
                "block_id": "channel",
                "label": {"type": "plain_text", "text": "Post the release card in"},
                "element": {
                    "type": "conversations_select",
                    "action_id": "value",
                    "filter": {"include": ["public"], "exclude_bot_users": True},
                },
            },
        ],
    }


def home(blocks):
    return {"type": "home", "blocks": blocks}


def context(text):
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def section(text):
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def button(text, action_id, value=None, style=None):
    element = {"type": "button", "text": {"type": "plain_text", "text": text}, "action_id": action_id}
    if value:
        element["value"] = value
    if style:
        element["style"] = style
    return element


def link(url, text):
    return {"type": "link", "url": url, "text": text}
