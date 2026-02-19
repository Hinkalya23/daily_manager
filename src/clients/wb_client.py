from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import asyncio

import httpx


@dataclass
class WildberriesClient:
    api_token: str
    stats_url: str = "https://statistics-api.wildberries.ru"
    adv_url: str = "https://advert-api.wildberries.ru"
    adv_max_retries: int = 3
    adv_retry_delay_seconds: float = 1.0

    async def fetch_metrics(self, report_date: date) -> dict[str, int | float | None]:
        headers = {"Authorization": self.api_token}

        sales = await self._get_stats(
            "/api/v1/supplier/sales",
            headers=headers,
            params={"dateFrom": report_date.isoformat(), "flag": 0},
        )
        orders = await self._get_stats(
            "/api/v1/supplier/orders",
            headers=headers,
            params={"dateFrom": report_date.isoformat(), "flag": 0},
        )

        adv_metrics = await self._fetch_adv_metrics(report_date, headers)

        orders_count = len(orders)
        order_sum = sum(float(item.get("totalPrice", 0)) for item in orders)
        avg_bill = (order_sum / orders_count) if orders_count else None

        add_to_cart = sum(int(item.get("isCancel", 0) == 0) for item in orders)
        clicks = adv_metrics.get("clicks")
        impressions = adv_metrics.get("views")
        ad_spend = adv_metrics.get("sum")

        return {
            "impressions_ads": impressions,
            "clicks": clicks,
            "add_to_cart": add_to_cart,
            "orders": orders_count,
            "avg_bill": avg_bill,
            "order_sum": order_sum,
            "ad_spend": ad_spend,
        }

    async def _fetch_adv_metrics(self, report_date: date, headers: dict[str, str]) -> dict[str, float | None]:
        # В WB рекламная статистика запрашивается через список кампаний + детализацию.
        # Здесь базовая реализация: если рекламных кампаний нет/нет доступа — возвращаем None.
        async with httpx.AsyncClient(base_url=self.adv_url, timeout=30.0) as client:
            campaigns_resp = await client.get("/adv/v1/promotion/count", headers=headers)
            if campaigns_resp.status_code >= 400:
                return {"views": None, "clicks": None, "sum": None}

            campaigns = campaigns_resp.json().get("adverts", [])
            campaign_ids: list[int] = []
            for state in campaigns:
                for campaign in state.get("advert_list", []):
                    advert_id = campaign.get("advertId")
                    if isinstance(advert_id, int):
                        campaign_ids.append(advert_id)

            if not campaign_ids:
                return {"views": None, "clicks": None, "sum": None}

            payload = [{"id": cid, "dates": [report_date.isoformat()]} for cid in campaign_ids]
            stats_resp = await self._post_adv_fullstats(client, headers, payload)

            # Иногда WB возвращает 400, если среди кампаний есть некорректная/архивная.
            # В таком случае пробуем собрать статистику по одной кампании,
            # чтобы не терять данные полностью.
            if stats_resp.status_code >= 400:
                return await self._fetch_adv_metrics_fallback(client, headers, report_date, campaign_ids)

            return self._sum_adv_stats(stats_resp.json())

    async def _fetch_adv_metrics_fallback(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        report_date: date,
        campaign_ids: list[int],
    ) -> dict[str, float | None]:
        total_views = 0.0
        total_clicks = 0.0
        total_sum = 0.0
        has_data = False

        for campaign_id in campaign_ids:
            payload = [{"id": campaign_id, "dates": [report_date.isoformat()]}]
            stats_resp = await self._post_adv_fullstats(client, headers, payload)
            if stats_resp.status_code == 429:
                break
            if stats_resp.status_code >= 400:
                continue

            raw_stats = stats_resp.json()
            if not isinstance(raw_stats, list):
                continue

            has_data = True
            metrics = self._sum_adv_stats(raw_stats)
            total_views += float(metrics.get("views") or 0)
            total_clicks += float(metrics.get("clicks") or 0)
            total_sum += float(metrics.get("sum") or 0)

        if not has_data:
            return {"views": None, "clicks": None, "sum": None}

        return {"views": total_views, "clicks": total_clicks, "sum": total_sum}

    async def _post_adv_fullstats(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        payload: list[dict[str, int | list[str]]],
    ) -> httpx.Response:
        for attempt in range(self.adv_max_retries):
            response = await client.post("/adv/v2/fullstats", headers=headers, json=payload)
            if response.status_code != 429:
                return response

            if attempt < self.adv_max_retries - 1:
                await asyncio.sleep(self.adv_retry_delay_seconds * (attempt + 1))

        return response

    @staticmethod
    def _sum_adv_stats(raw_stats: object) -> dict[str, float]:
        if not isinstance(raw_stats, list):
            return {"views": 0.0, "clicks": 0.0, "sum": 0.0}

        total_views = 0.0
        total_clicks = 0.0
        total_sum = 0.0
        for campaign_stat in raw_stats:
            if not isinstance(campaign_stat, dict):
                continue
            for day in campaign_stat.get("days", []):
                if not isinstance(day, dict):
                    continue
                total_views += float(day.get("views", 0))
                total_clicks += float(day.get("clicks", 0))
                total_sum += float(day.get("sum", 0))
        return {"views": total_views, "clicks": total_clicks, "sum": total_sum}

    async def _get_stats(self, path: str, headers: dict[str, str], params: dict[str, str | int]) -> list[dict]:
        async with httpx.AsyncClient(base_url=self.stats_url, timeout=30.0) as client:
            response = await client.get(path, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, list) else []
