from __future__ import annotations

import argparse
import csv
import json
import random
import re
import subprocess
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

EXPECTED_LABEL_RE = re.compile(
    r"<!--\s*bumpkin:expected-label:(MAJOR|MINOR|PATCH|NO_BUMP)\s*-->",
    re.IGNORECASE,
)
RECOMMENDATION_LABEL_RE = re.compile(
    r"Recommendation\s*:\s*.*\b(MAJOR|MINOR|PATCH|NO_BUMP)\b",
    re.IGNORECASE,
)
CONFIDENCE_RE = re.compile(r"Confidence\s*:\s*(high|medium|low)", re.IGNORECASE)
ANALYSIS_STATE_RE = re.compile(
    r"Analysis state:\s*([a-z_]+)\s*\(source=([^)]+)\)",
    re.IGNORECASE,
)
OVERRIDE_STATUS_RE = re.compile(r"Override\s*:\s*(.+)", re.IGNORECASE)
BUMPKIN_COMMENT_MARKER = "<!-- bumpkin:recommendation -->"

DEFAULT_DISTRIBUTION = {
    "MAJOR": 6,
    "MINOR": 8,
    "PATCH": 10,
    "NO_BUMP": 6,
}
DOC_CONFIG_HINTS = (
    "docs/",
    ".md",
    ".rst",
    ".txt",
    ".github/",
    "renovate.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    ".editorconfig",
)
JS_TS_EXTENSIONS = (
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
)


@dataclass
class CommitCandidate:
    sha: str
    subject: str
    files: list[str]
    expected_label: str
    category: str


@dataclass
class PRResultRow:
    pr_number: int
    url: str
    expected_label: str
    predicted_label: str
    confidence: str
    mode_used: str
    analysis_state: str
    classification_source: str
    override_status: str
    override_applied: bool
    mismatch_type: str
    status: str


@dataclass
class ParsedPrediction:
    label: str
    confidence: str
    mode_used: str
    analysis_state: str
    classification_source: str
    override_status: str
    override_applied: bool


def _run_command(args: list[str], *, stdin: str | None = None) -> str:
    proc = subprocess.run(
        args,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(args)}\n"
            f"stdout:\n{proc.stdout.strip()}\n"
            f"stderr:\n{proc.stderr.strip()}"
        )
    return proc.stdout


def _run_git(repo: Path, args: list[str], *, stdin: str | None = None) -> str:
    return _run_command(["git", "-C", str(repo), *args], stdin=stdin)


def _run_gh(args: list[str]) -> str:
    return _run_command(["gh", *args])


def _looks_docs_or_config_only(paths: list[str]) -> bool:
    if not paths:
        return False
    for path in paths:
        normalized = path.strip().lower()
        if not normalized:
            continue
        if any(hint in normalized for hint in DOC_CONFIG_HINTS):
            continue
        if normalized.endswith(JS_TS_EXTENSIONS):
            return False
        if "/src/" in f"/{normalized}" or normalized.startswith("src/"):
            return False
        if normalized.endswith((".py", ".go", ".rs", ".java", ".kt")):
            return False
    return True


def infer_expected_label(subject: str, files: list[str]) -> tuple[str, str]:
    lowered = subject.strip().lower()
    if _looks_docs_or_config_only(files):
        return "NO_BUMP", "docs_config_only"

    if "breaking change" in lowered or "!: " in lowered or lowered.startswith("feat!"):
        return "MAJOR", "breaking_subject"
    if lowered.startswith("feat"):
        return "MINOR", "feature_subject"
    if any(token in lowered for token in ("remove export", "drop api", "rename export")):
        return "MAJOR", "likely_breaking_api"
    if any(token in lowered for token in ("add export", "new api", "add endpoint")):
        return "MINOR", "likely_additive_api"
    return "PATCH", "default_patch"


