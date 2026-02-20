from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import httpx


@dataclass
class OzonClient:
    client_id: str
    api_key: str
    performance_client_id: str | None = None
    performance_client_secret: str | None = None
    seller_base_url: str = "https://api-seller.ozon.ru"
    performance_base_url: str = "https://api-performance.ozon.ru"

    async def fetch_metrics(self, report_date: date) -> dict[str, int | float | str | None]:
        analytics_totals = await self._fetch_sales_funnel_metrics(report_date)
        orders = analytics_totals.get("ordered_units")
        revenue = analytics_totals.get("revenue")
        avg_bill = None
        if orders and revenue is not None:
            avg_bill = revenue / orders

        return {
            "impressions": analytics_totals.get("hits_view"),
            "clicks": analytics_totals.get("session_view_pdp"),
            "add_to_cart": analytics_totals.get("hits_tocart_pdp"),
            "orders": orders,
            "avg_bill": avg_bill,
            "order_sum": revenue,
            "ad_spend": await self._fetch_ad_spend(report_date),
            "search_position": analytics_totals.get("position_category"),
        }

    async def _fetch_sales_funnel_metrics(self, report_date: date) -> dict[str, float]:
        payload = {
            "date_from": report_date.isoformat(),
            "date_to": report_date.isoformat(),
            "metrics": [
                "session_view_pdp",
                "hits_view",
                "position_category",
                "conv_tocart_pdp",
                "hits_tocart_pdp",
                "ordered_units",
                "cancellations",
                "returns",
                "revenue",
            ],
            "dimension": ["day"],
            "filters": [],
            "sort": [],
            "limit": 1000,
            "offset": 0,
        }
        response = await self._seller_post("/v1/analytics/data", json=payload)
        return self._sum_metrics(response, fallback_metric_names=payload["metrics"])

    async def _fetch_ad_spend(self, report_date: date) -> float | None:
        if not self.performance_client_id or not self.performance_client_secret:
            return None

        token = await self._get_performance_token()
        query = {
            "dateFrom": report_date.isoformat(),
            "dateTo": report_date.isoformat(),
        }
        try:
            response = await self._performance_get(
                "/api/client/statistics/expense/json",
                headers={"Authorization": f"Bearer {token}"},
                params=query,
            )
        except httpx.HTTPError:
            return None

        return self._sum_expense(response)

    async def _get_performance_token(self) -> str:
        payload = {
            "client_id": self.performance_client_id,
            "client_secret": self.performance_client_secret,
            "grant_type": "client_credentials",
        }
        response = await self._performance_post("/api/client/token", json=payload)
        access_token = response.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("Performance API returned empty access_token")
        return access_token

    async def _seller_post(self, path: str, json: dict) -> dict:
        headers = {
            "Client-Id": self.client_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(base_url=self.seller_base_url, timeout=30.0) as client:
            response = await client.post(path, headers=headers, json=json)
            response.raise_for_status()
            return response.json()

    async def _performance_post(self, path: str, json: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        async with httpx.AsyncClient(base_url=self.performance_base_url, timeout=30.0) as client:
            response = await client.post(path, headers=headers, json=json)
            response.raise_for_status()
            return response.json()

    async def _performance_get(self, path: str, headers: dict[str, str], params: dict) -> dict:
        async with httpx.AsyncClient(base_url=self.performance_base_url, timeout=30.0) as client:
            response = await client.get(path, headers=headers, params=params)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _sum_expense(raw: dict) -> float | None:
        if isinstance(raw, list):
            rows = raw
        else:
            rows = raw.get("rows") or raw.get("result") or []

        total = 0.0
        found = False
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in ("expense", "spent", "sum"):
                value = row.get(key)
                if value is None:
                    continue
                try:
                    total += float(value)
                    found = True
                    break
                except (TypeError, ValueError):
                    continue

        return total if found else None

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
                names.append(metric)
                continue
            if isinstance(metric, dict):
                metric_name = metric.get("key") or metric.get("name") or metric.get("metric")
                if isinstance(metric_name, str):
                    names.append(metric_name)
        return names
