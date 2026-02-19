from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_chat_id: int
    timezone: str
    report_hour: int
    report_minute: int
    ozon_client_id: str
    ozon_api_key: str
    wb_api_token: str
    report_days_back: int

    @staticmethod
    def from_env() -> "Settings":
        load_dotenv()

        return Settings(
            telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=int(_require("TELEGRAM_CHAT_ID")),
            timezone=os.getenv("TIMEZONE", "Europe/Moscow"),
            report_hour=int(os.getenv("REPORT_HOUR", "10")),
            report_minute=int(os.getenv("REPORT_MINUTE", "0")),
            ozon_client_id=_require("OZON_CLIENT_ID"),
            ozon_api_key=_require("OZON_API_KEY"),
            wb_api_token=_require("WB_API_TOKEN"),
            report_days_back=int(os.getenv("REPORT_DAYS_BACK", "1")),
        )


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Missing required environment variable: {key}")
    return value
