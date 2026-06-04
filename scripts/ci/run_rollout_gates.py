#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bumpkin.eval.rollout_gates import evaluate_preflight_gate, evaluate_rollout_gate


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate eval payloads against rollout gate thresholds.",
    )
    parser.add_argument(
        "--eval-json",
        action="append",
        default=[],
        help="Path to eval output JSON. Repeatable.",
    )
    parser.add_argument("--min-pass-rate", type=float, default=0.70)
    parser.add_argument("--max-unexpected-manual-review-rate", type=float, default=0.20)
    parser.add_argument("--max-unexpected-critical-missing-proofs-total", type=int, default=0)
    parser.add_argument("--max-contradiction-count", type=int, default=0)
    parser.add_argument("--expect-evaluated-count", type=int, default=None)
    parser.add_argument(
        "--require-preflight-status",
        choices=("any", "ok", "failed"),
        default="any",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    eval_paths = [Path(path) for path in args.eval_json]
    if not eval_paths:
        print("No --eval-json paths provided.")
        return 1

    failures: list[str] = []
    for path in eval_paths:
        if not path.exists():
            failures.append(f"{path}: file not found")
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            failures.append(f"{path}: payload must be an object")
            continue

        preflight = payload.get("preflight")
        if not isinstance(preflight, dict):
            preflight = {}
        preflight_gate = evaluate_preflight_gate(
            preflight,
            require_status=args.require_preflight_status,
        )
        failures.extend(f"{path}: {failure}" for failure in preflight_gate.failures)

        metrics = payload.get("metrics")
        if not isinstance(metrics, dict):
            failures.append(f"{path}: metrics must be an object")
            continue
        metric_gate = evaluate_rollout_gate(
            metrics,
            min_pass_rate=args.min_pass_rate,
            max_unexpected_manual_review_rate=args.max_unexpected_manual_review_rate,
            max_unexpected_critical_missing_proofs_total=args.max_unexpected_critical_missing_proofs_total,
            max_contradiction_count=args.max_contradiction_count,
            expect_evaluated_count=args.expect_evaluated_count,
        )
        failures.extend(f"{path}: {failure}" for failure in metric_gate.failures)

    if failures:
        print("Rollout gate validation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"Rollout gate validation passed for {len(eval_paths)} payload(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
