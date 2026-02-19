from __future__ import annotations

import asyncio
import logging
from datetime import time
from time import sleep
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut
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
_STARTUP_RETRY_DELAY_SECONDS = 5.0


def _resolve_target_destination(
    context: ContextTypes.DEFAULT_TYPE,
) -> tuple[int, int | None]:
    dynamic_chat_id = context.application.bot_data.get("runtime_chat_id")
    dynamic_thread_id = context.application.bot_data.get("runtime_message_thread_id")

    chat_id = (
        int(dynamic_chat_id)
        if dynamic_chat_id is not None
        else int(context.application.bot_data["chat_id"])
    )

    if dynamic_thread_id is not None:
        return chat_id, int(dynamic_thread_id)

    return chat_id, context.application.bot_data.get("message_thread_id")


def _remember_runtime_destination(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.effective_chat is None:
        return

    context.application.bot_data["runtime_chat_id"] = update.effective_chat.id

    if update.effective_message is not None:
        context.application.bot_data["runtime_message_thread_id"] = (
            update.effective_message.message_thread_id
        )


async def _send_with_retry(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    text: str,
    message_thread_id: int | None = None,
) -> bool:
    for attempt in range(_TELEGRAM_SEND_RETRIES + 1):
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                message_thread_id=message_thread_id,
            )
            return True
        except RetryAfter as exc:
            delay = float(exc.retry_after or _TELEGRAM_RETRY_DELAY_SECONDS)
            logger.warning("Telegram requested retry after %.1fs", delay)
            await asyncio.sleep(delay)
        except BadRequest:
            logger.exception(
                "Telegram rejected message for chat_id=%s, message_thread_id=%s",
                chat_id,
                message_thread_id,
            )
            return False
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
    chat_id: int
    message_thread_id: int | None
    chat_id, message_thread_id = _resolve_target_destination(context)

    try:
        report_date, metrics = await service.build_daily_report()
        text = metrics.to_telegram_text(report_date)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to build report")
        text = f"❌ Не удалось собрать отчет: {exc}"

    await _send_with_retry(
        context,
        chat_id=chat_id,
        text=text,
        message_thread_id=message_thread_id,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _remember_runtime_destination(update, context)
    await _reply_with_retry(
        update,
        "Привет! Я отправляю ежедневный отчет по Ozon/WB в 10:00.\n"
        "Команды:\n"
        "/report — отправить отчет сейчас",
    )


async def report_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    service: ReportService = context.application.bot_data["report_service"]
    _remember_runtime_destination(update, context)

    try:
        report_date, metrics = await service.build_daily_report()
        text = metrics.to_telegram_text(report_date)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to build on-demand report")
        text = f"❌ Не удалось собрать отчет: {exc}"

    await _reply_with_retry(update, text)


async def on_error(_: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled telegram update error", exc_info=context.error)


def _build_application(settings: Settings, report_service: ReportService) -> Application:
    app = Application.builder().token(settings.telegram_bot_token).build()
    app.bot_data["report_service"] = report_service
    app.bot_data["chat_id"] = settings.telegram_chat_id
    app.bot_data["message_thread_id"] = settings.telegram_message_thread_id

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
    return app


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

    logger.info(
        "Bot started. Daily report scheduled at %02d:%02d %s",
        settings.report_hour,
        settings.report_minute,
        settings.timezone,
    )

    while True:
        app = _build_application(settings, report_service)
        try:
            app.run_polling(close_loop=False)
            return
        except (TimedOut, NetworkError):
            logger.exception(
                "Telegram initialization failed due to network timeout. Retrying in %.1f seconds",
                _STARTUP_RETRY_DELAY_SECONDS,
            )
            sleep(_STARTUP_RETRY_DELAY_SECONDS)


if __name__ == "__main__":
    main()
