from pathlib import Path

from log_diagnostic_agent.demo import run_demo


DATA = Path(__file__).resolve().parents[1] / "data"


def test_demo_produces_validated_probable_diagnosis():
    report = run_demo(DATA)
    assert report.root_cause_status == "probable"
    assert report.validation_status == "validated"
    assert report.confidence > 0.8
    assert "connection pool" in report.probable_root_cause.lower()
    assert report.review_status == "pending"
    assert report.actual_remediation is None
