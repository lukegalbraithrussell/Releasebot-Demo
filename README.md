# ReleaseBot demo

A Bolt for Python app that shows two Slack features:

- **Slackbot MCP client**: the manifest connects GitHub's MCP server to Slackbot. No server code is involved.
- **Slack Code**: mentioning `@ReleaseBot cut bolt-python 1.31.0` opens a code channel with a context bar, a `CHANGELOG.md` diff, a release notes canvas, and per-channel slash commands.

The release is scripted: changes are read from the GitHub API, but nothing is tagged, pushed, or opened as a PR.

## Setup

1. Register a GitHub OAuth App with the callback URL `https://oauth2.slack.com/external/auth/callback`. Put its client ID in `manifest.json` under `external_auth_providers.oauth2.mcp_github.options.client_id`.
2. Create and install the app:

   ```sh
   slack install
   slack external-auth add-secret
   ```
3. Run the app:

   ```sh
   slack run
   ```

## Demo script

1. In a DM with Slackbot, click **Apps**, add ReleaseBot, and authorize GitHub.
2. Ask Slackbot: "What's been merged to slackapi/bolt-python since the last release?"
3. In a channel with ReleaseBot, post `@ReleaseBot cut bolt-python 1.31.0`.
4. Open the code channel from the card. Show the context bar, the **Code** tab diff, and the **Release notes** tab.
5. Run `/ship-release`. The summary posts back to the original thread and the channel archives.

## Shipping real releases

The demo only reads from GitHub. `/ship-release` updates Slack and nothing else. To make it ship, add GitHub writes to `release.py` and call them from `ship_release` in `app.py`.

### 1. Use a token that can write

Create a [fine-grained personal access token](https://github.com/settings/personal-access-tokens/new) scoped to the repos ReleaseBot may release, with these repository permissions:

- **Contents**: Read and write, to create tags, branches, commits, and releases
- **Pull requests**: Read and write, only if you open a changelog PR

Set it as `GITHUB_TOKEN` in `.env`. This token is separate from the GitHub connection in Slackbot, which uses each person's own OAuth token.

### 2. Add a write helper to `release.py`

`github_get` only reads. Add a sibling that sends a JSON body:

```python
def github_send(method, path, body):
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        data=json.dumps(body).encode(),
        method=method,
    )
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("Authorization", f"Bearer {os.environ['GITHUB_TOKEN']}")
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)
```

### 3. Publish the release

Creating a GitHub release also creates its tag on the default branch. Start with `draft: True` so a person publishes it from GitHub, and switch to `False` once you trust the flow:

```python
def publish_release(release):
    return github_send(
        "POST",
        f"/repos/{release.repo}/releases",
        {
            "tag_name": release.version,
            "target_commitish": release.default_branch,
            "name": release.version,
            "body": release_notes_markdown(release),
            "draft": True,
        },
    )
```

Then call it in `ship_release` before the summary message, and link the result:

```python
github_release = publish_release(release)
summary = client.chat_postMessage(
    channel=channel_id,
    text=f":rocket: Drafted <{github_release['html_url']}|{release.repo} {release.version}> with {len(release.changes)} changes.",
)
```
