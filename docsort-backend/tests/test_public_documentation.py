from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_documentation_index_points_to_current_sources():
    index = read("docs/README.md")
    for target in (
        "../README.md",
        "../SETUP.md",
        "../docsort-backend/ARCHITECTURE.md",
        "FLOW.md",
        "EVALUATION.md",
        "PITCH.md",
        "FINAL_IMPLEMENTATION_REPORT.md",
    ):
        assert target in index


def test_architecture_describes_real_processing_and_security_boundaries():
    architecture = read("docsort-backend/ARCHITECTURE.md")
    assert "BackgroundTasks" in architecture
    assert "not a durable external queue" in architecture
    assert "Integrity & Duplicate Check" in architecture
    assert "Secure File Storage" in architecture
    assert "OCR & AI Extraction" in architecture
    assert "Anomaly Check" in architecture
    assert "Classification & Filing" in architecture
    assert "review_status = needs_review" in architecture
    assert "PBKDF2-HMAC-SHA256" in architecture
    assert "flawlessly" not in architecture.lower()
    assert "image retention law" not in architecture.lower()


def test_flow_and_readme_present_domain_neutral_scope():
    readme = read("README.md")
    flow = read("docs/FLOW.md")
    pitch = read("docs/PITCH.md")
    assert "domain-neutral" in readme.lower()
    assert "human-in-the-loop" in (readme + flow + pitch).lower()
    assert "People & Document Map" in readme
    assert "OCR" in flow
    assert "Generative AI" in pitch


def test_final_implementation_report_records_final_validation_evidence():
    report = read("docs/FINAL_IMPLEMENTATION_REPORT.md")
    assert "Final Implementation Report" in report
    assert "432 passed, 0 failed" in report
    assert "one non-failing `StarletteDeprecationWarning`" in report
    assert "No broken requirements found" in report
    assert "database=ok" in report
    assert "storage=ok" in report
    assert "ocr=ok" in report
    assert "33 tests passed" in report
    assert "No issues found" in report
    assert "20-page PDF" in report
    assert "No project accuracy" in report
    assert "production certification" in report
