from __future__ import annotations

import asyncio
import logging
from datetime import time
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.error import NetworkError, RetryAfter, TimedOut
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from src.clients.ozon_client import OzonClient
from src.clients.wb_client import WildberriesClient
from src.config import Settings
from src.report_service import ReportService

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

_TELEGRAM_SEND_RETRIES = 2
_TELEGRAM_RETRY_DELAY_SECONDS = 2.0


async def _send_with_retry(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    text: str,
) -> bool:
    for attempt in range(_TELEGRAM_SEND_RETRIES + 1):
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
            return True
        except RetryAfter as exc:
            delay = float(exc.retry_after or _TELEGRAM_RETRY_DELAY_SECONDS)
            logger.warning("Telegram requested retry after %.1fs", delay)
            await asyncio.sleep(delay)
        except (TimedOut, NetworkError):
            if attempt >= _TELEGRAM_SEND_RETRIES:
                logger.exception("Failed to send Telegram message after retries")
                return False
            await asyncio.sleep(_TELEGRAM_RETRY_DELAY_SECONDS)
    return False


async def _reply_with_retry(
    update: Update,
    text: str,
) -> bool:
    if update.message is None:
        return False

    for attempt in range(_TELEGRAM_SEND_RETRIES + 1):
        try:
            await update.message.reply_text(text)
            return True
        except RetryAfter as exc:
            delay = float(exc.retry_after or _TELEGRAM_RETRY_DELAY_SECONDS)
            logger.warning("Telegram requested retry after %.1fs", delay)
            await asyncio.sleep(delay)
        except (TimedOut, NetworkError):
            if attempt >= _TELEGRAM_SEND_RETRIES:
                logger.exception("Failed to reply in Telegram after retries")
                return False
            await asyncio.sleep(_TELEGRAM_RETRY_DELAY_SECONDS)
    return False


async def send_daily_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    service: ReportService = context.application.bot_data["report_service"]
    chat_id: int = context.application.bot_data["chat_id"]

    try:
        report_date, metrics = await service.build_daily_report()
        text = metrics.to_telegram_text(report_date)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to build report")
        text = f"❌ Не удалось собрать отчет: {exc}"

    await _send_with_retry(context, chat_id=chat_id, text=text)


async def start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply_with_retry(
        update,
        "Привет! Я отправляю ежедневный отчет по Ozon/WB в 10:00.\n"
        "Команды:\n"
        "/report — отправить отчет сейчас",
    )


async def report_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    service: ReportService = context.application.bot_data["report_service"]

    try:
        report_date, metrics = await service.build_daily_report()
        text = metrics.to_telegram_text(report_date)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to build on-demand report")
        text = f"❌ Не удалось собрать отчет: {exc}"

    await _reply_with_retry(update, text)


async def on_error(_: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled telegram update error", exc_info=context.error)


def main() -> None:
    settings = Settings.from_env()

    ozon = OzonClient(
        client_id=settings.ozon_client_id,
        api_key=settings.ozon_api_key,
    )
    wb = WildberriesClient(
        api_token=settings.wb_api_token,
        brand_names=settings.wb_brand_names,
        subject_ids=settings.wb_subject_ids,
        tag_ids=settings.wb_tag_ids,
    )
    report_service = ReportService(
        ozon=ozon,
        wb=wb,
        report_days_back=settings.report_days_back,
    )

    app = Application.builder().token(settings.telegram_bot_token).build()
    app.bot_data["report_service"] = report_service
    app.bot_data["chat_id"] = settings.telegram_chat_id

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("report", report_now))
    app.add_error_handler(on_error)

    app.job_queue.run_daily(
        callback=send_daily_report,
        time=time(
            hour=settings.report_hour,
            minute=settings.report_minute,
            tzinfo=ZoneInfo(settings.timezone),
        ),
        name="daily-sales-report",
    )

    logger.info(
        "Bot started. Daily report scheduled at %02d:%02d %s",
        settings.report_hour,
        settings.report_minute,
        settings.timezone,
    )

    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
