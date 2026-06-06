from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, cast

from bumpkin.github.recommendations import (
    MergeRecommendation,
    MergeRecommendationRequest,
    PipelineRecommendationRunner,
    RecommendationRunner,
)
from bumpkin.github.releases import (
    GitHubReleasePublisher,
    ReleasePublisher,
    ReleasePublishRequest,
    ReleasePublishResult,
)
from bumpkin.github.tags import (
    GitHubTagPublisher,
    TagPublisher,
    TagPublishRequest,
    TagPublishResult,
)
from bumpkin.github.types import AppEvent
from bumpkin.versioning.tags import detect_next_version, list_tags, resolve_current_tag

_LABEL_PRECEDENCE = {"NO_BUMP": 0, "PATCH": 1, "MINOR": 2, "MAJOR": 3}
_SECTION_BY_LABEL = {
    "MAJOR": "Breaking Changes",
    "MINOR": "Features",
    "PATCH": "Fixes",
    "NO_BUMP": "Maintenance",
}
_SECTION_ORDER = ("Breaking Changes", "Features", "Fixes", "Maintenance")
_SUMMARY_LINE_RE = re.compile(r"(?im)^summary\s*:\s*(?P<value>.+)$")
_REASONING_LINE_RE = re.compile(r"(?im)^reasoning\s*:\s*(?P<value>.+)$")


@dataclass(frozen=True, slots=True)
class ReleaseScopedPullRequest:
    repository: str
    number: int
    title: str
    url: str
    author_login: str | None
    merged_at: datetime
    merge_commit_sha: str
    base_ref: str | None
    base_sha: str | None
    head_ref: str | None
    head_sha: str | None
    labels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReleaseRecommendationRecord:
    pull_request: ReleaseScopedPullRequest
    recommendation: MergeRecommendation | None
    status: str
    label: str | None
    reason: str | None = None
    summary: str | None = None
    reasoning: str | None = None
    evidence_lines: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReleasePlan:
    repository: str
    target_ref: str
    target_sha: str
    previous_tag: str | None
    next_tag: str | None
    release_label: str | None
    pull_requests: tuple[ReleaseScopedPullRequest, ...]
    recommendations: tuple[ReleaseRecommendationRecord, ...]
    release_notes: str
    notes: tuple[str, ...]
    status: str = "planned"


@dataclass(frozen=True, slots=True)
class ReleaseExecutionResult:
    status: str
    plan: ReleasePlan
    tag_result: TagPublishResult | None = None
    release_result: ReleasePublishResult | None = None


class GitHubRepositoryClientProtocol(Protocol):
    def list_tags(self) -> list[str]: ...

    def compare_commits(self, *, base_ref: str, head_ref: str) -> list[str]: ...

    def list_pull_requests_for_commit(self, commit_sha: str) -> list[int]: ...

    def get_pull_request(self, number: int) -> ReleaseScopedPullRequest: ...


def _normalize_label(label: str | None) -> str | None:
    normalized = (label or "").strip().upper().replace("-", "_").replace(" ", "_")
    if normalized == "NOBUMP":
        normalized = "NO_BUMP"
    return normalized if normalized in _LABEL_PRECEDENCE else None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bumpkin release-scoped workflow")
    parser.add_argument(
        "--operation",
        choices=("preview", "publish"),
        default="preview",
        help="Preview the release or publish the tag and GitHub Release.",
    )
    parser.add_argument(
        "--repository",
        default=os.getenv("GITHUB_REPOSITORY", ""),
        help="GitHub repository in owner/repo format.",
    )
    parser.add_argument(
        "--github-token",
        default=os.getenv("GITHUB_TOKEN", ""),
        help="GitHub token used for repository queries and release publishing.",
    )
    parser.add_argument(
        "--target-ref",
        default=os.getenv("GITHUB_SHA", ""),
        help="Target git ref or SHA for the release boundary head. Defaults to GITHUB_SHA or HEAD.",
    )
    parser.add_argument(
        "--base-tag",
        default="",
        help="Optional explicit previous tag override. Defaults to the latest parseable tag.",
    )
    parser.add_argument(
        "--output-markdown",
        default="artifacts/release/bumpkin-release-notes.md",
        help="Where to write the rendered release notes markdown artifact.",
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=15,
        help="GitHub API request timeout in seconds.",
    )
    return parser.parse_args()


