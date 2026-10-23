import functools
import logging
import os
import pickle
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError

from release import github_get, to_change

CACHE_SECONDS = 24 * 60 * 60
RETRY_SECONDS = 15 * 60
CACHE_FILE = Path(__file__).parent / ".cache" / "sdk_status.pickle"
NODE_SDK = "slackapi/node-slack-sdk"
NODE_PACKAGES = ["web-api", "socket-mode", "oauth", "types", "webhook", "logger", "rtm-api", "cli-hooks", "cli-test"]


@dataclass
class Sdk:
    repo: str
    package: str = ""

    @property
    def name(self):
        return f"@slack/{self.package}" if self.package else self.repo.split("/")[1]

    @property
    def url(self):
        if self.package:
            return f"https://github.com/{self.repo}/tree/main/packages/{self.package}"
        return f"https://github.com/{self.repo}"


SDKS = [
    Sdk("slackapi/bolt-python"),
    Sdk("slackapi/bolt-js"),
    Sdk("slackapi/python-slack-sdk"),
    Sdk("slackapi/java-slack-sdk"),
    Sdk("slackapi/slack-cli"),
    Sdk("slackapi/slack-github-action"),
] + [Sdk(NODE_SDK, package) for package in NODE_PACKAGES]


@dataclass
class SdkStatus:
    sdk: Sdk
    tag: str
    release_url: str
    released_at: datetime
    change_count: int
    branch: str
    changes: list = field(default_factory=list)
    packages: list = field(default_factory=list)

    @property
    def days_since(self):
        return (datetime.now(self.released_at.tzinfo) - self.released_at).days

    @property
    def compare_url(self):
        return f"https://github.com/{self.sdk.repo}/compare/{self.tag}...{self.branch}"


def read_cache_file():
    try:
        return pickle.loads(CACHE_FILE.read_bytes())
    except Exception:
        return {"loaded_at": 0.0, "statuses": []}


_cache = {**read_cache_file(), "error": None, "failed_at": 0.0}


def needs_refresh():
    stale = time.time() - _cache["loaded_at"] > CACHE_SECONDS
    return stale and time.time() - _cache["failed_at"] > RETRY_SECONDS


def loaded_at():
    return datetime.fromtimestamp(_cache["loaded_at"]).astimezone()


def last_error():
    return _cache["error"]


def statuses(refresh=False):
    if refresh or needs_refresh():
        try:
            _cache.update(statuses=load_all(), loaded_at=time.time(), error=None)
        except HTTPError as error:
            logging.warning("Couldn't refresh SDK release status: %s", error)
            _cache.update(error=describe(error), failed_at=time.time())
        else:
            CACHE_FILE.parent.mkdir(exist_ok=True)
            CACHE_FILE.write_bytes(pickle.dumps({"loaded_at": _cache["loaded_at"], "statuses": _cache["statuses"]}))
    return _cache["statuses"]


def describe(error):
    if error.code in (403, 429):
        hint = "" if os.environ.get("GITHUB_TOKEN") else " Set `GITHUB_TOKEN` in `.env` to raise the limit."
        return f"GitHub's rate limit was reached.{hint}"
    return f"GitHub returned {error.code} {error.reason}."


def load_all():
    node_releases = github_get(f"/repos/{NODE_SDK}/releases?per_page=100")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda sdk: load_status(sdk, node_releases), SDKS))
    loaded = [status for status in results if status]
    repos = [status for status in loaded if not status.sdk.package]
    packages = [status for status in loaded if status.sdk.package]
    return repos + ([node_summary(packages)] if packages else [])


def node_summary(packages):
    changes = list({change.url: change for package in packages for change in package.changes}.values())
    latest = max(packages, key=lambda package: package.released_at)
    return SdkStatus(
        sdk=Sdk(NODE_SDK),
        tag=f"{len(packages)} packages",
        release_url=f"https://github.com/{NODE_SDK}/releases",
        released_at=latest.released_at,
        change_count=len(changes),
        branch=latest.branch,
        changes=sorted(changes, key=lambda change: change.merged_at),
        packages=packages,
    )


def find_status(name):
    everything = [found for status in statuses() for found in [status, *status.packages]]
    return next((status for status in everything if status.sdk.name == name), None)


def load_status(sdk, node_releases):
    if not sdk.package:
        return load_repo_status(sdk)
    try:
        return load_package_status(sdk, node_releases)
    except StopIteration:
        logging.warning("No release found for %s in the latest %d releases", sdk.name, len(node_releases))
        return None


@functools.cache
def default_branch(repo):
    return github_get(f"/repos/{repo}")["default_branch"]


def load_repo_status(sdk):
    branch = default_branch(sdk.repo)
    latest = github_get(f"/repos/{sdk.repo}/releases/latest")
    comparison = github_get(f"/repos/{sdk.repo}/compare/{latest['tag_name']}...{branch}")
    return SdkStatus(
        sdk=sdk,
        tag=latest["tag_name"],
        release_url=latest["html_url"],
        released_at=datetime.fromisoformat(latest["published_at"]),
        change_count=comparison["total_commits"],
        branch=branch,
        changes=[to_change(commit) for commit in comparison["commits"]],
    )


def load_package_status(sdk, node_releases):
    prefix = f"{sdk.name}@"
    latest = next(
        release
        for release in node_releases
        if release["tag_name"].startswith(prefix) and not release["draft"] and not release["prerelease"]
    )
    branch = default_branch(sdk.repo)
    commits = []
    for page in range(1, 4):
        batch = github_get(
            f"/repos/{sdk.repo}/commits?sha={branch}&path=packages/{sdk.package}"
            f"&since={latest['published_at']}&per_page=100&page={page}"
        )
        commits += batch
        if len(batch) < 100:
            break
    return SdkStatus(
        sdk=sdk,
        tag=latest["tag_name"],
        release_url=latest["html_url"],
        released_at=datetime.fromisoformat(latest["published_at"]),
        change_count=len(commits),
        branch=branch,
        changes=[to_change(commit) for commit in reversed(commits)],
    )
