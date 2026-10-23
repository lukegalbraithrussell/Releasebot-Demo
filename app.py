import logging
import os
from urllib.error import HTTPError

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError

import code_channel
import home
import sdks
from blocks import review_blocks
from release import (
    Release,
    changelog_diff,
    collect_changes,
    find_previous_release,
    is_version,
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
    publish_release(client, channel_id, release)
    client.chat_postMessage(channel=channel_id, **review_message(release))
    code_channel.set_status(client, channel_id, "suspended")


def publish_release(client, channel_id, release):
    code_channel.publish_diff(client, channel_id, release, changelog_diff(release))
    code_channel.publish_canvas(client, channel_id, release, release_notes_markdown(release))
    code_channel.set_context_bar(client, channel_id, release, f"{len(release.included)} changes ready for review")


def review_message(release):
    excluded_count = len(release.changes) - len(release.included)
    excluded = f" ({excluded_count} excluded)" if excluded_count else ""
    text = (
        f"Found {len(release.included)} changes since `{release.previous_tag}`{excluded}. "
        "The *Code* tab has the `CHANGELOG.md` diff and the *Release notes* tab has the draft. "
        "Run `/ship-release` when it looks right, or `/refresh-notes` to pick up anything merged since."
    )
    return {"text": text, "blocks": review_blocks(release, text)}


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

    open_code_channel(client, release, event["channel"], event.get("thread_ts", event["ts"]))


def open_code_channel(client, release, origin_channel_id, origin_ts, invite_user_id=None):
    release.origin_ts = origin_ts
    try:
        channel_id = code_channel.create(client, release, origin_channel_id, origin_ts)
    except SlackApiError as error:
        logging.error(
            "agents.conversations.create failed: %s channel=%s origin_ts=%s session_id=%s",
            error.response["error"], origin_channel_id, origin_ts, release.session_id,
        )
        client.chat_postMessage(
            channel=origin_channel_id,
            thread_ts=origin_ts,
            text=f"I couldn't open a code channel for this release (`{error.response['error']}`).",
        )
        return
    releases[channel_id] = release
    if invite_user_id:
        try:
            client.conversations_invite(channel=channel_id, users=invite_user_id)
        except SlackApiError as error:
            logging.warning("Couldn't invite %s to %s: %s", invite_user_id, channel_id, error.response["error"])
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


@app.action("toggle_change")
def toggle_change(ack, action, body, client):
    ack()
    channel_id = body["channel"]["id"]
    release = releases.get(channel_id)
    if release is None:
        return
    release.excluded ^= {action["value"]}
    publish_release(client, channel_id, release)
    client.chat_update(channel=channel_id, ts=body["message"]["ts"], **review_message(release))


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
            f":rocket: Tagged `{release.repo}` {release.version} with {len(release.included)} changes "
            f"since `{release.previous_tag}`. The release notes are in the *Release notes* tab."
        ),
    )
    code_channel.archive(client, channel_id, summary["ts"])


def publish_overview(client, user_id, refresh=False):
    if refresh or sdks.needs_refresh():
        client.views_publish(user_id=user_id, view=home.loading_view())
    statuses = sdks.statuses(refresh=refresh)
    if statuses:
        view = home.overview_view(statuses, sdks.loaded_at(), sdks.last_error())
    else:
        view = home.error_view(sdks.last_error())
    client.views_publish(user_id=user_id, view=view)


@app.event("app_home_opened")
def open_home(event, client):
    if event.get("tab") == "home":
        publish_overview(client, event["user"])


@app.action("home_refresh")
def refresh_home(ack, body, client):
    ack()
    publish_overview(client, body["user"]["id"], refresh=True)


@app.action("home_back")
def back_to_overview(ack, body, client):
    ack()
    publish_overview(client, body["user"]["id"])


@app.action("view_sdk")
def view_sdk(ack, action, body, client):
    ack()
    status = sdks.find_status(action["value"])
    if status:
        client.views_publish(user_id=body["user"]["id"], view=home.detail_view(status))


@app.action("cut_release_from_home")
def open_cut_release(ack, action, body, client):
    ack()
    status = sdks.find_status(action["value"])
    if status:
        client.views_open(trigger_id=body["trigger_id"], view=home.cut_release_modal(status))


@app.view("cut_release")
def cut_release_from_home(ack, body, view, client):
    values = view["state"]["values"]
    version = values["version"]["value"]["value"].strip()
    channel_id = values["channel"]["value"]["selected_conversation"]
    user_id = body["user"]["id"]
    repo = view["private_metadata"]
    if not is_version(version):
        ack(response_action="errors", errors={"version": "Use a version like 1.31.0."})
        return
    release = Release(repo=repo, version=f"v{version.removeprefix('v')}")
    try:
        card = client.chat_postMessage(
            channel=channel_id,
            text=f"<@{user_id}> is cutting `{repo}` {release.version} from ReleaseBot's Home tab.",
        )
    except SlackApiError as error:
        reason = "Add ReleaseBot to this channel first." if error.response["error"] == "not_in_channel" else f"Couldn't post here ({error.response['error']})."
        ack(response_action="errors", errors={"channel": reason})
        return
    ack()

    try:
        find_previous_release(release)
    except HTTPError:
        client.chat_postMessage(channel=channel_id, thread_ts=card["ts"], text=f"I couldn't find a published release for `{repo}`.")
        return
    open_code_channel(client, release, channel_id, card["ts"], invite_user_id=user_id)


@app.event("agent_session_stopped")
def stop_release(event):
    releases.pop(event["channel"], None)


if __name__ == "__main__":
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
