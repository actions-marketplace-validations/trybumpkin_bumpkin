from __future__ import annotations

from datetime import UTC, datetime

from bumpkin.app.recommendations import MergeRecommendation
from bumpkin.app.releases import ReleasePublishResult
from bumpkin.app.tags import TagPublishResult
from bumpkin.release_job import (
    ReleaseExecutionResult,
    ReleaseScopedPullRequest,
    prepare_release_plan,
    publish_release_plan,
)


def _pull_request(
    *,
    number: int,
    title: str,
    author_login: str,
    merged_at: datetime,
) -> ReleaseScopedPullRequest:
    return ReleaseScopedPullRequest(
        repository="acme/repo",
        number=number,
        title=title,
        url=f"https://github.com/acme/repo/pull/{number}",
        author_login=author_login,
        merged_at=merged_at,
        merge_commit_sha=f"merge-{number}",
        base_ref="main",
        base_sha=f"base-{number}",
        head_ref=f"feature-{number}",
        head_sha=f"head-{number}",
        labels=(),
    )


class _FakeRepositoryClient:
    def __init__(
        self,
        *,
        tags: list[str],
        commits: list[str],
        pulls_by_commit: dict[str, list[int]],
        pull_requests: dict[int, ReleaseScopedPullRequest],
    ) -> None:
        self._tags = tags
        self._commits = commits
        self._pulls_by_commit = pulls_by_commit
        self._pull_requests = pull_requests

    def list_tags(self) -> list[str]:
        return list(self._tags)

    def compare_commits(self, *, base_ref: str, head_ref: str) -> list[str]:
        assert base_ref
        assert head_ref
        return list(self._commits)

    def list_pull_requests_for_commit(self, commit_sha: str) -> list[int]:
        return list(self._pulls_by_commit.get(commit_sha, []))

    def get_pull_request(self, number: int) -> ReleaseScopedPullRequest:
        return self._pull_requests[number]


class _FakeRecommendationRunner:
    def __init__(self, labels_by_pr: dict[int, str]) -> None:
        self._labels_by_pr = labels_by_pr

    def generate(self, request) -> MergeRecommendation:  # type: ignore[no-untyped-def]
        pr_number = int(request.payload["pull_request"]["number"])
        label = self._labels_by_pr[pr_number]
        return MergeRecommendation(
            body=(
                f"Recommendation : {label}\n"
                "Summary        : files affected: src/api.ts; public=1, internal=0.\n\n"
                f"Reasoning      : {label.lower()} evidence was detected from exported API analysis.\n\n"
                "Findings:\n"
                f"- src/api.ts | rule=export_symbol_{'removed' if label == 'MAJOR' else 'added'} | "
                f"scope=public_api | suggested={label} | symbol=publicThing\n\n"
                "Next version   : v1.2.3 -> v1.3.0\n"
            ),
            label=label,
            current_version="v1.2.3",
        )


class _InvalidRecommendationRunner:
    def generate(self, request) -> MergeRecommendation:  # type: ignore[no-untyped-def]
        _ = request
        return MergeRecommendation(
            body="recommendation: n/a",
            label=None,
            current_version="v1.2.3",
        )


class _FakeTagPublisher:
    def __init__(self, status: str = "created") -> None:
        self._status = status
        self.calls: list[object] = []

    def publish(self, request):  # type: ignore[no-untyped-def]
        self.calls.append(request)
        return TagPublishResult(
            status=self._status,
            tag_name=request.tag_name,
            url=f"https://github.com/{request.repository}/releases/tag/{request.tag_name}",
        )


class _FakeReleasePublisher:
    def __init__(self, status: str = "created") -> None:
        self._status = status
        self.calls: list[object] = []

    def publish(self, request):  # type: ignore[no-untyped-def]
        self.calls.append(request)
        return ReleasePublishResult(
            status=self._status,
            tag_name=request.tag_name,
            url=f"https://github.com/{request.repository}/releases/tag/{request.tag_name}",
            release_id=101,
        )


