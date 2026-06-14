"""Rich statistical profiler tests."""

from pathlib import Path

import pytest

from atria.skills.builtin.deep_analyze.dataloader import load_to_sqlite
from atria.skills.builtin.deep_analyze.profiler import build_rich_profile


@pytest.fixture
def jobs_db(tmp_path: Path) -> Path:
    """SQLite db with a small jobs-like dataset."""
    p = tmp_path / "jobs.csv"
    p.write_text(
        "job_title,industry,salary,automation_risk,country\n"
        "Engineer,Tech,120000,0.2,USA\n"
        "Analyst,Finance,85000,0.6,UK\n"
        "Driver,Transport,45000,0.9,USA\n"
        "Manager,Finance,110000,0.3,Germany\n"
        "Clerk,Retail,32000,0.85,UK\n"
        "Engineer,Finance,130000,0.15,USA\n"
    )
    db = tmp_path / "data.db"
    load_to_sqlite(p, db)
    return db


def test_base_schema_preserved(jobs_db: Path) -> None:
    profile = build_rich_profile(jobs_db, "jobs.csv")
    assert profile["file_name"] == "jobs.csv"
    assert profile["row_count"] == 6
    assert len(profile["columns"]) == 5


def test_categorical_columns_have_top_values(jobs_db: Path) -> None:
    profile = build_rich_profile(jobs_db, "jobs.csv")
    industry_col = next(c for c in profile["columns"] if c["name"] == "industry")
    assert "top_values" in industry_col
    assert len(industry_col["top_values"]) >= 1
    # Finance appears three times (Analyst, Manager, Engineer) — should be top
    top = industry_col["top_values"][0]
    assert top["value"] == "Finance"
    assert top["count"] == 3


def test_numeric_columns_have_outlier_count_and_skew(jobs_db: Path) -> None:
    profile = build_rich_profile(jobs_db, "jobs.csv")
    salary_col = next(c for c in profile["columns"] if c["name"] == "salary")
    assert "outlier_count" in salary_col
    assert "skewness" in salary_col
    assert "kurtosis" in salary_col
    assert "is_bimodal" in salary_col
    assert isinstance(salary_col["outlier_count"], int)
    assert isinstance(salary_col["skewness"], float)


def test_correlation_matrix_present(jobs_db: Path) -> None:
    profile = build_rich_profile(jobs_db, "jobs.csv")
    assert "correlations" in profile
    assert isinstance(profile["correlations"], list)
    # salary and automation_risk should produce a correlation entry
    pairs = {(c["col_a"], c["col_b"]) for c in profile["correlations"]}
    assert ("salary", "automation_risk") in pairs or ("automation_risk", "salary") in pairs


def test_significance_tests_present(jobs_db: Path) -> None:
    profile = build_rich_profile(jobs_db, "jobs.csv")
    assert "significance_tests" in profile
    assert isinstance(profile["significance_tests"], list)
    # should have at least one test (e.g. industry vs salary)
    assert len(profile["significance_tests"]) >= 1
    test = profile["significance_tests"][0]
    assert "categorical" in test
    assert "numeric" in test
    assert "p_value" in test
    assert "significant" in test
