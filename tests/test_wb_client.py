import unittest
from datetime import date

from src.clients.wb_client import WildberriesClient


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class WildberriesClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_campaign_ids_filters_by_exclamation_prefix(self):
        client = WildberriesClient(api_token="token", campaign_name_prefix="!")

        async def fake_get(_self, url, headers):
            return FakeResponse(
                200,
                {
                    "adverts": [
                        {
                            "advert_list": [
                                {"advertId": 1, "name": "! main"},
                                {"advertId": 2, "name": "Brand campaign"},
                                {"advertId": 3, "advertName": "! secondary"},
                            ]
                        }
                    ]
                },
            )

        http_client = type("C", (), {"get": fake_get})()
        campaign_ids = await client._get_campaign_ids(http_client, {"Authorization": "token"})

        self.assertEqual(campaign_ids, [1, 3])


    async def test_get_campaign_ids_supports_custom_prefix(self):
        client = WildberriesClient(api_token="token", campaign_name_prefix="#")

        async def fake_get(_self, url, headers):
            return FakeResponse(
                200,
                {
                    "adverts": [
                        {
                            "advert_list": [
                                {"advertId": 10, "name": "# priority"},
                                {"advertId": 11, "name": "! old"},
                            ]
                        }
                    ]
                },
            )

        http_client = type("C", (), {"get": fake_get})()
        campaign_ids = await client._get_campaign_ids(http_client, {"Authorization": "token"})

        self.assertEqual(campaign_ids, [10])


    async def test_get_campaign_ids_with_empty_prefix_returns_all_campaigns(self):
        client = WildberriesClient(api_token="token", campaign_name_prefix="")

        async def fake_get(_self, url, headers):
            return FakeResponse(
                200,
                {"adverts": [{"advert_list": [{"advertId": 21, "name": "A"}, {"advertId": 22, "name": "! B"}]}]},
            )

        http_client = type("C", (), {"get": fake_get})()
        campaign_ids = await client._get_campaign_ids(http_client, {"Authorization": "token"})

        self.assertEqual(campaign_ids, [21, 22])

    async def test_get_adv_spend_sums_only_selected_campaign_ids(self):
        client = WildberriesClient(api_token="token")

        async def fake_get_with_retry(_client, _url, _headers, _params):
            return FakeResponse(
                200,
                [
                    {"advertId": 1, "updSum": 100},
                    {"campaignId": 2, "updSum": 70},
                    {"advertId": 3, "updSum": 30},
                ],
            )

        client._get_with_retry = fake_get_with_retry

        spend = await client._get_adv_spend(object(), {}, date(2024, 1, 1), [1, 3])

        self.assertEqual(spend, 130.0)


if __name__ == "__main__":
    unittest.main()
