from __future__ import annotations

import re
from dataclasses import dataclass

PUBLIC_REMOVAL_PATTERNS = [
    re.compile(r"^-.*\bexport\s+(function|class|interface|type|const|let|var)\b"),
    re.compile(r"^-.*\bpublic\s+\w"),
    re.compile(r"^-.*\bpub\s+(fn|struct|enum|trait)\b"),
    re.compile(r"^-.*\bfunc\s+[A-Z]\w*\s*\("),
]

PUBLIC_ADDITION_PATTERNS = [
    re.compile(r"^\+.*\bexport\s+(function|class|interface|type|const|let|var)\b"),
    re.compile(r"^\+.*\bpublic\s+\w"),
    re.compile(r"^\+.*\bpub\s+(fn|struct|enum|trait)\b"),
    re.compile(r"^\+.*\bfunc\s+[A-Z]\w*\s*\("),
]

SIGNATURE_PATTERNS = [
    re.compile(r"^\s*[-+].*\bexport\s+function\s+([A-Za-z_]\w*)\s*\("),
    re.compile(r"^\s*[-+].*\bdef\s+([A-Za-z_]\w*)\s*\("),
    re.compile(r"^\s*[-+].*\bfunc\s+(?:\([^)]+\)\s*)?([A-Za-z_]\w*)\s*\("),
    re.compile(r"^\s*[-+].*\bpub\s+fn\s+([A-Za-z_]\w*)\s*\("),
]


@dataclass
class ImpactSummary:
    major_signals: int
    minor_signals: int
    patch_signals: int
    top_reasons: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "major_signals": self.major_signals,
            "minor_signals": self.minor_signals,
            "patch_signals": self.patch_signals,
            "top_reasons": self.top_reasons,
        }


def _extract_signature_name(line: str) -> str | None:
    for pattern in SIGNATURE_PATTERNS:
        match = pattern.search(line)
        if match:
            return match.group(1)
    return None


def summarize_impact(diff_text: str) -> ImpactSummary:
    major = 0
    minor = 0
    patch = 0

    removed_public = 0
    added_public = 0
    signature_changes = 0

    removed_signatures: set[str] = set()
    added_signatures: set[str] = set()
    major_lines: set[int] = set()
    minor_lines: set[int] = set()

    lines = diff_text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(("+++", "---", "@@", "diff --git", "index ")):
            continue
        if not line.startswith(("+", "-")):
            continue

        signature_name = _extract_signature_name(line)
        if signature_name:
            if line.startswith("-"):
                removed_signatures.add(signature_name)
            elif line.startswith("+"):
                added_signatures.add(signature_name)

        if line.startswith("-") and any(p.search(line) for p in PUBLIC_REMOVAL_PATTERNS):
            removed_public += 1
            major += 1
            major_lines.add(i)
            continue

        if line.startswith("+") and any(p.search(line) for p in PUBLIC_ADDITION_PATTERNS):
            added_public += 1
            minor += 1
            minor_lines.add(i)

    shared = removed_signatures & added_signatures
    signature_changes = len(shared)
    major += signature_changes

    for i, line in enumerate(lines):
        if i in major_lines or i in minor_lines:
            continue
        if line.startswith(("+++", "---", "@@", "diff --git", "index ")):
            continue
        if line.startswith(("+", "-")):
            patch += 1

    reasons: list[str] = []
    if removed_public:
        reasons.append(f"removed_public_symbols:{removed_public}")
    if signature_changes:
        reasons.append(f"signature_changes:{signature_changes}")
    if added_public:
        reasons.append(f"added_public_symbols:{added_public}")
    if patch:
        reasons.append(f"other_code_changes:{patch}")

    return ImpactSummary(
        major_signals=major,
        minor_signals=minor,
        patch_signals=patch,
        top_reasons=reasons[:4],
    )


__all__ = ["ImpactSummary", "summarize_impact"]
