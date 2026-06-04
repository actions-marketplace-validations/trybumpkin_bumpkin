from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bumpkin.versioning.tags import ParsedTag
else:
    ParsedTag = Any


def bump_semver(version: str, label: str) -> str:
    from bumpkin.versioning.tags import bump_semver as _bump_semver

    return _bump_semver(version, label)


def parse_tag(tag: str) -> ParsedTag | None:
    from bumpkin.versioning.tags import parse_tag as _parse_tag

    return _parse_tag(tag)


def detect_next_version(
    label: str,
    latest_tag: str | None = None,
    tags: list[str] | None = None,
    *,
    pre_1_0_breaking_as_minor: bool = True,
) -> tuple[str | None, str | None, list[str]]:
    from bumpkin.versioning.tags import detect_next_version as _detect_next_version

    return _detect_next_version(
        label,
        latest_tag=latest_tag,
        tags=tags,
        pre_1_0_breaking_as_minor=pre_1_0_breaking_as_minor,
    )


__all__ = ["ParsedTag", "bump_semver", "detect_next_version", "parse_tag"]
