import logging
import os
from urllib.error import HTTPError

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

import code_channel
from release import (
    changelog_diff,
    collect_changes,
    find_previous_release,
    parse_release_request,
    release_notes_markdown,
)

logging.basicConfig(level=logging.INFO)

app = App(token=os.environ["SLACK_BOT_TOKEN"])
releases = {}

USAGE = "Tell me which repo to release, like `@ReleaseBot cut bolt-python` or `@ReleaseBot cut slackapi/bolt-python 1.31.0`."


def prepare_release(client, channel_id, release):
    code_channel.set_status(client, channel_id, "processing")
    code_channel.set_context_bar(client, channel_id, release, "Collecting changes")
    client.chat_postMessage(channel=channel_id, text=f"Collecting everything merged to `{release.repo}` since the last release.")

    collect_changes(release)
    code_channel.publish_diff(client, channel_id, release, changelog_diff(release))
    code_channel.publish_canvas(client, channel_id, release, release_notes_markdown(release))
    code_channel.set_context_bar(client, channel_id, release, f"{len(release.changes)} changes ready for review")

    client.chat_postMessage(
        channel=channel_id,
        text=(
            f"Found {len(release.changes)} changes since `{release.previous_tag}`. "
            "The *Code* tab has the `CHANGELOG.md` diff and the *Release notes* tab has the draft. "
            "Run `/ship-release` when it looks right, or `/refresh-notes` to pick up anything merged since."
        ),
    )
    code_channel.set_status(client, channel_id, "suspended")


@app.event("app_mention")
def start_release(event, client, say):
    if event["channel"] in releases:
        return
    release = parse_release_request(event["text"])
    if release is None:
        say(text=USAGE, thread_ts=event["ts"])
        return
    try:
        find_previous_release(release)
    except HTTPError:
        say(text=f"I couldn't find a published release for `{release.repo}`. {USAGE}", thread_ts=event["ts"])
        return

    channel_id = code_channel.create(client, release, event["channel"], event["ts"])
    releases[channel_id] = release
    code_channel.register_commands(client, channel_id)
    prepare_release(client, channel_id, release)


@app.event("message")
def reply_in_code_channel(event, client, context):
    if event["channel"] not in releases or event.get("bot_id") or event.get("subtype"):
        return
    if f"<@{context.bot_user_id}>" in event.get("text", ""):
        return
    release = releases[event["channel"]]
    client.chat_postMessage(
        channel=event["channel"],
        text=(
            f"Got it. Run `/ship-release` when you're ready to tag {release.version}, "
            "or `/refresh-notes` to pull in anything merged since."
        ),
    )


@app.command("/refresh-notes")
def refresh_notes(ack, command, client):
    ack()
    release = releases.get(command["channel_id"])
    if release:
        prepare_release(client, command["channel_id"], release)


@app.command("/ship-release")
def ship_release(ack, command, client):
    ack()
    channel_id = command["channel_id"]
    release = releases.pop(channel_id, None)
    if release is None:
        return

    code_channel.set_status(client, channel_id, "processing")
    code_channel.set_context_bar(client, channel_id, release, f"Tagged {release.version}")
    summary = client.chat_postMessage(
        channel=channel_id,
        text=(
            f":rocket: Tagged `{release.repo}` {release.version} with {len(release.changes)} changes "
            f"since `{release.previous_tag}`. The release notes are in the *Release notes* tab."
        ),
    )
    code_channel.archive(client, channel_id, summary["ts"])


@app.event("agent_session_stopped")
def stop_release(event):
    releases.pop(event["channel"], None)


if __name__ == "__main__":
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
