from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import logging

import httpx

logger = logging.getLogger(__name__)


@dataclass
class OzonClient:
    client_id: str
    api_key: str
    base_url: str = "https://api-seller.ozon.ru"

    async def fetch_metrics(self, report_date: date) -> dict[str, int | float | str | None]:
        headers = {
            "Client-Id": self.client_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
        }
        requested_metrics = [
            "views",      # показы
            "clicks",     # клики/переходы
            "to_cart",    # добавление в корзину
            "orders",     # заказы
            "revenue",    # сумма заказов
            "avg_price",  # средний чек
            "adv_sum",    # рекламные расходы
        ]
        payload = {
            "date_from": report_date.isoformat(),
            "date_to": report_date.isoformat(),
            "dimension": ["sku"],
            "metrics": requested_metrics,
            "limit": 1000,
            "offset": 0,
        }

        metrics_response = await self._post("/v1/analytics/data", headers=headers, json=payload)
        totals = self._sum_metrics(metrics_response, requested_metrics)

        order_sum = totals.get("revenue")
        orders = totals.get("orders")
        avg_bill = totals.get("avg_price")
        if avg_bill is None and order_sum is not None and orders:
            avg_bill = order_sum / orders

        search_position = await self._fetch_search_position(headers=headers, report_date=report_date)

        return {
            "impressions": totals.get("views"),
            "clicks": totals.get("clicks"),
            "add_to_cart": totals.get("to_cart"),
            "orders": orders,
            "avg_bill": avg_bill,
            "order_sum": order_sum,
            "ad_spend": totals.get("adv_sum"),
            "search_position": search_position,
        }

    async def _fetch_search_position(self, headers: dict[str, str], report_date: date) -> str | None:
        # endpoint /v1/product/info/visibility недоступен на части аккаунтов (404).
        # Не роняем сбор отчёта, просто возвращаем н/д.
        payload = {"date_from": report_date.isoformat(), "date_to": report_date.isoformat(), "limit": 1, "offset": 0}
        try:
            data = await self._post("/v1/product/info/visibility", headers=headers, json=payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (403, 404):
                logger.info("Ozon search position endpoint is unavailable for current account: %s", exc.response.status_code)
                return None
            raise

        items = data.get("result", {}).get("items", [])
        if not items:
            return None

        first = items[0]
        position = first.get("position", {})
        search_pos = position.get("search")
        catalog_pos = position.get("category")
        if search_pos is None and catalog_pos is None:
            return None
        return f"search: {search_pos}, catalog: {catalog_pos}"

    async def _post(self, path: str, headers: dict[str, str], json: dict) -> dict:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:
            response = await client.post(path, headers=headers, json=json)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _sum_metrics(raw: dict, requested_metrics: list[str]) -> dict[str, float]:
        result = raw.get("result", {})

        # 1) часть ответов содержит totals напрямую
        totals_raw = result.get("totals")
        if isinstance(totals_raw, list):
            return OzonClient._sum_metrics_from_list(totals_raw, requested_metrics)

        # 2) классический массив data с metrics
        rows = result.get("data", [])
        metric_names = result.get("metrics") or requested_metrics
        totals: dict[str, float] = {}

        for row in rows:
            row_metrics = row.get("metrics", [])
            totals = OzonClient._merge_metric_values(totals, metric_names, row_metrics)

        return totals

    @staticmethod
    def _sum_metrics_from_list(values: list[object], metric_names: list[str]) -> dict[str, float]:
        totals: dict[str, float] = {}
        for name, value in zip(metric_names, values):
            try:
                totals[name] = float(value)
            except (TypeError, ValueError):
                continue
        return totals

    @staticmethod
    def _merge_metric_values(
        totals: dict[str, float],
        metric_names: list[str],
        row_metrics: list[object],
    ) -> dict[str, float]:
        for name, value in zip(metric_names, row_metrics):
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            totals[name] = totals.get(name, 0.0) + numeric
        return totals
