"""Data Quality Agent: an LLM plans which checks to run, calls deterministic
tools, and writes a Markdown report. `--offline` runs a scripted planner so
the pipeline can be demoed and unit-tested without an API key."""
from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

import pandas as pd

from . import tools

SYSTEM = """You are a senior data-quality engineer. You are given a dataset path.
Investigate it with the tools: load it, profile every column, run anomaly
checks on numeric/date/categorical columns, check duplicates on the most
plausible key, validate any email-like column, then call write_rules with a
JSON list of validation rules (each: column, rule, threshold, rationale).
Finish with a concise Markdown report: a health score out of 100, a table of
findings (severity, column, issue, count), and recommended fixes. Only cite
numbers returned by tools."""


def run_anthropic(path: str, model: str) -> str:
    import anthropic  # imported lazily so offline mode has no SDK dependency

    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": f"Audit the dataset at {path}."}]
    while True:
        resp = client.messages.create(model=model, max_tokens=4000, system=SYSTEM,
                                      tools=tools.TOOLS, messages=messages)
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text")
        results = []
        for block in resp.content:
            if block.type == "tool_use":
                print(f"  -> {block.name}({json.dumps(block.input)})")
                out = tools.dispatch(block.name, block.input)
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": json.dumps(out, default=str)})
        messages.append({"role": "user", "content": results})


def run_openai(path: str, model: str) -> str:
    from openai import OpenAI  # lazy import, same reason as above

    client = OpenAI()
    oa_tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                  "parameters": t["input_schema"]}} for t in tools.TOOLS]
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Audit the dataset at {path}."}]
    while True:
        resp = client.chat.completions.create(model=model, messages=messages, tools=oa_tools)
        msg = resp.choices[0].message
        messages.append(msg)
        if not msg.tool_calls:
            return msg.content or ""
        for call in msg.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            print(f"  -> {call.function.name}({json.dumps(args)})")
            out = tools.dispatch(call.function.name, args)
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": json.dumps(out, default=str)})


PROVIDERS = {"anthropic": (run_anthropic, "ANTHROPIC_API_KEY", "claude-sonnet-5"),
             "openai": (run_openai, "OPENAI_API_KEY", "gpt-5")}


