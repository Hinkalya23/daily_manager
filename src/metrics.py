from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DailyMetrics:
    ozon_impressions: int | None
    wb_impressions_ads: int | None
    ozon_clicks: int | None
    wb_clicks: int | None
    ozon_add_to_cart: int | None
    wb_add_to_cart: int | None
    ozon_orders: int | None
    wb_orders: int | None
    ozon_avg_bill: float | None
    wb_avg_bill: float | None
    ozon_order_sum: float | None
    wb_order_sum: float | None
    ozon_ad_spend: float | None
    wb_ad_spend: float | None
    ozon_search_position: str | None

    def to_telegram_text(self, report_date: str) -> str:
        return (
            f"📊 Ежедневный отчет за {report_date}\n\n"
            f"Показы (OZON): {_fmt(self.ozon_impressions)}\n"
            f"Показы (Wildberries) (реклама): {_fmt(self.wb_impressions_ads)}\n"
            f"Клики / Переход в карточку (OZON): {_fmt(self.ozon_clicks)}\n"
            f"Клики / Переход в карточку (WB): {_fmt(self.wb_clicks)}\n"
            f"Добавили в корзину (OZON): {_fmt(self.ozon_add_to_cart)}\n"
            f"Добавили в корзину (WB): {_fmt(self.wb_add_to_cart)}\n"
            f"Заказы (OZON): {_fmt(self.ozon_orders)}\n"
            f"Заказы (WB): {_fmt(self.wb_orders)}\n"
            f"Средний чек (OZON): {_fmt(self.ozon_avg_bill)}\n"
            f"Средний чек (WB): {_fmt(self.wb_avg_bill)}\n"
            f"Сумма заказов (OZON): {_fmt(self.ozon_order_sum)}\n"
            f"Сумма заказов (WB): {_fmt(self.wb_order_sum)}\n"
            f"Расходы на рекламу (OZON): {_fmt(self.ozon_ad_spend)}\n"
            f"Расходы на рекламу (WB): {_fmt(self.wb_ad_spend)}\n"
            f"Позиция в поиске и каталоге (OZON): {_fmt(self.ozon_search_position)}"
        )


def _fmt(value: object | None) -> str:
    return "н/д" if value is None else str(value)