def _run_git(args: list[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _resolve_target_ref(input_target_ref: str) -> tuple[str, str]:
    target_ref = input_target_ref.strip()
    if target_ref:
        try:
            target_sha = _run_git(["rev-parse", target_ref])
        except (RuntimeError, subprocess.CalledProcessError):
            target_sha = target_ref
        return target_ref, target_sha
    try:
        target_sha = _run_git(["rev-parse", "HEAD"])
    except (RuntimeError, subprocess.CalledProcessError) as err:
        raise RuntimeError("Unable to resolve HEAD for release target.") from err
    return target_sha, target_sha


def _parse_iso8601(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)  # noqa: UP017
    return parsed.astimezone(timezone.utc)  # noqa: UP017


def _json_request(
    *,
    token: str,
    url: str,
    timeout_seconds: int,
) -> object:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "bumpkin-release-job",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1, timeout_seconds)) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="ignore").strip()
        raise RuntimeError(f"GitHub API error {err.code}: {detail or err.reason}") from err
    except urllib.error.URLError as err:
        raise RuntimeError(f"GitHub API request failed: {err.reason}") from err
    return json.loads(body) if body else None


class GitHubRepositoryClient:
    def __init__(
        self,
        *,
        repository: str,
        token: str,
        timeout_seconds: int = 15,
    ) -> None:
        self._repository = repository.strip()
        self._token = token.strip()
        self._timeout_seconds = max(1, timeout_seconds)
        if not self._repository:
            raise ValueError("repository is required.")
        if not self._token:
            raise ValueError("github token is required.")

    def list_tags(self) -> list[str]:
        page = 1
        per_page = 100
        collected: list[str] = []
        while True:
            url = (
                f"https://api.github.com/repos/{self._repository}/tags"
                f"?per_page={per_page}&page={page}"
            )
            payload = _json_request(
                token=self._token, url=url, timeout_seconds=self._timeout_seconds
            )
            if not isinstance(payload, list):
                break
            items = cast("list[object]", payload)
            if not items:
                break
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = str(cast("dict[str, object]", item).get("name", "")).strip()
                if name:
                    collected.append(name)
            if len(items) < per_page:
                break
            page += 1
        return collected

    def compare_commits(self, *, base_ref: str, head_ref: str) -> list[str]:
        encoded_base = urllib.parse.quote(base_ref, safe="")
        encoded_head = urllib.parse.quote(head_ref, safe="")
        url = f"https://api.github.com/repos/{self._repository}/compare/{encoded_base}...{encoded_head}"
        payload = _json_request(token=self._token, url=url, timeout_seconds=self._timeout_seconds)
        if not isinstance(payload, dict):
            raise RuntimeError("GitHub compare API returned an unexpected payload.")
        payload_map = cast("dict[str, object]", payload)
        commits = payload_map.get("commits")
        if not isinstance(commits, list):
            raise RuntimeError("GitHub compare API did not include commit data.")
        commit_shas: list[str] = []
        for item in commits:
            if not isinstance(item, dict):
                continue
            sha = str(cast("dict[str, object]", item).get("sha", "")).strip()
            if sha:
                commit_shas.append(sha)
        return list(dict.fromkeys(commit_shas))

    def list_pull_requests_for_commit(self, commit_sha: str) -> list[int]:
        normalized_sha = commit_sha.strip()
        if not normalized_sha:
            return []
        url = f"https://api.github.com/repos/{self._repository}/commits/{normalized_sha}/pulls"
        payload = _json_request(token=self._token, url=url, timeout_seconds=self._timeout_seconds)
        if not isinstance(payload, list):
            return []
        pull_numbers: list[int] = []
        for item in cast("list[object]", payload):
            if not isinstance(item, dict):
                continue
            number = cast("dict[str, object]", item).get("number")
            if isinstance(number, int) and number > 0:
                pull_numbers.append(number)
        return list(dict.fromkeys(pull_numbers))

    def get_pull_request(self, number: int) -> ReleaseScopedPullRequest:
        url = f"https://api.github.com/repos/{self._repository}/pulls/{number}"
        payload = _json_request(token=self._token, url=url, timeout_seconds=self._timeout_seconds)
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"GitHub pull request API returned an unexpected payload for PR #{number}."
            )
        payload_map = cast("dict[str, object]", payload)
        title = str(payload_map.get("title", "")).strip()
        html_url = str(payload_map.get("html_url", "")).strip()
        merge_commit_sha = str(payload_map.get("merge_commit_sha", "")).strip()
        merged_at_raw = str(payload_map.get("merged_at", "")).strip()
        if not merge_commit_sha or not merged_at_raw:
            raise RuntimeError(
                f"PR #{number} is missing merged metadata required for a release batch."
            )
        user = payload_map.get("user")
        author_login = None
        if isinstance(user, dict):
            author_login = str(cast("dict[str, object]", user).get("login", "")).strip() or None
        base = payload_map.get("base")
        head = payload_map.get("head")
        base_ref = base_sha = head_ref = head_sha = None
        if isinstance(base, dict):
            base_map = cast("dict[str, object]", base)
            base_ref = str(base_map.get("ref", "")).strip() or None
            base_sha = str(base_map.get("sha", "")).strip() or None
        if isinstance(head, dict):
            head_map = cast("dict[str, object]", head)
            head_ref = str(head_map.get("ref", "")).strip() or None
            head_sha = str(head_map.get("sha", "")).strip() or None
        labels_raw = payload_map.get("labels")
        labels: list[str] = []
        if isinstance(labels_raw, list):
            for item in cast("list[object]", labels_raw):
                if not isinstance(item, dict):
                    continue
                label_name = str(cast("dict[str, object]", item).get("name", "")).strip()
                if label_name:
                    labels.append(label_name)
        return ReleaseScopedPullRequest(
            repository=self._repository,
            number=number,
            title=title or f"PR #{number}",
            url=html_url or f"https://github.com/{self._repository}/pull/{number}",
            author_login=author_login,
            merged_at=_parse_iso8601(merged_at_raw),
            merge_commit_sha=merge_commit_sha,
            base_ref=base_ref,
            base_sha=base_sha,
            head_ref=head_ref,
            head_sha=head_sha,
            labels=tuple(labels),
        )


