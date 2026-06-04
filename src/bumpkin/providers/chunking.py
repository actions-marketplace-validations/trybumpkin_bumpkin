from __future__ import annotations

from typing import Any


def _classified_result(
    *,
    label: str,
    confidence: str,
    reasoning: str,
    changelog: str,
) -> dict[str, Any]:
    return {
        "status": "classified",
        "label": label,
        "confidence": confidence,
        "reasoning": reasoning,
        "changelog": changelog,
    }


def _manual_review_result(reasoning: str) -> dict[str, Any]:
    return {
        "status": "manual_review",
        "label": None,
        "confidence": None,
        "reasoning": reasoning,
        "changelog": None,
    }


def split_large_unit(unit: str, max_chars: int) -> list[str]:
    if len(unit) <= max_chars:
        return [unit]

    lines = unit.splitlines(keepends=True)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        line_len = len(line)
        if current and current_len + line_len > max_chars:
            chunks.append("".join(current))
            current = [line]
            current_len = line_len
            continue
        current.append(line)
        current_len += line_len
    if current:
        chunks.append("".join(current))
    return chunks


def split_diff_units_into_chunks(
    diff_units: list[tuple[str, str]],
    *,
    max_chunk_tokens: int,
    max_chunk_count: int,
) -> tuple[list[dict[str, Any]], int, set[str], set[str]]:
    max_chars = max(80, max_chunk_tokens * 4)
    raw_segments: list[dict[str, Any]] = []
    all_files: set[str] = set()

    for path, text in diff_units:
        normalized_path = str(path or "").strip()
        if not normalized_path or not text.strip():
            continue
        all_files.add(normalized_path)
        for segment in split_large_unit(text, max_chars=max_chars):
            if not segment.strip():
                continue
            raw_segments.append({"text": segment, "files": {normalized_path}})

    if not raw_segments:
        return [], 0, all_files, set()

    chunks: list[dict[str, Any]] = []
    current_parts: list[str] = []
    current_files: set[str] = set()
    current_len = 0

    for segment in raw_segments:
        seg_text = str(segment["text"])
        seg_files = set(segment["files"])
        seg_len = len(seg_text)
        if current_parts and current_len + seg_len > max_chars:
            chunks.append({"text": "".join(current_parts), "files": set(current_files)})
            current_parts = [seg_text]
            current_files = set(seg_files)
            current_len = seg_len
            continue
        current_parts.append(seg_text)
        current_files.update(seg_files)
        current_len += seg_len

    if current_parts:
        chunks.append({"text": "".join(current_parts), "files": set(current_files)})

    if max_chunk_count > 0 and len(chunks) > max_chunk_count:
        kept_chunks = chunks[:max_chunk_count]
        dropped_chunks = chunks[max_chunk_count:]
        omitted_files: set[str] = set()
        for chunk in dropped_chunks:
            omitted_files.update(chunk["files"])
        return kept_chunks, len(dropped_chunks), all_files, omitted_files

    return chunks, 0, all_files, set()


def split_diff_into_chunks(
    diff_text: str,
    *,
    max_chunk_tokens: int,
    max_chunk_count: int,
) -> tuple[list[str], int]:
    if not diff_text.strip():
        return [], 0

    max_chars = max(80, max_chunk_tokens * 4)
    raw_units: list[str]
    if "diff --git " in diff_text:
        prefix, *rest = diff_text.split("diff --git ")
        raw_units = []
        if prefix.strip():
            raw_units.append(prefix)
        raw_units.extend(f"diff --git {part}" for part in rest if part.strip())
    else:
        raw_units = [diff_text]

    sized_units: list[str] = []
    for unit in raw_units:
        sized_units.extend(split_large_unit(unit, max_chars=max_chars))

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for unit in sized_units:
        unit_len = len(unit)
        if current and current_len + unit_len > max_chars:
            chunks.append("".join(current))
            current = [unit]
            current_len = unit_len
        else:
            current.append(unit)
            current_len += unit_len
    if current:
        chunks.append("".join(current))

    if max_chunk_count <= 0 or len(chunks) <= max_chunk_count:
        return chunks, 0

    skipped = len(chunks) - max_chunk_count
    return chunks[:max_chunk_count], skipped


def aggregate_chunk_recommendations(
    recommendations: list[dict[str, str]],
    *,
    truncated: bool,
    valid_labels: set[str],
    label_priority: dict[str, int],
    aggregate_changelog: dict[str, str],
) -> dict[str, Any]:
    if not recommendations:
        return _manual_review_result(
            reasoning="Chunked analysis produced no successful chunk recommendations."
        )

    counts = dict.fromkeys(valid_labels, 0)
    for item in recommendations:
        counts[item["label"]] += 1

    selected = max(counts, key=lambda label: (counts[label], label_priority[label]))
    selected_confidences = [
        item["confidence"] for item in recommendations if item["label"] == selected
    ]
    if "low" in selected_confidences:
        confidence = "low"
    elif "medium" in selected_confidences:
        confidence = "medium"
    else:
        confidence = "high"

    reasoning = (
        "Chunked model analysis aggregated labels: "
        + ", ".join(f"{label}={counts[label]}" for label in ("MAJOR", "MINOR", "PATCH", "NO_BUMP"))
        + f"; selected {selected} by highest-severity rule."
    )
    if truncated:
        reasoning += " Diff was truncated before chunking."

    return _classified_result(
        label=selected,
        confidence=confidence,
        reasoning=reasoning,
        changelog=aggregate_changelog[selected],
    )


def with_chunking_metadata(
    result: dict[str, Any],
    *,
    enabled: bool,
    chunk_count: int,
    succeeded: int,
    failed: int,
    skipped: int,
    max_chunk_tokens: int,
    max_chunk_count: int,
    failure_policy: str,
    files_total: int = 0,
    omitted_files: list[str] | None = None,
) -> dict[str, Any]:
    omitted = sorted({item.strip() for item in (omitted_files or []) if item and item.strip()})
    files_total_value = max(0, int(files_total))
    files_omitted = len(omitted)
    files_covered = max(0, files_total_value - files_omitted)
    enriched = dict(result)
    enriched["chunking"] = {
        "enabled": enabled,
        "chunk_count": chunk_count,
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
        "max_chunk_tokens": max_chunk_tokens,
        "max_chunk_count": max_chunk_count,
        "failure_policy": failure_policy,
        "files_total": files_total_value,
        "files_covered": files_covered,
        "files_omitted": files_omitted,
        "omitted_files": omitted,
        "omitted_files_sample": omitted[:5],
    }
    return enriched
