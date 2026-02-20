from src.clients.ozon_client import OzonClient


def test_sum_metrics_with_scalar_rows():
    raw = {
        "result": {
            "metrics": ["session_view_pdp", "hits_view", "ordered_units", "revenue"],
            "data": [{"metrics": [12, 100, 3, 1500]}],
        }
    }

    totals = OzonClient._sum_metrics(raw, fallback_metric_names=[])

    assert totals["session_view_pdp"] == 12
    assert totals["hits_view"] == 100
    assert totals["ordered_units"] == 3
    assert totals["revenue"] == 1500


def test_sum_metrics_with_object_totals():
    raw = {
        "result": {
            "totals": [
                {"key": "session_view_pdp", "value": 20},
                {"key": "hits_view", "value": 120},
                {"key": "ordered_units", "value": 4},
                {"key": "revenue", "value": 2000},
            ]
        }
    }

    totals = OzonClient._sum_metrics(raw, fallback_metric_names=[])

    assert totals["session_view_pdp"] == 20
    assert totals["hits_view"] == 120
    assert totals["ordered_units"] == 4
    assert totals["revenue"] == 2000


def test_sum_expense_with_nested_cost_key():
    raw = {
        "rows": [
            {"campaignId": 1, "stats": {"cost": 120.5}},
            {"campaignId": 2, "stats": {"cost": 79.5}},
        ]
    }

    total = OzonClient._sum_expense(raw)

    assert total == 200.0
