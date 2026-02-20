# daily_manager

Telegram-бот на Python, который каждый день в настроенное время отправляет отчет по метрикам маркетплейсов **Ozon** и **Wildberries**.

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
- `TELEGRAM_MESSAGE_THREAD_ID` — ID топика (message thread) в Telegram-чате; если задан, ежедневный отчет отправляется именно в этот топик
- `TIMEZONE` — таймзона (по умолчанию `Europe/Moscow`)
- `REPORT_HOUR`, `REPORT_MINUTE` — время ежедневной отправки (по умолчанию 10:00)
- `OZON_CLIENT_ID`, `OZON_API_KEY` — доступы к Seller API Ozon (воронка продаж)
- `OZON_PERFORMANCE_CLIENT_ID`, `OZON_PERFORMANCE_CLIENT_SECRET` — доступы к Ozon Performance API (расходы на рекламу). Опционально: если не заданы, поле расходов будет `н/д`
- `WB_API_TOKEN` — токен WB API
- `WB_AD_CAMPAIGN_PREFIX` — префикс названия рекламных кампаний WB для метрик показов/расходов (по умолчанию `!`, пустое значение = все кампании)
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

- Интеграция с Ozon для воронки продаж использует Seller API `POST /v1/analytics/data` (метрики `session_view_pdp`, `hits_view`, `position_category`, `hits_tocart_pdp`, `ordered_units`, `revenue` и др.).
- Расходы на рекламу Ozon берутся из Performance API: `POST /api/client/token` + `GET /api/client/statistics/expense/json`.
- Интеграция с WB использует статистическое, рекламное и seller analytics API (`https://dev.wildberries.ru/`), включая `/api/analytics/v3/sales-funnel/products` (с пагинацией) для нерекламных метрик WB и fallback на `/api/analytics/v3/sales-funnel/grouped/history`.
- Для рекламных метрик WB бот сначала получает кампании через `/api/advert/v2/adverts?statuses=7,9,11`, фильтрует их по `settings.name` с учётом `WB_AD_CAMPAIGN_PREFIX`, затем считает показы через `/adv/v3/fullstats` и расходы через `/adv/v1/upd` только по выбранным `advertId`.
- Некоторые метрики в разных кабинетах могут требовать дополнительных прав, или отличаться по структуре ответа.
- Если API не возвращает конкретную метрику, бот покажет `н/д`.

## Структура проекта

- `main.py` — запуск Telegram-бота и планировщик ежедневной отправки.
- `src/config.py` — чтение переменных окружения.
- `src/report_service.py` — сборка итогового отчета.
- `src/clients/ozon_client.py` — получение метрик из Ozon API.
- `src/clients/wb_client.py` — получение метрик из WB API.
- `src/metrics.py` — структура и формат сообщения отчета.
