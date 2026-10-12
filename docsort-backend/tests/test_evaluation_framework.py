import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.evaluation.metrics import evaluate_records, summarize_latency


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent


def test_evaluation_metrics_keep_correctness_review_and_ocr_separate():
    records = [
        {
            "id": "doc-1",
            "ground_truth": {
                "doc_type": "Invoice",
                "raw_text": "hello world",
                "fields": {"Invoice Number": "INV-1", "Vendor": "Acme"},
            },
            "prediction": {
                "doc_type": " invoice ",
                "raw_text": "hello world",
                "fields": [
                    {"label": "Invoice Number", "value": "INV-1"},
                    {"label": "Vendor", "value": "Acme"},
                ],
            },
            "reviewed": {
                "doc_type": "Invoice",
                "fields": {"Invoice Number": "INV-1", "Vendor": "Acme"},
            },
            "timings": {"processing_ms": 100},
        },
        {
            "id": "doc-2",
            "ground_truth": {
                "doc_type": "Resume",
                "raw_text": "one two",
                "fields": {"Name": "Alice", "Email": "a@example.com"},
            },
            "prediction": {
                "doc_type": "Contract",
                "raw_text": "one too",
                "fields": {"Name": "Alicia", "Extra": "unexpected"},
            },
            "reviewed": {
                "doc_type": "Resume",
                "fields": {"Name": "Alice", "Email": "a@example.com"},
            },
            "timings": {"processing_ms": 300},
        },
    ]

    report = evaluate_records(records)

    assert report["classification"]["accuracy"] == 0.5
    assert report["classification"]["evaluated"] == 2
    assert report["field_extraction"]["precision"] == 0.5
    assert report["field_extraction"]["recall"] == 0.5
    assert report["field_extraction"]["f1"] == 0.5
    assert report["field_extraction"]["strict_document_match_rate"] == 0.5
    assert report["human_review"]["document_correction_rate"] == 0.5
    assert report["human_review"]["classification_correction_rate"] == 0.5
    assert report["human_review"]["field_correction_rate"] == 0.6
    assert report["ocr"]["character_error_rate"] == pytest.approx(1 / 18, abs=1e-6)
    assert report["ocr"]["word_error_rate"] == 0.25
    assert report["processing_latency_ms"] == {
        "samples": 2,
        "mean_ms": 200.0,
        "median_ms": 200.0,
        "p95_ms": 290.0,
        "min_ms": 100.0,
        "max_ms": 300.0,
    }


def test_missing_evidence_is_null_not_fabricated_zero():
    report = evaluate_records([{"id": "doc-1", "ground_truth": {}, "prediction": {}}])

    assert report["classification"]["evaluated"] == 0
    assert report["classification"]["accuracy"] is None
    assert report["field_extraction"]["precision"] is None
    assert report["ocr"]["character_error_rate"] is None
    assert report["processing_latency_ms"]["samples"] == 0
    assert report["processing_latency_ms"]["median_ms"] is None


def test_latency_summary_reports_distribution_without_hiding_samples():
    assert summarize_latency([10, 20, 30, 40]) == {
        "samples": 4,
        "mean_ms": 25.0,
        "median_ms": 25.0,
        "p95_ms": 38.5,
        "min_ms": 10.0,
        "max_ms": 40.0,
    }


def test_dataset_cli_generates_aggregate_json(tmp_path):
    dataset = tmp_path / "evaluation.jsonl"
    dataset.write_text(
        json.dumps({
            "id": "doc-1",
            "ground_truth": {"doc_type": "Invoice", "fields": {"A": "1"}},
            "prediction": {"doc_type": "Invoice", "fields": {"A": "1"}},
            "timings": {"processing_ms": 12.5},
        }) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "metrics.json"

    completed = subprocess.run(
        [sys.executable, "evaluation/evaluate_dataset.py", str(dataset), "--output", str(output)],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["classification"]["accuracy"] == 1.0
    assert report["field_extraction"]["f1"] == 1.0
    assert report["processing_latency_ms"]["samples"] == 1


def test_evaluation_contract_and_docs_are_versionable_but_private_data_is_ignored():
    schema_path = BACKEND_ROOT / "evaluation/evaluation_record.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["title"] == "DocSort Evaluation Record"
    assert schema["required"] == ["id", "ground_truth", "prediction"]
    assert schema["properties"]["timings"]["properties"]["duplicate_reused"] == {"type": "boolean"}

    guide = (PROJECT_ROOT / "docs/EVALUATION.md").read_text(encoding="utf-8")
    assert "OCR confidence is **not** classification accuracy" in guide
    assert "TBD" in guide
    assert "Do not report a percentage until" in guide

    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "docsort-backend/evaluation/data/" in gitignore
    assert "docsort-backend/evaluation/results/" in gitignore


def test_upload_pipeline_exposes_real_processing_timing_and_persists_raw_ocr_text():
    source = (BACKEND_ROOT / "app/api/upload.py").read_text(encoding="utf-8")
    schema = (BACKEND_ROOT / "app/schemas/upload_schema.py").read_text(encoding="utf-8")

    assert '"processing_ms"' in source
    assert '"raw_text":        extracted.get("raw_text")' in source
    assert "progress,document_id" in source
    assert "progress: Optional[dict]" in schema


def test_search_benchmark_does_not_embed_or_write_a_token():
    source = (BACKEND_ROOT / "evaluation/benchmark_search.py").read_text(encoding="utf-8")

    assert 'os.environ.get("DOCSORT_EVAL_TOKEN")' in source
    assert '"Authorization": f"Bearer {token}"' in source
    assert '"token"' not in source.split("report =", 1)[1]


def test_duplicate_reuse_is_excluded_from_model_quality_and_full_processing_latency():
    records = [
        {
            "id": "fresh",
            "ground_truth": {"doc_type": "Invoice", "fields": {"A": "1"}},
            "prediction": {"doc_type": "Invoice", "fields": {"A": "1"}},
            "timings": {"processing_ms": 400, "duplicate_reused": False},
        },
        {
            "id": "duplicate",
            "ground_truth": {"doc_type": "Resume", "fields": {"Name": "Alice"}},
            "prediction": {"doc_type": "Resume", "fields": {"Name": "Alice"}},
            "timings": {"processing_ms": 5, "duplicate_reused": True},
        },
    ]

    report = evaluate_records(records)

    assert report["dataset"]["records"] == 2
    assert report["dataset"]["duplicate_reused_excluded"] == 1
    assert report["classification"]["evaluated"] == 1
    assert report["field_extraction"]["documents_evaluated"] == 1
    assert report["processing_latency_ms"]["samples"] == 1
    assert report["processing_latency_ms"]["mean_ms"] == 400.0
    assert report["duplicate_reuse_latency_ms"]["samples"] == 1
    assert report["duplicate_reuse_latency_ms"]["mean_ms"] == 5.0
