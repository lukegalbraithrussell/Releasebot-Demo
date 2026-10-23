import difflib
import json
import os
import re
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Change:
    title: str
    url: str
    author: str
    author_url: str
    merged_at: datetime


@dataclass
class Release:
    repo: str
    version: str
    previous_tag: str = ""
    default_branch: str = "main"
    origin_ts: str = ""
    changes: list = field(default_factory=list)
    excluded: set = field(default_factory=set)

    @property
    def included(self):
        return [change for change in self.changes if change.url not in self.excluded]

    @property
    def repo_url(self):
        return f"https://github.com/{self.repo}"

    @property
    def branch(self):
        return f"release/{self.version}"

    @property
    def compare_url(self):
        return f"{self.repo_url}/compare/{self.previous_tag}...{self.default_branch}"

    @property
    def session_id(self):
        return f"release-{self.repo.replace('/', '-')}-{self.version}-{self.origin_ts}"


CHANGE_TYPES = ["feat", "fix", "perf", "refactor", "docs", "test", "ci", "build", "chore", "deps", "other"]
FILLER_WORDS = {"a", "an", "the", "cut", "ship", "please", "release", "new", "version", "for", "of", "to"}


def is_version(word):
    return word.removeprefix("v")[:1].isdigit()


def parse_release_request(text):
    words = [word.strip(".,!?`") for word in text.split() if not word.startswith("<@")]
    versions = [word for word in words if is_version(word)]
    repos = [word for word in words if "/" in word] or [
        word for word in words if word.lower() not in FILLER_WORDS and not is_version(word)
    ]
    if not repos:
        return None
    repo = repos[-1] if "/" in repos[-1] else f"slackapi/{repos[-1]}"
    version = f"v{versions[-1].removeprefix('v')}" if versions else ""
    return Release(repo=repo, version=version)


def next_minor_version(tag):
    major, minor, *_ = tag.removeprefix("v").split(".")
    return f"v{major}.{int(minor) + 1}.0"


def find_previous_release(release):
    release.default_branch = github_get(f"/repos/{release.repo}")["default_branch"]
    release.previous_tag = github_get(f"/repos/{release.repo}/releases/latest")["tag_name"]
    release.version = release.version or next_minor_version(release.previous_tag)
    return release


def github_get(path):
    request = urllib.request.Request(f"https://api.github.com{path}")
    request.add_header("Accept", "application/vnd.github+json")
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def collect_changes(release):
    comparison = github_get(f"/repos/{release.repo}/compare/{release.previous_tag}...{release.default_branch}")
    release.changes = [to_change(commit) for commit in comparison["commits"]]
    return release


def to_change(commit):
    author = commit.get("author") or {}
    return Change(
        title=commit["commit"]["message"].splitlines()[0],
        url=commit["html_url"],
        author=author.get("login", commit["commit"]["author"]["name"]),
        author_url=author.get("html_url", ""),
        merged_at=datetime.fromisoformat(commit["commit"]["committer"]["date"]),
    )


def is_dependency_bump(change):
    return "deps" in change.title.split(":")[0]


def change_type(change):
    if is_dependency_bump(change):
        return "deps"
    match = re.match(r"(\w+)(\(.*?\))?!?:", change.title)
    prefix = match.group(1).lower() if match else "other"
    return prefix if prefix in CHANGE_TYPES else "other"


def changelog_section(release):
    features = [change for change in release.included if not is_dependency_bump(change)]
    dependencies = [change for change in release.included if is_dependency_bump(change)]
    lines = [f"## {release.version}", ""]
    if features:
        lines += ["### Changes", ""] + [f"- {change.title} by @{change.author}" for change in features] + [""]
    if dependencies:
        lines += ["### Dependencies", ""] + [f"- {change.title}" for change in dependencies] + [""]
    return lines


def changelog_diff(release):
    before = ["# Changelog", ""]
    after = before + changelog_section(release)
    hunks = difflib.unified_diff(
        [f"{line}\n" for line in before],
        [f"{line}\n" for line in after],
        fromfile="a/CHANGELOG.md",
        tofile="b/CHANGELOG.md",
    )
    return "diff --git a/CHANGELOG.md b/CHANGELOG.md\n" + "".join(hunks)


def release_notes_markdown(release):
    return "\n".join(
        [
            f"# {release.repo} {release.version}",
            "",
            f"{len(release.included)} changes since [{release.previous_tag}]({release.compare_url}).",
            "",
        ]
        + changelog_section(release)[2:]
    )
