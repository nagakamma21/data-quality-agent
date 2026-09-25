"""Deterministic data-quality tools. The LLM decides *which* to call and
interprets results; these functions do the actual measurement so numbers
in the report are never hallucinated."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

_DF: pd.DataFrame | None = None
_PATH: str | None = None
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def load_dataset(path: str) -> dict:
    """Load a CSV or Parquet file into memory and return its shape/schema."""
    global _DF, _PATH
    p = Path(path)
    _DF = pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p)
    _PATH = str(p)
    return {
        "path": _PATH,
        "rows": int(len(_DF)),
        "columns": {c: str(t) for c, t in _DF.dtypes.items()},
    }


def _df() -> pd.DataFrame:
    if _DF is None:
        raise RuntimeError("Call load_dataset first")
    return _DF


def profile_columns() -> dict:
    """Per-column null rate, distinct count, and numeric summary."""
    df = _df()
    out = {}
    for c in df.columns:
        s = df[c]
        info = {
            "dtype": str(s.dtype),
            "null_pct": round(float(s.isna().mean() * 100), 2),
            "distinct": int(s.nunique(dropna=True)),
        }
        if pd.api.types.is_numeric_dtype(s):
            q = s.quantile([0.01, 0.5, 0.99])
            info.update(min=float(s.min()), p01=float(q[0.01]), median=float(q[0.5]),
                        p99=float(q[0.99]), max=float(s.max()))
        else:
            info["top_values"] = {str(k): int(v) for k, v in s.value_counts(dropna=True).head(8).items()}
        out[c] = info
    return out


def detect_anomalies(column: str, method: str = "iqr") -> dict:
    """Flag numeric outliers (iqr or zscore), negatives, and future dates."""
    df = _df()
    s = df[column]
    result: dict = {"column": column}
    if pd.api.types.is_numeric_dtype(s):
        clean = s.dropna()
        if method == "zscore":
            z = (clean - clean.mean()) / clean.std()
            mask = z.abs() > 3
        else:
            q1, q3 = clean.quantile([0.25, 0.75])
            iqr = q3 - q1
            mask = (clean < q1 - 3 * iqr) | (clean > q3 + 3 * iqr)
        result["outliers"] = int(mask.sum())
        result["outlier_examples"] = [float(v) for v in clean[mask].head(5)]
        result["negatives"] = int((clean < 0).sum())
    else:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            parsed = pd.to_datetime(s, errors="coerce")
        if parsed.notna().mean() > 0.8:
            future = parsed > pd.Timestamp.today()
            result["future_dates"] = int(future.sum())
            result["unparseable"] = int((parsed.isna() & s.notna()).sum())
        else:
            stripped = s.dropna().astype(str)
            result["leading_trailing_whitespace"] = int((stripped != stripped.str.strip()).sum())
            result["case_variants"] = int(stripped.str.strip().str.lower().nunique() != stripped.nunique())
            result["placeholder_values"] = int(stripped.str.strip().str.lower().isin(
                ["n/a", "na", "null", "none", "", "-", "unknown"]).sum())
    return result


def check_duplicates(key_columns: list[str] | None = None) -> dict:
    """Count exact duplicate rows, or duplicates on a candidate key."""
    df = _df()
    if key_columns:
        dupes = df.duplicated(subset=key_columns, keep=False)
        return {"key": key_columns, "duplicate_rows": int(dupes.sum())}
    return {"key": "all_columns", "duplicate_rows": int(df.duplicated(keep=False).sum())}


def validate_pattern(column: str, pattern: str = "email") -> dict:
    """Check string values against a named pattern (email) or a regex."""
    df = _df()
    s = df[column].dropna().astype(str)
    rx = EMAIL_RE if pattern == "email" else re.compile(pattern)
    bad = ~s.str.match(rx)
    return {"column": column, "pattern": pattern, "invalid": int(bad.sum()),
            "examples": s[bad].head(5).tolist()}


def write_rules(rules: list[dict]) -> dict:
    """Persist validation rules as JSON (consumable by a CI check)."""
    out = Path("reports") / "validation_rules.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(rules, indent=2))
    return {"written": str(out), "rule_count": len(rules)}


TOOLS = [
    {"name": "load_dataset", "description": load_dataset.__doc__,
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "profile_columns", "description": profile_columns.__doc__,
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "detect_anomalies", "description": detect_anomalies.__doc__,
     "input_schema": {"type": "object", "properties": {"column": {"type": "string"},
                      "method": {"type": "string", "enum": ["iqr", "zscore"]}}, "required": ["column"]}},
    {"name": "check_duplicates", "description": check_duplicates.__doc__,
     "input_schema": {"type": "object", "properties": {"key_columns": {"type": "array", "items": {"type": "string"}}}}},
    {"name": "validate_pattern", "description": validate_pattern.__doc__,
     "input_schema": {"type": "object", "properties": {"column": {"type": "string"}, "pattern": {"type": "string"}},
                      "required": ["column"]}},
    {"name": "write_rules", "description": write_rules.__doc__,
     "input_schema": {"type": "object", "properties": {"rules": {"type": "array", "items": {"type": "object"}}},
                      "required": ["rules"]}},
]

REGISTRY = {
    "load_dataset": load_dataset,
    "profile_columns": profile_columns,
    "detect_anomalies": detect_anomalies,
    "check_duplicates": check_duplicates,
    "validate_pattern": validate_pattern,
    "write_rules": write_rules,
}


def dispatch(name: str, args: dict):
    return REGISTRY[name](**args)
