from __future__ import annotations

import logging
from datetime import time
from zoneinfo import ZoneInfo

from telegram import Update
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


async def send_daily_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    service: ReportService = context.application.bot_data["report_service"]
    chat_id: int = context.application.bot_data["chat_id"]

    try:
        report_date, metrics = await service.build_daily_report()
        text = metrics.to_telegram_text(report_date)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to build report")
        text = f"❌ Не удалось собрать отчет: {exc}"

    await context.bot.send_message(chat_id=chat_id, text=text)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Я отправляю ежедневный отчет по Ozon/WB в 10:00.\n"
        "Команды:\n"
        "/report — отправить отчет сейчас"
    )


async def report_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    service: ReportService = context.application.bot_data["report_service"]

    try:
        report_date, metrics = await service.build_daily_report()
        text = metrics.to_telegram_text(report_date)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to build on-demand report")
        text = f"❌ Не удалось собрать отчет: {exc}"

    await update.message.reply_text(text)


def main() -> None:
    settings = Settings.from_env()

    ozon = OzonClient(
        client_id=settings.ozon_client_id,
        api_key=settings.ozon_api_key,
    )
    wb = WildberriesClient(
        api_token=settings.wb_api_token,
        nm_ids=settings.wb_nm_ids,
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
