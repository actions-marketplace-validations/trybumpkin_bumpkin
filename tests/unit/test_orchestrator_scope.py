from __future__ import annotations

from bumpkin.orchestrator import scope as orchestrator_scope


def test_resolve_merge_parent_sha_uses_local_git_when_available(monkeypatch) -> None:
    monkeypatch.setattr(
        "bumpkin.orchestrator.scope.run_git",
        lambda args: "parent-sha" if args == ["rev-parse", "merge-sha^1"] else "",
    )

    parent = orchestrator_scope.resolve_merge_parent_sha("merge-sha")

    assert parent == "parent-sha"


def test_resolve_merge_parent_sha_falls_back_to_github_api(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "abc")

    def fake_run_git(_args: list[str]) -> str:
        raise RuntimeError("missing git object")

    def fake_request(token: str, url: str) -> object:
        assert token
        assert url.endswith("/repos/acme/repo/commits/merge-sha")
        return {"parents": [{"sha": "api-parent-sha"}]}

    monkeypatch.setattr("bumpkin.orchestrator.scope.run_git", fake_run_git)
    monkeypatch.setattr("bumpkin.orchestrator.scope.github_api_request", fake_request)

    parent = orchestrator_scope.resolve_merge_parent_sha("merge-sha")

    assert parent == "api-parent-sha"


def test_resolve_merge_parent_sha_returns_none_without_env_for_api_fallback(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(
        "bumpkin.orchestrator.scope.run_git",
        lambda _args: (_ for _ in ()).throw(RuntimeError("missing git object")),
    )

    parent = orchestrator_scope.resolve_merge_parent_sha("merge-sha")

    assert parent is None
