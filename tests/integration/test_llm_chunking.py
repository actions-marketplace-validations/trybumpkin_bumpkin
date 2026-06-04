import llm
from llm import LLMUnavailableError, get_recommendation


def test_split_diff_into_chunks_respects_max_chunk_count() -> None:
    diff_text = (
        "diff --git a/a.ts b/a.ts\n+ const A = 1;\n"
        "diff --git a/b.ts b/b.ts\n+ const B = 2;\n"
        "diff --git a/c.ts b/c.ts\n+ const C = 3;\n"
    )
    chunks, skipped = llm._split_diff_into_chunks(
        diff_text,
        max_chunk_tokens=20,
        max_chunk_count=1,
    )
    assert len(chunks) == 1
    assert skipped >= 1


def test_get_recommendation_chunking_aggregates_highest_severity(
    monkeypatch,
) -> None:
    def fake_call(*, diff_text: str, **_: object) -> dict[str, str]:
        if "removeUser" in diff_text:
            return {
                "label": "MAJOR",
                "confidence": "high",
                "reasoning": "Breaking export removed from public API.",
                "changelog": "feat: remove exported api symbol",
            }
        return {
            "label": "MINOR",
            "confidence": "high",
            "reasoning": "New exported helper added to the public API.",
            "changelog": "feat: add exported helper",
        }

    monkeypatch.setattr(llm, "_call_github_models", fake_call)
    diff_text = (
        "diff --git a/a.ts b/a.ts\n+ export function addUser() {}\n"
        "diff --git a/b.ts b/b.ts\n- export function removeUser() {}\n+ function removeUser() {}\n"
    )
    result, mode, fallback_reason, _ = get_recommendation(
        mode="auto",
        diff_text=diff_text,
        truncated=False,
        language_group="javascript-typescript",
        prompt_version="js-ts-v1",
        surface_area_hints=None,
        language_hints=None,
        model="primary/model",
        fallback_model=None,
        endpoint="https://models.github.ai/inference/chat/completions",
        token="token",
        max_retries=1,
        chunking_enabled=True,
        chunk_max_tokens=20,
        chunk_max_count=12,
    )
    assert mode == "github-models"
    assert fallback_reason is None
    assert result["status"] == "classified"
    assert result["label"] == "MAJOR"
    assert result["chunking"]["enabled"] is True
    assert result["chunking"]["chunk_count"] >= 2
    assert result["chunking"]["files_total"] == 0


def test_get_recommendation_chunking_partial_failure_downgrades_to_manual_review(
    monkeypatch,
) -> None:
    def fake_call(*, diff_text: str, **_: object) -> dict[str, str]:
        if "FAIL_CHUNK" in diff_text:
            raise LLMUnavailableError("provider timeout")
        return {
            "label": "PATCH",
            "confidence": "medium",
            "reasoning": "Internal implementation updates with no public API changes.",
            "changelog": "fix: internal implementation update",
        }

    monkeypatch.setattr(llm, "_call_github_models", fake_call)
    diff_text = (
        "diff --git a/a.ts b/a.ts\n+ // OK_CHUNK\n+ const a = 1;\n"
        "diff --git a/b.ts b/b.ts\n+ // FAIL_CHUNK\n+ const b = 2;\n"
    )
    result, mode, fallback_reason, _ = get_recommendation(
        mode="auto",
        diff_text=diff_text,
        truncated=False,
        language_group="javascript-typescript",
        prompt_version="js-ts-v1",
        surface_area_hints=None,
        language_hints=None,
        model="primary/model",
        fallback_model=None,
        endpoint="https://models.github.ai/inference/chat/completions",
        token="token",
        max_retries=1,
        chunking_enabled=True,
        chunk_max_tokens=20,
        chunk_max_count=12,
        chunk_failure_policy="MANUAL_REVIEW",
    )
    assert mode == "github-models"
    assert fallback_reason is not None
    assert result["status"] == "manual_review"
    assert result["chunking"]["failed"] >= 1
    assert result["chunking"]["succeeded"] >= 1


def test_get_recommendation_chunking_partial_failure_can_emit_patch(
    monkeypatch,
) -> None:
    def fake_call(*, diff_text: str, **_: object) -> dict[str, str]:
        if "FAIL_CHUNK" in diff_text:
            raise LLMUnavailableError("provider timeout")
        return {
            "label": "PATCH",
            "confidence": "medium",
            "reasoning": "Internal implementation updates with no public API changes.",
            "changelog": "fix: internal implementation update",
        }

    monkeypatch.setattr(llm, "_call_github_models", fake_call)
    diff_text = (
        "diff --git a/a.ts b/a.ts\n+ // OK_CHUNK\n+ const a = 1;\n"
        "diff --git a/b.ts b/b.ts\n+ // FAIL_CHUNK\n+ const b = 2;\n"
    )
    result, mode, fallback_reason, _ = get_recommendation(
        mode="auto",
        diff_text=diff_text,
        truncated=False,
        language_group="javascript-typescript",
        prompt_version="js-ts-v1",
        surface_area_hints=None,
        language_hints=None,
        model="primary/model",
        fallback_model=None,
        endpoint="https://models.github.ai/inference/chat/completions",
        token="token",
        max_retries=1,
        chunking_enabled=True,
        chunk_max_tokens=20,
        chunk_max_count=12,
        chunk_failure_policy="PATCH",
    )
    assert mode == "github-models"
    assert fallback_reason is not None
    assert result["status"] == "classified"
    assert result["label"] == "PATCH"
    assert result["confidence"] == "low"


def test_get_recommendation_chunking_marks_manual_when_chunk_limit_omits_files(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        llm,
        "_call_github_models",
        lambda **_: {
            "label": "PATCH",
            "confidence": "medium",
            "reasoning": "Internal implementation updates with no public API changes.",
            "changelog": "fix: internal implementation update",
        },
    )
    diff_units = [
        ("src/a.ts", "diff --git a/src/a.ts b/src/a.ts\n+ const a = 1;\n"),
        ("src/b.ts", "diff --git a/src/b.ts b/src/b.ts\n+ const b = 2;\n"),
    ]
    result, mode, fallback_reason, _ = get_recommendation(
        mode="auto",
        diff_text="".join(unit[1] for unit in diff_units),
        truncated=False,
        language_group="javascript-typescript",
        prompt_version="js-ts-v1",
        surface_area_hints=None,
        language_hints=None,
        model="primary/model",
        fallback_model=None,
        endpoint="https://models.github.ai/inference/chat/completions",
        token="token",
        max_retries=1,
        chunking_enabled=True,
        chunk_max_tokens=20,
        chunk_max_count=1,
        diff_units=diff_units,
    )
    assert mode == "github-models"
    assert fallback_reason == "chunk_limit_coverage_gap"
    assert result["status"] == "manual_review"
    assert result["chunking"]["files_total"] == 2
    assert result["chunking"]["files_omitted"] == 1
    assert result["chunking"]["omitted_files"] == ["src/b.ts"]
