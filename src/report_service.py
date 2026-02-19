from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from src.clients.ozon_client import OzonClient
from src.clients.wb_client import WildberriesClient
from src.metrics import DailyMetrics


@dataclass
class ReportService:
    ozon: OzonClient
    wb: WildberriesClient
    report_days_back: int = 1

    async def build_daily_report(self) -> tuple[str, DailyMetrics]:
        report_date = date.today() - timedelta(days=self.report_days_back)

        ozon_data = await self.ozon.fetch_metrics(report_date)
        wb_data = await self.wb.fetch_metrics(report_date)

        report = DailyMetrics(
            ozon_impressions=_to_int(ozon_data.get("impressions")),
            wb_impressions_ads=_to_int(wb_data.get("impressions_ads")),
            ozon_clicks=_to_int(ozon_data.get("clicks")),
            wb_clicks=_to_int(wb_data.get("clicks")),
            ozon_add_to_cart=_to_int(ozon_data.get("add_to_cart")),
            wb_add_to_cart=_to_int(wb_data.get("add_to_cart")),
            ozon_orders=_to_int(ozon_data.get("orders")),
            wb_orders=_to_int(wb_data.get("orders")),
            ozon_avg_bill=_to_float(ozon_data.get("avg_bill")),
            wb_avg_bill=_to_float(wb_data.get("avg_bill")),
            ozon_order_sum=_to_float(ozon_data.get("order_sum")),
            wb_order_sum=_to_float(wb_data.get("order_sum")),
            ozon_ad_spend=_to_float(ozon_data.get("ad_spend")),
            wb_ad_spend=_to_float(wb_data.get("ad_spend")),
            ozon_search_position=(
                str(ozon_data.get("search_position"))
                if ozon_data.get("search_position") is not None
                else None
            ),
        )

        return report_date.isoformat(), report


def _to_int(value: object | None) -> int | None:
    if value is None:
        return None
    return int(float(value))


def _to_float(value: object | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)
