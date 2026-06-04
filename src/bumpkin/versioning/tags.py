from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import cast

VERSION_RE = re.compile(
    r"^(?P<prefix>.*?)(?P<version>\d+(?:\.\d+){2,3})(?:[-+][0-9A-Za-z][0-9A-Za-z.-]*)?$"
)


@dataclass
class ParsedTag:
    original_tag: str
    prefix: str
    version: str
    parts: list[int]
    scheme: str


def bump_semver(version: str, label: str) -> str:
    major, minor, patch = [int(x) for x in version.split(".")]
    normalized = label.upper()

    if normalized == "MAJOR":
        return f"{major + 1}.0.0"
    if normalized == "MINOR":
        return f"{major}.{minor + 1}.0"
    if normalized == "NO_BUMP":
        return f"{major}.{minor}.{patch}"
    return f"{major}.{minor}.{patch + 1}"


def _run_git(args: list[str]) -> str:
    proc = subprocess.run(["git", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _list_tags() -> list[str]:
    local_tags = [
        tag.strip() for tag in _run_git(["tag", "--sort=-creatordate"]).splitlines() if tag.strip()
    ]
    if local_tags:
        return local_tags
    repository = os.getenv("GITHUB_REPOSITORY", "").strip()
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not repository or not token:
        return []
    return _fetch_tags_from_github_api(repository=repository, token=token)


def _github_api_request(token: str, url: str) -> object:
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "bumpkin-app",
        },
    )
    try:
        with urllib.request.urlopen(req) as response:
            body = response.read().decode("utf-8")
    except (urllib.error.HTTPError, urllib.error.URLError):
        return []
    return json.loads(body) if body else []


def _fetch_tags_from_github_api(*, repository: str, token: str) -> list[str]:
    page = 1
    per_page = 100
    collected: list[str] = []
    while True:
        url = f"https://api.github.com/repos/{repository}/tags?per_page={per_page}&page={page}"
        payload = _github_api_request(token, url)
        if not isinstance(payload, list):
            break
        payload_items = cast("list[object]", payload)
        items = [
            cast("dict[str, object]", item) for item in payload_items if isinstance(item, dict)
        ]
        if not items:
            break
        for item in items:
            name = str(item.get("name", "")).strip()
            if name:
                collected.append(name)
        if len(items) < per_page:
            break
        page += 1
    return collected


def parse_tag(tag: str) -> ParsedTag | None:
    match = VERSION_RE.match(tag.strip())
    if not match:
        return None

    prefix = match.group("prefix")
    version = match.group("version")
    parts = [int(x) for x in version.split(".")]

    if len(parts) == 4:
        scheme = "four-part"
    elif len(parts) == 3:
        if parts[0] == 0:
            scheme = "zero-based"
        elif 2000 <= parts[0] <= 2100 and 1 <= parts[1] <= 12 and 1 <= parts[2] <= 31:
            scheme = "calver"
        else:
            scheme = "semver"
    else:
        return None

    return ParsedTag(
        original_tag=tag,
        prefix=prefix,
        version=version,
        parts=parts,
        scheme=scheme,
    )


def _next_version(
    parsed: ParsedTag,
    label: str,
    *,
    pre_1_0_breaking_as_minor: bool = True,
) -> str:
    normalized = label.upper()
    if normalized == "NO_BUMP":
        return parsed.version
    if parsed.scheme == "semver":
        return bump_semver(parsed.version, normalized)

    if parsed.scheme == "zero-based":
        _, minor, patch = parsed.parts
        if normalized == "MAJOR" and not pre_1_0_breaking_as_minor:
            return "1.0.0"
        if normalized in {"MAJOR", "MINOR"}:
            return f"0.{minor + 1}.0"
        return f"0.{minor}.{patch + 1}"

    if parsed.scheme == "four-part":
        major, minor, patch, build = parsed.parts
        core = bump_semver(f"{major}.{minor}.{patch}", normalized)
        return f"{core}.{build + 1}"

    if parsed.scheme == "calver":
        now = datetime.now(timezone.utc)  # noqa: UP017 - keep basedpyright compatibility
        return f"{now.year}.{now.month:02d}.{now.day:02d}"

    raise ValueError(f"Unsupported scheme: {parsed.scheme}")


def _resolve_output_prefix(
    parsed_current: ParsedTag, parsed_tags: list[ParsedTag]
) -> tuple[str, str | None]:
    scheme_prefixes = {
        parsed.prefix for parsed in parsed_tags if parsed.scheme == parsed_current.scheme
    }
    if len(scheme_prefixes) <= 1:
        return parsed_current.prefix, None
    return "v", (
        "Detected mixed tag prefixes for the current versioning scheme; "
        "defaulting next version prefix to 'v'."
    )


