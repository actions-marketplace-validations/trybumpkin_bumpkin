from corpus_cli import (
    CommitCandidate,
    PRResultRow,
    build_balanced_queue,
    extract_bumpkin_prediction,
    infer_expected_label,
    parse_expected_label_from_body,
    summarize_rows,
)


def test_parse_expected_label_from_body() -> None:
    body = "<!-- bumpkin:expected-label:minor -->\nExpected label: MINOR\n"
    assert parse_expected_label_from_body(body) == "MINOR"
    assert parse_expected_label_from_body("no marker") == "UNKNOWN"


def test_extract_bumpkin_prediction_classified_comment() -> None:
    comment = (
        "<!-- bumpkin:recommendation -->\n"
        "🤖 Bumpkin (semantic fallback)\n\n"
        "Analysis state: degraded_fallback (source=semantic-fallback)\n"
        "Recommendation : 🟡 MINOR\n"
        "Confidence     : high\n"
        "Override      : none\n"
    )
    prediction = extract_bumpkin_prediction(comment)
    assert prediction.label == "MINOR"
    assert prediction.confidence == "high"
    assert prediction.mode_used == "fallback-heuristic"
    assert prediction.analysis_state == "degraded_fallback"
    assert prediction.classification_source == "semantic-fallback"
    assert prediction.override_applied is False


def test_extract_bumpkin_prediction_manual_review_comment() -> None:
    comment = (
        "<!-- bumpkin:recommendation -->\n"
        "🤖 Bumpkin Manual Review Required\n\n"
        "⚠️ Manual review required.\n"
    )
    prediction = extract_bumpkin_prediction(comment)
    assert prediction.label == "MANUAL_REVIEW"
    assert prediction.confidence == "none"
    assert prediction.mode_used == "github-models"


def test_infer_expected_label_docs_only() -> None:
    label, category = infer_expected_label(
        "chore: update docs",
        ["docs/guide.md", ".github/workflows/ci.yml"],
    )
    assert label == "NO_BUMP"
    assert category == "docs_config_only"


def test_build_balanced_queue_uses_distribution_targets() -> None:
    candidates = [
        CommitCandidate("a1", "feat: one", ["src/a.ts"], "MINOR", "feature_subject"),
        CommitCandidate("a2", "feat: two", ["src/b.ts"], "MINOR", "feature_subject"),
        CommitCandidate("a3", "feat: three", ["src/c.ts"], "MINOR", "feature_subject"),
        CommitCandidate("b1", "fix: one", ["src/d.ts"], "PATCH", "default_patch"),
        CommitCandidate("b2", "fix: two", ["src/e.ts"], "PATCH", "default_patch"),
        CommitCandidate("c1", "feat!: break", ["src/f.ts"], "MAJOR", "breaking_subject"),
        CommitCandidate("d1", "docs: one", ["docs/x.md"], "NO_BUMP", "docs_config_only"),
    ]
    selected = build_balanced_queue(
        candidates,
        target_count=5,
        seed=7,
        distribution={"MAJOR": 1, "MINOR": 2, "PATCH": 1, "NO_BUMP": 1},
    )
    labels = [row.expected_label for row in selected]
    assert labels.count("MAJOR") == 1
    assert labels.count("MINOR") == 2
    assert labels.count("PATCH") == 1
    assert labels.count("NO_BUMP") == 1


def test_summarize_rows_builds_confusion_matrix() -> None:
    rows = [
        PRResultRow(
            1,
            "u1",
            "MAJOR",
            "MAJOR",
            "high",
            "github-models",
            "authoritative",
            "model",
            "none",
            False,
            "none",
            "matched",
        ),
        PRResultRow(
            2,
            "u2",
            "MINOR",
            "PATCH",
            "medium",
            "fallback-heuristic",
            "degraded_fallback",
            "semantic-fallback",
            "none",
            False,
            "natural",
            "mismatch",
        ),
        PRResultRow(
            3,
            "u3",
            "PATCH",
            "MAJOR",
            "low",
            "github-models",
            "degraded_fallback",
            "no-diff-heuristic",
            "applied via `bump:major`: PATCH → MAJOR",
            True,
            "forced_override",
            "mismatch",
        ),
    ]
    summary = summarize_rows(rows)
    assert summary["total"] == 3
    assert summary["matched"] == 1
    assert summary["mismatched"] == 2
    assert summary["disagreement_rate"] == 2 / 3
    assert summary["false_major_count"] == 1
    assert summary["false_minor_count"] == 0
    assert summary["natural_mismatches"] == 1
    assert summary["forced_override_mismatches"] == 1
    assert summary["degraded_fallback"]["total"] == 2
    assert summary["degraded_fallback"]["mismatches"] == 2
    assert summary["fallback"]["total"] == 2
    assert summary["fallback"]["mismatches"] == 2
    assert summary["fallback"]["mismatch_rate"] == 1.0
    assert summary["by_expected_label"]["MINOR"]["disagreement_rate"] == 1.0
    assert summary["confusion"]["MAJOR"]["MAJOR"] == 1
    assert summary["confusion"]["MINOR"]["PATCH"] == 1
