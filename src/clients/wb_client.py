from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import httpx


@dataclass
class WildberriesClient:
    api_token: str
    stats_url: str = "https://statistics-api.wildberries.ru"
    adv_url: str = "https://advert-api.wildberries.ru"

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
                    campaign_ids.append(campaign.get("advertId"))

            if not campaign_ids:
                return {"views": None, "clicks": None, "sum": None}

            payload = [{"id": cid, "dates": [report_date.isoformat()]} for cid in campaign_ids if cid]
            stats_resp = await client.post("/adv/v2/fullstats", headers=headers, json=payload)
            if stats_resp.status_code >= 400:
                return {"views": None, "clicks": None, "sum": None}

            total_views = 0.0
            total_clicks = 0.0
            total_sum = 0.0
            for campaign_stat in stats_resp.json():
                for day in campaign_stat.get("days", []):
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
