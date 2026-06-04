from __future__ import annotations

import argparse
from datetime import UTC, datetime

from bumpkin.app.recommendations import MergeRecommendation
from bumpkin.app.releases import ReleasePublishRequest, ReleasePublishResult
from bumpkin.app.tags import TagPublishRequest, TagPublishResult
from bumpkin.release_job import (
    ReleaseExecutionResult,
    ReleasePlan,
    ReleaseScopedPullRequest,
    prepare_release_plan,
    publish_release_plan,
    run_release_job,
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
        self.compare_calls: list[tuple[str, str]] = []

    def list_tags(self) -> list[str]:
        return list(self._tags)

    def compare_commits(self, *, base_ref: str, head_ref: str) -> list[str]:
        self.compare_calls.append((base_ref, head_ref))
        return list(self._commits)

    def list_pull_requests_for_commit(self, commit_sha: str) -> list[int]:
        return list(self._pulls_by_commit.get(commit_sha, []))

    def get_pull_request(self, number: int) -> ReleaseScopedPullRequest:
        return self._pull_requests[number]


class _FakeRecommendationRunner:
    def __init__(self, labels_by_pr: dict[int, str]) -> None:
        self._labels_by_pr = labels_by_pr
        self.requested_pr_numbers: list[int] = []

    def generate(self, request) -> MergeRecommendation:  # type: ignore[no-untyped-def]
        pr_payload = request.payload["pull_request"]
        pr_number = int(pr_payload["number"])
        self.requested_pr_numbers.append(pr_number)
        label = self._labels_by_pr[pr_number]
        return MergeRecommendation(
            body=f"recommendation: {label}",
            label=label,
            current_version="v1.2.3",
        )


class _InvalidRecommendationRunner:
    def __init__(self) -> None:
        self.requested_pr_numbers: list[int] = []

    def generate(self, request) -> MergeRecommendation:  # type: ignore[no-untyped-def]
        pr_payload = request.payload["pull_request"]
        pr_number = int(pr_payload["number"])
        self.requested_pr_numbers.append(pr_number)
        return MergeRecommendation(
            body="recommendation: n/a",
            label=None,
            current_version="v1.2.3",
        )


class _FakeTagPublisher:
    def __init__(self, status: str = "created") -> None:
        self._status = status
        self.calls: list[TagPublishRequest] = []

    def publish(self, request: TagPublishRequest) -> TagPublishResult:
        self.calls.append(request)
        return TagPublishResult(
            status=self._status,
            tag_name=request.tag_name,
            url=f"https://github.com/{request.repository}/releases/tag/{request.tag_name}",
        )


class _FakeReleasePublisher:
    def __init__(self, status: str = "created") -> None:
        self._status = status
        self.calls: list[ReleasePublishRequest] = []

    def publish(self, request: ReleasePublishRequest) -> ReleasePublishResult:
        self.calls.append(request)
        return ReleasePublishResult(
            status=self._status,
            tag_name=request.tag_name,
            url=f"https://github.com/{request.repository}/releases/tag/{request.tag_name}",
            release_id=99,
        )


def test_prepare_release_plan_builds_release_batch(monkeypatch) -> None:
    pr_12 = _pull_request(
        number=12,
        title="Add release-scoped aggregation",
        author_login="alice",
        merged_at=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
    )
    pr_14 = _pull_request(
        number=14,
        title="Fix duplicate tag publishing",
        author_login="bob",
        merged_at=datetime(2026, 6, 2, 15, 30, tzinfo=UTC),
    )
    client = _FakeRepositoryClient(
        tags=["v1.2.3"],
        commits=["c1", "c2"],
        pulls_by_commit={"c1": [12], "c2": [14]},
        pull_requests={12: pr_12, 14: pr_14},
    )
    runner = _FakeRecommendationRunner({12: "MINOR", 14: "PATCH"})

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

    assert client.compare_calls == [("v1.2.3", "main")]
    assert runner.requested_pr_numbers == [12, 14]
    assert plan.previous_tag == "v1.2.3"
    assert plan.next_tag == "v1.3.0"
    assert plan.release_label == "MINOR"
    assert plan.status == "planned"
    assert plan.target_sha == "sha-main"
    assert [pull.number for pull in plan.pull_requests] == [12, 14]
    assert "## Features" in plan.release_notes
    assert "## Fixes" in plan.release_notes
    assert "- [PR #12](https://github.com/acme/repo/pull/12) by @alice: Add release-scoped aggregation" in plan.release_notes
    assert "- [PR #14](https://github.com/acme/repo/pull/14) by @bob: Fix duplicate tag publishing" in plan.release_notes
    assert "## Contributors" in plan.release_notes
    assert "@alice, @bob" in plan.release_notes


def test_prepare_release_plan_returns_empty_preview_when_scope_has_no_pull_requests(
    monkeypatch,
) -> None:
    client = _FakeRepositoryClient(
        tags=["v2.0.0"],
        commits=[],
        pulls_by_commit={},
        pull_requests={},
    )

    monkeypatch.setattr("bumpkin.release_job._resolve_target_ref", lambda _target: ("main", "sha-main"))
    monkeypatch.setattr("bumpkin.release_job.list_tags", lambda: [])

    plan = prepare_release_plan(
        repository="acme/repo",
        github_token="token-123",
        target_ref="main",
        base_tag="",
        client=client,
    )

    assert plan.previous_tag == "v2.0.0"
    assert plan.next_tag is None
    assert plan.release_label is None
    assert plan.status == "skipped"
    assert plan.pull_requests == ()
    assert "Included PRs: 0" in plan.release_notes
    assert "No merged pull requests were found in this release scope." in plan.release_notes


def test_prepare_release_plan_returns_no_release_plan_for_no_bump_batch(monkeypatch) -> None:
    pr_21 = _pull_request(
        number=21,
        title="Tidy docs wording",
        author_login="alice",
        merged_at=datetime(2026, 6, 3, 9, 0, tzinfo=UTC),
    )
    client = _FakeRepositoryClient(
        tags=["v1.2.3"],
        commits=["c1"],
        pulls_by_commit={"c1": [21]},
        pull_requests={21: pr_21},
    )
    runner = _FakeRecommendationRunner({21: "NO_BUMP"})

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

    assert plan.previous_tag == "v1.2.3"
    assert plan.next_tag is None
    assert plan.release_label == "NO_BUMP"
    assert plan.status == "skipped"
    assert "No new release will be published for this batch." in plan.release_notes
    assert "All included pull requests were classified as NO_BUMP." in plan.release_notes
    assert "## Included PRs" in plan.release_notes


def test_prepare_release_plan_returns_needs_review_for_unresolved_batch(monkeypatch) -> None:
    pr_22 = _pull_request(
        number=22,
        title="Refactor boundary behavior",
        author_login="alice",
        merged_at=datetime(2026, 6, 3, 11, 0, tzinfo=UTC),
    )
    client = _FakeRepositoryClient(
        tags=["v1.2.3"],
        commits=["c1"],
        pulls_by_commit={"c1": [22]},
        pull_requests={22: pr_22},
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

    assert plan.status == "needs_review"
    assert plan.previous_tag == "v1.2.3"
    assert plan.next_tag is None
    assert plan.release_label is None
    assert "## Needs Review" in plan.release_notes
    assert "Refactor boundary behavior" in plan.release_notes


def test_publish_release_plan_accepts_existing_tag_and_updates_release() -> None:
    plan = ReleasePlan(
        repository="acme/repo",
        target_ref="main",
        target_sha="sha-main",
        previous_tag="v1.2.3",
        next_tag="v1.3.0",
        release_label="MINOR",
        pull_requests=(),
        recommendations=(),
        release_notes="# v1.3.0\n",
        notes=(),
    )
    tag_publisher = _FakeTagPublisher(status="exists")
    release_publisher = _FakeReleasePublisher(status="updated")

    result = publish_release_plan(
        plan,
        github_token="token-123",
        tag_publisher=tag_publisher,
        release_publisher=release_publisher,
    )

    assert isinstance(result, ReleaseExecutionResult)
    assert result.status == "published"
    assert tag_publisher.calls[0].tag_name == "v1.3.0"
    assert release_publisher.calls[0].tag_name == "v1.3.0"
    assert release_publisher.calls[0].body == "# v1.3.0\n"


def test_publish_release_plan_skips_no_bump_batches() -> None:
    plan = ReleasePlan(
        repository="acme/repo",
        target_ref="main",
        target_sha="sha-main",
        previous_tag="v1.2.3",
        next_tag=None,
        release_label="NO_BUMP",
        pull_requests=(),
        recommendations=(),
        release_notes="# Release Preview\n",
        notes=(),
    )

    result = publish_release_plan(plan, github_token="token-123")

    assert result.status == "skipped"
    assert result.tag_result is None
    assert result.release_result is None


def test_publish_release_plan_blocks_needs_review_batches() -> None:
    plan = ReleasePlan(
        repository="acme/repo",
        target_ref="main",
        target_sha="sha-main",
        previous_tag="v1.2.3",
        next_tag=None,
        release_label=None,
        pull_requests=(),
        recommendations=(),
        release_notes="# Release Preview\n",
        notes=(),
        status="needs_review",
    )

    result = publish_release_plan(plan, github_token="token-123")

    assert result.status == "needs_review"
    assert result.tag_result is None
    assert result.release_result is None


def test_run_release_job_preview_writes_outputs_and_summary(tmp_path, monkeypatch) -> None:
    plan = ReleasePlan(
        repository="acme/repo",
        target_ref="main",
        target_sha="sha-main",
        previous_tag="v1.2.3",
        next_tag="v1.3.0",
        release_label="MINOR",
        pull_requests=(
            _pull_request(
                number=12,
                title="Add release-scoped aggregation",
                author_login="alice",
                merged_at=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
            ),
        ),
        recommendations=(),
        release_notes="# v1.3.0\n\nHello release.\n",
        notes=(),
    )
    notes_path = tmp_path / "release-notes.md"
    output_path = tmp_path / "github-output.txt"
    summary_path = tmp_path / "step-summary.md"

    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))
    monkeypatch.setattr("bumpkin.release_job.prepare_release_plan", lambda **_kwargs: plan)

    exit_code = run_release_job(
        argparse.Namespace(
            operation="preview",
            repository="acme/repo",
            github_token="token-123",
            target_ref="main",
            base_tag="",
            output_markdown=str(notes_path),
            request_timeout=15,
        )
    )

    assert exit_code == 0
    assert notes_path.read_text(encoding="utf-8") == "# v1.3.0\n\nHello release.\n"
    assert "release_status<<__BUMPKIN_EOF__" in output_path.read_text(encoding="utf-8")
    assert "planned" in output_path.read_text(encoding="utf-8")
    assert summary_path.read_text(encoding="utf-8").strip() == "# v1.3.0\n\nHello release."


