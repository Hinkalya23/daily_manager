# daily_manager

Telegram-бот на Python, который каждый день в **10:00** отправляет отчет по метрикам маркетплейсов **Ozon** и **Wildberries**.

## Что отправляет бот

- Показы (OZON)
- Показы (Wildberries) (реклама)
- Клики / Переход в карточку (OZON)
- Клики / Переход в карточку (WB)
- Добавили в корзину (OZON)
- Добавили в корзину (WB)
- Заказы (OZON)
- Заказы (WB)
- Средний чек (OZON)
- Средний чек (WB)
- Сумма заказов (OZON)
- Сумма заказов (WB)
- Расходы на рекламу (OZON)
- Расходы на рекламу (WB)
- Позиция в поиске и каталоге (OZON)

## Установка

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Настройка

1. Скопируйте шаблон переменных окружения:

```bash
cp .env.example .env
```

2. Заполните `.env`:

- `TELEGRAM_BOT_TOKEN` — токен бота от @BotFather
- `TELEGRAM_CHAT_ID` — ID чата, куда слать отчет
- `TIMEZONE` — таймзона (по умолчанию `Europe/Moscow`)
- `REPORT_HOUR`, `REPORT_MINUTE` — время ежедневной отправки (по умолчанию 10:00)
- `OZON_CLIENT_ID`, `OZON_API_KEY` — доступы к Seller API Ozon
- `WB_API_TOKEN` — токен WB API
- `WB_BRAND_NAMES`, `WB_SUBJECT_IDS`, `WB_TAG_IDS` — фильтры grouped-воронки WB (через запятую, можно оставить пустыми для всех карточек)
- `REPORT_DAYS_BACK` — за какой день брать отчет (1 = вчера)

## Запуск

```bash
python main.py
```

## Команды бота

- `/start` — приветствие и список команд
- `/report` — отправить отчет вручную сразу

## Важные примечания по API

- Интеграция с Ozon использует Seller API (`https://docs.ozon.ru/api/seller/`).
- Интеграция с WB использует статистическое, рекламное и seller analytics API (`https://dev.wildberries.ru/`), включая `/api/analytics/v3/sales-funnel/grouped/history` для всех нерекламных метрик WB.
- Некоторые метрики в разных кабинетах могут требовать дополнительных прав, или отличаться по структуре ответа.
- Если API не возвращает конкретную метрику, бот покажет `н/д`.

## Структура проекта

- `main.py` — запуск Telegram-бота и планировщик ежедневной отправки.
- `src/config.py` — чтение переменных окружения.
- `src/report_service.py` — сборка итогового отчета.
- `src/clients/ozon_client.py` — получение метрик из Ozon API.
- `src/clients/wb_client.py` — получение метрик из WB API.
- `src/metrics.py` — структура и формат сообщения отчета.
