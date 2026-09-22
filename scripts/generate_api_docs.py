"""Генератор справочника API: docs/api/*.md и docs/api/openapi.json.

Технические таблицы (параметры, поля, типы) строятся из OpenAPI-схемы, которую собирает само приложение;
ошибки (HTTPException/JSONResponse с кодом >= 400, включая вспомогательные функции) — разбором кода роутов;
описания эндпоинтов — вручную в словаре S ниже. Запускайте после ЛЮБОГО изменения API:

    BOT_TOKEN=x python scripts/generate_api_docs.py        (PowerShell: $env:BOT_TOKEN='x')

Файл API.md (вводный, ручной) скриптом НЕ перезаписывается.
"""
import ast
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault('BOT_TOKEN', 'docs-generation')
os.environ.setdefault('DATABASE_URL', 'sqlite+aiosqlite:///:memory:')

from app.cabinet.app import create_app  # noqa: E402

OUT = REPO / 'docs' / 'api'
schema = create_app(None).openapi()
COMPONENTS = schema['components']['schemas']

# ---- разбор ошибок из кода роутов ----------------------------------------------------------------------
STATUS_NAMES = {
    'HTTP_400_BAD_REQUEST': 400, 'HTTP_401_UNAUTHORIZED': 401, 'HTTP_402_PAYMENT_REQUIRED': 402, 'HTTP_403_FORBIDDEN': 403,
    'HTTP_404_NOT_FOUND': 404, 'HTTP_409_CONFLICT': 409, 'HTTP_422_UNPROCESSABLE_ENTITY': 422, 'HTTP_429_TOO_MANY_REQUESTS': 429,
    'HTTP_500_INTERNAL_SERVER_ERROR': 500, 'HTTP_502_BAD_GATEWAY': 502, 'HTTP_503_SERVICE_UNAVAILABLE': 503,
}


def const_str(node) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            parts.append(value.value if isinstance(value, ast.Constant) else '{…}')
        return ''.join(parts)
    return None


def status_of(node) -> int | None:
    if isinstance(node, ast.Attribute) and node.attr in STATUS_NAMES:
        return STATUS_NAMES[node.attr]
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    return None


def route_info(func: ast.AsyncFunctionDef, prefix: str):
    for deco in func.decorator_list:
        if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute) and deco.func.attr in ('get', 'post', 'patch', 'put', 'delete'):
            path = deco.args[0].value if deco.args and isinstance(deco.args[0], ast.Constant) else None
            yield deco.func.attr.upper(), prefix + path


def errors_in(func: ast.AsyncFunctionDef) -> list[tuple[int, str]]:
    found = []
    for node in ast.walk(func):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'HTTPException' and node.args:
            code = status_of(node.args[0])
            message = const_str(node.args[1]) if len(node.args) > 1 else None
            if code:
                found.append((code, message or ''))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'JSONResponse':
            code = None
            for kw in node.keywords:
                if kw.arg == 'status_code':
                    code = status_of(kw.value)
            if code and code >= 400:
                reason = ''
                if node.args and isinstance(node.args[0], ast.Dict):
                    for key, value in zip(node.args[0].keys, node.args[0].values):
                        if isinstance(key, ast.Constant) and key.value == 'reason':
                            reason = const_str(value) or ''
                found.append((code, reason))
    return list(dict.fromkeys(found))




