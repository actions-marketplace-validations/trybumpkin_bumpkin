from version import detect_next_version, parse_tag


def test_parse_tag_supports_prefixed_semver() -> None:
    parsed = parse_tag("release-v1.2.3")
    assert parsed is not None
    assert parsed.prefix == "release-v"
    assert parsed.scheme == "semver"


def test_parse_tag_supports_semver_prerelease_suffix() -> None:
    parsed = parse_tag("v1.2.3-beta.1")
    assert parsed is not None
    assert parsed.version == "1.2.3"
    assert parsed.scheme == "semver"


def test_parse_tag_supports_calver_suffix() -> None:
    parsed = parse_tag("v2026.03.11-1-1-15bc435")
    assert parsed is not None
    assert parsed.version == "2026.03.11"
    assert parsed.scheme == "calver"


def test_detect_next_version_for_semver() -> None:
    current, nxt, notes = detect_next_version("MINOR", latest_tag="v1.2.3")
    assert current == "v1.2.3"
    assert nxt == "v1.3.0"
    assert any("semver" in n for n in notes)


def test_detect_next_version_for_zero_based_major() -> None:
    current, nxt, _ = detect_next_version("MAJOR", latest_tag="0.4.2")
    assert current == "0.4.2"
    assert nxt == "0.5.0"


def test_detect_next_version_for_zero_based_major_can_use_strict_major() -> None:
    current, nxt, _ = detect_next_version(
        "MAJOR",
        latest_tag="0.4.2",
        pre_1_0_breaking_as_minor=False,
    )
    assert current == "0.4.2"
    assert nxt == "1.0.0"


def test_detect_next_version_for_no_bump() -> None:
    current, nxt, notes = detect_next_version("NO_BUMP", latest_tag="v1.2.3")
    assert current == "v1.2.3"
    assert nxt is None
    assert any("NO_BUMP classification" in note for note in notes)


def test_detect_next_version_for_four_part() -> None:
    current, nxt, _ = detect_next_version("PATCH", latest_tag="app/v1.2.3.9")
    assert current == "app/v1.2.3.9"
    assert nxt == "app/v1.2.4.10"


def test_detect_next_version_preserves_consistent_release_prefix() -> None:
    current, nxt, _ = detect_next_version(
        "PATCH",
        tags=["release-1.2.3", "release-1.2.2", "release-1.2.1"],
    )
    assert current == "release-1.2.3"
    assert nxt == "release-1.2.4"


def test_detect_next_version_defaults_to_v_on_mixed_prefixes() -> None:
    current, nxt, notes = detect_next_version(
        "PATCH",
        tags=["release-1.2.3", "v1.2.2", "1.2.1"],
    )
    assert current == "release-1.2.3"
    assert nxt == "v1.2.4"
    assert any("mixed tag prefixes" in note for note in notes)


def test_detect_next_version_skips_unparseable_newer_tag_with_note() -> None:
    current, nxt, notes = detect_next_version(
        "PATCH",
        tags=["release-latest", "v1.2.3", "v1.2.2"],
    )
    assert current == "v1.2.3"
    assert nxt == "v1.2.4"
    assert any("Skipped 1 unparseable tag(s)" in note for note in notes)


def test_detect_next_version_selects_highest_parseable_tag_when_order_is_non_monotonic() -> None:
    current, nxt, notes = detect_next_version(
        "PATCH",
        tags=["v0.15.8", "v0.17.0", "v0.16.9"],
    )
    assert current == "v0.17.0"
    assert nxt == "v0.17.1"
    assert any("non-monotonic" in note for note in notes)


def test_detect_next_version_uses_github_tag_fallback_when_local_git_empty(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "token-123")
    monkeypatch.setattr("bumpkin.versioning.tags._run_git", lambda _args: "")
    monkeypatch.setattr(
        "bumpkin.versioning.tags._fetch_tags_from_github_api",
        lambda **_kwargs: ["v1.2.3", "v1.2.2"],
    )

    current, nxt, _notes = detect_next_version("PATCH")

    assert current == "v1.2.3"
    assert nxt == "v1.2.4"
