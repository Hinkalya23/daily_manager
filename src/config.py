from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_chat_id: int
    telegram_message_thread_id: int | None
    timezone: str
    report_hour: int
    report_minute: int
    ozon_client_id: str
    ozon_api_key: str
    ozon_performance_client_id: str | None
    ozon_performance_client_secret: str | None
    wb_api_token: str
    wb_brand_names: tuple[str, ...]
    wb_subject_ids: tuple[int, ...]
    wb_tag_ids: tuple[int, ...]
    wb_ad_campaign_prefix: str
    report_days_back: int

    @staticmethod
    def from_env() -> "Settings":
        load_dotenv()

        return Settings(
            telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=int(_require("TELEGRAM_CHAT_ID")),
            telegram_message_thread_id=_parse_optional_int(
                os.getenv("TELEGRAM_MESSAGE_THREAD_ID")
            ),
            timezone=os.getenv("TIMEZONE", "Europe/Moscow"),
            report_hour=int(os.getenv("REPORT_HOUR", "10")),
            report_minute=int(os.getenv("REPORT_MINUTE", "0")),
            ozon_client_id=_require("OZON_CLIENT_ID"),
            ozon_api_key=_require("OZON_API_KEY"),
            ozon_performance_client_id=_parse_optional_str(
                os.getenv("OZON_PERFORMANCE_CLIENT_ID")
            ),
            ozon_performance_client_secret=_parse_optional_str(
                os.getenv("OZON_PERFORMANCE_CLIENT_SECRET")
            ),
            wb_api_token=_require("WB_API_TOKEN"),
            wb_brand_names=_parse_str_list(os.getenv("WB_BRAND_NAMES", "")),
            wb_subject_ids=_parse_int_list(os.getenv("WB_SUBJECT_IDS", "")),
            wb_tag_ids=_parse_int_list(os.getenv("WB_TAG_IDS", "")),
            wb_ad_campaign_prefix=os.getenv("WB_AD_CAMPAIGN_PREFIX", "!").strip(),
            report_days_back=int(os.getenv("REPORT_DAYS_BACK", "1")),
        )


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Missing required environment variable: {key}")
    return value


def _parse_optional_int(raw_value: str | None) -> int | None:
    if raw_value is None:
        return None

    value = raw_value.strip()
    if not value:
        return None
    return int(value)


def _parse_optional_str(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None

    value = raw_value.strip()
    if not value:
        return None
    return value


def _parse_int_list(raw_value: str) -> tuple[int, ...]:
    if not raw_value.strip():
        return tuple()

    result: list[int] = []
    for chunk in raw_value.split(","):
        value = chunk.strip()
        if not value:
            continue
        result.append(int(value))
    return tuple(result)


def _parse_str_list(raw_value: str) -> tuple[str, ...]:
    if not raw_value.strip():
        return tuple()

    result: list[str] = []
    for chunk in raw_value.split(","):
        value = chunk.strip()
        if value:
            result.append(value)
    return tuple(result)