# ---- ошибки: разбор кода + вспомогательные функции ------------------------------------------------------------
ROOT = REPO / 'app' / 'cabinet'
HELPER_ERRORS: dict[str, list] = {}
ROUTE_ERRORS: dict[str, list] = {}
ROUTE_CALLS: dict[str, set] = {}
for filename, prefix in (('routes.py', '/cabinet'), ('admin_routes.py', '/cabinet/admin'), ('webhooks.py', '')):
    tree = ast.parse((ROOT / filename).read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            routes = list(route_info(node, prefix))
            errors = errors_in(node)
            if not routes:
                HELPER_ERRORS[node.name] = errors
            calls = {c.func.id for c in ast.walk(node) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
            for method, path in routes:
                ROUTE_ERRORS[f'{method} {path}'] = errors
                ROUTE_CALLS[f'{method} {path}'] = calls
for key, calls in ROUTE_CALLS.items():
    for name in sorted(calls):
        if name in HELPER_ERRORS:
            ROUTE_ERRORS[key] = list(dict.fromkeys(ROUTE_ERRORS[key] + HELPER_ERRORS[name]))

# ---- ручные описания -------------------------------------------------------------------------------------------
S = {}  # 'METHOD path' -> (заголовок, [примечания])


def add(method, path, title, *notes):
    S[f'{method} {path}'] = (title, list(notes))


# --- пользовательский API
add('POST', '/cabinet/auth/telegram', 'Вход через Telegram Mini App',
    'Принимает строку `initData`, которую Telegram передаёт Mini App. Подпись проверяется секретом бота (HMAC-SHA256), `auth_date` не должен быть старше 24 часов. Если пользователя ещё нет — создаётся автоматически (язык берётся из `language_code`: `ru` или `en`, иначе `ru`).',
    'В ответе — JWT (HS256, срок жизни 12 часов). Дальше передавайте его в заголовке `Authorization: Bearer <token>`. Refresh-токена нет: при истечении получите новый `initData` у Telegram и войдите заново.',
    'Заблокированный пользователь получает `403`.')
add('GET', '/cabinet/dashboard', 'Главный экран', 'Баланс, текущая подписка (трафик, срок, статус, ссылка на подключение) и признак `is_admin` (для показа входа в админку).')
add('GET', '/cabinet/profile', 'Профиль', 'Данные пользователя и баланс (открывается по нажатию на имя/аватар).')
add('POST', '/cabinet/settings/language', 'Сменить язык', 'Тот же `User.language`, который переключается в самом боте.')
add('GET', '/cabinet/tariffs', 'Тарифы и способы оплаты',
    'Активные тарифы с ценами по периодам, уже со скидкой пользователя (`discount_percent`, дедлайн скидки в `discount_expires_at`, если она временная), и доступные способы оплаты. Способ `balance` показывается, только если на балансе есть средства.')
add('POST', '/cabinet/subscription/purchase', 'Купить или продлить подписку',
    'Тот же код, что и в боте. Метод оплаты берётся из списка `payment_methods` ответа `GET /cabinet/tariffs`.',
    'Оплата с баланса (`balance`) выполняется сразу. Внешний способ создаёт платёж у провайдера и возвращает ссылку на оплату; подписка выдаётся после подтверждения платежа (вебхук или фоновая проверка). Если на балансе есть средства, часть суммы автоматически списывается с баланса.',
    'Продление активной подписки считается от текущей даты окончания, истёкшей — от текущего момента.')
add('GET', '/cabinet/tariff/change-preview', 'Расчёт смены тарифа',
    'Считает доплату за смену тарифа на активной подписке: (цена дня нового тарифа − цена дня старого) × оставшиеся дни. Даунгрейд бесплатный, срок подписки не меняется.')
add('POST', '/cabinet/tariff/change', 'Сменить тариф',
    'Списывает доплату с баланса (если она больше нуля) и переключает подписку на новый тариф с тем же сроком. Только с баланса, внешние платёжные способы не поддерживаются.')
add('GET', '/cabinet/connect-apps', 'VPN-клиенты для подключения', 'Список приложений по платформам для кнопки «Подключить VPN» (по конфигурации панели Remnawave). Нужна подписка, иначе `404`.')
add('GET', '/cabinet/devices', 'Мои устройства', 'Список подключённых устройств (HWID) из Remnawave.')
add('DELETE', '/cabinet/devices', 'Сбросить все мои устройства', 'Удаляет все привязанные устройства пользователя на панели.')
add('DELETE', '/cabinet/devices/{hwid}', 'Удалить моё устройство', 'Удаляет одно устройство по HWID.')
add('GET', '/cabinet/transactions', 'История моих транзакций', 'Постраничная история (размер страницы 15): оплаты, бонусы, реферальные начисления.')
add('POST', '/cabinet/promocode/activate', 'Активировать промокод',
    'Тот же код, что и команда `/promo` в боте. Промокод на баланс начисляет сумму, промокод на дни продлевает подписку. Каждый пользователь может активировать промокод один раз; действует лимит активаций.',
    'Ошибки активации приходят как `400` с текстом причины (не найден, не активен, истёк, уже использован, лимит исчерпан).')
add('POST', '/cabinet/gift/purchase', 'Купить подарочную подписку', 'Та же логика, что в боте; цены и периоды берутся из активного тарифа. В ответе `gift_link` (если код создан сразу) или `payment_url` (если нужна оплата у провайдера).')
add('GET', '/cabinet/referral', 'Реферальная программа', 'Реферальная ссылка и статистика — то же, что показывает бот.')

# --- админка: аналитика
add('GET', '/cabinet/admin/overview', 'Обзор', 'Главная сводка: выручка за сегодня/7/30 дней и всё время, подписки, пользователи, конверсия, средний чек, MRR/ARR, churn, трафик. MRR — прокси «выручка за 30 дней» (настоящего рекуррентного биллинга нет), ARR = MRR × 12.')
add('GET', '/cabinet/admin/revenue-timeseries', 'Выручка по дням', 'Точка на каждый день периода: сумма и число платежей.')
add('GET', '/cabinet/admin/recent-payments', 'Последние платежи', 'Лента последних успешных платежей (без оплат с баланса).')
add('GET', '/cabinet/admin/sales-breakdown', 'Разбивка продаж', 'Выручка по типам транзакций, по платёжным провайдерам и по дням недели, а также число активных подписок по тарифам.')
add('GET', '/cabinet/admin/revenue-composition', 'Состав выручки по провайдерам и дням', 'Для stacked-графика: список дней и ряд значений на каждого провайдера.')
add('GET', '/cabinet/admin/subscription-pulse', 'Пульс подписок', 'Новые и продлённые за сегодня, истекающие за 24 часа и за 3 дня.')
add('GET', '/cabinet/admin/alerts', 'Требует внимания', 'Живой снимок проблем: подписки на грани истечения, недоступные и отключённые ноды, высокая загрузка памяти панели, обращения без ответа. Истории состояний нет.')
add('GET', '/cabinet/admin/ltv', 'LTV', 'ARPU, средний и медианный LTV платящих, топ-20 плательщиков.')
add('GET', '/cabinet/admin/cohorts', 'Когорты', 'Когорты по месяцу регистрации: выручка на пользователя по месяцам после регистрации.')
add('GET', '/cabinet/admin/referrals', 'Реферальная воронка', 'Приглашённые, платящие из них, конверсия, выплаченные комиссии и топ рефереров.')
add('GET', '/cabinet/admin/net-profit', 'Чистая прибыль', 'Выручка минус расходы на инфраструктуру (данные Remnawave Infra Billing). Все суммы в рублях (число с плавающей точкой), а не в копейках.')
# --- админка: инфраструктура
add('GET', '/cabinet/admin/nodes', 'Список нод', 'Ноды из панели Remnawave.')
add('GET', '/cabinet/admin/nodes/{node_uuid}', 'Карточка ноды', 'Подробности ноды (`404`, если не найдена).')
add('POST', '/cabinet/admin/nodes/{node_uuid}/enable', 'Включить ноду', 'Команда панели Remnawave.')
add('POST', '/cabinet/admin/nodes/{node_uuid}/disable', 'Отключить ноду', 'Команда панели Remnawave.')
add('POST', '/cabinet/admin/nodes/{node_uuid}/restart', 'Перезапустить ноду', 'Команда панели Remnawave.')
add('GET', '/cabinet/admin/infra-billing', 'Расходы на инфраструктуру', 'Данные Infra Billing панели Remnawave (числа без указания валюты; считаются рублями).')
add('GET', '/cabinet/admin/monitoring', 'Мониторинг', 'Состояние панели (память, процессор) и метрики нод.')
# --- админка: пользователи
add('GET', '/cabinet/admin/users', 'Список пользователей', 'Поиск `query` — по `telegram_id` (если введено число) или по части username (без учёта регистра, `@` в начале игнорируется). Фильтр `filter`: `all`, `no_sub` (без подписки), `blocked`, `blocked_bot` (заблокировали бота). Размер страницы 20.')
add('GET', '/cabinet/admin/users/{user_id}', 'Карточка пользователя', 'Баланс, подписка, число приглашённых и сумма реферальных начислений, скидочная группа, персональный процент реферала, флаги блокировки и блокировки бота, последние транзакции.')
add('POST', '/cabinet/admin/users/{user_id}/balance', 'Изменить баланс', 'Положительная сумма начисляет (создаёт транзакцию `topup`), отрицательная списывает (`refund`), но баланс не уходит ниже нуля. Пользователю приходит уведомление. Сумма — в рублях (`amount_rub`).')
add('POST', '/cabinet/admin/users/{user_id}/subscription-days', 'Продлить или сократить подписку', 'Положительное число дней продлевает (если подписки нет — выдаёт на активном тарифе), отрицательное сокращает действующую подписку.')
add('POST', '/cabinet/admin/users/{user_id}/block', 'Заблокировать / разблокировать', 'В кабинете заблокированный пользователь получает `403` на каждый запрос; в боте блокировка проверяется в обработчиках, связанных с деньгами и бонусами.')
add('POST', '/cabinet/admin/users/{user_id}/message', 'Написать пользователю в Telegram', 'Отправляет сообщение от имени бота. `{"status": "sent"}` при успехе; `{"status": "blocked_bot"}`, если пользователь заблокировал бота (флаг сохраняется); `502` при другой ошибке Telegram.')
add('POST', '/cabinet/admin/users/massban', 'Массовая блокировка', 'Блокирует пользователей по списку `telegram_id`. Возвращает, сколько запрошено и сколько заблокировано (несуществующие id пропускаются).')
add('DELETE', '/cabinet/admin/users/{user_id}', 'Удалить (анонимизировать) пользователя', 'Не физическое удаление: пользователь блокируется, username стирается. Финансовая история и рефералы сохраняются. Ответ `{"status": "anonymized"}`.')
add('POST', '/cabinet/admin/users/{user_id}/referral-commission', 'Персональный процент реферала', 'Задаёт процент комиссии реферера для этого пользователя (0–100) или сбрасывает на общий (`null`).')
add('POST', '/cabinet/admin/users/{user_id}/promo-group', 'Назначить скидочную группу', 'Назначает скидочную группу; `promo_group_id: null` снимает её.')
add('GET', '/cabinet/admin/users/{user_id}/devices', 'Устройства пользователя', 'Устройства (HWID) из Remnawave. `404`, если у пользователя нет подписки в панели.')
add('DELETE', '/cabinet/admin/users/{user_id}/devices', 'Сбросить все устройства пользователя', 'Удаляет все устройства на панели.')
add('DELETE', '/cabinet/admin/users/{user_id}/devices/{hwid}', 'Удалить устройство пользователя', 'Удаляет одно устройство по HWID.')
add('GET', '/cabinet/admin/users/{user_id}/traffic-by-node', 'Трафик пользователя по нодам', 'Расход трафика по нодам из Remnawave.')
add('POST', '/cabinet/admin/users/{user_id}/sync/from-panel', 'Синхронизировать из панели', 'Панель — источник истины: подтягивает трафик, срок и статус в БД.')
add('POST', '/cabinet/admin/users/{user_id}/sync/to-panel', 'Синхронизировать в панель', 'БД — источник истины: прописывает срок и статус в панель.')
add('GET', '/cabinet/admin/users/{user_id}/transactions', 'Транзакции пользователя', 'Постраничная история транзакций одного пользователя.')
# --- админка: подписки, транзакции
add('GET', '/cabinet/admin/subscriptions', 'Подписки всех пользователей', 'Данные только из нашей БД (Remnawave не опрашивается). Фильтр `status`: `active`, `expired`, `disabled`; поиск `query` как в списке пользователей; сортировка по дате окончания (сначала дальние). Размер страницы 20.')
add('GET', '/cabinet/admin/transactions', 'Транзакции всех пользователей', 'Фильтры: `type` (`topup`, `subscription_payment`, `referral_reward`, `refund`, `gift`), `status` (`pending`, `completed`, `failed`), поиск `query`. Размер страницы 20.')
add('GET', '/cabinet/admin/transactions/platega-reconcile', 'Сверка с кабинетом Platega', 'Возвращает `{recordId: status}` за последние `days` дней (до 31). Реальный запрос к Platega боевыми ключами; в режиме `stub` возвращает пустой объект.')
add('GET', '/cabinet/admin/transactions/{transaction_id}', 'Детали транзакции', 'Транзакция с данными платежа: `raw_payload`, сырой ответ провайдера.')
# --- админка: поддержка
add('GET', '/cabinet/admin/support/threads', 'Обращения в поддержку', 'Тикеты: пользователь, последнее сообщение, статус, признак `unread` (последнее сообщение от пользователя без ответа), назначенный админ.')
add('GET', '/cabinet/admin/support/threads/{ticket_id}', 'Переписка по обращению', 'Все сообщения тикета.')
add('POST', '/cabinet/admin/support/threads/{ticket_id}/reply', 'Ответить на обращение', 'Отправляет ответ пользователю в Telegram. `502`, если отправить не удалось.')
add('POST', '/cabinet/admin/support/threads/{ticket_id}/close', 'Закрыть обращение', 'Ответ `{"status": "closed"}`.')
add('POST', '/cabinet/admin/support/threads/{ticket_id}/reopen', 'Открыть обращение снова', 'Ответ `{"status": "open"}`.')
# --- админка: скидки и акции
add('GET', '/cabinet/admin/promo-groups', 'Скидочные группы', 'Постоянные скидки для отдельных пользователей.')
add('POST', '/cabinet/admin/promo-groups', 'Создать скидочную группу', 'Название и процент скидки (0–100).')
add('PATCH', '/cabinet/admin/promo-groups/{group_id}', 'Изменить скидочную группу', 'Меняются только переданные поля.')
add('DELETE', '/cabinet/admin/promo-groups/{group_id}', 'Удалить скидочную группу', 'У пользователей группа снимается.')
add('GET', '/cabinet/admin/promo-codes', 'Промокоды', 'Все промокоды с числом активаций.')
add('POST', '/cabinet/admin/promo-codes', 'Создать промокод', 'Код приводится к верхнему регистру и должен быть уникальным. Тип `balance` (значение в копейках) или `days` (значение в днях).')
add('PATCH', '/cabinet/admin/promo-codes/{code_id}', 'Изменить промокод', 'Меняются только переданные поля.')
add('DELETE', '/cabinet/admin/promo-codes/{code_id}', 'Удалить промокод', 'Удаляет промокод.')
add('GET', '/cabinet/admin/campaigns', 'Маркетинговые кампании', 'Deep-link кампании с бонусом для новых пользователей (`start_parameter` — параметр ссылки бота).')
add('POST', '/cabinet/admin/campaigns', 'Создать кампанию', 'Бонус: на баланс, дни подписки или только атрибуция. `start_parameter` должен быть уникальным.')
add('PATCH', '/cabinet/admin/campaigns/{campaign_id}', 'Изменить кампанию', 'Меняются только переданные поля.')
add('DELETE', '/cabinet/admin/campaigns/{campaign_id}', 'Удалить кампанию', 'Удаляет кампанию.')
add('GET', '/cabinet/admin/campaigns/{campaign_id}/stats', 'Статистика кампании', 'Регистрации, платящие, конверсия, выручка.')
# --- админка: уведомления бота
add('GET', '/cabinet/admin/notifications/templates', 'Автоматические сообщения бота', 'Все 15 событий с текущим текстом, заводским текстом, переменными, признаками `is_customized`/`enabled`, подписью кнопки (если есть) и автором последней правки.')
add('PUT', '/cabinet/admin/notifications/templates/{key}', 'Изменить сообщение', 'Частичное обновление: применяются только переданные поля. `template` — текст в HTML Telegram (разрешённые теги, переменные `{имя}` из списка события; кастомные эмодзи — `<tg-emoji emoji-id="…">`); `template: null` возвращает заводской текст; `enabled: false` отключает отправку; `button_text` — подпись кнопки (у событий с кнопкой). Изменения действуют сразу. Ошибки проверок — `422` со списком сообщений.')
add('DELETE', '/cabinet/admin/notifications/templates/{key}', 'Сбросить сообщение к заводскому', 'Удаляет правку целиком (текст, кнопку, флаг «включено»). Повторный вызов безопасен.')
add('POST', '/cabinet/admin/notifications/templates/{key}/preview', 'Предпросмотр', 'Рендерит текст с примерами переменных без сохранения; возвращает длину видимого текста и предупреждения (например, про кастомные эмодзи). Пустое тело — предпросмотр текущего текста.')
add('POST', '/cabinet/admin/notifications/templates/{key}/test', 'Отправить тест мне', 'Отправляет предпросмотр вызвавшему админу в Telegram (с настоящей кнопкой, если она есть). `502` с текстом причины, если Telegram отклонил сообщение (например, недопустимое кастомное эмодзи).')
add('GET', '/cabinet/admin/notifications/emoji', 'Кастомные эмодзи', 'Кастомные эмодзи из `app/emoji.py` с заданным ID — для вставки в текст.')
# --- админка: рассылки
add('GET', '/cabinet/admin/broadcasts/options', 'Данные для формы рассылки', 'Категории аудитории и тарифы с live-счётчиком получателей, список доступных кнопок-конструктора.')
add('POST', '/cabinet/admin/broadcasts/preview', 'Предпросмотр аудитории', 'Название категории и число получателей без запуска рассылки. `400`, если `target` не входит в известные категории и не `tariff:<id>` существующего тарифа.')
add('POST', '/cabinet/admin/broadcasts/', 'Запустить рассылку', 'Создаёт запись и запускает отправку ФОНОВОЙ задачей — ответ `202` сразу, прогресс через `GET .../{id}`. Не более одной рассылки одновременно: `409`, если уже есть `in_progress`. `media_file_id` — Telegram file_id, полученный где-то ещё (загрузка файла через API не поддерживается). `400` при неизвестной аудитории/типе медиа/кнопке.')
add('GET', '/cabinet/admin/broadcasts/', 'История рассылок', 'Постранично, новые сверху.')
add('GET', '/cabinet/admin/broadcasts/{broadcast_id}', 'Статус рассылки', 'Для опроса прогресса: `total_count`/`sent_count`/`failed_count`/`blocked_count`, `status` (`in_progress`/`completed`/`partial`/`cancelled`/`interrupted`).')
add('POST', '/cabinet/admin/broadcasts/{broadcast_id}/cancel', 'Остановить рассылку', 'Не откатывает уже отправленные сообщения — останавливает перед следующей пачкой. `409`, если рассылка уже не `in_progress`.')
# --- система
add('GET', '/health', 'Проверка живости', 'Всегда `{"status": "ok"}`; базу данных и внешние сервисы не проверяет.')
add('GET', '/platega-webhook', 'Проверка адреса вебхука Platega', 'Platega обращается к адресу при сохранении вебхука в кабинете — без `200` сохранить его нельзя.')
add('POST', '/platega-webhook', 'Вебхук Platega', 'Подробности — в разделе «Вебхуки платёжных провайдеров» файла `API.md`.')
add('POST', '/cispay-webhook', 'Вебхук cisPay', 'Подробности — в разделе «Вебхуки платёжных провайдеров» файла `API.md`.')

GROUPS_USER = [
    ('Авторизация', ['/cabinet/auth/telegram']),
    ('Главная, профиль, настройки', ['/cabinet/dashboard', '/cabinet/profile', '/cabinet/settings/language']),
    ('Тарифы и подписка', ['/cabinet/tariffs', '/cabinet/subscription/purchase', '/cabinet/tariff/change-preview', '/cabinet/tariff/change', '/cabinet/connect-apps']),
    ('Устройства', ['/cabinet/devices', '/cabinet/devices/{hwid}']),
    ('Платежи, промокоды, подарки', ['/cabinet/transactions', '/cabinet/promocode/activate', '/cabinet/gift/purchase']),
    ('Рефералы', ['/cabinet/referral']),
]
GROUPS_ADMIN = [
    ('Аналитика', ['/cabinet/admin/overview', '/cabinet/admin/revenue-timeseries', '/cabinet/admin/recent-payments', '/cabinet/admin/sales-breakdown', '/cabinet/admin/revenue-composition', '/cabinet/admin/subscription-pulse', '/cabinet/admin/alerts', '/cabinet/admin/ltv', '/cabinet/admin/cohorts', '/cabinet/admin/referrals', '/cabinet/admin/net-profit']),
    ('Инфраструктура', ['/cabinet/admin/nodes', '/cabinet/admin/nodes/{node_uuid}', '/cabinet/admin/nodes/{node_uuid}/enable', '/cabinet/admin/nodes/{node_uuid}/disable', '/cabinet/admin/nodes/{node_uuid}/restart', '/cabinet/admin/infra-billing', '/cabinet/admin/monitoring']),
    ('Пользователи', ['/cabinet/admin/users', '/cabinet/admin/users/massban', '/cabinet/admin/users/{user_id}', '/cabinet/admin/users/{user_id}/balance', '/cabinet/admin/users/{user_id}/subscription-days', '/cabinet/admin/users/{user_id}/block', '/cabinet/admin/users/{user_id}/message', '/cabinet/admin/users/{user_id}/referral-commission', '/cabinet/admin/users/{user_id}/promo-group', '/cabinet/admin/users/{user_id}/devices', '/cabinet/admin/users/{user_id}/devices/{hwid}', '/cabinet/admin/users/{user_id}/traffic-by-node', '/cabinet/admin/users/{user_id}/sync/from-panel', '/cabinet/admin/users/{user_id}/sync/to-panel', '/cabinet/admin/users/{user_id}/transactions']),
    ('Подписки и транзакции', ['/cabinet/admin/subscriptions', '/cabinet/admin/transactions', '/cabinet/admin/transactions/platega-reconcile', '/cabinet/admin/transactions/{transaction_id}']),
    ('Поддержка', ['/cabinet/admin/support/threads', '/cabinet/admin/support/threads/{ticket_id}', '/cabinet/admin/support/threads/{ticket_id}/reply', '/cabinet/admin/support/threads/{ticket_id}/close', '/cabinet/admin/support/threads/{ticket_id}/reopen']),
    ('Скидки, промокоды, кампании', ['/cabinet/admin/promo-groups', '/cabinet/admin/promo-groups/{group_id}', '/cabinet/admin/promo-codes', '/cabinet/admin/promo-codes/{code_id}', '/cabinet/admin/campaigns', '/cabinet/admin/campaigns/{campaign_id}', '/cabinet/admin/campaigns/{campaign_id}/stats']),
    ('Уведомления бота', ['/cabinet/admin/notifications/templates', '/cabinet/admin/notifications/templates/{key}', '/cabinet/admin/notifications/templates/{key}/preview', '/cabinet/admin/notifications/templates/{key}/test', '/cabinet/admin/notifications/emoji']),
    ('Рассылки', ['/cabinet/admin/broadcasts/options', '/cabinet/admin/broadcasts/preview', '/cabinet/admin/broadcasts/', '/cabinet/admin/broadcasts/{broadcast_id}', '/cabinet/admin/broadcasts/{broadcast_id}/cancel']),
]
GROUPS_SYSTEM = [('Служебные', ['/health', '/platega-webhook', '/cispay-webhook'])]

METHOD_ORDER = ['get', 'post', 'patch', 'put', 'delete']


# ---- рендер типов ----------------------------------------------------------------------------------------------
def anchor_schema(name: str) -> str:
    return 'schema-' + re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def anchor_op(method: str, path: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', f'{method}-{path}'.lower()).strip('-')


def ref_name(ref: str) -> str:
    return ref.rsplit('/', 1)[-1]


def type_of(sch: dict, link_prefix: str = '') -> str:
    if not sch:
        return 'any'
    if '$ref' in sch:
        name = ref_name(sch['$ref'])
        return f'[{name}]({link_prefix}#{anchor_schema(name)})'
    for key in ('anyOf', 'oneOf'):
        if key in sch:
            parts = [type_of(p, link_prefix) for p in sch[key] if p.get('type') != 'null']
            nullable = any(p.get('type') == 'null' for p in sch[key])
            text = ' \\| '.join(parts) if parts else 'null'
            return text + (' \\| null' if nullable and parts else '')
    if 'allOf' in sch:
        return ' & '.join(type_of(p, link_prefix) for p in sch['allOf'])
    if 'enum' in sch:
        return 'enum: ' + ' \\| '.join(f'`{v}`' for v in sch['enum'])
    if 'const' in sch:
        return f'`{sch["const"]}`'
    t = sch.get('type')
    if t == 'array':
        return type_of(sch.get('items', {}), link_prefix) + '[]'
    if t == 'object':
        if 'additionalProperties' in sch and isinstance(sch['additionalProperties'], dict):
            return f'object<string, {type_of(sch["additionalProperties"], link_prefix)}>'
        return 'object'
    if t == 'string' and sch.get('format'):
        return f'string ({sch["format"]})'
    return t or 'any'


def constraints(sch: dict) -> str:
    bits = []
    for key, label in (('minimum', '≥'), ('maximum', '≤'), ('exclusiveMinimum', '>'), ('minLength', 'длина ≥'), ('maxLength', 'длина ≤')):
        if key in sch:
            bits.append(f'{label} {sch[key]}')
    if 'default' in sch:
        bits.append(f'по умолчанию `{json.dumps(sch["default"], ensure_ascii=False)}`')
    return ', '.join(bits)


def resolve(sch: dict) -> dict:
    if '$ref' in sch:
        return COMPONENTS[ref_name(sch['$ref'])]
    return sch


def fields_table(sch: dict, link_prefix: str = '') -> list[str]:
    sch = resolve(sch)
    props = sch.get('properties', {})
    if not props:
        return []
    required = set(sch.get('required', []))
    lines = ['| Поле | Тип | Обязательное | Примечание |', '|---|---|---|---|']
    for name, prop in props.items():
        note = ' '.join(x for x in [prop.get('description', ''), constraints(prop)] if x)
        lines.append(f'| `{name}` | {type_of(prop, link_prefix)} | {"да" if name in required else "нет"} | {note} |')
    return lines


def skeleton(sch: dict, depth: int = 0):
    sch = resolve(sch)
    for key in ('anyOf', 'oneOf'):
        if key in sch:
            options = [p for p in sch[key] if p.get('type') != 'null']
            return skeleton(options[0], depth) if options else None
    if 'enum' in sch:
        return sch['enum'][0]
    t = sch.get('type')
    if t == 'object' or 'properties' in sch:
        if depth > 2:
            return {}
        return {name: skeleton(p, depth + 1) for name, p in sch.get('properties', {}).items() if name in sch.get('required', [])}
    if t == 'array':
        return []
    if t == 'string':
        return 'string'
    if t == 'integer':
        return sch.get('default', sch.get('minimum', 0))
    if t == 'number':
        return sch.get('default', 0)
    if t == 'boolean':
        return sch.get('default', False)
    return None


def response_type(op: dict) -> tuple[str, str]:
    for code in ('200', '201'):
        if code in op['responses']:
            content = op['responses'][code].get('content', {}).get('application/json', {})
            sch = content.get('schema')
            return code, type_of(sch) if sch else '—'
    return '200', '—'


def is_secured(op: dict) -> bool:
    return bool(op.get('security'))


def render_op(method: str, path: str, op: dict, admin: bool) -> list[str]:
    key = f'{method.upper()} {path}'
    title, notes = S.get(key, (op.get('summary', key), []))
    lines = [f'### {method.upper()} `{path}` — {title}', f'<a id="{anchor_op(method, path)}"></a>', '']
    if notes:
        lines += [n if n.endswith(('.', '»', ')', '`')) else n for n in [' '.join(notes)]] + ['']
    if path.startswith('/cabinet/admin'):
        auth = 'администратор (`Authorization: Bearer`)'
    elif is_secured(op):
        auth = 'пользователь (`Authorization: Bearer`)'
    else:
        auth = 'не требуется' if not path.endswith('webhook') else 'по заголовкам провайдера (см. `API.md`)'
    lines += [f'**Доступ:** {auth}', '']

    params = op.get('parameters', [])
    if params:
        lines += ['**Параметры**', '', '| Имя | Где | Тип | Обязательный | Примечание |', '|---|---|---|---|---|']
        for p in params:
            note = ' '.join(x for x in [p.get('description', ''), constraints(p.get('schema', {}))] if x)
            lines.append(f'| `{p["name"]}` | {p["in"]} | {type_of(p.get("schema", {}))} | {"да" if p.get("required") else "нет"} | {note} |')
        lines.append('')

    body = op.get('requestBody', {}).get('content', {}).get('application/json', {}).get('schema')
    if body:
        lines += [f'**Тело запроса** (JSON): {type_of(body)}', '']
        table = fields_table(body)
        if table:
            lines += table + ['']
        example = skeleton(body)
        if example:
            lines += ['Заготовка (только обязательные поля, значения — заглушки по типу):', '', '```json', json.dumps(example, ensure_ascii=False, indent=2), '```', '']

    code, rtype = response_type(op)
    lines += [f'**Ответ {code}:** {rtype}', '']
    errors = ROUTE_ERRORS.get(key, [])
    error_rows = []
    if path.startswith('/cabinet/admin'):
        error_rows += [(401, 'Требуется авторизация / невалидный или истёкший токен'), (403, 'Требуются права администратора / пользователь заблокирован')]
    elif is_secured(op):
        error_rows += [(401, 'Требуется авторизация / невалидный или истёкший токен'), (403, 'Пользователь заблокирован')]
    if path == '/cabinet/auth/telegram':
        error_rows.append((401, '`initData` пустая, подпись неверна, данные устарели (старше 24 часов) или нет поля `user`'))
    for status_code, message in errors:
        if not (path in ('/cabinet/auth/telegram',) and status_code == 401):
            error_rows.append((status_code, message or 'см. описание'))
    if any(p.get('in') in ('query', 'path') for p in params) or body:
        error_rows.append((422, 'Ошибка валидации параметров или тела запроса'))
    error_rows = sorted(dict.fromkeys(error_rows), key=lambda row: (row[0], row[1]))
    if error_rows:
        lines += ['**Ошибки**', '', '| Код | Когда |', '|---|---|']
        lines += [f'| {c} | {m} |' for c, m in error_rows] + ['']
    lines += ['---', '']
    return lines


def render_group_file(title: str, intro: str, groups, admin: bool) -> str:
    out = [f'# {title}', '', intro, '']
    out += ['## Содержание', '']
    for name, paths in groups:
        out.append(f'- **{name}**')
        for path in paths:
            for method in METHOD_ORDER:
                op = schema['paths'].get(path, {}).get(method)
                if op:
                    label = S.get(f'{method.upper()} {path}', (op.get('summary'),))[0]
                    out.append(f'  - [{method.upper()} `{path}`](#{anchor_op(method, path)}) — {label}')
    out.append('')
    for name, paths in groups:
        out += [f'## {name}', '']
        for path in paths:
            for method in METHOD_ORDER:
                op = schema['paths'].get(path, {}).get(method)
                if op:
                    out += render_op(method, path, op, admin)
    return '\n'.join(out).rstrip() + '\n'


def render_schemas() -> str:
    out = ['# Схемы данных', '', 'Все структуры, используемые в запросах и ответах. Сгенерировано из OpenAPI-схемы (`docs/api/openapi.json`). Деньги — в копейках, если в имени поля `kopeks`; даты — ISO-8601 (UTC).', '']
    out += ['## Содержание', '']
    for name in sorted(COMPONENTS):
        out.append(f'- [{name}](#{anchor_schema(name)})')
    out.append('')
    for name in sorted(COMPONENTS):
        sch = COMPONENTS[name]
        out += [f'## {name}', f'<a id="{anchor_schema(name)}"></a>', '']
        if sch.get('description'):
            out += [sch['description'], '']
        table = fields_table(sch)
        if table:
            out += table + ['']
        elif 'enum' in sch:
            out += ['Значения: ' + ', '.join(f'`{v}`' for v in sch['enum']), '']
        else:
            out += [f'Тип: {sch.get("type", "object")}', '']
    return '\n'.join(out).rstrip() + '\n'


def used_schema_links_fix(text: str, prefix: str) -> str:
    """Ссылки на схемы ведут в schemas.md (в справочниках) — подставляем имя файла."""
    return re.sub(r'\]\(#(schema-[a-z0-9-]+)\)', rf']({prefix}schemas.md#\1)', text)


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    cabinet = render_group_file(
        'Справочник: пользовательский API (Mini App)',
        'Эндпоинты для Telegram Mini App. Базовые правила (авторизация, ошибки, деньги, даты) — в [API.md](API.md). Все эндпоинты, кроме входа, требуют заголовок `Authorization: Bearer <token>`.',
        GROUPS_USER, False)
    admin = render_group_file(
        'Справочник: административный API',
        'Эндпоинты веб-админки (`/cabinet/admin/*`). Доступны только администраторам: у пользователя должен стоять флаг `is_admin`, а его `telegram_id` — входить в `ADMIN_TELEGRAM_IDS`. Базовые правила — в [API.md](API.md). Размер страницы в списках — 20.',
        GROUPS_ADMIN, True)
    system = render_group_file(
        'Справочник: служебные эндпоинты и вебхуки',
        'Эндпоинты вне префикса `/cabinet`. Вебхуки вызывают платёжные провайдеры, а не клиентские приложения. Подробное описание — в [API.md](API.md).',
        GROUPS_SYSTEM, False)
    for name, text in (('reference-cabinet.md', cabinet), ('reference-admin.md', admin), ('reference-system.md', system)):
        (OUT / name).write_text(used_schema_links_fix(text, ''), encoding='utf-8')
    (OUT / 'schemas.md').write_text(render_schemas(), encoding='utf-8')
    (OUT / 'openapi.json').write_text(json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    covered = {p for _, ps in GROUPS_USER + GROUPS_ADMIN + GROUPS_SYSTEM for p in ps}
    missing = sorted(set(schema['paths']) - covered)
    print('missing from groups:', missing)
    print('summaries missing:', sorted({f'{m.upper()} {p}' for p, ops in schema['paths'].items() for m in ops} - set(S)))
