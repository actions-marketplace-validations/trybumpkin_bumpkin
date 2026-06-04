from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol, cast


@dataclass(frozen=True, slots=True)
class TagPublishRequest:
    repository: str
    tag_name: str
    target_sha: str
    installation_id: int | None = None


@dataclass(frozen=True, slots=True)
class TagPublishResult:
    status: str
    tag_name: str
    url: str | None = None
    message: str | None = None


class TagPublisher(Protocol):
    def publish(self, request: TagPublishRequest) -> TagPublishResult: ...


class NoopTagPublisher:
    def publish(self, request: TagPublishRequest) -> TagPublishResult:
        return TagPublishResult(
            status="skipped",
            tag_name=request.tag_name,
            message="publisher_unavailable",
        )


def _as_dict(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return cast("dict[str, Any]", value)


class GitHubTagPublisher:
    def __init__(
        self,
        *,
        token: str,
        user_agent: str = "bumpkin-app",
        timeout_seconds: int = 10,
    ) -> None:
        self._token = token.strip()
        self._user_agent = user_agent.strip() or "bumpkin-app"
        self._timeout_seconds = timeout_seconds

    def publish(self, request: TagPublishRequest) -> TagPublishResult:
        if not self._token:
            return TagPublishResult(
                status="skipped",
                tag_name=request.tag_name,
                message="missing_token",
            )
        tag_name = request.tag_name.strip()
        target_sha = request.target_sha.strip()
        repository = request.repository.strip()
        if not tag_name:
            raise ValueError("tag_name is required.")
        if not target_sha:
            raise ValueError("target_sha is required.")
        if not repository:
            raise ValueError("repository is required.")

        ref = f"refs/tags/{tag_name}"
        try:
            self._api_request(
                url=f"https://api.github.com/repos/{repository}/git/refs",
                method="POST",
                payload={"ref": ref, "sha": target_sha},
            )
        except urllib.error.HTTPError as err:
            if err.code == 422 and self._is_ref_exists_error(err):
                return TagPublishResult(
                    status="exists",
                    tag_name=tag_name,
                    url=_tag_url(repository=repository, tag_name=tag_name),
                    message="tag_already_exists",
                )
            raise RuntimeError(_format_http_error(err)) from err

        return TagPublishResult(
            status="created",
            tag_name=tag_name,
            url=_tag_url(repository=repository, tag_name=tag_name),
        )

    def _api_request(
        self,
        *,
        url: str,
        method: str,
        payload: dict[str, Any] | None = None,
    ) -> object:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": self._user_agent,
            },
        )
        with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
            body = response.read().decode("utf-8")
        return json.loads(body) if body else {}

    def _is_ref_exists_error(self, err: urllib.error.HTTPError) -> bool:
        try:
            body = err.read().decode("utf-8")
        except Exception:  # noqa: BLE001 - keep 422 fallback resilient
            return False
        if not body.strip():
            return False
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return "Reference already exists" in body
        payload_obj = _as_dict(payload)
        if payload_obj is None:
            return "Reference already exists" in body
        message = str(payload_obj.get("message", "")).strip()
        return "Reference already exists" in message


def _tag_url(*, repository: str, tag_name: str) -> str:
    return f"https://github.com/{repository}/releases/tag/{urllib.parse.quote(tag_name, safe='')}"


def _format_http_error(err: urllib.error.HTTPError) -> str:
    try:
        body = err.read().decode("utf-8")
    except Exception:  # noqa: BLE001 - preserve best-effort error details
        body = ""
    detail = body.strip()
    if detail:
        return f"GitHub tag API error {err.code}: {detail}"
    return f"GitHub tag API error {err.code}: {err.reason}"


__all__ = [
    "GitHubTagPublisher",
    "NoopTagPublisher",
    "TagPublishRequest",
    "TagPublishResult",
    "TagPublisher",
]
