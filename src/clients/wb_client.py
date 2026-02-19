from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date

import httpx


@dataclass
class WildberriesClient:
    api_token: str
    brand_names: tuple[str, ...] = ()
    subject_ids: tuple[int, ...] = ()
    tag_ids: tuple[int, ...] = ()
    stats_url: str = "https://statistics-api.wildberries.ru"
    adv_url: str = "https://advert-api.wildberries.ru"
    analytics_url: str = "https://seller-analytics-api.wildberries.ru"
    adv_max_retries: int = 3
    adv_retry_delay_seconds: float = 20.0
    adv_batch_size: int = 50

    async def fetch_metrics(self, report_date: date) -> dict[str, int | float | None]:
        headers = {"Authorization": self.api_token}

        async with httpx.AsyncClient(timeout=30.0) as client:
            campaign_ids = await self._get_campaign_ids(client, headers)

            adv_views = await self._get_adv_views(client, headers, report_date, campaign_ids)
            adv_spend = await self._get_adv_spend(client, headers, report_date)

            funnel_stats = await self._get_sales_funnel_metrics(client, headers, report_date)

        orders_count = int(funnel_stats.get("orders") or 0)
        order_sum = float(funnel_stats.get("order_sum") or 0)
        avg_bill = (order_sum / orders_count) if orders_count else None

        return {
            "impressions_ads": adv_views,
            "clicks": funnel_stats.get("clicks"),
            "add_to_cart": funnel_stats.get("add_to_cart"),
            "orders": orders_count,
            "avg_bill": avg_bill,
            "order_sum": order_sum,
            "ad_spend": adv_spend,
        }

    async def _get_campaign_ids(self, client: httpx.AsyncClient, headers: dict[str, str]) -> list[int]:
        response = await client.get(f"{self.adv_url}/adv/v1/promotion/count", headers=headers)
        if response.status_code >= 400:
            return []

        payload = response.json()
        adverts = payload.get("adverts", []) if isinstance(payload, dict) else []
        campaign_ids: list[int] = []
        for state in adverts:
            if not isinstance(state, dict):
                continue
            for campaign in state.get("advert_list", []):
                if not isinstance(campaign, dict):
                    continue
                advert_id = campaign.get("advertId")
                if isinstance(advert_id, int):
                    campaign_ids.append(advert_id)
        return campaign_ids

    async def _get_adv_views(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        report_date: date,
        campaign_ids: list[int],
    ) -> float | None:
        if not campaign_ids:
            return None

        total_views = 0.0
        has_data = False
        for idx in range(0, len(campaign_ids), self.adv_batch_size):
            batch = campaign_ids[idx : idx + self.adv_batch_size]
            params = {
                "ids": ",".join(str(campaign_id) for campaign_id in batch),
                "beginDate": report_date.isoformat(),
                "endDate": report_date.isoformat(),
            }
            response = await self._get_with_retry(client, f"{self.adv_url}/adv/v3/fullstats", headers, params)
            if response is None or response.status_code >= 400:
                continue

            raw_stats = response.json()
            if not isinstance(raw_stats, list):
                continue

            has_data = True
            for row in raw_stats:
                if not isinstance(row, dict):
                    continue
                total_views += float(row.get("views", 0) or 0)

        if not has_data:
            return None
        return total_views

    async def _get_adv_spend(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        report_date: date,
    ) -> float | None:
        params = {"from": report_date.isoformat(), "to": report_date.isoformat()}
        response = await self._get_with_retry(client, f"{self.adv_url}/adv/v1/upd", headers, params)
        if response is None or response.status_code >= 400:
            return None

        raw_stats = response.json()
        if not isinstance(raw_stats, list):
            return None

        return sum(float(row.get("updSum", 0) or 0) for row in raw_stats if isinstance(row, dict))

    async def _get_sales_funnel_metrics(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        report_date: date,
    ) -> dict[str, float | None]:
        payload = {
            "selectedPeriod": {"start": report_date.isoformat(), "end": report_date.isoformat()},
            "brandNames": self._resolve_brand_names(),
            "subjectIds": self._resolve_ids(self.subject_ids),
            "tagIds": self._resolve_ids(self.tag_ids),
            "skipDeletedNm": True,
            "aggregationLevel": "day",
        }
        response = await self._post_with_retry(
            client,
            f"{self.analytics_url}/api/analytics/v3/sales-funnel/grouped/history",
            headers,
            payload,
        )
        if response is None or response.status_code >= 400:
            return {
                "clicks": None,
                "add_to_cart": None,
                "orders": None,
                "order_sum": None,
            }

        raw_data = response.json()
        if not isinstance(raw_data, list):
            return {
                "clicks": None,
                "add_to_cart": None,
                "orders": None,
                "order_sum": None,
            }

        metrics = self._parse_sales_funnel_rows(raw_data)
        if metrics is None:
            return {
                "clicks": None,
                "add_to_cart": None,
                "orders": None,
                "order_sum": None,
            }

        return metrics

    def _resolve_brand_names(self) -> list[str]:
        return list(dict.fromkeys(name.strip() for name in self.brand_names if name.strip()))

    @staticmethod
    def _resolve_ids(values: tuple[int, ...]) -> list[int]:
        return list(dict.fromkeys(values))

    def _parse_sales_funnel_rows(self, raw_data: list[object]) -> dict[str, float] | None:
        clicks = 0.0
        add_to_cart = 0.0
        orders = 0.0
        order_sum = 0.0
        has_data = False

        for product_row in raw_data:
            if not isinstance(product_row, dict):
                continue
            history = product_row.get("history", [])
            if not isinstance(history, list):
                continue
            for day_row in history:
                if not isinstance(day_row, dict):
                    continue
                has_data = True
                clicks += self._extract_number(day_row, "openCardCount", "openCard", "clicks")
                add_to_cart += self._extract_number(day_row, "addToCartCount", "addToCart", "atbs")
                orders += self._extract_number(day_row, "ordersCount", "orders", "ordersSumCount")
                order_sum += self._extract_number(day_row, "ordersSumRub", "ordersSum", "ordersAmount")

        if not has_data:
            return None

        return {
            "clicks": clicks,
            "add_to_cart": add_to_cart,
            "orders": orders,
            "order_sum": order_sum,
        }

    async def _get_with_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        params: dict[str, str],
    ) -> httpx.Response | None:
        response: httpx.Response | None = None
        for attempt in range(self.adv_max_retries):
            response = await client.get(url, headers=headers, params=params)
            if response.status_code != 429:
                return response

            if attempt < self.adv_max_retries - 1:
                await asyncio.sleep(self.adv_retry_delay_seconds)
        return response

    async def _post_with_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
    ) -> httpx.Response | None:
        response: httpx.Response | None = None
        for attempt in range(self.adv_max_retries):
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code != 429:
                return response

            if attempt < self.adv_max_retries - 1:
                await asyncio.sleep(self.adv_retry_delay_seconds)
        return response

    @staticmethod
    def _extract_number(source: dict[str, object], *keys: str) -> float:
        for key in keys:
            value = source.get(key)
            if isinstance(value, dict):
                nested = WildberriesClient._extract_number(value, "value", "count", "total")
                if nested:
                    return nested
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return 0.0
