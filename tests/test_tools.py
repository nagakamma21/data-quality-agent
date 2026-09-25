from dq_agent import tools

def setup_module():
    tools.load_dataset("sample_data/orders.csv")

def test_schema():
    assert tools.load_dataset("sample_data/orders.csv")["rows"] == 507

def test_negatives_and_outliers():
    r = tools.detect_anomalies("amount")
    assert r["negatives"] == 6 and r["outliers"] >= 4

def test_future_dates():
    assert tools.detect_anomalies("order_date")["future_dates"] == 5

def test_duplicates():
    assert tools.check_duplicates(["order_id"])["duplicate_rows"] == 14

def test_email():
    assert tools.validate_pattern("email")["invalid"] == 4
