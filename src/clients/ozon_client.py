from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import httpx


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
            "views",
            "clicks",
            "to_cart",
            "orders",
            "revenue",
            "avg_price",
            "adv_sum",
        ]

        payload = {
            "date_from": report_date.isoformat(),
            "date_to": report_date.isoformat(),
            "dimension": ["sku"],
            "metrics": requested_metrics,
            "limit": 1000,
            "offset": 0,
        }

        metrics_response = await self._post(
            "/v1/analytics/data",
            headers=headers,
            json=payload,
        )

        totals = self._sum_metrics(metrics_response, fallback_metric_names=requested_metrics)
        return {
            "impressions": totals.get("views"),
            "clicks": totals.get("clicks"),
            "add_to_cart": totals.get("to_cart"),
            "orders": totals.get("orders"),
            "avg_bill": totals.get("avg_price"),
            "order_sum": totals.get("revenue"),
            "ad_spend": totals.get("adv_sum"),
            # Убрали запрос к нестабильному endpoint видимости, чтобы избежать 404
            # и не ломать сбор основного ежедневного отчёта.
            "search_position": None,
        }

    async def _post(self, path: str, headers: dict[str, str], json: dict) -> dict:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:
            response = await client.post(path, headers=headers, json=json)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _sum_metrics(raw: dict, fallback_metric_names: list[str]) -> dict[str, float]:
        result = raw.get("result", {})
        rows = result.get("data", [])
        response_metric_names = OzonClient._extract_metric_names(result.get("metrics", []))
        default_metric_names = response_metric_names or fallback_metric_names
        totals: dict[str, float] = {}

        for row in rows:
            metric_values = row.get("metrics", [])
            metric_names = row.get("metric_names") or default_metric_names
            if len(metric_names) != len(metric_values):
                continue
            for name, value in zip(metric_names, metric_values):
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    continue
                totals[name] = totals.get(name, 0.0) + numeric

        if not totals:
            totals_values = result.get("totals", [])
            if len(totals_values) != len(default_metric_names):
                return totals
            for name, value in zip(default_metric_names, totals_values):
                try:
                    totals[name] = float(value)
                except (TypeError, ValueError):
                    continue

        return totals

    @staticmethod
    def _extract_metric_names(raw_metrics: list[object]) -> list[str]:
        names: list[str] = []
        for metric in raw_metrics:
            if isinstance(metric, str):
                normalized = OzonClient._normalize_metric_name(metric)
                if normalized is not None:
                    names.append(normalized)
                continue
            if isinstance(metric, dict):
                metric_name = metric.get("key") or metric.get("name") or metric.get("metric")
                normalized = OzonClient._normalize_metric_name(metric_name)
                if normalized is not None:
                    names.append(normalized)
        return names

    @staticmethod
    def _normalize_metric_name(metric_name: object) -> str | None:
        if not isinstance(metric_name, str):
            return None

        aliases = {
            "views": "views",
            "view": "views",
            "show": "views",
            "clicks": "clicks",
            "to_cart": "to_cart",
            "orders": "orders",
            "revenue": "revenue",
            "avg_price": "avg_price",
            "adv_sum": "adv_sum",
            "sum": "revenue",
            "sales_sum": "revenue",
        }

        key = metric_name.strip().lower()
        return aliases.get(key)
