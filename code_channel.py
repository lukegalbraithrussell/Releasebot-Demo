COMMANDS = [
    {"name": "ship-release", "description": "Tag the release and archive this channel"},
    {"name": "refresh-notes", "description": "Pull the latest merged changes and rebuild the notes"},
]


def create(client, release, origin_channel_id, origin_message_ts):
    response = client.api_call(
        "agents.conversations.create",
        json={
            "name": f"Release {release.repo} {release.version}",
            "session_id": release.session_id,
            "origin_channel_id": origin_channel_id,
            "origin_message_ts": origin_message_ts,
        },
    )
    return response["channel_id"]


def set_status(client, channel_id, status):
    client.api_call("agents.sessions.setStatus", json={"channel_id": channel_id, "status": status})


def set_context_bar(client, channel_id, release, progress_label):
    items = [
        {"key": "repo", "label": release.repo, "icon": "folder", "url": release.repo_url},
        {"key": "branch", "label": release.branch, "icon": "branch"},
        {"key": "progress", "label": progress_label, "icon": "terminal"},
    ]
    if release.previous_tag:
        items.insert(2, {"key": "compare", "label": f"{release.previous_tag}...{release.default_branch}", "icon": "link", "url": release.compare_url})
    client.api_call(
        "agents.conversations.setProperties",
        json={"channel_id": channel_id, "code_channel": {"context_bar_items": items}},
    )


def publish_diff(client, channel_id, release, diff):
    client.api_call(
        "agents.conversations.setView",
        json={
            "channel_id": channel_id,
            "type": "diff",
            "content": diff,
            "base_branch": release.default_branch,
            "head_branch": release.branch,
        },
    )


def publish_canvas(client, channel_id, release, markdown):
    canvas = client.canvases_create(
        title=f"{release.repo} {release.version} release notes",
        document_content={"type": "markdown", "markdown": markdown},
    )
    client.api_call(
        "agents.conversations.setView",
        json={
            "channel_id": channel_id,
            "type": "canvas",
            "view_key": "release-notes",
            "name": "Release notes",
            "canvas_id": canvas["canvas_id"],
            "access_level": "comment",
        },
    )


def register_commands(client, channel_id):
    client.api_call("agents.conversations.setCommands", json={"channel_id": channel_id, "commands": COMMANDS})


def archive(client, channel_id, summary_message_ts):
    client.api_call(
        "agents.conversations.archive",
        json={"channel_id": channel_id, "summary_message_ts": summary_message_ts},
    )