def _read_git_log_with_fallback(source_repo: Path, rev_range: str) -> tuple[str, str]:
    base_args = [
        "log",
        "--no-merges",
        "--reverse",
        "--pretty=format:%H%x1f%s",
        "--name-only",
    ]
    try:
        return _run_git(source_repo, [*base_args, rev_range]), rev_range
    except RuntimeError as err:
        if "ambiguous argument" not in str(err):
            raise
        fallback = "HEAD"
        return _run_git(source_repo, [*base_args, fallback]), fallback


def list_commit_candidates(source_repo: Path, rev_range: str) -> tuple[list[CommitCandidate], str]:
    raw, resolved_rev_range = _read_git_log_with_fallback(source_repo, rev_range)
    lines = raw.splitlines()
    out: list[CommitCandidate] = []

    current_sha = ""
    current_subject = ""
    current_files: list[str] = []

    def flush() -> None:
        nonlocal current_sha, current_subject, current_files
        if not current_sha:
            return
        file_list = [file for file in current_files if file]
        label, category = infer_expected_label(current_subject, file_list)
        out.append(
            CommitCandidate(
                sha=current_sha,
                subject=current_subject,
                files=file_list,
                expected_label=label,
                category=category,
            )
        )
        current_sha = ""
        current_subject = ""
        current_files = []

    for line in lines:
        if "\x1f" in line:
            flush()
            sha, subject = line.split("\x1f", 1)
            current_sha = sha.strip()
            current_subject = subject.strip()
            continue
        stripped = line.strip()
        if not stripped:
            continue
        current_files.append(stripped)
    flush()

    return [candidate for candidate in out if candidate.files], resolved_rev_range


def build_balanced_queue(
    candidates: list[CommitCandidate],
    *,
    target_count: int,
    seed: int,
    distribution: dict[str, int],
) -> list[CommitCandidate]:
    randomizer = random.Random(seed)
    by_label: dict[str, list[CommitCandidate]] = {label: [] for label in distribution}
    for candidate in candidates:
        if candidate.expected_label in by_label:
            by_label[candidate.expected_label].append(candidate)
    for rows in by_label.values():
        randomizer.shuffle(rows)

    selected: list[CommitCandidate] = []
    for label, target in distribution.items():
        selected.extend(by_label[label][:target])

    if len(selected) < target_count:
        selected_shas = {row.sha for row in selected}
        remainder = [row for row in candidates if row.sha not in selected_shas]
        randomizer.shuffle(remainder)
        selected.extend(remainder[: max(0, target_count - len(selected))])

    selected = selected[:target_count]
    selected.sort(key=lambda row: row.sha)
    return selected


def _repo_slug_from_remote(repo: Path) -> str:
    remote = _run_git(repo, ["config", "--get", "remote.origin.url"]).strip()
    if remote.startswith("git@github.com:"):
        slug = remote.removeprefix("git@github.com:")
    elif remote.startswith("https://github.com/"):
        slug = remote.removeprefix("https://github.com/")
    else:
        raise ValueError(f"Unsupported remote format for GitHub slug extraction: {remote}")
    return slug.removesuffix(".git").strip("/")