def test_release_job_flow_plans_and_publishes_release_batch(monkeypatch) -> None:
    pr_31 = _pull_request(
        number=31,
        title="Add release preview artifact upload",
        author_login="alice",
        merged_at=datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
    )
    pr_32 = _pull_request(
        number=32,
        title="Fix release summary output",
        author_login="bob",
        merged_at=datetime(2026, 6, 2, 14, 0, tzinfo=UTC),
    )
    client = _FakeRepositoryClient(
        tags=["v1.2.3"],
        commits=["c1", "c2"],
        pulls_by_commit={"c1": [31], "c2": [32]},
        pull_requests={31: pr_31, 32: pr_32},
    )
    runner = _FakeRecommendationRunner({31: "MINOR", 32: "PATCH"})
    tag_publisher = _FakeTagPublisher(status="exists")
    release_publisher = _FakeReleasePublisher(status="updated")

    monkeypatch.setattr("bumpkin.release_job._resolve_target_ref", lambda _target: ("main", "sha-main"))
    monkeypatch.setattr("bumpkin.release_job.list_tags", lambda: [])

    plan = prepare_release_plan(
        repository="acme/repo",
        github_token="token-123",
        target_ref="main",
        base_tag="",
        client=client,
        recommendation_runner=runner,
    )
    result = publish_release_plan(
        plan,
        github_token="token-123",
        tag_publisher=tag_publisher,
        release_publisher=release_publisher,
    )

    assert plan.previous_tag == "v1.2.3"
    assert plan.next_tag == "v1.3.0"
    assert plan.release_label == "MINOR"
    assert plan.status == "planned"
    assert "## Why this bump" in plan.release_notes
    assert "## Key evidence" in plan.release_notes
    assert "## Features" in plan.release_notes
    assert "## Fixes" in plan.release_notes
    assert isinstance(result, ReleaseExecutionResult)
    assert result.status == "published"
    assert len(tag_publisher.calls) == 1
    assert len(release_publisher.calls) == 1
    assert tag_publisher.calls[0].tag_name == "v1.3.0"
    assert release_publisher.calls[0].tag_name == "v1.3.0"


def test_release_job_flow_skips_publish_for_no_bump_batch(monkeypatch) -> None:
    pr_41 = _pull_request(
        number=41,
        title="Clarify docs for release preview",
        author_login="alice",
        merged_at=datetime(2026, 6, 3, 9, 0, tzinfo=UTC),
    )
    client = _FakeRepositoryClient(
        tags=["v1.2.3"],
        commits=["c1"],
        pulls_by_commit={"c1": [41]},
        pull_requests={41: pr_41},
    )
    runner = _FakeRecommendationRunner({41: "NO_BUMP"})
    tag_publisher = _FakeTagPublisher()
    release_publisher = _FakeReleasePublisher()

    monkeypatch.setattr("bumpkin.release_job._resolve_target_ref", lambda _target: ("main", "sha-main"))
    monkeypatch.setattr("bumpkin.release_job.list_tags", lambda: [])

    plan = prepare_release_plan(
        repository="acme/repo",
        github_token="token-123",
        target_ref="main",
        base_tag="",
        client=client,
        recommendation_runner=runner,
    )
    result = publish_release_plan(
        plan,
        github_token="token-123",
        tag_publisher=tag_publisher,
        release_publisher=release_publisher,
    )

    assert plan.release_label == "NO_BUMP"
    assert plan.status == "skipped"
    assert plan.next_tag is None
    assert "No new release will be published for this batch." in plan.release_notes
    assert "## Versioning context" in plan.release_notes
    assert result.status == "skipped"
    assert tag_publisher.calls == []
    assert release_publisher.calls == []


def test_release_job_flow_surfaces_needs_review_batch(monkeypatch) -> None:
    pr_51 = _pull_request(
        number=51,
        title="Refactor API boundary detection",
        author_login="alice",
        merged_at=datetime(2026, 6, 3, 12, 0, tzinfo=UTC),
    )
    client = _FakeRepositoryClient(
        tags=["v1.2.3"],
        commits=["c1"],
        pulls_by_commit={"c1": [51]},
        pull_requests={51: pr_51},
    )
    runner = _InvalidRecommendationRunner()

    monkeypatch.setattr("bumpkin.release_job._resolve_target_ref", lambda _target: ("main", "sha-main"))
    monkeypatch.setattr("bumpkin.release_job.list_tags", lambda: [])

    plan = prepare_release_plan(
        repository="acme/repo",
        github_token="token-123",
        target_ref="main",
        base_tag="",
        client=client,
        recommendation_runner=runner,
    )
    result = publish_release_plan(plan, github_token="token-123")

    assert plan.status == "needs_review"
    assert plan.next_tag is None
    assert "## Needs Review" in plan.release_notes
    assert result.status == "needs_review"
