from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date

import httpx


@dataclass
class WildberriesClient:
    api_token: str
    nm_ids: tuple[int, ...] = ()
    stats_url: str = "https://statistics-api.wildberries.ru"
    adv_url: str = "https://advert-api.wildberries.ru"
    analytics_url: str = "https://seller-analytics-api.wildberries.ru"
    adv_max_retries: int = 3
    adv_retry_delay_seconds: float = 20.0
    adv_batch_size: int = 50
    funnel_page_limit: int = 1000

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
        nm_ids = await self._resolve_nm_ids(client, headers, report_date)

        clicks = 0.0
        add_to_cart = 0.0
        orders = 0.0
        order_sum = 0.0
        has_data = False

        offset = 0
        while True:
            payload = {
                "selectedPeriod": {"start": report_date.isoformat(), "end": report_date.isoformat()},
                "pastPeriod": {"start": report_date.isoformat(), "end": report_date.isoformat()},
                "nmIds": nm_ids,
                "brandNames": [],
                "subjectIds": [],
                "tagIds": [],
                "skipDeletedNm": True,
                "limit": self.funnel_page_limit,
                "offset": offset,
            }
            response = await self._post_with_retry(
                client,
                f"{self.analytics_url}/api/analytics/v3/sales-funnel/products",
                headers,
                payload,
            )
            if response is None or response.status_code >= 400:
                break

            raw_data = response.json()
            products = self._extract_products(raw_data)
            if products is None:
                break

            if not products:
                if offset == 0:
                    return {
                        "clicks": None,
                        "add_to_cart": None,
                        "orders": None,
                        "order_sum": None,
                    }
                break

            for product_row in products:
                if not isinstance(product_row, dict):
                    continue
                current_period = self._pick_current_period_row(product_row)
                if current_period is None:
                    current_period = product_row

                has_data = True
                clicks += self._extract_number(current_period, "openCard", "openCardCount", "clicks")
                add_to_cart += self._extract_number(current_period, "addToCart", "addToCartCount", "atbs")
                orders += self._extract_number(current_period, "orders", "ordersCount", "ordersSumCount")
                order_sum += self._extract_number(current_period, "ordersSumRub", "ordersSum", "ordersAmount")

            if len(products) < self.funnel_page_limit:
                break
            offset += self.funnel_page_limit

        if not has_data:
            return {
                "clicks": None,
                "add_to_cart": None,
                "orders": None,
                "order_sum": None,
            }

        return {
            "clicks": clicks,
            "add_to_cart": add_to_cart,
            "orders": orders,
            "order_sum": order_sum,
        }

    async def _resolve_nm_ids(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        report_date: date,
    ) -> list[int]:
        if self.nm_ids:
            return list(self.nm_ids[:1000])

        response = await client.get(
            f"{self.stats_url}/api/v1/supplier/orders",
            headers=headers,
            params={"dateFrom": report_date.isoformat(), "flag": 0},
        )
        if response.status_code >= 400:
            return []

        data = response.json()
        if not isinstance(data, list):
            return []

        nm_ids: list[int] = []
        seen: set[int] = set()
        for row in data:
            if not isinstance(row, dict):
                continue
            nm_id = row.get("nmId")
            if isinstance(nm_id, int) and nm_id not in seen:
                seen.add(nm_id)
                nm_ids.append(nm_id)
            if len(nm_ids) >= 1000:
                break
        return nm_ids

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
    def _extract_products(raw_data: object) -> list[dict[str, object]] | None:
        if not isinstance(raw_data, dict):
            return None
        data = raw_data.get("data")
        if not isinstance(data, dict):
            return None
        products = data.get("products")
        if not isinstance(products, list):
            return None
        return [row for row in products if isinstance(row, dict)]

    @staticmethod
    def _pick_current_period_row(product_row: dict[str, object]) -> dict[str, object] | None:
        candidates = [
            product_row.get("currentPeriod"),
            product_row.get("selectedPeriod"),
            product_row.get("current"),
            product_row.get("metrics"),
            product_row.get("statistics"),
            product_row.get("stats"),
        ]

        for candidate in candidates:
            if isinstance(candidate, dict):
                return candidate

        data = product_row.get("data")
        if isinstance(data, dict):
            for key in ("currentPeriod", "selectedPeriod", "current", "metrics", "statistics", "stats"):
                nested = data.get(key)
                if isinstance(nested, dict):
                    return nested

        return None

    @staticmethod
    def _extract_number(source: dict[str, object], *keys: str) -> float:
        for key in keys:
            value = source.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return 0.0
