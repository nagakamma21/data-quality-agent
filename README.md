# Data Quality Agent

An LLM-driven agent that audits a dataset the way a senior data engineer would: it decides which checks to run, executes them through deterministic tools, and produces a scored Markdown report plus a machine-readable validation ruleset.

**Why an agent, not a script?** A script runs the same checks on every table. The agent reads the schema first, picks the checks that fit (email validation only on email-like columns, future-date checks only on dates, duplicate checks on the most plausible key), and explains its findings in plain language. Every number in the report comes from a tool call, never from the model.

## Architecture

```
 dataset.csv ──► Agent loop (Claude tool use)
                    │  decides which check to run next
                    ▼
              ┌───────────────────────────────┐
              │ tools.py  (deterministic)      │
              │  load_dataset   profile_columns│
              │  detect_anomalies  check_dups  │
              │  validate_pattern  write_rules │
              └───────────────────────────────┘
                    │  JSON results
                    ▼
        reports/report.md  +  reports/validation_rules.json
```

## Quick start

```bash
pip install -r requirements.txt

# No API key needed - scripted planner, same tool chain
python -m dq_agent.agent sample_data/orders.csv --offline

# Full agent: the model plans the audit and writes the narrative
export ANTHROPIC_API_KEY=...
python -m dq_agent.agent sample_data/orders.csv
```

## Sample result

Run against `sample_data/orders.csv` (507 rows, 7 columns, with defects deliberately injected):

| Severity | Column | Issue | Count |
|---|---|---|---|
| HIGH | `order_date` | dates in the future | 5 |
| HIGH | `amount` | negative values | 6 |
| HIGH | `amount` | missing values | 5.13% |
| HIGH | `email` | invalid email format | 4 |
| HIGH | `order_id` | duplicate primary key | 14 |
| MEDIUM | `amount` | statistical outliers (IQR x3) | 7 |
| LOW | `region` | whitespace / inconsistent casing | 8 |

Health score: **38 / 100**. All injected defects were recovered; the generated `validation_rules.json` (10 rules) can gate a CI pipeline or be translated into Great Expectations / dbt tests.

## Design decisions

- **Tools are pure and testable.** `tests/` asserts each check independently of the LLM (`pytest`).
- **Offline mode** mirrors the tool sequence an LLM would choose, so the pipeline is demoable without credentials and cheap to run in CI.
- **Rules as output, not just findings.** The agent's job ends with something a pipeline can enforce.

## Roadmap

- Databricks / Snowflake connectors (Spark DataFrame profiling)
- Emit dbt `schema.yml` tests directly from the ruleset
- Trend the health score across runs and alert on regression

## Author

Naga Kamma — BI / AI-ML engineer. Formerly Agentic AI Lead on a COBOL-to-Java modernization program.