def _build_app_event(pull_request: ReleaseScopedPullRequest) -> AppEvent:
    return AppEvent(
        event="pull_request",
        action="closed",
        installation_id=None,
        repository=pull_request.repository,
        pull_request_number=pull_request.number,
        sender_login=pull_request.author_login,
        delivery_id=f"release-scope-pr-{pull_request.number}",
        merged=True,
        merge_commit_sha=pull_request.merge_commit_sha,
        base_ref=pull_request.base_ref,
        base_sha=pull_request.base_sha,
        head_ref=pull_request.head_ref,
        head_sha=pull_request.head_sha,
    )


def _build_payload(pull_request: ReleaseScopedPullRequest) -> dict[str, object]:
    return {
        "action": "closed",
        "repository": {"full_name": pull_request.repository},
        "pull_request": {
            "number": pull_request.number,
            "merged": True,
            "merge_commit_sha": pull_request.merge_commit_sha,
            "title": pull_request.title,
            "html_url": pull_request.url,
            "user": {"login": pull_request.author_login or ""},
            "base": {"ref": pull_request.base_ref or "", "sha": pull_request.base_sha or ""},
            "head": {"ref": pull_request.head_ref or "", "sha": pull_request.head_sha or ""},
            "labels": [{"name": label} for label in pull_request.labels],
        },
    }


def _discover_pull_requests(
    *,
    client: GitHubRepositoryClientProtocol,
    base_ref: str,
    head_ref: str,
) -> list[ReleaseScopedPullRequest]:
    pull_numbers: list[int] = []
    for commit_sha in client.compare_commits(base_ref=base_ref, head_ref=head_ref):
        pull_numbers.extend(client.list_pull_requests_for_commit(commit_sha))
    unique_numbers = sorted({number for number in pull_numbers if number > 0})
    pull_requests = [client.get_pull_request(number) for number in unique_numbers]
    merged_pull_requests = [
        pull_request for pull_request in pull_requests if pull_request.merge_commit_sha.strip()
    ]
    merged_pull_requests.sort(key=lambda item: (item.merged_at, item.number))
    return merged_pull_requests


