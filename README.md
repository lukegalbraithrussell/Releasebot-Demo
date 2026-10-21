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

3. Install dependencies and set tokens:

   ```sh
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.sample .env
   ```

   `GITHUB_TOKEN` is optional; without it, the GitHub API allows 60 requests an hour.

4. Run the app:

   ```sh
   slack run
   ```

## Demo script

1. In a DM with Slackbot, click **Apps**, add ReleaseBot, and authorize GitHub.
2. Ask Slackbot: "What's been merged to slackapi/bolt-python since the last release?"
3. In a channel with ReleaseBot, post `@ReleaseBot cut bolt-python 1.31.0`.
4. Open the code channel from the card. Show the context bar, the **Code** tab diff, and the **Release notes** tab.
5. Run `/ship-release`. The summary posts back to the original thread and the channel archives.