def _select_current_tag(
    latest_tag: str | None, tags: list[str]
) -> tuple[ParsedTag | None, str | None, list[str]]:
    notes: list[str] = []
    if latest_tag:
        parsed_latest = parse_tag(latest_tag)
        if not parsed_latest:
            return (
                None,
                (f"Could not parse latest tag {latest_tag!r}; next version not computed."),
                notes,
            )
        return parsed_latest, None, notes

    parsed_candidates: list[ParsedTag] = []
    skipped_unparseable = 0
    for tag in tags:
        parsed = parse_tag(tag)
        if parsed:
            parsed_candidates.append(parsed)
        else:
            skipped_unparseable += 1

    if parsed_candidates:
        selected = max(parsed_candidates, key=lambda parsed: tuple(parsed.parts))
        if skipped_unparseable:
            notes.append(
                "Skipped "
                f"{skipped_unparseable} unparseable tag(s) while selecting highest "
                f"parseable tag {selected.original_tag!r}."
            )
        first_parseable = parsed_candidates[0]
        if selected.original_tag != first_parseable.original_tag:
            notes.append(
                "Tag source order was non-monotonic; selected highest parseable tag "
                f"{selected.original_tag!r} for next-version computation."
            )
        return selected, None, notes

    if tags:
        return (
            None,
            (f"Could not parse latest tag {tags[0]!r}; next version not computed."),
            notes,
        )
    return None, "No tags detected; next version not computed.", notes


def detect_next_version(
    label: str,
    latest_tag: str | None = None,
    tags: list[str] | None = None,
    *,
    pre_1_0_breaking_as_minor: bool = True,
) -> tuple[str | None, str | None, list[str]]:
    notes: list[str] = []
    detected_tags = tags if tags is not None else _list_tags()
    current, selection_error, selection_notes = _select_current_tag(latest_tag, detected_tags)
    notes.extend(selection_notes)
    if selection_error:
        notes.append(selection_error)
        return latest_tag or (detected_tags[0] if detected_tags else None), None, notes
    if current is None:
        notes.append("Could not resolve current tag for next version computation.")
        return latest_tag or (detected_tags[0] if detected_tags else None), None, notes

    normalized = label.upper()
    if latest_tag:
        parsed_tags = [current]
    else:
        parsed_tags = [parsed for tag in detected_tags if (parsed := parse_tag(tag))]
    output_prefix, prefix_note = _resolve_output_prefix(current, parsed_tags)
    if prefix_note:
        notes.append(prefix_note)

    if normalized == "NO_BUMP":
        notes.append("NO_BUMP classification: next version not computed.")
        notes.append(f"Detected versioning scheme: {current.scheme}.")
        return current.original_tag, None, notes

    next_version = _next_version(
        current,
        normalized,
        pre_1_0_breaking_as_minor=pre_1_0_breaking_as_minor,
    )
    notes.append(f"Detected versioning scheme: {current.scheme}.")
    if current.scheme == "zero-based":
        if pre_1_0_breaking_as_minor:
            notes.append("Zero-based policy: breaking changes before 1.0.0 bump the minor version.")
        else:
            notes.append(
                "Zero-based policy: breaking changes before 1.0.0 use strict MAJOR semantics."
            )
    if current.scheme == "calver":
        notes.append("CalVer detected: next version uses current UTC date.")

    return current.original_tag, f"{output_prefix}{next_version}", notes


def resolve_current_tag(
    *,
    latest_tag: str | None = None,
    tags: list[str] | None = None,
) -> tuple[str | None, list[str]]:
    notes: list[str] = []
    detected_tags = tags if tags is not None else _list_tags()
    current, selection_error, selection_notes = _select_current_tag(latest_tag, detected_tags)
    notes.extend(selection_notes)
    if selection_error:
        notes.append(selection_error)
        return latest_tag or (detected_tags[0] if detected_tags else None), notes
    if current is None:
        notes.append("Could not resolve current tag.")
        return latest_tag or (detected_tags[0] if detected_tags else None), notes
    return current.original_tag, notes


def list_tags() -> list[str]:
    return _list_tags()


__all__ = [
    "ParsedTag",
    "bump_semver",
    "detect_next_version",
    "list_tags",
    "parse_tag",
    "resolve_current_tag",
]
