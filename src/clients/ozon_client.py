from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import httpx

logger = logging.getLogger(__name__)


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

        impressions = self._pick_metric(analytics_totals, "hits_view", "views", "view", "show")
        clicks = self._pick_metric(analytics_totals, "session_view_pdp", "clicks")
        add_to_cart = self._pick_metric(
            analytics_totals,
            "hits_tocart_pdp",
            "to_cart",
            "hits_tocart",
        )
        orders = self._pick_metric(analytics_totals, "ordered_units", "orders")
        revenue = self._pick_metric(analytics_totals, "revenue", "sales_sum", "sum")
        search_position = self._pick_metric(analytics_totals, "position_category")

        legacy_totals: dict[str, float] = {}
        if all(value is None for value in (impressions, clicks, add_to_cart, orders, revenue, search_position)):
            logger.info("Ozon funnel metrics are empty; retrying with legacy analytics metrics")
            legacy_totals = await self._fetch_legacy_metrics(report_date)
            impressions = self._pick_metric(legacy_totals, "views", "view", "show")
            clicks = self._pick_metric(legacy_totals, "clicks")
            add_to_cart = self._pick_metric(legacy_totals, "to_cart", "hits_tocart")
            orders = self._pick_metric(legacy_totals, "orders", "ordered_units")
            revenue = self._pick_metric(legacy_totals, "revenue", "sales_sum", "sum")
            if search_position is None:
                search_position = self._pick_metric(legacy_totals, "position_category")

        avg_bill = None
        if orders is not None and revenue is not None and orders != 0:
            avg_bill = revenue / orders

        ad_spend = await self._fetch_ad_spend(report_date)
        if ad_spend is None:
            ad_spend = self._pick_metric(analytics_totals, "adv_sum")
            if ad_spend is None:
                ad_spend = self._pick_metric(legacy_totals, "adv_sum")

        return {
            "impressions": impressions,
            "clicks": clicks,
            "add_to_cart": add_to_cart,
            "orders": orders,
            "avg_bill": avg_bill,
            "order_sum": revenue,
            "ad_spend": ad_spend,
            "search_position": search_position,
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
        totals = self._sum_metrics(response, fallback_metric_names=payload["metrics"])
        if not totals:
            logger.warning("Ozon analytics response did not contain parsable metrics")
        return totals

    async def _fetch_legacy_metrics(self, report_date: date) -> dict[str, float]:
        payload = {
            "date_from": report_date.isoformat(),
            "date_to": report_date.isoformat(),
            "metrics": [
                "views",
                "clicks",
                "to_cart",
                "orders",
                "revenue",
                "avg_price",
                "adv_sum",
                "position_category",
            ],
            "dimension": ["sku"],
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
            row_value = OzonClient._extract_expense_value(row)
            if row_value is None:
                continue
            total += row_value
            found = True

        return total if found else None

    @staticmethod
    def _extract_expense_value(row: dict[str, object]) -> float | None:
        candidate_keys = (
            "expense",
            "spent",
            "sum",
            "cost",
            "expense_value",
            "expensevalue",
            "money_spent",
            "moneyspent",
        )

        for key in candidate_keys:
            if key in row:
                try:
                    return float(row[key])
                except (TypeError, ValueError):
                    pass

        for value in row.values():
            if not isinstance(value, dict):
                continue
            for nested_key in candidate_keys:
                if nested_key in value:
                    try:
                        return float(value[nested_key])
                    except (TypeError, ValueError):
                        pass

        return None

    @staticmethod
    def _sum_metrics(raw: dict, fallback_metric_names: list[str]) -> dict[str, float]:
        if not isinstance(raw, dict):
            return {}

        result = raw.get("result") if isinstance(raw.get("result"), dict) else raw
        rows = result.get("data", []) if isinstance(result, dict) else []
        response_metric_names = OzonClient._extract_metric_names(result.get("metrics", []))
        default_metric_names = response_metric_names or fallback_metric_names
        totals: dict[str, float] = {}

        for row in rows:
            if not isinstance(row, dict):
                continue
            row_metrics = row.get("metrics", [])
            if isinstance(row_metrics, dict):
                for name, value in row_metrics.items():
                    OzonClient._add_metric(totals, name, value)
                continue

            if row_metrics and isinstance(row_metrics[0], dict):
                for metric in row_metrics:
                    metric_name = metric.get("key") or metric.get("name") or metric.get("metric")
                    metric_value = metric.get("value")
                    OzonClient._add_metric(totals, metric_name, metric_value)
                continue

            metric_names = row.get("metric_names") or default_metric_names
            if len(metric_names) != len(row_metrics):
                continue
            for name, value in zip(metric_names, row_metrics):
                OzonClient._add_metric(totals, name, value)

        if totals:
            return totals

        totals_values = result.get("totals", []) if isinstance(result, dict) else []
        if isinstance(totals_values, dict):
            for name, value in totals_values.items():
                OzonClient._add_metric(totals, name, value)
            return totals

        if totals_values and isinstance(totals_values[0], dict):
            for metric in totals_values:
                metric_name = metric.get("key") or metric.get("name") or metric.get("metric")
                metric_value = metric.get("value")
                OzonClient._add_metric(totals, metric_name, metric_value)
            return totals

        if len(totals_values) != len(default_metric_names):
            return totals
        for name, value in zip(default_metric_names, totals_values):
            OzonClient._add_metric(totals, name, value)

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

    @staticmethod
    def _add_metric(target: dict[str, float], name: object, value: object) -> None:
        if not isinstance(name, str):
            return

        normalized_name = name.strip().lower()
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return
        target[normalized_name] = target.get(normalized_name, 0.0) + numeric

    @staticmethod
    def _pick_metric(totals: dict[str, float], *names: str) -> float | None:
        for name in names:
            value = totals.get(name)
            if value is not None:
                return value
        return None
