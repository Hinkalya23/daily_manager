from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import logging

import httpx

logger = logging.getLogger(__name__)


@dataclass
class WildberriesClient:
    api_token: str
    stats_url: str = "https://statistics-api.wildberries.ru"
    adv_url: str = "https://advert-api.wildberries.ru"

    async def fetch_metrics(self, report_date: date) -> dict[str, int | float | None]:
        headers = {"Authorization": self.api_token}

        orders = await self._get_stats(
            "/api/v1/supplier/orders",
            headers=headers,
            params={"dateFrom": report_date.isoformat(), "flag": 0},
        )
        adv_metrics = await self._fetch_adv_metrics(report_date, headers)

        orders_count = len(orders)
        order_sum = sum(float(item.get("totalPrice", 0)) for item in orders)
        avg_bill = (order_sum / orders_count) if orders_count else None

        return {
            "impressions_ads": adv_metrics.get("views"),
            "clicks": adv_metrics.get("clicks"),
            # В статистических endpoint WB нет прямой метрики add-to-cart.
            # Чтобы не искажать отчёт, возвращаем None вместо суррогатных значений.
            "add_to_cart": None,
            "orders": orders_count,
            "avg_bill": avg_bill,
            "order_sum": order_sum,
            "ad_spend": adv_metrics.get("sum"),
        }

    async def _fetch_adv_metrics(self, report_date: date, headers: dict[str, str]) -> dict[str, float | None]:
        async with httpx.AsyncClient(base_url=self.adv_url, timeout=30.0) as client:
            campaigns_resp = await client.get("/adv/v1/promotion/count", headers=headers)
            if campaigns_resp.status_code >= 400:
                logger.warning("WB adv campaign list request failed: %s", campaigns_resp.status_code)
                return {"views": None, "clicks": None, "sum": None}

            campaign_ids = self._extract_campaign_ids(campaigns_resp.json())
            if not campaign_ids:
                return {"views": None, "clicks": None, "sum": None}

            stats = await self._request_fullstats(client, headers, campaign_ids, report_date)
            if stats is None:
                logger.warning("WB adv fullstats request failed for all supported payload formats")
                return {"views": None, "clicks": None, "sum": None}

            return self._sum_adv_stats(stats)

    async def _request_fullstats(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        campaign_ids: list[int],
        report_date: date,
    ) -> list[dict] | None:
        date_iso = report_date.isoformat()
        payload_variants: list[list[dict[str, object]]] = [
            [{"id": cid, "dates": [date_iso]} for cid in campaign_ids],
            [{"id": cid, "from": date_iso, "to": date_iso} for cid in campaign_ids],
        ]

        for payload in payload_variants:
            response = await client.post("/adv/v2/fullstats", headers=headers, json=payload)
            if response.status_code < 400:
                body = response.json()
                if isinstance(body, list):
                    return body
            logger.info("WB fullstats payload variant failed: status=%s", response.status_code)

        return None

    @staticmethod
    def _sum_adv_stats(stats: list[dict]) -> dict[str, float | None]:
        total_views = 0.0
        total_clicks = 0.0
        total_sum = 0.0

        for campaign_stat in stats:
            for day in campaign_stat.get("days", []):
                total_views += float(day.get("views", 0))
                total_clicks += float(day.get("clicks", 0))
                total_sum += float(day.get("sum", 0))

        return {
            "views": total_views if total_views else None,
            "clicks": total_clicks if total_clicks else None,
            "sum": total_sum if total_sum else None,
        }

    @staticmethod
    def _extract_campaign_ids(raw: dict) -> list[int]:
        campaign_ids: list[int] = []
        for state in raw.get("adverts", []):
            for campaign in state.get("advert_list", []):
                campaign_id = campaign.get("advertId")
                if isinstance(campaign_id, int):
                    campaign_ids.append(campaign_id)
        return campaign_ids

    async def _get_stats(self, path: str, headers: dict[str, str], params: dict[str, str | int]) -> list[dict]:
        async with httpx.AsyncClient(base_url=self.stats_url, timeout=30.0) as client:
            response = await client.get(path, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, list) else []
