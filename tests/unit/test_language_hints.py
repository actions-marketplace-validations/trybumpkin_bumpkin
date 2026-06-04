from language import detect_language_hints


def test_detect_language_hints_for_multiple_languages() -> None:
    hints = detect_language_hints(["src/api.ts", "pkg/service.py", "cmd/main.go"])
    assert len(hints) == 3
    assert any("JavaScript/TypeScript" in hint for hint in hints)
    assert any("Python" in hint for hint in hints)
    assert any("Go" in hint for hint in hints)


def test_detect_language_hints_empty_for_unknown_extensions() -> None:
    hints = detect_language_hints(["README.md", "assets/logo.svg"])
    assert hints == []