def test_run_release_job_publish_writes_publish_outputs(tmp_path, monkeypatch) -> None:
    plan = ReleasePlan(
        repository="acme/repo",
        target_ref="main",
        target_sha="sha-main",
        previous_tag="v1.2.3",
        next_tag="v1.3.0",
        release_label="MINOR",
        pull_requests=(
            _pull_request(
                number=12,
                title="Add release-scoped aggregation",
                author_login="alice",
                merged_at=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
            ),
        ),
        recommendations=(),
        release_notes="# v1.3.0\n\nPublished release.\n",
        notes=(),
    )
    execution = ReleaseExecutionResult(
        status="published",
        plan=plan,
        tag_result=TagPublishResult(
            status="created",
            tag_name="v1.3.0",
            url="https://github.com/acme/repo/releases/tag/v1.3.0",
        ),
        release_result=ReleasePublishResult(
            status="created",
            tag_name="v1.3.0",
            url="https://github.com/acme/repo/releases/tag/v1.3.0",
            release_id=42,
        ),
    )
    notes_path = tmp_path / "release-notes.md"
    output_path = tmp_path / "github-output.txt"
    summary_path = tmp_path / "step-summary.md"

    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))
    monkeypatch.setattr("bumpkin.release_job.prepare_release_plan", lambda **_kwargs: plan)
    monkeypatch.setattr(
        "bumpkin.release_job.publish_release_plan",
        lambda *_args, **_kwargs: execution,
    )

    exit_code = run_release_job(
        argparse.Namespace(
            operation="publish",
            repository="acme/repo",
            github_token="token-123",
            target_ref="main",
            base_tag="",
            output_markdown=str(notes_path),
            request_timeout=15,
        )
    )

    assert exit_code == 0
    output_text = output_path.read_text(encoding="utf-8")
    assert "release_status<<__BUMPKIN_EOF__" in output_text
    assert "published" in output_text
    assert "https://github.com/acme/repo/releases/tag/v1.3.0" in output_text
    assert summary_path.read_text(encoding="utf-8").strip() == "# v1.3.0\n\nPublished release."