def _write_queue_json(
    path: Path,
    rows: list[CommitCandidate],
    *,
    source_repo: Path,
    rev_range: str,
    resolved_rev_range: str,
) -> None:
    payload = {
        "source_repo": str(source_repo),
        "rev_range": rev_range,
        "resolved_rev_range": resolved_rev_range,
        "count": len(rows),
        "items": [asdict(row) for row in rows],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def _load_queue(path: Path) -> list[CommitCandidate]:
    payload = json.loads(path.read_text())
    return [
        CommitCandidate(
            sha=str(row["sha"]),
            subject=str(row["subject"]),
            files=[str(item) for item in row.get("files", [])],
            expected_label=str(row["expected_label"]).upper(),
            category=str(row["category"]),
        )
        for row in payload.get("items", [])
    ]


def _pr_body(item: CommitCandidate) -> str:
    return (
        f"<!-- bumpkin:expected-label:{item.expected_label} -->\n"
        f"Expected label: {item.expected_label}\n"
        f"Category: {item.category}\n"
        f"Source commit: {item.sha}\n"
    )


def _apply_source_commit(source_repo: Path, fixture_repo: Path, sha: str) -> None:
    patch = _run_git(source_repo, ["show", "--format=", "--binary", sha])
    _run_git(
        fixture_repo,
        ["apply", "-3", "--whitespace=nowarn", "-"],
        stdin=patch,
    )


def open_replay_prs(
    *,
    source_repo: Path,
    fixture_repo: Path,
    queue: list[CommitCandidate],
    base_branch: str,
    limit: int,
    dry_run: bool,
) -> list[dict[str, Any]]:
    repo_slug = _repo_slug_from_remote(fixture_repo)
    selected = queue if limit <= 0 else queue[:limit]
    results: list[dict[str, Any]] = []

    _run_git(fixture_repo, ["checkout", base_branch])
    _run_git(fixture_repo, ["pull", "--ff-only", "origin", base_branch])

    for index, item in enumerate(selected, start=1):
        branch = f"corpus/{index:03d}-{item.expected_label.lower()}-{item.sha[:8]}"
        title = f"corpus: replay {item.sha[:8]} [{item.expected_label}]"
        body = _pr_body(item)

        if dry_run:
            results.append(
                {
                    "sha": item.sha,
                    "branch": branch,
                    "title": title,
                    "expected_label": item.expected_label,
                    "category": item.category,
                    "status": "dry_run",
                }
            )
            continue

        try:
            _run_git(fixture_repo, ["checkout", "-B", branch, base_branch])
            _apply_source_commit(source_repo, fixture_repo, item.sha)
            _run_git(fixture_repo, ["add", "-A"])
            status = _run_git(fixture_repo, ["status", "--porcelain"]).strip()
            if not status:
                results.append(
                    {
                        "sha": item.sha,
                        "branch": branch,
                        "status": "skipped_no_changes",
                    }
                )
                _run_git(fixture_repo, ["checkout", base_branch])
                _run_git(fixture_repo, ["branch", "-D", branch])
                continue

            _run_git(
                fixture_repo,
                ["commit", "-m", f"chore(corpus): replay {item.sha[:8]} ({item.expected_label})"],
            )
            _run_git(fixture_repo, ["push", "-u", "origin", branch])
            pr_url = _run_gh(
                [
                    "pr",
                    "create",
                    "--repo",
                    repo_slug,
                    "--base",
                    base_branch,
                    "--head",
                    branch,
                    "--title",
                    title,
                    "--body",
                    body,
                ]
            ).strip()
            results.append(
                {
                    "sha": item.sha,
                    "branch": branch,
                    "status": "opened",
                    "url": pr_url,
                    "expected_label": item.expected_label,
                    "category": item.category,
                }
            )
        except RuntimeError as err:
            results.append(
                {
                    "sha": item.sha,
                    "branch": branch,
                    "status": "failed",
                    "error": str(err),
                }
            )
            with suppress(RuntimeError):
                _run_git(fixture_repo, ["checkout", base_branch])

    return results


def parse_expected_label_from_body(body: str) -> str:
    match = EXPECTED_LABEL_RE.search(body or "")
    if not match:
        return "UNKNOWN"
    return match.group(1).upper()


def _infer_mode_from_comment(*, lowered_body: str, analysis_state: str, source: str) -> str:
    if analysis_state == "degraded_fallback":
        if source == "semantic-fallback":
            return "fallback-heuristic"
        if source == "no-diff-heuristic":
            return "no-diff-heuristic"
        return "degraded_fallback"
    if "semantic fallback" in lowered_body:
        return "fallback-heuristic"
    if "stub mode" in lowered_body:
        return "stub"
    return "github-models"


def extract_bumpkin_prediction(comment_body: str) -> ParsedPrediction:
    lowered = (comment_body or "").lower()
    if BUMPKIN_COMMENT_MARKER not in lowered:
        return ParsedPrediction(
            label="UNKNOWN",
            confidence="unknown",
            mode_used="missing_comment",
            analysis_state="unknown",
            classification_source="unknown",
            override_status="unknown",
            override_applied=False,
        )

    analysis_match = ANALYSIS_STATE_RE.search(comment_body or "")
    analysis_state = analysis_match.group(1).strip().lower() if analysis_match else "unknown"
    classification_source = analysis_match.group(2).strip().lower() if analysis_match else "unknown"
    override_match = OVERRIDE_STATUS_RE.search(comment_body or "")
    override_status = override_match.group(1).strip() if override_match else "unknown"
    override_applied = override_status.lower().startswith("applied via ")

    mode = _infer_mode_from_comment(
        lowered_body=lowered,
        analysis_state=analysis_state,
        source=classification_source,
    )

    if "manual review required" in lowered:
        return ParsedPrediction(
            label="MANUAL_REVIEW",
            confidence="none",
            mode_used=mode,
            analysis_state=analysis_state,
            classification_source=classification_source,
            override_status=override_status,
            override_applied=override_applied,
        )

    label_match = RECOMMENDATION_LABEL_RE.search(comment_body or "")
    confidence_match = CONFIDENCE_RE.search(comment_body or "")
    label = label_match.group(1).upper() if label_match else "UNKNOWN"
    confidence = confidence_match.group(1).lower() if confidence_match else "unknown"
    return ParsedPrediction(
        label=label,
        confidence=confidence,
        mode_used=mode,
        analysis_state=analysis_state,
        classification_source=classification_source,
        override_status=override_status,
        override_applied=override_applied,
    )


def _find_latest_bumpkin_comment(comments: list[dict[str, Any]]) -> str:
    for comment in reversed(comments):
        body = str(comment.get("body", ""))
        if BUMPKIN_COMMENT_MARKER in body:
            return body
    return ""


def collect_results(*, repo: str, limit: int) -> list[PRResultRow]:
    prs = json.loads(
        _run_gh(
            [
                "pr",
                "list",
                "--repo",
                repo,
                "--state",
                "merged",
                "--limit",
                str(limit),
                "--json",
                "number,url,body",
            ]
        )
    )

    rows: list[PRResultRow] = []
    for pr in prs:
        number = int(pr["number"])
        body = str(pr.get("body", ""))
        expected_label = parse_expected_label_from_body(body)
        comments = json.loads(
            _run_gh(
                [
                    "api",
                    f"repos/{repo}/issues/{number}/comments",
                ]
            )
        )
        latest = _find_latest_bumpkin_comment(comments if isinstance(comments, list) else [])
        prediction = extract_bumpkin_prediction(latest)
        status = "matched" if expected_label == prediction.label else "mismatch"
        mismatch_type = "none"
        if status == "mismatch":
            mismatch_type = "forced_override" if prediction.override_applied else "natural"
        rows.append(
            PRResultRow(
                pr_number=number,
                url=str(pr.get("url", "")),
                expected_label=expected_label,
                predicted_label=prediction.label,
                confidence=prediction.confidence,
                mode_used=prediction.mode_used,
                analysis_state=prediction.analysis_state,
                classification_source=prediction.classification_source,
                override_status=prediction.override_status,
                override_applied=prediction.override_applied,
                mismatch_type=mismatch_type,
                status=status,
            )
        )
    rows.sort(key=lambda row: row.pr_number)
    return rows


def write_results_tsv(path: Path, rows: list[PRResultRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(
            [
                "pr_number",
                "url",
                "expected_label",
                "predicted_label",
                "confidence",
                "mode_used",
                "analysis_state",
                "classification_source",
                "override_status",
                "override_applied",
                "mismatch_type",
                "status",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.pr_number,
                    row.url,
                    row.expected_label,
                    row.predicted_label,
                    row.confidence,
                    row.mode_used,
                    row.analysis_state,
                    row.classification_source,
                    row.override_status,
                    str(row.override_applied).lower(),
                    row.mismatch_type,
                    row.status,
                ]
            )


def summarize_rows(rows: list[PRResultRow]) -> dict[str, Any]:
    total = len(rows)
    matched = sum(1 for row in rows if row.status == "matched")
    mismatched = total - matched
    confusion: dict[str, dict[str, int]] = {}
    by_expected_label: dict[str, dict[str, float | int]] = {}
    for row in rows:
        expected = row.expected_label
        observed = row.predicted_label
        bucket = confusion.setdefault(expected, {})
        bucket[observed] = bucket.get(observed, 0) + 1
        expected_bucket = by_expected_label.setdefault(
            expected,
            {"total": 0, "mismatched": 0, "disagreement_rate": 0.0},
        )
        expected_bucket["total"] += 1
        if row.status != "matched":
            expected_bucket["mismatched"] += 1

    for bucket in by_expected_label.values():
        total_for_label = int(bucket["total"])
        mismatched_for_label = int(bucket["mismatched"])
        bucket["disagreement_rate"] = (
            mismatched_for_label / total_for_label if total_for_label else 0.0
        )

    false_major_count = sum(
        1 for row in rows if row.predicted_label == "MAJOR" and row.expected_label != "MAJOR"
    )
    false_minor_count = sum(
        1 for row in rows if row.predicted_label == "MINOR" and row.expected_label != "MINOR"
    )
    degraded_rows = [row for row in rows if row.analysis_state == "degraded_fallback"]
    degraded_total = len(degraded_rows)
    degraded_mismatches = sum(1 for row in degraded_rows if row.status != "matched")
    fallback_rows = [
        row
        for row in rows
        if row.classification_source in {"semantic-fallback", "no-diff-heuristic"}
    ]
    fallback_total = len(fallback_rows)
    fallback_mismatches = sum(1 for row in fallback_rows if row.status != "matched")
    forced_override_mismatches = sum(
        1 for row in rows if row.status == "mismatch" and row.mismatch_type == "forced_override"
    )
    natural_mismatches = sum(
        1 for row in rows if row.status == "mismatch" and row.mismatch_type == "natural"
    )
    return {
        "total": total,
        "matched": matched,
        "mismatched": mismatched,
        "pass_rate": matched / total if total else 0.0,
        "disagreement_rate": mismatched / total if total else 0.0,
        "forced_override_mismatches": forced_override_mismatches,
        "natural_mismatches": natural_mismatches,
        "forced_override_mismatch_rate": (
            forced_override_mismatches / mismatched if mismatched else 0.0
        ),
        "by_expected_label": by_expected_label,
        "false_major_count": false_major_count,
        "false_minor_count": false_minor_count,
        "degraded_fallback": {
            "total": degraded_total,
            "mismatches": degraded_mismatches,
            "mismatch_rate": degraded_mismatches / degraded_total if degraded_total else 0.0,
        },
        "fallback": {
            "total": fallback_total,
            "mismatches": fallback_mismatches,
            "mismatch_rate": fallback_mismatches / fallback_total if fallback_total else 0.0,
        },
        "confusion": confusion,
    }


def _parse_distribution(raw: str) -> dict[str, int]:
    if not raw.strip():
        return dict(DEFAULT_DISTRIBUTION)
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("--distribution must be a JSON object")
    out: dict[str, int] = {}
    for key, value in parsed.items():
        label = str(key).upper()
        if label not in {"MAJOR", "MINOR", "PATCH", "NO_BUMP"}:
            raise ValueError(f"Unsupported label in distribution: {key}")
        out[label] = int(value)
    return out


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bumpkin corpus acceleration CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build-queue", help="Build balanced replay queue from source commits.")
    build.add_argument("--source-repo", required=True, help="Path to source TS/JS repository.")
    build.add_argument("--rev-range", default="HEAD~300..HEAD", help="Git revision range.")
    build.add_argument(
        "--target-count", type=int, default=30, help="How many queue items to produce."
    )
    build.add_argument("--seed", type=int, default=42, help="Random seed for queue selection.")
    build.add_argument(
        "--distribution",
        default="",
        help='Optional JSON distribution, e.g. \'{"MAJOR":6,"MINOR":8,"PATCH":10,"NO_BUMP":6}\'',
    )
    build.add_argument("--output", default="artifacts/live-pr-validation/queue.json")

    open_prs = sub.add_parser("open-prs", help="Create replay PRs from queue.")
    open_prs.add_argument("--queue-file", required=True)
    open_prs.add_argument("--source-repo", required=True)
    open_prs.add_argument("--fixture-repo", required=True)
    open_prs.add_argument("--base-branch", default="main")
    open_prs.add_argument("--limit", type=int, default=0)
    open_prs.add_argument("--dry-run", action="store_true")
    open_prs.add_argument("--output", default="artifacts/live-pr-validation/open-prs.json")

    collect = sub.add_parser(
        "collect-results", help="Collect expected vs predicted labels from merged PRs."
    )
    collect.add_argument("--repo", default="", help="GitHub repo slug owner/name.")
    collect.add_argument("--fixture-repo", default="", help="Local repo path to infer owner/name.")
    collect.add_argument("--limit", type=int, default=200)
    collect.add_argument("--output", default="artifacts/live-pr-validation/results.tsv")
    collect.add_argument("--summary", default="artifacts/live-pr-validation/summary.json")

    summarize = sub.add_parser("summarize-results", help="Summarize existing TSV results file.")
    summarize.add_argument("--input", default="artifacts/live-pr-validation/results.tsv")

    return parser


def _main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "build-queue":
        source_repo = Path(args.source_repo).resolve()
        distribution = _parse_distribution(args.distribution)
        candidates, resolved_rev_range = list_commit_candidates(source_repo, args.rev_range)
        selected = build_balanced_queue(
            candidates,
            target_count=args.target_count,
            seed=args.seed,
            distribution=distribution,
        )
        output = Path(args.output)
        _write_queue_json(
            output,
            selected,
            source_repo=source_repo,
            rev_range=args.rev_range,
            resolved_rev_range=resolved_rev_range,
        )
        print(
            json.dumps(
                {
                    "output": str(output),
                    "total_candidates": len(candidates),
                    "selected": len(selected),
                    "resolved_rev_range": resolved_rev_range,
                },
                indent=2,
            )
        )
        return 0

    if args.command == "open-prs":
        queue = _load_queue(Path(args.queue_file))
        result_rows = open_replay_prs(
            source_repo=Path(args.source_repo).resolve(),
            fixture_repo=Path(args.fixture_repo).resolve(),
            queue=queue,
            base_branch=args.base_branch,
            limit=args.limit,
            dry_run=args.dry_run,
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result_rows, indent=2))
        print(json.dumps({"output": str(output), "rows": len(result_rows)}, indent=2))
        return 0

    if args.command == "collect-results":
        repo = args.repo.strip()
        if not repo:
            if not args.fixture_repo:
                raise ValueError("Provide --repo or --fixture-repo for collect-results.")
            repo = _repo_slug_from_remote(Path(args.fixture_repo).resolve())
        rows = collect_results(repo=repo, limit=args.limit)
        write_results_tsv(Path(args.output), rows)
        summary = summarize_rows(rows)
        summary_path = Path(args.summary)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2))
        print(
            json.dumps(
                {"rows": len(rows), "output": args.output, "summary": args.summary}, indent=2
            )
        )
        return 0

    if args.command == "summarize-results":
        with Path(args.input).open() as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            rows = [
                PRResultRow(
                    pr_number=int(row["pr_number"]),
                    url=row["url"],
                    expected_label=row["expected_label"],
                    predicted_label=row["predicted_label"],
                    confidence=row["confidence"],
                    mode_used=row["mode_used"],
                    analysis_state=row.get("analysis_state", "unknown"),
                    classification_source=row.get("classification_source", "unknown"),
                    override_status=row.get("override_status", "unknown"),
                    override_applied=str(row.get("override_applied", "")).strip().lower() == "true",
                    mismatch_type=row.get("mismatch_type", "none"),
                    status=row["status"],
                )
                for row in reader
            ]
        print(json.dumps(summarize_rows(rows), indent=2))
        return 0

    raise AssertionError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(_main())
