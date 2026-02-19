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

        # Endpoint analytics/data агрегирует метрики по товарам. При необходимости
        # можно скорректировать dimensions/metrics под вашу категорию и витрину.
        requested_metrics = [
            "views",  # показы
            "clicks",  # клики/переходы
            "to_cart",  # добавление в корзину
            "orders",  # заказы
            "revenue",  # сумма заказов
            "avg_price",  # средний чек
            "adv_sum",  # рекламные расходы
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

        # Для позиции в поиске используем endpoint по видимости/поиску.
        # В некоторых кабинетах требуется отдельный метод/доступ.
        search_position = await self._fetch_search_position(headers=headers, report_date=report_date)

        totals = self._sum_metrics(metrics_response, fallback_metric_names=requested_metrics)
        return {
            "impressions": totals.get("views"),
            "clicks": totals.get("clicks"),
            "add_to_cart": totals.get("to_cart"),
            "orders": totals.get("orders"),
            "avg_bill": totals.get("avg_price"),
            "order_sum": totals.get("revenue"),
            "ad_spend": totals.get("adv_sum"),
            "search_position": search_position,
        }

    async def _fetch_search_position(self, headers: dict[str, str], report_date: date) -> str | None:
        payload = {
            "date_from": report_date.isoformat(),
            "date_to": report_date.isoformat(),
            "limit": 1,
            "offset": 0,
        }
        try:
            data = await self._post("/v1/product/info/visibility", headers=headers, json=payload)
            items = data.get("result", {}).get("items", [])
            if not items:
                return None
            first = items[0]
            search_pos = first.get("position", {}).get("search")
            catalog_pos = first.get("position", {}).get("category")
            return f"search: {search_pos}, catalog: {catalog_pos}"
        except httpx.HTTPError:
            return None

    async def _post(self, path: str, headers: dict[str, str], json: dict) -> dict:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:
            response = await client.post(path, headers=headers, json=json)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _sum_metrics(raw: dict, fallback_metric_names: list[str]) -> dict[str, float]:
        result = raw.get("result", {})
        rows = result.get("data", [])
        default_metric_names = OzonClient._extract_metric_names(result.get("metrics", [])) or fallback_metric_names
        totals: dict[str, float] = {}

        for row in rows:
            metric_values = row.get("metrics", [])
            metric_names = row.get("metric_names", default_metric_names)
            for name, value in zip(metric_names, metric_values):
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    continue
                totals[name] = totals.get(name, 0.0) + numeric

        # В некоторых ответах OZON агрегированные значения могут приходить
        # в result.totals, даже если result.data пустой.
        if not totals:
            totals_values = result.get("totals", [])
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
                metric_name = metric.get("key") or metric.get("name")
                if isinstance(metric_name, str):
                    names.append(metric_name)
        return names
