#!/usr/bin/env python3
"""Evaluate a DocSort JSONL dataset without requiring a live backend."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.evaluation.metrics import evaluate_records  # noqa: E402


def load_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_number}: {exc.msg}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"Line {line_number} must be a JSON object")
            if not record.get("id"):
                raise ValueError(f"Line {line_number} is missing a non-empty 'id'")
            if not isinstance(record.get("ground_truth"), dict):
                raise ValueError(f"Line {line_number} is missing object 'ground_truth'")
            if not isinstance(record.get("prediction"), dict):
                raise ValueError(f"Line {line_number} is missing object 'prediction'")
            records.append(record)
    if not records:
        raise ValueError("Dataset contains no evaluation records")
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute DocSort evaluation metrics from labelled JSONL data.")
    parser.add_argument("dataset", type=Path, help="Path to the labelled JSONL dataset")
    parser.add_argument("--output", type=Path, help="Optional path for aggregate JSON metrics")
    args = parser.parse_args()

    try:
        records = load_jsonl(args.dataset)
        report = evaluate_records(records)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