def _analyze_pull_requests(
    *,
    pull_requests: list[ReleaseScopedPullRequest],
    recommendation_runner: RecommendationRunner,
    github_token: str,
) -> list[ReleaseRecommendationRecord]:
    recommendation_records: list[ReleaseRecommendationRecord] = []
    for pull_request in pull_requests:
        try:
            recommendation = recommendation_runner.generate(
                MergeRecommendationRequest(
                    event=_build_app_event(pull_request),
                    payload=_build_payload(pull_request),
                    provider_token=github_token,
                )
            )
        except RuntimeError as err:
            recommendation_records.append(
                ReleaseRecommendationRecord(
                    pull_request=pull_request,
                    recommendation=None,
                    status="unsupported",
                    label=None,
                    reason=str(err),
                )
            )
            continue
        summary, reasoning, evidence_lines = _extract_recommendation_insights(recommendation.body)
        label = _normalize_label(recommendation.label)
        if label is None:
            recommendation_records.append(
                ReleaseRecommendationRecord(
                    pull_request=pull_request,
                    recommendation=recommendation,
                    status="needs_review",
                    label=None,
                    reason="PR recommendation did not produce a normalized release label.",
                    summary=summary,
                    reasoning=reasoning,
                    evidence_lines=evidence_lines,
                )
            )
            continue
        recommendation_records.append(
            ReleaseRecommendationRecord(
                pull_request=pull_request,
                recommendation=recommendation,
                status="classified",
                label=label,
                summary=summary,
                reasoning=reasoning,
                evidence_lines=evidence_lines,
            )
        )
    return recommendation_records


