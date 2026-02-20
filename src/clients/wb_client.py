from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, timedelta

import httpx


@dataclass
class WildberriesClient:
    api_token: str
    brand_names: tuple[str, ...] = ()
    subject_ids: tuple[int, ...] = ()
    tag_ids: tuple[int, ...] = ()
    campaign_name_symbol: str = "!"
    stats_url: str = "https://statistics-api.wildberries.ru"
    adv_url: str = "https://advert-api.wildberries.ru"
    analytics_url: str = "https://seller-analytics-api.wildberries.ru"
    adv_max_retries: int = 3
    adv_retry_delay_seconds: float = 20.0
    request_delay_seconds: float = 1.0
    adv_batch_size: int = 50
    _last_request_time: float | None = None
    _request_lock: asyncio.Lock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._request_lock = asyncio.Lock()

    async def fetch_metrics(self, report_date: date) -> dict[str, int | float | None]:
        headers = {"Authorization": self.api_token}

        async with httpx.AsyncClient(timeout=30.0) as client:
            campaign_ids = await self._get_campaign_ids(client, headers)

            adv_views = await self._get_adv_views(client, headers, report_date, campaign_ids)
            adv_spend = await self._get_adv_spend(client, headers, report_date, campaign_ids)

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
        all_campaign_ids: list[int] = []
        matched_campaign_ids: list[int] = []
        for state in adverts:
            if not isinstance(state, dict):
                continue
            for campaign in state.get("advert_list", []):
                if not isinstance(campaign, dict):
                    continue
                advert_id = campaign.get("advertId")
                if not isinstance(advert_id, int):
                    continue

                all_campaign_ids.append(advert_id)

                campaign_name = self._extract_campaign_name(campaign)
                if not campaign_name:
                    # Some WB responses do not include campaign names in this endpoint.
                    # Keep the campaign to avoid dropping all ad metrics to н/д.
                    matched_campaign_ids.append(advert_id)
                    continue

                if self._campaign_matches_symbol(campaign_name):
                    matched_campaign_ids.append(advert_id)

        # Fallback: if symbol-filtered subset is empty, use all campaigns so ad metrics
        # are still collected for payloads where names are missing or inconsistent.
        return matched_campaign_ids or all_campaign_ids

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
        campaign_ids: list[int],
    ) -> float | None:
        if not campaign_ids:
            return None

        params = {"from": report_date.isoformat(), "to": report_date.isoformat()}
        response = await self._get_with_retry(client, f"{self.adv_url}/adv/v1/upd", headers, params)
        if response is None or response.status_code >= 400:
            return None

        raw_stats = response.json()
        if not isinstance(raw_stats, list):
            return None

        campaign_ids_set = set(campaign_ids)
        return sum(
            float(row.get("updSum", 0) or 0)
            for row in raw_stats
            if isinstance(row, dict) and self._extract_campaign_id(row) in campaign_ids_set
        )

    @staticmethod
    def _extract_campaign_name(campaign: dict[str, object]) -> str:
        for key in ("name", "advertName", "campaignName", "advert_nm"):
            raw_name = campaign.get(key)
            if raw_name is not None:
                return str(raw_name).strip()
        return ""


    def _campaign_matches_symbol(self, campaign_name: str) -> bool:
        symbol = self.campaign_name_symbol.strip()
        if not symbol:
            return True
        campaign_name_clean = campaign_name.lstrip()
        return campaign_name_clean.startswith(symbol)

    @staticmethod
    def _extract_campaign_id(row: dict[str, object]) -> int | None:
        for key in ("advertId", "advertsId", "campaignId", "advert_id"):
            value = row.get(key)
            try:
                return int(value) if value is not None else None
            except (TypeError, ValueError):
                continue
        return None

    async def _get_sales_funnel_metrics(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        report_date: date,
    ) -> dict[str, float | None]:
        products_metrics = await self._get_sales_funnel_products_metrics(client, headers, report_date)
        if products_metrics is not None:
            return products_metrics

        # Fallback to grouped/history in case products endpoint is temporarily unavailable.
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
        rows = raw_data.get("data", []) if isinstance(raw_data, dict) else raw_data
        if not isinstance(rows, list):
            return {
                "clicks": None,
                "add_to_cart": None,
                "orders": None,
                "order_sum": None,
            }

        metrics = self._parse_sales_funnel_rows(rows)
        if metrics is None:
            return {
                "clicks": None,
                "add_to_cart": None,
                "orders": None,
                "order_sum": None,
            }

        return metrics

    async def _get_sales_funnel_products_metrics(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        report_date: date,
    ) -> dict[str, float] | None:
        payload = {
            "selectedPeriod": {"start": report_date.isoformat(), "end": report_date.isoformat()},
            "pastPeriod": {"start": report_date.isoformat(), "end": report_date.isoformat()},
            "brandNames": self._resolve_brand_names(),
            "subjectIds": self._resolve_ids(self.subject_ids),
            "tagIds": self._resolve_ids(self.tag_ids),
            "nmIds": [],
            "skipDeletedNm": True,
            "limit": 1000,
            "offset": 0,
        }

        clicks = 0.0
        add_to_cart = 0.0
        orders = 0.0
        order_sum = 0.0
        has_data = False

        while True:
            response = await self._post_with_retry(
                client,
                f"{self.analytics_url}/api/analytics/v3/sales-funnel/products",
                headers,
                payload,
            )
            if response is None or response.status_code >= 400:
                return None

            raw_data = response.json()
            if not isinstance(raw_data, dict):
                return None

            data = raw_data.get("data", {})
            if not isinstance(data, dict):
                return None

            products = data.get("products", [])
            if not isinstance(products, list):
                return None

            for product_row in products:
                if not isinstance(product_row, dict):
                    continue
                statistic = product_row.get("statistic", {})
                if not isinstance(statistic, dict):
                    continue
                selected = statistic.get("selected", {})
                if not isinstance(selected, dict):
                    continue
                has_data = True
                clicks += self._extract_number(selected, "openCount", "openCardCount", "openCard", "clicks")
                add_to_cart += self._extract_number(selected, "cartCount", "addToCartCount", "addToCart", "atbs")
                orders += self._extract_number(selected, "orderCount", "ordersCount", "orders", "ordersSumCount")
                order_sum += self._extract_number(selected, "orderSum", "ordersSumRub", "ordersSum", "ordersAmount")

            if len(products) < int(payload["limit"]):
                break
            payload["offset"] = int(payload["offset"]) + int(payload["limit"])

        if not has_data:
            return None

        return {
            "clicks": clicks,
            "add_to_cart": add_to_cart,
            "orders": orders,
            "order_sum": order_sum,
        }

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
                clicks += self._extract_number(day_row, "openCount", "openCardCount", "openCard", "clicks")
                add_to_cart += self._extract_number(day_row, "cartCount", "addToCartCount", "addToCart", "atbs")
                orders += self._extract_number(day_row, "orderCount", "ordersCount", "orders", "ordersSumCount")
                order_sum += self._extract_number(day_row, "orderSum", "ordersSumRub", "ordersSum", "ordersAmount")

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
            response = await self._throttled_get(client, url, headers=headers, params=params)
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
            response = await self._throttled_post(client, url, headers=headers, json=payload)
            if response.status_code != 429:
                return response

            if attempt < self.adv_max_retries - 1:
                await asyncio.sleep(self.adv_retry_delay_seconds)
        return response

    async def _throttled_get(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, str],
    ) -> httpx.Response:
        await self._wait_for_request_slot()
        return await client.get(url, headers=headers, params=params)

    async def _throttled_post(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
    ) -> httpx.Response:
        await self._wait_for_request_slot()
        return await client.post(url, headers=headers, json=json)

    async def _wait_for_request_slot(self) -> None:
        if self.request_delay_seconds <= 0:
            return

        async with self._request_lock:
            now = asyncio.get_running_loop().time()
            if self._last_request_time is not None:
                elapsed = now - self._last_request_time
                wait_seconds = self.request_delay_seconds - elapsed
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)
            self._last_request_time = asyncio.get_running_loop().time()

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
