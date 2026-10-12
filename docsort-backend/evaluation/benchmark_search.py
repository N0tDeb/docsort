#!/usr/bin/env python3
"""Benchmark authenticated DocSort search latency using a fixed query set."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

import httpx

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.evaluation.metrics import summarize_latency  # noqa: E402


def load_queries(path: Path) -> list[str]:
    queries = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not queries:
        raise ValueError("Query file contains no non-empty queries")
    return queries


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure DocSort /search response time.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="DocSort API base URL")
    parser.add_argument("--queries", type=Path, required=True, help="Text file with one fixed query per line")
    parser.add_argument("--iterations", type=int, default=5, help="Number of timed passes over the query file")
    parser.add_argument("--warmup", type=int, default=1, help="Untimed warm-up passes")
    parser.add_argument("--output", type=Path, help="Optional aggregate JSON output")
    args = parser.parse_args()

    if args.iterations < 1 or args.warmup < 0:
        parser.error("iterations must be >= 1 and warmup must be >= 0")

    token = os.environ.get("DOCSORT_EVAL_TOKEN")
    if not token:
        parser.error("Set DOCSORT_EVAL_TOKEN to a valid test-user JWT. The token is never written to output.")

    try:
        queries = load_queries(args.queries)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    latencies: list[float] = []
    base_url = args.base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        with httpx.Client(base_url=base_url, headers=headers, timeout=30.0) as client:
            for _ in range(args.warmup):
                for query in queries:
                    response = client.get("/search", params={"q": query, "limit": 20})
                    response.raise_for_status()

            for _ in range(args.iterations):
                for query in queries:
                    started = time.perf_counter()
                    response = client.get("/search", params={"q": query, "limit": 20})
                    response.raise_for_status()
                    latencies.append((time.perf_counter() - started) * 1000.0)
    except httpx.HTTPError as exc:
        parser.error(f"Search benchmark request failed: {exc}")

    report = {
        "queries": len(queries),
        "iterations": args.iterations,
        "warmup_passes": args.warmup,
        "search_latency_ms": summarize_latency(latencies),
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