def _extract_first_match(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    value = " ".join(match.group("value").split()).strip()
    return value or None


def _extract_findings_block_lines(body: str) -> tuple[str, ...]:
    lines = body.splitlines()
    findings_started = False
    findings: list[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if not findings_started:
            if stripped.lower() == "findings:":
                findings_started = True
            continue
        if not stripped:
            if findings:
                break
            continue
        if stripped.startswith("- "):
            findings.append(stripped[2:].strip())
            continue
        if findings:
            break
    return tuple(line for line in findings if line)


def _extract_recommendation_insights(body: str) -> tuple[str | None, str | None, tuple[str, ...]]:
    return (
        _extract_first_match(_SUMMARY_LINE_RE, body),
        _extract_first_match(_REASONING_LINE_RE, body),
        _extract_findings_block_lines(body),
    )


def _versioning_context_notes(notes: tuple[str, ...] | list[str]) -> list[str]:
    relevant_prefixes = (
        "Detected versioning scheme:",
        "Zero-based policy:",
        "CalVer detected:",
        "Detected mixed tag prefixes",
        "Tag source order was non-monotonic;",
    )
    return [note for note in notes if note.startswith(relevant_prefixes)]


def _top_label_records(
    recommendations: list[ReleaseRecommendationRecord],
    release_label: str | None,
) -> list[ReleaseRecommendationRecord]:
    normalized_label = _normalize_label(release_label)
    if normalized_label is None:
        return []
    return [
        record
        for record in recommendations
        if record.status == "classified" and record.label == normalized_label
    ]


def _release_label_headline(
    release_label: str, matching_records: list[ReleaseRecommendationRecord]
) -> str:
    count = len(matching_records)
    if release_label == "MAJOR":
        return f"Breaking public API evidence was detected in {count} merged PR(s)."
    if release_label == "MINOR":
        return f"User-facing additive changes were detected in {count} merged PR(s)."
    if release_label == "PATCH":
        return f"Backward-compatible runtime changes were detected in {count} merged PR(s)."
    if release_label == "NO_BUMP":
        return f"All {count} merged PR(s) resolved to NO_BUMP."
    return f"{count} merged PR(s) contributed to this release decision."


def _build_release_why_lines(
    *,
    release_label: str | None,
    recommendations: list[ReleaseRecommendationRecord],
) -> list[str]:
    normalized_label = _normalize_label(release_label)
    if normalized_label is None:
        return []
    matching_records = _top_label_records(recommendations, normalized_label)
    if not matching_records:
        return []
    lines = [_release_label_headline(normalized_label, matching_records)]
    seen_reasoning: set[str] = set()
    for record in matching_records:
        reasoning = " ".join((record.reasoning or "").split()).strip()
        if not reasoning or reasoning in seen_reasoning:
            continue
        seen_reasoning.add(reasoning)
        lines.append(reasoning.rstrip(".") + ".")
        if len(lines) >= 3:
            break
    return lines


def _humanize_evidence_line(line: str) -> str:
    parts = [part.strip() for part in line.split("|") if part.strip()]
    if not parts:
        return line.strip()
    path = parts[0]
    details: list[str] = []
    for part in parts[1:]:
        key, sep, value = part.partition("=")
        if not sep:
            continue
        normalized_key = key.strip().lower()
        normalized_value = " ".join(value.split()).strip()
        if not normalized_value:
            continue
        if normalized_key in {"suggested", "severity"}:
            continue
        if normalized_key == "scope" and normalized_value.lower() == "non_runtime":
            continue
        if normalized_key == "rule":
            details.append(normalized_value.replace("_", " "))
            continue
        if normalized_key == "scope":
            details.append(normalized_value.replace("_", " "))
            continue
        details.append(normalized_value)
    if not details:
        return path
    return f"{path} - {'; '.join(details)}"


def _build_release_evidence_lines(
    *,
    release_label: str | None,
    recommendations: list[ReleaseRecommendationRecord],
    max_items: int = 3,
) -> list[str]:
    evidence: list[str] = []
    seen: set[str] = set()
    has_detailed_evidence = False
    for record in _top_label_records(recommendations, release_label):
        for raw_line in record.evidence_lines:
            detail = _humanize_evidence_line(raw_line)
            line = f"PR #{record.pull_request.number}: {detail}"
            if line in seen:
                continue
            seen.add(line)
            evidence.append(line)
            has_detailed_evidence = True
            if len(evidence) >= max_items:
                return evidence
        if record.summary and not has_detailed_evidence:
            line = f"PR #{record.pull_request.number}: {record.summary}"
            if line not in seen:
                seen.add(line)
                evidence.append(line)
                if len(evidence) >= max_items:
                    return evidence
    return evidence


def _aggregate_release_label(recommendations: list[ReleaseRecommendationRecord]) -> str | None:
    best_label: str | None = None
    best_rank = -1
    for record in recommendations:
        if record.status != "classified" or not record.label:
            continue
        rank = _LABEL_PRECEDENCE.get(record.label, -1)
        if rank > best_rank:
            best_rank = rank
            best_label = record.label
    return best_label


def _render_release_notes(
    *,
    previous_tag: str | None,
    next_tag: str | None,
    release_label: str | None,
    recommendations: list[ReleaseRecommendationRecord],
    notes: tuple[str, ...] | list[str] = (),
) -> str:
    heading = next_tag or "Release Preview"
    lines: list[str] = [f"# {heading}", ""]
    if previous_tag:
        lines.append(f"Previous tag: {previous_tag}")
    if next_tag:
        lines.append(f"Next tag: {next_tag}")
    if release_label:
        lines.append(f"Release type: {release_label}")
    lines.append(f"Included PRs: {len(recommendations)}")

    why_lines = _build_release_why_lines(
        release_label=release_label,
        recommendations=recommendations,
    )
    if why_lines:
        lines.extend(["", "## Why this bump"])
        lines.extend(f"- {line}" for line in why_lines)

    versioning_notes = _versioning_context_notes(notes)
    if versioning_notes:
        lines.extend(["", "## Versioning context"])
        lines.extend(f"- {note}" for note in versioning_notes)

    evidence_lines = _build_release_evidence_lines(
        release_label=release_label,
        recommendations=recommendations,
    )
    if evidence_lines:
        lines.extend(["", "## Key evidence"])
        lines.extend(f"- {line}" for line in evidence_lines)

    grouped: dict[str, list[ReleaseRecommendationRecord]] = {
        section: [] for section in _SECTION_ORDER
    }
    unresolved: list[ReleaseRecommendationRecord] = []
    contributors: list[str] = []
    seen_contributors: set[str] = set()
    for record in recommendations:
        if record.status != "classified" or not record.label:
            unresolved.append(record)
            continue
        section = _SECTION_BY_LABEL.get(record.label, "Maintenance")
        grouped.setdefault(section, []).append(record)
        author = (record.pull_request.author_login or "").strip()
        if author and author not in seen_contributors:
            seen_contributors.add(author)
            contributors.append(author)

    for section in _SECTION_ORDER:
        section_records = grouped.get(section, [])
        if not section_records:
            continue
        lines.extend(["", f"## {section}"])
        for record in section_records:
            pull_request = record.pull_request
            author = (
                f"@{pull_request.author_login}" if pull_request.author_login else "unknown author"
            )
            lines.append(
                f"- [PR #{pull_request.number}]({pull_request.url}) by {author}: {pull_request.title.rstrip('.')}"
            )

    if unresolved:
        lines.extend(["", "## Needs Review"])
        for record in unresolved:
            pull_request = record.pull_request
            author = (
                f"@{pull_request.author_login}" if pull_request.author_login else "unknown author"
            )
            reason = (record.reason or record.status).rstrip(".")
            lines.append(
                f"- [PR #{pull_request.number}]({pull_request.url}) by {author}: {pull_request.title.rstrip('.')} ({reason})"
            )

    if contributors:
        lines.extend(["", "## Contributors", ", ".join(f"@{author}" for author in contributors)])

    return "\n".join(lines).strip() + "\n"


def _render_no_release_notes(
    *,
    previous_tag: str | None,
    release_label: str,
    recommendations: list[ReleaseRecommendationRecord],
    notes: tuple[str, ...] | list[str] = (),
) -> str:
    lines = ["# Release Preview", ""]
    if previous_tag:
        lines.append(f"Previous tag: {previous_tag}")
    lines.append(f"Release type: {release_label}")
    lines.append(f"Included PRs: {len(recommendations)}")
    lines.extend(
        [
            "",
            "No new release will be published for this batch.",
            "All included pull requests were classified as NO_BUMP.",
        ]
    )

    versioning_notes = _versioning_context_notes(notes)
    if versioning_notes:
        lines.extend(["", "## Versioning context"])
        lines.extend(f"- {note}" for note in versioning_notes)

    maintenance_records = [
        record
        for record in recommendations
        if record.label is not None and _SECTION_BY_LABEL.get(record.label) == "Maintenance"
    ]
    if maintenance_records:
        lines.extend(["", "## Included PRs"])
        for record in maintenance_records:
            pull_request = record.pull_request
            author = (
                f"@{pull_request.author_login}" if pull_request.author_login else "unknown author"
            )
            lines.append(
                f"- [PR #{pull_request.number}]({pull_request.url}) by {author}: {pull_request.title.rstrip('.')}"
            )

    return "\n".join(lines).strip() + "\n"


def prepare_release_plan(
    *,
    repository: str,
    github_token: str,
    target_ref: str,
    base_tag: str,
    client: GitHubRepositoryClientProtocol | None = None,
    recommendation_runner: RecommendationRunner | None = None,
    request_timeout: int = 15,
) -> ReleasePlan:
    normalized_repository = repository.strip()
    if not normalized_repository:
        raise ValueError("repository is required.")
    normalized_token = github_token.strip()
    if not normalized_token:
        raise ValueError("github token is required.")
    resolved_target_ref, target_sha = _resolve_target_ref(target_ref)
    api_client = client or GitHubRepositoryClient(
        repository=normalized_repository,
        token=normalized_token,
        timeout_seconds=request_timeout,
    )
    notes: list[str] = []
    candidate_tags = list_tags()
    if not candidate_tags:
        candidate_tags = api_client.list_tags()
    previous_tag, current_tag_notes = resolve_current_tag(
        latest_tag=base_tag.strip() or None,
        tags=candidate_tags,
    )
    notes.extend(current_tag_notes)
    if previous_tag is None:
        raise RuntimeError(
            "No previous tag found. Create an initial release tag or pass --base-tag."
        )

    pull_requests = _discover_pull_requests(
        client=api_client,
        base_ref=previous_tag,
        head_ref=resolved_target_ref,
    )
    if not pull_requests:
        return ReleasePlan(
            status="skipped",
            repository=normalized_repository,
            target_ref=resolved_target_ref,
            target_sha=target_sha,
            previous_tag=previous_tag,
            next_tag=None,
            release_label=None,
            pull_requests=(),
            recommendations=(),
            release_notes=(
                f"# Release Preview\n\nPrevious tag: {previous_tag}\nIncluded PRs: 0\n\n"
                "No merged pull requests were found in this release scope.\n"
            ),
            notes=tuple(notes),
        )

    runner = recommendation_runner or PipelineRecommendationRunner()
    recommendations = _analyze_pull_requests(
        pull_requests=pull_requests,
        recommendation_runner=runner,
        github_token=normalized_token,
    )
    unresolved_records = [record for record in recommendations if record.status != "classified"]
    release_label = _aggregate_release_label(recommendations)
    if release_label is None and unresolved_records:
        notes.append(
            "Release scope contains unresolved pull requests that need review before publish."
        )
        release_notes = _render_release_notes(
            previous_tag=previous_tag,
            next_tag=None,
            release_label=None,
            recommendations=recommendations,
            notes=notes,
        )
        return ReleasePlan(
            status="needs_review",
            repository=normalized_repository,
            target_ref=resolved_target_ref,
            target_sha=target_sha,
            previous_tag=previous_tag,
            next_tag=None,
            release_label=None,
            pull_requests=tuple(pull_requests),
            recommendations=tuple(recommendations),
            release_notes=release_notes,
            notes=tuple(notes),
        )
    if release_label is None:
        raise RuntimeError("Could not determine an aggregate release label.")
    _, next_tag, version_notes = detect_next_version(release_label, latest_tag=previous_tag)
    notes.extend(version_notes)
    if release_label == "NO_BUMP":
        notes.append(
            "Release scope resolved to NO_BUMP; no tag or GitHub Release will be published."
        )
        release_notes = _render_no_release_notes(
            previous_tag=previous_tag,
            release_label=release_label,
            recommendations=recommendations,
            notes=notes,
        )
        return ReleasePlan(
            status="skipped",
            repository=normalized_repository,
            target_ref=resolved_target_ref,
            target_sha=target_sha,
            previous_tag=previous_tag,
            next_tag=None,
            release_label=release_label,
            pull_requests=tuple(pull_requests),
            recommendations=tuple(recommendations),
            release_notes=release_notes,
            notes=tuple(notes),
        )
    if not next_tag:
        raise RuntimeError("Could not compute the next release tag from the current scope.")
    release_notes = _render_release_notes(
        previous_tag=previous_tag,
        next_tag=next_tag,
        release_label=release_label,
        recommendations=recommendations,
        notes=notes,
    )
    return ReleasePlan(
        status="planned",
        repository=normalized_repository,
        target_ref=resolved_target_ref,
        target_sha=target_sha,
        previous_tag=previous_tag,
        next_tag=next_tag,
        release_label=release_label,
        pull_requests=tuple(pull_requests),
        recommendations=tuple(recommendations),
        release_notes=release_notes,
        notes=tuple(notes),
    )


def publish_release_plan(
    plan: ReleasePlan,
    *,
    github_token: str,
    tag_publisher: TagPublisher | None = None,
    release_publisher: ReleasePublisher | None = None,
) -> ReleaseExecutionResult:
    normalized_token = github_token.strip()
    if not normalized_token:
        raise ValueError("github token is required.")
    if plan.status == "needs_review":
        return ReleaseExecutionResult(status="needs_review", plan=plan)
    if not plan.next_tag:
        if plan.status == "skipped" or plan.release_label == "NO_BUMP":
            return ReleaseExecutionResult(status="skipped", plan=plan)
        raise RuntimeError("Cannot publish a release plan without a next tag.")
    tag_publisher_impl = tag_publisher or GitHubTagPublisher(token=normalized_token)
    release_publisher_impl = release_publisher or GitHubReleasePublisher(token=normalized_token)
    tag_result = tag_publisher_impl.publish(
        TagPublishRequest(
            repository=plan.repository,
            tag_name=plan.next_tag,
            target_sha=plan.target_sha,
        )
    )
    if tag_result.status not in {"created", "exists"}:
        raise RuntimeError(
            tag_result.message or f"Tag publish failed with status {tag_result.status}."
        )
    release_result = release_publisher_impl.publish(
        ReleasePublishRequest(
            repository=plan.repository,
            tag_name=plan.next_tag,
            target_sha=plan.target_sha,
            body=plan.release_notes,
            name=plan.next_tag,
        )
    )
    if release_result.status not in {"created", "updated"}:
        raise RuntimeError(
            release_result.message or f"Release publish failed with status {release_result.status}."
        )
    return ReleaseExecutionResult(
        status="published",
        plan=plan,
        tag_result=tag_result,
        release_result=release_result,
    )


def _write_text_file(path_value: str, content: str) -> str:
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)


def _write_github_output(values: dict[str, str]) -> None:
    output_path = os.getenv("GITHUB_OUTPUT", "").strip()
    if not output_path:
        return
    lines: list[str] = []
    for key, value in values.items():
        lines.append(f"{key}<<__BUMPKIN_EOF__")
        lines.append(value)
        lines.append("__BUMPKIN_EOF__")
    with Path(output_path).open("a", encoding="utf-8") as output_file:
        output_file.write("\n".join(lines) + "\n")


def _append_step_summary(markdown: str) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
    if not summary_path:
        return
    with Path(summary_path).open("a", encoding="utf-8") as summary_file:
        summary_file.write(markdown.rstrip() + "\n")


def _build_summary_payload(
    *,
    status: str,
    plan: ReleasePlan,
    release_url: str | None = None,
    tag_url: str | None = None,
    notes_path: str,
) -> dict[str, str]:
    return {
        "release_status": status,
        "release_previous_tag": plan.previous_tag or "",
        "release_next_tag": plan.next_tag or "",
        "release_label": plan.release_label or "",
        "release_pr_count": str(len(plan.pull_requests)),
        "release_notes_path": notes_path,
        "release_target_sha": plan.target_sha,
        "release_url": release_url or "",
        "tag_url": tag_url or "",
    }


def run_release_job(args: argparse.Namespace | None = None) -> int:
    parsed = args or _parse_args()
    plan = prepare_release_plan(
        repository=parsed.repository,
        github_token=parsed.github_token,
        target_ref=parsed.target_ref,
        base_tag=parsed.base_tag,
        request_timeout=parsed.request_timeout,
    )
    notes_path = _write_text_file(parsed.output_markdown, plan.release_notes)
    if parsed.operation == "publish":
        execution = publish_release_plan(plan, github_token=parsed.github_token)
        release_url = execution.release_result.url if execution.release_result else None
        tag_url = execution.tag_result.url if execution.tag_result else None
        _append_step_summary(plan.release_notes)
        _write_github_output(
            _build_summary_payload(
                status=execution.status,
                plan=plan,
                release_url=release_url,
                tag_url=tag_url,
                notes_path=notes_path,
            )
        )
        print(
            json.dumps(
                {
                    "status": execution.status,
                    "previous_tag": plan.previous_tag,
                    "next_tag": plan.next_tag,
                    "release_label": plan.release_label,
                    "pull_request_count": len(plan.pull_requests),
                    "release_url": release_url,
                    "tag_url": tag_url,
                    "release_notes_path": notes_path,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    _append_step_summary(plan.release_notes)
    status = plan.status if plan.pull_requests else "skipped"
    _write_github_output(
        _build_summary_payload(
            status=status,
            plan=plan,
            notes_path=notes_path,
        )
    )
    print(
        json.dumps(
            {
                "status": status,
                "previous_tag": plan.previous_tag,
                "next_tag": plan.next_tag,
                "release_label": plan.release_label,
                "pull_request_count": len(plan.pull_requests),
                "release_notes_path": notes_path,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    return run_release_job()


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "GitHubRepositoryClient",
    "ReleaseExecutionResult",
    "ReleasePlan",
    "ReleaseRecommendationRecord",
    "ReleaseScopedPullRequest",
    "main",
    "prepare_release_plan",
    "publish_release_plan",
    "run_release_job",
]
