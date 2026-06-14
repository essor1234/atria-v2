"""Rich statistical profiler for deep_analyze."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from .dataloader import profile_schema

logger = logging.getLogger(__name__)


def build_rich_profile(db_path: Path, file_name: str) -> Dict[str, Any]:
    """Extend profile_schema() with outliers, correlations, and significance tests."""
    import sqlite3

    with sqlite3.connect(db_path) as cx:
        df = pd.read_sql_query("SELECT * FROM raw", cx)

    base = profile_schema(db_path, file_name)

    enriched_cols: List[Dict[str, Any]] = []
    for col_info in base["columns"]:
        name = col_info["name"]
        s = df[name]
        col = dict(col_info)
        dtype = col_info["dtype"]

        if dtype == "string":
            vc = s.value_counts().head(10)
            col["top_values"] = [
                {"value": str(k), "count": int(v)} for k, v in vc.items()
            ]
        elif dtype in {"int", "float"}:
            clean = s.dropna()
            if len(clean) >= 4:
                q1 = float(clean.quantile(0.25))
                q3 = float(clean.quantile(0.75))
                iqr = q3 - q1
                lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
                col["outlier_count"] = int(((clean < lower) | (clean > upper)).sum())
                col["skewness"] = float(clean.skew())
                col["kurtosis"] = float(clean.kurt())
                # Sarle's bimodality coefficient: bc > 0.555 suggests bimodality
                n = len(clean)
                sk, ku = col["skewness"], col["kurtosis"]
                if n > 3:
                    bc = (sk ** 2 + 1) / (ku + 3 * (n - 1) ** 2 / ((n - 2) * (n - 3)))
                    col["is_bimodal"] = bc > 0.555
                else:
                    col["is_bimodal"] = False
            else:
                col["outlier_count"] = 0
                col["skewness"] = 0.0
                col["kurtosis"] = 0.0
                col["is_bimodal"] = False
        enriched_cols.append(col)

    # Pearson correlation matrix between numeric columns
    num_cols = [c["name"] for c in base["columns"] if c["dtype"] in {"int", "float"}]
    correlations: List[Dict[str, Any]] = []
    if len(num_cols) >= 2:
        corr_df = df[num_cols].corr(method="pearson")
        for i, c1 in enumerate(num_cols):
            for c2 in num_cols[i + 1 :]:
                r = corr_df.loc[c1, c2]
                if not pd.isna(r):
                    correlations.append(
                        {
                            "col_a": c1,
                            "col_b": c2,
                            "r": round(float(r), 3),
                            "notable": bool(abs(r) > 0.7),
                        }
                    )

    # Kruskal-Wallis significance tests: top-5 categorical × numeric pairs
    cat_cols = [c["name"] for c in base["columns"] if c["dtype"] == "string"]
    significance_tests: List[Dict[str, Any]] = []
    try:
        from scipy import stats as scipy_stats  # noqa: PLC0415

        pairs = [(cat, num) for cat in cat_cols for num in num_cols]
        pairs_sorted = sorted(pairs, key=lambda p: df[p[0]].nunique())[:5]
        for cat, num in pairs_sorted:
            groups = [
                grp[num].dropna().values
                for _, grp in df.groupby(cat)
                if len(grp[num].dropna()) >= 2
            ]
            if len(groups) >= 2:
                try:
                    h, p = scipy_stats.kruskal(*groups)
                except ValueError:
                    continue
                significance_tests.append(
                    {
                        "categorical": cat,
                        "numeric": num,
                        "h_stat": round(float(h), 3),
                        "p_value": round(float(p), 4),
                        "significant": bool(p < 0.05),
                    }
                )
    except ImportError:
        logger.warning("scipy not available; skipping significance tests")

    return {
        **base,
        "columns": enriched_cols,
        "correlations": correlations,
        "significance_tests": significance_tests,
    }
