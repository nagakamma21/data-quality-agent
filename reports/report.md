# Data Quality Report — `orders.csv`

**Date:** 2026-09-22  **Rows:** 507  **Columns:** 7

## Health score: 38 / 100

## Findings

| Severity | Column | Issue | Count |
|---|---|---|---|
| HIGH | `order_date` | dates in the future | 5 |
| HIGH | `amount` | missing values | 5.13% |
| HIGH | `amount` | negative values | 6 |
| HIGH | `email` | invalid email format | 4 |
| HIGH | `*` | exact duplicate rows | 14 |
| HIGH | `order_id` | duplicate primary key | 14 |
| MEDIUM | `region` | missing values | 0.2% |
| MEDIUM | `amount` | statistical outliers (IQR x3) | 7 |
| MEDIUM | `email` | missing values | 0.79% |
| LOW | `region` | leading/trailing whitespace | 8 |
| LOW | `region` | inconsistent casing | yes |

## Recommended fixes

- Reject or quarantine negative amounts at ingestion; likely refund rows mis-loaded.
- Deduplicate on `order_id` before loading to the warehouse.
- Normalize categorical columns (trim + title-case) and enforce a controlled vocabulary.
- Add an `order_date <= today` constraint; future dates indicate a source system bug.
- Validate emails at capture; route invalid records to a review queue.

Validation rules written to `reports/validation_rules.json` (10 rules).