def run_offline(path: str) -> str:
    """Scripted planner: same tool calls an LLM would make, heuristic report."""
    schema = tools.load_dataset(path)
    prof = tools.profile_columns()
    findings, rules = [], []
    df = tools._df()

    for col, info in prof.items():
        if info["null_pct"] > 0:
            sev = "HIGH" if info["null_pct"] > 5 else "MEDIUM"
            findings.append((sev, col, "missing values", f'{info["null_pct"]}%'))
            rules.append({"column": col, "rule": "null_pct_lte", "threshold": 1.0,
                          "rationale": "Column is expected to be populated"})
        an = tools.detect_anomalies(col)
        if an.get("outliers"):
            findings.append(("MEDIUM", col, "statistical outliers (IQR x3)", an["outliers"]))
            rules.append({"column": col, "rule": "between", "threshold": [info["p01"], info["p99"]],
                          "rationale": "Values outside p01-p99 band need review"})
        if an.get("negatives"):
            findings.append(("HIGH", col, "negative values", an["negatives"]))
            rules.append({"column": col, "rule": "gte", "threshold": 0, "rationale": "Amounts cannot be negative"})
        if an.get("future_dates"):
            findings.append(("HIGH", col, "dates in the future", an["future_dates"]))
            rules.append({"column": col, "rule": "lte_today", "threshold": None, "rationale": "Event dates cannot be in the future"})
        if an.get("leading_trailing_whitespace"):
            findings.append(("LOW", col, "leading/trailing whitespace", an["leading_trailing_whitespace"]))
        if an.get("case_variants"):
            findings.append(("LOW", col, "inconsistent casing", "yes"))
            rules.append({"column": col, "rule": "in_set", "threshold": list(info["top_values"])[:4],
                          "rationale": "Controlled vocabulary"})
        if an.get("placeholder_values"):
            findings.append(("MEDIUM", col, "placeholder values (n/a, unknown...)", an["placeholder_values"]))
        if "email" in col.lower():
            v = tools.validate_pattern(col, "email")
            if v["invalid"]:
                findings.append(("HIGH", col, "invalid email format", v["invalid"]))
                rules.append({"column": col, "rule": "matches_email", "threshold": None, "rationale": "Contact field"})

    key = next((c for c in df.columns if c.lower().endswith("_id")), None)
    d_all = tools.check_duplicates()
    if d_all["duplicate_rows"]:
        findings.append(("HIGH", "*", "exact duplicate rows", d_all["duplicate_rows"]))
        rules.append({"column": "*", "rule": "unique_rows", "threshold": None, "rationale": "No exact duplicates"})
    if key:
        d_key = tools.check_duplicates([key])
        if d_key["duplicate_rows"]:
            findings.append(("HIGH", key, "duplicate primary key", d_key["duplicate_rows"]))
            rules.append({"column": key, "rule": "unique", "threshold": None, "rationale": "Candidate primary key"})

    tools.write_rules(rules)
    weights = {"HIGH": 8, "MEDIUM": 4, "LOW": 1}
    score = max(0, 100 - sum(weights[f[0]] for f in findings))
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    findings.sort(key=lambda f: order[f[0]])

    lines = [f"# Data Quality Report — `{Path(path).name}`", "",
             f"**Date:** {date.today()}  **Rows:** {schema['rows']}  **Columns:** {len(schema['columns'])}",
             "", f"## Health score: {score} / 100", "",
             "## Findings", "", "| Severity | Column | Issue | Count |", "|---|---|---|---|"]
    lines += [f"| {s} | `{c}` | {i} | {n} |" for s, c, i, n in findings]
    lines += ["", "## Recommended fixes", ""]
    if any(f[2].startswith("negative") for f in findings):
        lines.append("- Reject or quarantine negative amounts at ingestion; likely refund rows mis-loaded.")
    if any("duplicate" in f[2] for f in findings):
        lines.append(f"- Deduplicate on `{key or 'all columns'}` before loading to the warehouse.")
    if any("casing" in f[2] or "whitespace" in f[2] for f in findings):
        lines.append("- Normalize categorical columns (trim + title-case) and enforce a controlled vocabulary.")
    if any("future" in f[2] for f in findings):
        lines.append("- Add an `order_date <= today` constraint; future dates indicate a source system bug.")
    if any("email" in f[2] for f in findings):
        lines.append("- Validate emails at capture; route invalid records to a review queue.")
    lines += ["", f"Validation rules written to `reports/validation_rules.json` ({len(rules)} rules)."]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Run the Data Quality Agent on a CSV/Parquet file.")
    ap.add_argument("path")
    ap.add_argument("--offline", action="store_true", help="Run without an LLM (scripted planner)")
    ap.add_argument("--provider", choices=PROVIDERS, default=os.getenv("DQ_PROVIDER", "anthropic"))
    ap.add_argument("--model", default=os.getenv("DQ_MODEL"), help="Override the provider's default model")
    ap.add_argument("--out", default="reports/report.md")
    args = ap.parse_args()

    runner, key_env, default_model = PROVIDERS[args.provider]
    model = args.model or default_model
    use_llm = not args.offline and os.getenv(key_env)
    print(f"Mode: {args.provider + ' (' + model + ')' if use_llm else 'offline planner'}")
    report = runner(args.path, model) if use_llm else run_offline(args.path)
    Path(args.out).parent.mkdir(exist_ok=True)
    Path(args.out).write_text(report)
    print(report)
    print(f"\nSaved to {args.out}")


if __name__ == "__main__":
    main()
