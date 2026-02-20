import asyncio
from datetime import date

from src.report_service import ReportService


class OzonOk:
    async def fetch_metrics(self, _: date):
        return {
            "impressions": 100,
            "clicks": 10,
            "add_to_cart": 2,
            "orders": 1,
            "avg_bill": 500,
            "order_sum": 500,
            "ad_spend": 50,
            "search_position": 12,
        }


class WbFail:
    async def fetch_metrics(self, _: date):
        raise RuntimeError("wb fail")


class OzonFail:
    async def fetch_metrics(self, _: date):
        raise RuntimeError("ozon fail")


class WbOk:
    async def fetch_metrics(self, _: date):
        return {
            "impressions_ads": 200,
            "clicks": 30,
            "add_to_cart": 5,
            "orders": 2,
            "avg_bill": 700,
            "order_sum": 1400,
            "ad_spend": 120,
        }


def test_report_keeps_ozon_when_wb_fails():
    service = ReportService(ozon=OzonOk(), wb=WbFail(), report_days_back=1)

    _, metrics = asyncio.run(service.build_daily_report())

    assert metrics.ozon_impressions == 100
    assert metrics.wb_impressions_ads is None


def test_report_keeps_wb_when_ozon_fails():
    service = ReportService(ozon=OzonFail(), wb=WbOk(), report_days_back=1)

    _, metrics = asyncio.run(service.build_daily_report())

    assert metrics.ozon_impressions is None
    assert metrics.wb_impressions_ads == 200
