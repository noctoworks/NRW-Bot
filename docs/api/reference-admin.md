# Справочник: административный API

Эндпоинты веб-админки (`/cabinet/admin/*`). Доступны только администраторам: у пользователя должен стоять флаг `is_admin`, а его `telegram_id` — входить в `ADMIN_TELEGRAM_IDS`. Базовые правила — в [API.md](API.md). Размер страницы в списках — 20.

## Содержание

- **Аналитика**
  - [GET `/cabinet/admin/overview`](#get-cabinet-admin-overview) — Обзор
  - [GET `/cabinet/admin/revenue-timeseries`](#get-cabinet-admin-revenue-timeseries) — Выручка по дням
  - [GET `/cabinet/admin/recent-payments`](#get-cabinet-admin-recent-payments) — Последние платежи
  - [GET `/cabinet/admin/sales-breakdown`](#get-cabinet-admin-sales-breakdown) — Разбивка продаж
  - [GET `/cabinet/admin/revenue-composition`](#get-cabinet-admin-revenue-composition) — Состав выручки по провайдерам и дням
  - [GET `/cabinet/admin/subscription-pulse`](#get-cabinet-admin-subscription-pulse) — Пульс подписок
  - [GET `/cabinet/admin/alerts`](#get-cabinet-admin-alerts) — Требует внимания
  - [GET `/cabinet/admin/ltv`](#get-cabinet-admin-ltv) — LTV
  - [GET `/cabinet/admin/cohorts`](#get-cabinet-admin-cohorts) — Когорты
  - [GET `/cabinet/admin/referrals`](#get-cabinet-admin-referrals) — Реферальная воронка
  - [GET `/cabinet/admin/referrals/timeseries`](#get-cabinet-admin-referrals-timeseries) — Динамика рефералов по дням
  - [GET `/cabinet/admin/net-profit`](#get-cabinet-admin-net-profit) — Чистая прибыль
- **Инфраструктура**
  - [GET `/cabinet/admin/nodes`](#get-cabinet-admin-nodes) — Список нод
  - [GET `/cabinet/admin/nodes/{node_uuid}`](#get-cabinet-admin-nodes-node-uuid) — Карточка ноды
  - [POST `/cabinet/admin/nodes/{node_uuid}/enable`](#post-cabinet-admin-nodes-node-uuid-enable) — Включить ноду
  - [POST `/cabinet/admin/nodes/{node_uuid}/disable`](#post-cabinet-admin-nodes-node-uuid-disable) — Отключить ноду
  - [POST `/cabinet/admin/nodes/{node_uuid}/restart`](#post-cabinet-admin-nodes-node-uuid-restart) — Перезапустить ноду
  - [GET `/cabinet/admin/infra-billing`](#get-cabinet-admin-infra-billing) — Расходы на инфраструктуру
  - [GET `/cabinet/admin/monitoring`](#get-cabinet-admin-monitoring) — Мониторинг
- **Пользователи**
  - [GET `/cabinet/admin/users`](#get-cabinet-admin-users) — Список пользователей
  - [POST `/cabinet/admin/users/massban`](#post-cabinet-admin-users-massban) — Массовая блокировка
  - [GET `/cabinet/admin/users/{user_id}`](#get-cabinet-admin-users-user-id) — Карточка пользователя
  - [DELETE `/cabinet/admin/users/{user_id}`](#delete-cabinet-admin-users-user-id) — Удалить (анонимизировать) пользователя
  - [POST `/cabinet/admin/users/{user_id}/balance`](#post-cabinet-admin-users-user-id-balance) — Изменить баланс
  - [POST `/cabinet/admin/users/{user_id}/subscription-days`](#post-cabinet-admin-users-user-id-subscription-days) — Продлить или сократить подписку
  - [POST `/cabinet/admin/users/{user_id}/block`](#post-cabinet-admin-users-user-id-block) — Заблокировать / разблокировать
  - [POST `/cabinet/admin/users/{user_id}/message`](#post-cabinet-admin-users-user-id-message) — Написать пользователю в Telegram
  - [POST `/cabinet/admin/users/{user_id}/referral-commission`](#post-cabinet-admin-users-user-id-referral-commission) — Персональный процент реферала
  - [POST `/cabinet/admin/users/{user_id}/promo-group`](#post-cabinet-admin-users-user-id-promo-group) — Назначить скидочную группу
  - [GET `/cabinet/admin/users/{user_id}/devices`](#get-cabinet-admin-users-user-id-devices) — Устройства пользователя
  - [DELETE `/cabinet/admin/users/{user_id}/devices`](#delete-cabinet-admin-users-user-id-devices) — Сбросить все устройства пользователя
  - [DELETE `/cabinet/admin/users/{user_id}/devices/{hwid}`](#delete-cabinet-admin-users-user-id-devices-hwid) — Удалить устройство пользователя
  - [GET `/cabinet/admin/users/{user_id}/traffic-by-node`](#get-cabinet-admin-users-user-id-traffic-by-node) — Трафик пользователя по нодам
  - [POST `/cabinet/admin/users/{user_id}/revoke-subscription`](#post-cabinet-admin-users-user-id-revoke-subscription) — Перевыпустить доступ
  - [POST `/cabinet/admin/users/{user_id}/sync/from-panel`](#post-cabinet-admin-users-user-id-sync-from-panel) — Синхронизировать из панели
  - [POST `/cabinet/admin/users/{user_id}/sync/to-panel`](#post-cabinet-admin-users-user-id-sync-to-panel) — Синхронизировать в панель
  - [GET `/cabinet/admin/users/{user_id}/transactions`](#get-cabinet-admin-users-user-id-transactions) — Транзакции пользователя
- **Подписки и транзакции**
  - [GET `/cabinet/admin/subscriptions`](#get-cabinet-admin-subscriptions) — Подписки всех пользователей
  - [GET `/cabinet/admin/transactions`](#get-cabinet-admin-transactions) — Транзакции всех пользователей
  - [GET `/cabinet/admin/transactions/platega-reconcile`](#get-cabinet-admin-transactions-platega-reconcile) — Сверка с кабинетом Platega
  - [GET `/cabinet/admin/transactions/{transaction_id}`](#get-cabinet-admin-transactions-transaction-id) — Детали транзакции
- **Поддержка**
  - [GET `/cabinet/admin/support/threads`](#get-cabinet-admin-support-threads) — Обращения в поддержку
  - [GET `/cabinet/admin/support/threads/{ticket_id}`](#get-cabinet-admin-support-threads-ticket-id) — Переписка по обращению
  - [POST `/cabinet/admin/support/threads/{ticket_id}/reply`](#post-cabinet-admin-support-threads-ticket-id-reply) — Ответить на обращение
  - [POST `/cabinet/admin/support/threads/{ticket_id}/close`](#post-cabinet-admin-support-threads-ticket-id-close) — Закрыть обращение
  - [POST `/cabinet/admin/support/threads/{ticket_id}/reopen`](#post-cabinet-admin-support-threads-ticket-id-reopen) — Открыть обращение снова
- **Скидки, промокоды, кампании**
  - [GET `/cabinet/admin/promo-groups`](#get-cabinet-admin-promo-groups) — Скидочные группы
  - [POST `/cabinet/admin/promo-groups`](#post-cabinet-admin-promo-groups) — Создать скидочную группу
  - [PATCH `/cabinet/admin/promo-groups/{group_id}`](#patch-cabinet-admin-promo-groups-group-id) — Изменить скидочную группу
  - [DELETE `/cabinet/admin/promo-groups/{group_id}`](#delete-cabinet-admin-promo-groups-group-id) — Удалить скидочную группу
  - [GET `/cabinet/admin/promo-codes`](#get-cabinet-admin-promo-codes) — Промокоды
  - [POST `/cabinet/admin/promo-codes`](#post-cabinet-admin-promo-codes) — Создать промокод
  - [PATCH `/cabinet/admin/promo-codes/{code_id}`](#patch-cabinet-admin-promo-codes-code-id) — Изменить промокод
  - [DELETE `/cabinet/admin/promo-codes/{code_id}`](#delete-cabinet-admin-promo-codes-code-id) — Удалить промокод
  - [GET `/cabinet/admin/campaigns`](#get-cabinet-admin-campaigns) — Маркетинговые кампании
  - [POST `/cabinet/admin/campaigns`](#post-cabinet-admin-campaigns) — Создать кампанию
  - [PATCH `/cabinet/admin/campaigns/{campaign_id}`](#patch-cabinet-admin-campaigns-campaign-id) — Изменить кампанию
  - [DELETE `/cabinet/admin/campaigns/{campaign_id}`](#delete-cabinet-admin-campaigns-campaign-id) — Удалить кампанию
  - [GET `/cabinet/admin/campaigns/{campaign_id}/stats`](#get-cabinet-admin-campaigns-campaign-id-stats) — Статистика кампании
- **Уведомления бота**
  - [GET `/cabinet/admin/notifications/templates`](#get-cabinet-admin-notifications-templates) — Автоматические сообщения бота
  - [PUT `/cabinet/admin/notifications/templates/{key}`](#put-cabinet-admin-notifications-templates-key) — Изменить сообщение
  - [DELETE `/cabinet/admin/notifications/templates/{key}`](#delete-cabinet-admin-notifications-templates-key) — Сбросить сообщение к заводскому
  - [POST `/cabinet/admin/notifications/templates/{key}/preview`](#post-cabinet-admin-notifications-templates-key-preview) — Предпросмотр
  - [POST `/cabinet/admin/notifications/templates/{key}/test`](#post-cabinet-admin-notifications-templates-key-test) — Отправить тест мне
  - [GET `/cabinet/admin/notifications/emoji`](#get-cabinet-admin-notifications-emoji) — Кастомные эмодзи
- **Рассылки**
  - [GET `/cabinet/admin/broadcasts/options`](#get-cabinet-admin-broadcasts-options) — Данные для формы рассылки
  - [POST `/cabinet/admin/broadcasts/preview`](#post-cabinet-admin-broadcasts-preview) — Предпросмотр аудитории
  - [GET `/cabinet/admin/broadcasts/`](#get-cabinet-admin-broadcasts) — История рассылок
  - [POST `/cabinet/admin/broadcasts/`](#post-cabinet-admin-broadcasts) — Запустить рассылку
  - [GET `/cabinet/admin/broadcasts/{broadcast_id}`](#get-cabinet-admin-broadcasts-broadcast-id) — Статус рассылки
  - [POST `/cabinet/admin/broadcasts/{broadcast_id}/cancel`](#post-cabinet-admin-broadcasts-broadcast-id-cancel) — Остановить рассылку

## Аналитика

### GET `/cabinet/admin/overview` — Обзор
<a id="get-cabinet-admin-overview"></a>

Главная сводка: выручка за сегодня/7/30 дней и всё время, подписки, пользователи, конверсия, средний чек, MRR/ARR, churn, трафик. MRR — прокси «выручка за 30 дней» (настоящего рекуррентного биллинга нет), ARR = MRR × 12.

**Доступ:** администратор (`Authorization: Bearer`)

**Ответ 200:** [OverviewResponse](schemas.md#schema-overviewresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |

---

### GET `/cabinet/admin/revenue-timeseries` — Выручка по дням
<a id="get-cabinet-admin-revenue-timeseries"></a>

Точка на каждый день периода: сумма и число платежей.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `days` | query | integer | нет | ≥ 1, ≤ 800, по умолчанию `30` |

**Ответ 200:** [RevenuePointOut](schemas.md#schema-revenuepointout)[]

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 422 | Ошибка валидации параметров или тела запроса |

---

### GET `/cabinet/admin/recent-payments` — Последние платежи
<a id="get-cabinet-admin-recent-payments"></a>

Лента последних успешных платежей (без оплат с баланса).

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `limit` | query | integer | нет | ≥ 1, ≤ 50, по умолчанию `10` |

**Ответ 200:** [RecentPaymentOut](schemas.md#schema-recentpaymentout)[]

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 422 | Ошибка валидации параметров или тела запроса |

---

### GET `/cabinet/admin/sales-breakdown` — Разбивка продаж
<a id="get-cabinet-admin-sales-breakdown"></a>

Выручка по типам транзакций, по платёжным провайдерам и по дням недели, а также число активных подписок по тарифам.

**Доступ:** администратор (`Authorization: Bearer`)

**Ответ 200:** [SalesBreakdownResponse](schemas.md#schema-salesbreakdownresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |

---

### GET `/cabinet/admin/revenue-composition` — Состав выручки по провайдерам и дням
<a id="get-cabinet-admin-revenue-composition"></a>

Для stacked-графика: список дней и ряд значений на каждого провайдера.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `days` | query | integer | нет | ≥ 1, ≤ 90, по умолчанию `30` |

**Ответ 200:** [RevenueCompositionResponse](schemas.md#schema-revenuecompositionresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 422 | Ошибка валидации параметров или тела запроса |

---

### GET `/cabinet/admin/subscription-pulse` — Пульс подписок
<a id="get-cabinet-admin-subscription-pulse"></a>

Новые и продлённые за сегодня, истекающие за 24 часа и за 3 дня.

**Доступ:** администратор (`Authorization: Bearer`)

**Ответ 200:** [SubscriptionPulseOut](schemas.md#schema-subscriptionpulseout)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |

---

### GET `/cabinet/admin/alerts` — Требует внимания
<a id="get-cabinet-admin-alerts"></a>

Живой снимок проблем: подписки на грани истечения, недоступные и отключённые ноды, высокая загрузка памяти панели, обращения без ответа. Истории состояний нет.

**Доступ:** администратор (`Authorization: Bearer`)

**Ответ 200:** [AlertOut](schemas.md#schema-alertout)[]

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |

---

### GET `/cabinet/admin/ltv` — LTV
<a id="get-cabinet-admin-ltv"></a>

ARPU, средний и медианный LTV платящих, топ-20 плательщиков.

**Доступ:** администратор (`Authorization: Bearer`)

**Ответ 200:** [LtvResponse](schemas.md#schema-ltvresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |

---

### GET `/cabinet/admin/cohorts` — Когорты
<a id="get-cabinet-admin-cohorts"></a>

Когорты по месяцу регистрации: выручка на пользователя по месяцам после регистрации.

**Доступ:** администратор (`Authorization: Bearer`)

**Ответ 200:** [CohortsResponse](schemas.md#schema-cohortsresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |

---

### GET `/cabinet/admin/referrals` — Реферальная воронка
<a id="get-cabinet-admin-referrals"></a>

Приглашённые, платящие из них, конверсия, выплаченные комиссии и топ рефереров.

**Доступ:** администратор (`Authorization: Bearer`)

**Ответ 200:** [ReferralFunnelResponse](schemas.md#schema-referralfunnelresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |

---

### GET `/cabinet/admin/referrals/timeseries` — Динамика рефералов по дням
<a id="get-cabinet-admin-referrals-timeseries"></a>

Ровно `days` точек (1–365, по умолчанию 30) по календарным дням UTC, по возрастанию, последняя — сегодня; дни без событий — нули. `invited` — зарегистрировавшиеся рефералы, `paid_first` — рефералы, чей ПЕРВЫЙ платёж (те же правила, что у `referred_paying_count`: подписка/подарок, завершён, не с баланса) пришёлся на этот день (каждый реферал считается один раз за всё время), `earnings_kopeks` — начисленные рефереру комиссии за день, в копейках. `422` при `days` вне 1–365.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `days` | query | integer | нет | ≥ 1, ≤ 365, по умолчанию `30` |

**Ответ 200:** [ReferralTimeseriesResponse](schemas.md#schema-referraltimeseriesresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 422 | Ошибка валидации параметров или тела запроса |

---

### GET `/cabinet/admin/net-profit` — Чистая прибыль
<a id="get-cabinet-admin-net-profit"></a>

Выручка минус расходы на инфраструктуру (данные Remnawave Infra Billing). Все суммы в рублях (число с плавающей точкой), а не в копейках.

**Доступ:** администратор (`Authorization: Bearer`)

**Ответ 200:** [NetProfitOut](schemas.md#schema-netprofitout)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |

---

## Инфраструктура

### GET `/cabinet/admin/nodes` — Список нод
<a id="get-cabinet-admin-nodes"></a>

Ноды из панели Remnawave.

**Доступ:** администратор (`Authorization: Bearer`)

**Ответ 200:** [NodeOut](schemas.md#schema-nodeout)[]

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |

---

### GET `/cabinet/admin/nodes/{node_uuid}` — Карточка ноды
<a id="get-cabinet-admin-nodes-node-uuid"></a>

Подробности ноды (`404`, если не найдена).

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `node_uuid` | path | string | да |  |

**Ответ 200:** [NodeDetailOut](schemas.md#schema-nodedetailout)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 422 | Ошибка валидации параметров или тела запроса |

---

### POST `/cabinet/admin/nodes/{node_uuid}/enable` — Включить ноду
<a id="post-cabinet-admin-nodes-node-uuid-enable"></a>

Команда панели Remnawave.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `node_uuid` | path | string | да |  |

**Ответ 200:** [NodeOut](schemas.md#schema-nodeout)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 422 | Ошибка валидации параметров или тела запроса |

---

### POST `/cabinet/admin/nodes/{node_uuid}/disable` — Отключить ноду
<a id="post-cabinet-admin-nodes-node-uuid-disable"></a>

Команда панели Remnawave.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `node_uuid` | path | string | да |  |

**Ответ 200:** [NodeOut](schemas.md#schema-nodeout)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 422 | Ошибка валидации параметров или тела запроса |

---

### POST `/cabinet/admin/nodes/{node_uuid}/restart` — Перезапустить ноду
<a id="post-cabinet-admin-nodes-node-uuid-restart"></a>

Команда панели Remnawave.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `node_uuid` | path | string | да |  |

**Ответ 200:** object

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 422 | Ошибка валидации параметров или тела запроса |

---

### GET `/cabinet/admin/infra-billing` — Расходы на инфраструктуру
<a id="get-cabinet-admin-infra-billing"></a>

Данные Infra Billing панели Remnawave (числа без указания валюты; считаются рублями).

**Доступ:** администратор (`Authorization: Bearer`)

**Ответ 200:** [InfraBillingOut](schemas.md#schema-infrabillingout)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |

---

### GET `/cabinet/admin/monitoring` — Мониторинг
<a id="get-cabinet-admin-monitoring"></a>

Состояние панели (память, процессор) и метрики нод.

**Доступ:** администратор (`Authorization: Bearer`)

**Ответ 200:** [MonitoringResponse](schemas.md#schema-monitoringresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |

---

## Пользователи

### GET `/cabinet/admin/users` — Список пользователей
<a id="get-cabinet-admin-users"></a>

Поиск `query` — по `telegram_id` (если введено число) или по части username или имени (`full_name`); `@` в начале игнорируется; регистр не важен на PostgreSQL, на SQLite (dev) — только для латиницы. Тот же поиск в списках подписок и транзакций. Фильтр `filter`: `all`, `no_sub` (без подписки), `blocked`, `blocked_bot` (заблокировали бота). Размер страницы 20.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `query` | query | string \| null | нет |  |
| `filter` | query | string | нет | по умолчанию `"all"` |
| `page` | query | integer | нет | ≥ 1, по умолчанию `1` |

**Ответ 200:** [AdminUserListResponse](schemas.md#schema-adminuserlistresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 400 | Неизвестный фильтр |
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 422 | Ошибка валидации параметров или тела запроса |

---

### POST `/cabinet/admin/users/massban` — Массовая блокировка
<a id="post-cabinet-admin-users-massban"></a>

Блокирует пользователей по списку `telegram_id`. Возвращает, сколько запрошено и сколько заблокировано (несуществующие id пропускаются).

**Доступ:** администратор (`Authorization: Bearer`)

**Тело запроса** (JSON): [MassbanRequest](schemas.md#schema-massbanrequest)

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `telegram_ids` | integer[] | да |  |

Заготовка (только обязательные поля, значения — заглушки по типу):

```json
{
  "telegram_ids": []
}
```

**Ответ 200:** [MassbanResponse](schemas.md#schema-massbanresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 400 | Список telegram_id пуст |
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 422 | Ошибка валидации параметров или тела запроса |

---

### GET `/cabinet/admin/users/{user_id}` — Карточка пользователя
<a id="get-cabinet-admin-users-user-id"></a>

Баланс, подписка, число приглашённых и сумма реферальных начислений, скидочная группа, персональный процент реферала, флаги блокировки и блокировки бота, последние транзакции.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `user_id` | path | integer | да |  |

**Ответ 200:** [AdminUserDetailResponse](schemas.md#schema-adminuserdetailresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Пользователь не найден |
| 422 | Ошибка валидации параметров или тела запроса |

---

### DELETE `/cabinet/admin/users/{user_id}` — Удалить (анонимизировать) пользователя
<a id="delete-cabinet-admin-users-user-id"></a>

Не физическое удаление: пользователь блокируется, username стирается. Финансовая история и рефералы сохраняются. Ответ `{"status": "anonymized"}`.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `user_id` | path | integer | да |  |

**Ответ 200:** object<string, string>

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Пользователь не найден |
| 422 | Ошибка валидации параметров или тела запроса |

---

### POST `/cabinet/admin/users/{user_id}/balance` — Изменить баланс
<a id="post-cabinet-admin-users-user-id-balance"></a>

Положительная сумма начисляет (создаёт транзакцию `topup`), отрицательная списывает (`refund`), но баланс не уходит ниже нуля. Пользователю приходит уведомление. Сумма — в рублях (`amount_rub`).

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `user_id` | path | integer | да |  |

**Тело запроса** (JSON): [BalanceAdjustRequest](schemas.md#schema-balanceadjustrequest)

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `amount_rub` | number | да |  |

Заготовка (только обязательные поля, значения — заглушки по типу):

```json
{
  "amount_rub": 0
}
```

**Ответ 200:** [AdminUserDetailResponse](schemas.md#schema-adminuserdetailresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 400 | Баланс уже равен 0 — списывать нечего |
| 400 | Сумма не может быть нулевой |
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Пользователь не найден |
| 422 | Ошибка валидации параметров или тела запроса |

---

### POST `/cabinet/admin/users/{user_id}/subscription-days` — Продлить или сократить подписку
<a id="post-cabinet-admin-users-user-id-subscription-days"></a>

Положительное число дней продлевает (если подписки нет — выдаёт на активном тарифе), отрицательное сокращает действующую подписку.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `user_id` | path | integer | да |  |

**Тело запроса** (JSON): [SubscriptionDaysAdjustRequest](schemas.md#schema-subscriptiondaysadjustrequest)

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `days` | integer | да |  |

Заготовка (только обязательные поля, значения — заглушки по типу):

```json
{
  "days": 0
}
```

**Ответ 200:** [AdminUserDetailResponse](schemas.md#schema-adminuserdetailresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 400 | Нет активного тарифа для выдачи подписки |
| 400 | У пользователя нет подписки — сокращать нечего |
| 400 | Число дней не может быть нулевым |
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Пользователь не найден |
| 422 | Ошибка валидации параметров или тела запроса |

---

### POST `/cabinet/admin/users/{user_id}/block` — Заблокировать / разблокировать
<a id="post-cabinet-admin-users-user-id-block"></a>

В кабинете заблокированный пользователь получает `403` на каждый запрос; в боте блокировка проверяется в обработчиках, связанных с деньгами и бонусами.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `user_id` | path | integer | да |  |

**Тело запроса** (JSON): [BlockRequest](schemas.md#schema-blockrequest)

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `blocked` | boolean | да |  |

Заготовка (только обязательные поля, значения — заглушки по типу):

```json
{
  "blocked": false
}
```

**Ответ 200:** [AdminUserDetailResponse](schemas.md#schema-adminuserdetailresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Пользователь не найден |
| 422 | Ошибка валидации параметров или тела запроса |

---

### POST `/cabinet/admin/users/{user_id}/message` — Написать пользователю в Telegram
<a id="post-cabinet-admin-users-user-id-message"></a>

Отправляет сообщение от имени бота. `{"status": "sent"}` при успехе; `{"status": "blocked_bot"}`, если пользователь заблокировал бота (флаг сохраняется); `502` при другой ошибке Telegram.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `user_id` | path | integer | да |  |

**Тело запроса** (JSON): [MessageRequest](schemas.md#schema-messagerequest)

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `text` | string | да |  |

Заготовка (только обязательные поля, значения — заглушки по типу):

```json
{
  "text": "string"
}
```

**Ответ 200:** object<string, string>

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Пользователь не найден |
| 422 | Ошибка валидации параметров или тела запроса |
| 502 | Не удалось отправить сообщение |

---

### POST `/cabinet/admin/users/{user_id}/referral-commission` — Персональный процент реферала
<a id="post-cabinet-admin-users-user-id-referral-commission"></a>

Задаёт процент комиссии реферера для этого пользователя (0–100) или сбрасывает на общий (`null`).

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `user_id` | path | integer | да |  |

**Тело запроса** (JSON): [ReferralCommissionRequest](schemas.md#schema-referralcommissionrequest)

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `commission_percent` | integer \| null | нет |  |

**Ответ 200:** [AdminUserDetailResponse](schemas.md#schema-adminuserdetailresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Пользователь не найден |
| 422 | Ошибка валидации параметров или тела запроса |

---

### POST `/cabinet/admin/users/{user_id}/promo-group` — Назначить скидочную группу
<a id="post-cabinet-admin-users-user-id-promo-group"></a>

Назначает скидочную группу; `promo_group_id: null` снимает её.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `user_id` | path | integer | да |  |

**Тело запроса** (JSON): [SetUserPromoGroupRequest](schemas.md#schema-setuserpromogrouprequest)

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `promo_group_id` | integer \| null | нет |  |

**Ответ 200:** [AdminUserDetailResponse](schemas.md#schema-adminuserdetailresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Пользователь не найден |
| 404 | Промогруппа не найдена |
| 422 | Ошибка валидации параметров или тела запроса |

---

### GET `/cabinet/admin/users/{user_id}/devices` — Устройства пользователя
<a id="get-cabinet-admin-users-user-id-devices"></a>

Устройства (HWID) из Remnawave. `404`, если у пользователя нет подписки в панели.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `user_id` | path | integer | да |  |

**Ответ 200:** [DeviceOut](schemas.md#schema-deviceout)[]

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Пользователь не найден |
| 422 | Ошибка валидации параметров или тела запроса |

---

### DELETE `/cabinet/admin/users/{user_id}/devices` — Сбросить все устройства пользователя
<a id="delete-cabinet-admin-users-user-id-devices"></a>

Удаляет все устройства на панели.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `user_id` | path | integer | да |  |

**Ответ 200:** object<string, string>

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Пользователь не найден |
| 404 | У пользователя нет активной подписки в Remnawave |
| 422 | Ошибка валидации параметров или тела запроса |

---

### DELETE `/cabinet/admin/users/{user_id}/devices/{hwid}` — Удалить устройство пользователя
<a id="delete-cabinet-admin-users-user-id-devices-hwid"></a>

Удаляет одно устройство по HWID.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `user_id` | path | integer | да |  |
| `hwid` | path | string | да |  |

**Ответ 200:** object<string, string>

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Пользователь не найден |
| 404 | У пользователя нет активной подписки в Remnawave |
| 422 | Ошибка валидации параметров или тела запроса |

---

### GET `/cabinet/admin/users/{user_id}/traffic-by-node` — Трафик пользователя по нодам
<a id="get-cabinet-admin-users-user-id-traffic-by-node"></a>

Расход трафика по нодам из Remnawave.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `user_id` | path | integer | да |  |
| `days` | query | integer | нет | по умолчанию `30` |

**Ответ 200:** [UserNodeTrafficOut](schemas.md#schema-usernodetrafficout)[]

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Пользователь не найден |
| 422 | Ошибка валидации параметров или тела запроса |

---

### POST `/cabinet/admin/users/{user_id}/revoke-subscription` — Перевыпустить доступ
<a id="post-cabinet-admin-users-user-id-revoke-subscription"></a>

Перевыпуск доступа в Remnawave. `mode`: `link_and_passwords` — новая ссылка подписки и новые пароли; `passwords_only` — только пароли, ссылка остаётся прежней (`revokeOnlyPasswords` на панели). Новая ссылка (`subscription_url`, `short_uuid`) записывается в БД — Mini App берёт её оттуда, «Синхронизировать из панели» ссылку не обновляет; в ответе — новая ссылка, либо `null` для `passwords_only`. `reset_devices` — заодно отвязать все устройства; `notify` — отправить пользователю сообщение бота (событие `subscription_revoked`, текст правится в «Уведомлениях бота»). `404` — нет `remnawave_uuid` или подписки. `502` — панель не ответила / не вернула ссылку, либо перевыпуск прошёл, но сбросить устройства не удалось (тогда ссылка в БД уже новая, а пользователь при `notify` уже получил сообщение — повторите сброс устройств).

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `user_id` | path | integer | да |  |

**Тело запроса** (JSON): [RevokeSubscriptionRequest](schemas.md#schema-revokesubscriptionrequest)

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `mode` | enum: `link_and_passwords` \| `passwords_only` | да |  |
| `reset_devices` | boolean | нет | по умолчанию `false` |
| `notify` | boolean | нет | по умолчанию `false` |

Заготовка (только обязательные поля, значения — заглушки по типу):

```json
{
  "mode": "link_and_passwords"
}
```

**Ответ 200:** [RevokeSubscriptionResponse](schemas.md#schema-revokesubscriptionresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Пользователь не найден |
| 404 | У пользователя нет remnawave_uuid |
| 404 | У пользователя нет подписки в БД |
| 422 | Ошибка валидации параметров или тела запроса |
| 502 | Доступ перевыпущен, но сбросить устройства не удалось — повторите сброс устройств |
| 502 | Не удалось перевыпустить доступ в Remnawave — попробуйте позже |
| 502 | Панель перевыпустила ссылку, но не вернула её — возьмите новую ссылку в Remnawave |

---

### POST `/cabinet/admin/users/{user_id}/sync/from-panel` — Синхронизировать из панели
<a id="post-cabinet-admin-users-user-id-sync-from-panel"></a>

Панель — источник истины: подтягивает трафик, срок и статус в БД.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `user_id` | path | integer | да |  |

**Ответ 200:** [SyncResultResponse](schemas.md#schema-syncresultresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Пользователь не найден |
| 404 | У пользователя нет remnawave_uuid |
| 404 | У пользователя нет подписки в БД |
| 422 | Ошибка валидации параметров или тела запроса |

---

### POST `/cabinet/admin/users/{user_id}/sync/to-panel` — Синхронизировать в панель
<a id="post-cabinet-admin-users-user-id-sync-to-panel"></a>

БД — источник истины: прописывает срок и статус в панель.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `user_id` | path | integer | да |  |

**Ответ 200:** [SyncResultResponse](schemas.md#schema-syncresultresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Пользователь не найден |
| 404 | У пользователя нет remnawave_uuid |
| 404 | У пользователя нет подписки в БД |
| 422 | Ошибка валидации параметров или тела запроса |

---

### GET `/cabinet/admin/users/{user_id}/transactions` — Транзакции пользователя
<a id="get-cabinet-admin-users-user-id-transactions"></a>

Постраничная история транзакций одного пользователя.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `user_id` | path | integer | да |  |
| `page` | query | integer | нет | ≥ 1, по умолчанию `1` |

**Ответ 200:** [app__cabinet__admin_schemas__PaginatedTransactionsResponse](schemas.md#schema-app-cabinet-admin-schemas-paginatedtransactionsresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Пользователь не найден |
| 422 | Ошибка валидации параметров или тела запроса |

---

## Подписки и транзакции

### GET `/cabinet/admin/subscriptions` — Подписки всех пользователей
<a id="get-cabinet-admin-subscriptions"></a>

Данные только из нашей БД (Remnawave не опрашивается). Фильтр `status`: `active`, `expired`, `disabled`; поиск `query` как в списке пользователей; сортировка по дате окончания (сначала дальние). Размер страницы 20.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `query` | query | string \| null | нет |  |
| `status` | query | string \| null | нет |  |
| `page` | query | integer | нет | ≥ 1, по умолчанию `1` |

**Ответ 200:** [SubscriptionListResponse](schemas.md#schema-subscriptionlistresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 400 | Неизвестный статус подписки |
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 422 | Ошибка валидации параметров или тела запроса |

---

### GET `/cabinet/admin/transactions` — Транзакции всех пользователей
<a id="get-cabinet-admin-transactions"></a>

Фильтры: `type` (`topup`, `subscription_payment`, `referral_reward`, `refund`, `gift`), `status` (`pending`, `completed`, `failed`), поиск `query`. Размер страницы 20.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `query` | query | string \| null | нет |  |
| `type` | query | string \| null | нет |  |
| `status` | query | string \| null | нет |  |
| `page` | query | integer | нет | ≥ 1, по умолчанию `1` |

**Ответ 200:** [TransactionListResponse](schemas.md#schema-transactionlistresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 400 | Неизвестный статус транзакции |
| 400 | Неизвестный тип транзакции |
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 422 | Ошибка валидации параметров или тела запроса |

---

### GET `/cabinet/admin/transactions/platega-reconcile` — Сверка с кабинетом Platega
<a id="get-cabinet-admin-transactions-platega-reconcile"></a>

Возвращает `{recordId: status}` за последние `days` дней (до 31). Реальный запрос к Platega боевыми ключами; в режиме `stub` возвращает пустой объект.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `days` | query | integer | нет | ≥ 1, ≤ 31, по умолчанию `7` |

**Ответ 200:** object<string, string>

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 422 | Ошибка валидации параметров или тела запроса |

---

### GET `/cabinet/admin/transactions/{transaction_id}` — Детали транзакции
<a id="get-cabinet-admin-transactions-transaction-id"></a>

Транзакция с данными платежа: `raw_payload`, сырой ответ провайдера.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `transaction_id` | path | integer | да |  |

**Ответ 200:** [AdminTransactionDetailResponse](schemas.md#schema-admintransactiondetailresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Транзакция не найдена |
| 422 | Ошибка валидации параметров или тела запроса |

---

## Поддержка

### GET `/cabinet/admin/support/threads` — Обращения в поддержку
<a id="get-cabinet-admin-support-threads"></a>

Тикеты: пользователь, последнее сообщение, статус, признак `unread` (последнее сообщение от пользователя без ответа), назначенный админ.

**Доступ:** администратор (`Authorization: Bearer`)

**Ответ 200:** [SupportThreadOut](schemas.md#schema-supportthreadout)[]

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |

---

### GET `/cabinet/admin/support/threads/{ticket_id}` — Переписка по обращению
<a id="get-cabinet-admin-support-threads-ticket-id"></a>

Все сообщения тикета.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `ticket_id` | path | integer | да |  |

**Ответ 200:** [SupportThreadDetailResponse](schemas.md#schema-supportthreaddetailresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Пользователь не найден |
| 404 | Тикет не найден |
| 422 | Ошибка валидации параметров или тела запроса |

---

### POST `/cabinet/admin/support/threads/{ticket_id}/reply` — Ответить на обращение
<a id="post-cabinet-admin-support-threads-ticket-id-reply"></a>

Отправляет ответ пользователю в Telegram. `502`, если отправить не удалось.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `ticket_id` | path | integer | да |  |

**Тело запроса** (JSON): [SupportReplyRequest](schemas.md#schema-supportreplyrequest)

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `text` | string | да |  |

Заготовка (только обязательные поля, значения — заглушки по типу):

```json
{
  "text": "string"
}
```

**Ответ 200:** object<string, string>

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Пользователь не найден |
| 404 | Тикет не найден |
| 422 | Ошибка валидации параметров или тела запроса |
| 502 | Не удалось отправить сообщение |

---

### POST `/cabinet/admin/support/threads/{ticket_id}/close` — Закрыть обращение
<a id="post-cabinet-admin-support-threads-ticket-id-close"></a>

Ответ `{"status": "closed"}`.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `ticket_id` | path | integer | да |  |

**Ответ 200:** object<string, string>

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Тикет не найден |
| 422 | Ошибка валидации параметров или тела запроса |

---

### POST `/cabinet/admin/support/threads/{ticket_id}/reopen` — Открыть обращение снова
<a id="post-cabinet-admin-support-threads-ticket-id-reopen"></a>

Ответ `{"status": "open"}`.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `ticket_id` | path | integer | да |  |

**Ответ 200:** object<string, string>

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Тикет не найден |
| 422 | Ошибка валидации параметров или тела запроса |

---

## Скидки, промокоды, кампании

### GET `/cabinet/admin/promo-groups` — Скидочные группы
<a id="get-cabinet-admin-promo-groups"></a>

Постоянные скидки для отдельных пользователей.

**Доступ:** администратор (`Authorization: Bearer`)

**Ответ 200:** [PromoGroupOut](schemas.md#schema-promogroupout)[]

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |

---

### POST `/cabinet/admin/promo-groups` — Создать скидочную группу
<a id="post-cabinet-admin-promo-groups"></a>

Название и процент скидки (0–100).

**Доступ:** администратор (`Authorization: Bearer`)

**Тело запроса** (JSON): [PromoGroupCreateRequest](schemas.md#schema-promogroupcreaterequest)

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `name` | string | да | длина ≥ 1, длина ≤ 64 |
| `discount_percent` | integer | да | ≥ 0.0, ≤ 100.0 |

Заготовка (только обязательные поля, значения — заглушки по типу):

```json
{
  "name": "string",
  "discount_percent": 0.0
}
```

**Ответ 200:** [PromoGroupOut](schemas.md#schema-promogroupout)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 422 | Ошибка валидации параметров или тела запроса |

---

### PATCH `/cabinet/admin/promo-groups/{group_id}` — Изменить скидочную группу
<a id="patch-cabinet-admin-promo-groups-group-id"></a>

Меняются только переданные поля.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `group_id` | path | integer | да |  |

**Тело запроса** (JSON): [PromoGroupUpdateRequest](schemas.md#schema-promogroupupdaterequest)

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `name` | string \| null | нет |  |
| `discount_percent` | integer \| null | нет |  |

**Ответ 200:** [PromoGroupOut](schemas.md#schema-promogroupout)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Промогруппа не найдена |
| 422 | Ошибка валидации параметров или тела запроса |

---

### DELETE `/cabinet/admin/promo-groups/{group_id}` — Удалить скидочную группу
<a id="delete-cabinet-admin-promo-groups-group-id"></a>

У пользователей группа снимается.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `group_id` | path | integer | да |  |

**Ответ 200:** object<string, string>

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Промогруппа не найдена |
| 422 | Ошибка валидации параметров или тела запроса |

---

### GET `/cabinet/admin/promo-codes` — Промокоды
<a id="get-cabinet-admin-promo-codes"></a>

Все промокоды с числом активаций.

**Доступ:** администратор (`Authorization: Bearer`)

**Ответ 200:** [PromoCodeOut](schemas.md#schema-promocodeout)[]

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |

---

### POST `/cabinet/admin/promo-codes` — Создать промокод
<a id="post-cabinet-admin-promo-codes"></a>

Код приводится к верхнему регистру и должен быть уникальным. Тип `balance` (значение в копейках) или `days` (значение в днях).

**Доступ:** администратор (`Authorization: Bearer`)

**Тело запроса** (JSON): [PromoCodeCreateRequest](schemas.md#schema-promocodecreaterequest)

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `code` | string | да | длина ≥ 1, длина ≤ 32 |
| `type` | enum: `balance` \| `days` | да |  |
| `value` | integer | да | > 0.0 |
| `max_activations` | integer | нет | > 0.0, по умолчанию `1` |
| `expires_at` | string (date-time) \| null | нет |  |

Заготовка (только обязательные поля, значения — заглушки по типу):

```json
{
  "code": "string",
  "type": "balance",
  "value": 0
}
```

**Ответ 200:** [PromoCodeOut](schemas.md#schema-promocodeout)

**Ошибки**

| Код | Когда |
|---|---|
| 400 | Код не может быть пустым |
| 400 | Промокод {…} уже существует |
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 422 | Ошибка валидации параметров или тела запроса |

---

### PATCH `/cabinet/admin/promo-codes/{code_id}` — Изменить промокод
<a id="patch-cabinet-admin-promo-codes-code-id"></a>

Меняются только переданные поля.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `code_id` | path | integer | да |  |

**Тело запроса** (JSON): [PromoCodeUpdateRequest](schemas.md#schema-promocodeupdaterequest)

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `is_active` | boolean | да |  |

Заготовка (только обязательные поля, значения — заглушки по типу):

```json
{
  "is_active": false
}
```

**Ответ 200:** [PromoCodeOut](schemas.md#schema-promocodeout)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Промокод не найден |
| 422 | Ошибка валидации параметров или тела запроса |

---

### DELETE `/cabinet/admin/promo-codes/{code_id}` — Удалить промокод
<a id="delete-cabinet-admin-promo-codes-code-id"></a>

Удаляет промокод.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `code_id` | path | integer | да |  |

**Ответ 200:** object<string, string>

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Промокод не найден |
| 422 | Ошибка валидации параметров или тела запроса |

---

### GET `/cabinet/admin/campaigns` — Маркетинговые кампании
<a id="get-cabinet-admin-campaigns"></a>

Deep-link кампании с бонусом для новых пользователей (`start_parameter` — параметр ссылки бота).

**Доступ:** администратор (`Authorization: Bearer`)

**Ответ 200:** [CampaignOut](schemas.md#schema-campaignout)[]

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |

---

### POST `/cabinet/admin/campaigns` — Создать кампанию
<a id="post-cabinet-admin-campaigns"></a>

Бонус: на баланс, дни подписки или только атрибуция. `start_parameter` должен быть уникальным.

**Доступ:** администратор (`Authorization: Bearer`)

**Тело запроса** (JSON): [CampaignCreateRequest](schemas.md#schema-campaigncreaterequest)

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `name` | string | да | длина ≥ 1, длина ≤ 128 |
| `start_parameter` | string | да | длина ≥ 1, длина ≤ 64 |
| `bonus_type` | string | да |  |
| `balance_bonus_kopeks` | integer | нет | ≥ 0.0, по умолчанию `0` |
| `subscription_duration_days` | integer \| null | нет |  |

Заготовка (только обязательные поля, значения — заглушки по типу):

```json
{
  "name": "string",
  "start_parameter": "string",
  "bonus_type": "string"
}
```

**Ответ 200:** [CampaignOut](schemas.md#schema-campaignout)

**Ошибки**

| Код | Когда |
|---|---|
| 400 | start_parameter уже занят другой кампанией |
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 422 | Ошибка валидации параметров или тела запроса |

---

### PATCH `/cabinet/admin/campaigns/{campaign_id}` — Изменить кампанию
<a id="patch-cabinet-admin-campaigns-campaign-id"></a>

Меняются только переданные поля.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `campaign_id` | path | integer | да |  |

**Тело запроса** (JSON): [CampaignUpdateRequest](schemas.md#schema-campaignupdaterequest)

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `name` | string \| null | нет |  |
| `is_active` | boolean \| null | нет |  |
| `balance_bonus_kopeks` | integer \| null | нет |  |
| `subscription_duration_days` | integer \| null | нет |  |

**Ответ 200:** [CampaignOut](schemas.md#schema-campaignout)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Кампания не найдена |
| 422 | Ошибка валидации параметров или тела запроса |

---

### DELETE `/cabinet/admin/campaigns/{campaign_id}` — Удалить кампанию
<a id="delete-cabinet-admin-campaigns-campaign-id"></a>

Удаляет кампанию.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `campaign_id` | path | integer | да |  |

**Ответ 200:** object<string, string>

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Кампания не найдена |
| 422 | Ошибка валидации параметров или тела запроса |

---

### GET `/cabinet/admin/campaigns/{campaign_id}/stats` — Статистика кампании
<a id="get-cabinet-admin-campaigns-campaign-id-stats"></a>

Регистрации, платящие, конверсия, выручка.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `campaign_id` | path | integer | да |  |

**Ответ 200:** [CampaignStatsResponse](schemas.md#schema-campaignstatsresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 404 | Кампания не найдена |
| 422 | Ошибка валидации параметров или тела запроса |

---

## Уведомления бота

### GET `/cabinet/admin/notifications/templates` — Автоматические сообщения бота
<a id="get-cabinet-admin-notifications-templates"></a>

Все 18 событий с текущим текстом, заводским текстом, переменными, признаками `is_customized`/`enabled`, подписью кнопки (если есть) и автором последней правки.

**Доступ:** администратор (`Authorization: Bearer`)

**Ответ 200:** [TemplateOut](schemas.md#schema-templateout)[]

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |

---

### PUT `/cabinet/admin/notifications/templates/{key}` — Изменить сообщение
<a id="put-cabinet-admin-notifications-templates-key"></a>

Частичное обновление: применяются только переданные поля. `template` — текст в HTML Telegram (разрешённые теги, переменные `{имя}` из списка события; кастомные эмодзи — `<tg-emoji emoji-id="…">`); `template: null` возвращает заводской текст; `enabled: false` отключает отправку; `button_text` — подпись кнопки (у событий с кнопкой). Изменения действуют сразу. Ошибки проверок — `422` со списком сообщений.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `key` | path | string | да |  |

**Тело запроса** (JSON): [TemplateUpdateRequest](schemas.md#schema-templateupdaterequest)

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `template` | string \| null | нет |  |
| `button_text` | string \| null | нет |  |
| `enabled` | boolean \| null | нет |  |

**Ответ 200:** [TemplateOut](schemas.md#schema-templateout)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 422 | Ошибка валидации параметров или тела запроса |

---

### DELETE `/cabinet/admin/notifications/templates/{key}` — Сбросить сообщение к заводскому
<a id="delete-cabinet-admin-notifications-templates-key"></a>

Удаляет правку целиком (текст, кнопку, флаг «включено»). Повторный вызов безопасен.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `key` | path | string | да |  |

**Ответ 200:** object

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 422 | Ошибка валидации параметров или тела запроса |

---

### POST `/cabinet/admin/notifications/templates/{key}/preview` — Предпросмотр
<a id="post-cabinet-admin-notifications-templates-key-preview"></a>

Рендерит текст с примерами переменных без сохранения; возвращает длину видимого текста и предупреждения (например, про кастомные эмодзи). Пустое тело — предпросмотр текущего текста.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `key` | path | string | да |  |

**Тело запроса** (JSON): [PreviewRequest](schemas.md#schema-previewrequest)

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `template` | string \| null | нет |  |
| `button_text` | string \| null | нет |  |

**Ответ 200:** [PreviewResponse](schemas.md#schema-previewresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 422 | Ошибка валидации параметров или тела запроса |

---

### POST `/cabinet/admin/notifications/templates/{key}/test` — Отправить тест мне
<a id="post-cabinet-admin-notifications-templates-key-test"></a>

Отправляет предпросмотр вызвавшему админу в Telegram (с настоящей кнопкой, если она есть). `502` с текстом причины, если Telegram отклонил сообщение (например, недопустимое кастомное эмодзи).

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `key` | path | string | да |  |

**Тело запроса** (JSON): [PreviewRequest](schemas.md#schema-previewrequest)

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `template` | string \| null | нет |  |
| `button_text` | string \| null | нет |  |

**Ответ 200:** object

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 422 | Ошибка валидации параметров или тела запроса |

---

### GET `/cabinet/admin/notifications/emoji` — Кастомные эмодзи
<a id="get-cabinet-admin-notifications-emoji"></a>

Кастомные эмодзи из `app/emoji.py` с заданным ID — для вставки в текст.

**Доступ:** администратор (`Authorization: Bearer`)

**Ответ 200:** [EmojiOut](schemas.md#schema-emojiout)[]

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |

---

## Рассылки

### GET `/cabinet/admin/broadcasts/options` — Данные для формы рассылки
<a id="get-cabinet-admin-broadcasts-options"></a>

Категории аудитории и тарифы с live-счётчиком получателей, список доступных кнопок-конструктора.

**Доступ:** администратор (`Authorization: Bearer`)

**Ответ 200:** [BroadcastOptionsResponse](schemas.md#schema-broadcastoptionsresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |

---

### POST `/cabinet/admin/broadcasts/preview` — Предпросмотр аудитории
<a id="post-cabinet-admin-broadcasts-preview"></a>

Название категории и число получателей без запуска рассылки. `400`, если `target` не входит в известные категории и не `tariff:<id>` существующего тарифа.

**Доступ:** администратор (`Authorization: Bearer`)

**Тело запроса** (JSON): [BroadcastPreviewRequest](schemas.md#schema-broadcastpreviewrequest)

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `target` | string | да |  |

Заготовка (только обязательные поля, значения — заглушки по типу):

```json
{
  "target": "string"
}
```

**Ответ 200:** [BroadcastPreviewResponse](schemas.md#schema-broadcastpreviewresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 422 | Ошибка валидации параметров или тела запроса |

---

### GET `/cabinet/admin/broadcasts/` — История рассылок
<a id="get-cabinet-admin-broadcasts"></a>

Постранично, новые сверху.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `page` | query | integer | нет | ≥ 1, по умолчанию `1` |

**Ответ 200:** [BroadcastListResponse](schemas.md#schema-broadcastlistresponse)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 422 | Ошибка валидации параметров или тела запроса |

---

### POST `/cabinet/admin/broadcasts/` — Запустить рассылку
<a id="post-cabinet-admin-broadcasts"></a>

Создаёт запись и запускает отправку ФОНОВОЙ задачей — ответ `202` сразу, прогресс через `GET .../{id}`. Не более одной рассылки одновременно: `409`, если уже есть `in_progress`. `media_file_id` — Telegram file_id, полученный где-то ещё (загрузка файла через API не поддерживается). `400` при неизвестной аудитории/типе медиа/кнопке.

**Доступ:** администратор (`Authorization: Bearer`)

**Тело запроса** (JSON): [BroadcastCreateRequest](schemas.md#schema-broadcastcreaterequest)

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `target` | string | да |  |
| `text` | string | да | длина ≥ 1, длина ≤ 4000 |
| `media_type` | string \| null | нет |  |
| `media_file_id` | string \| null | нет |  |
| `buttons` | string[] | нет |  |

Заготовка (только обязательные поля, значения — заглушки по типу):

```json
{
  "target": "string",
  "text": "string"
}
```

**Ответ 200:** —

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 422 | Ошибка валидации параметров или тела запроса |

---

### GET `/cabinet/admin/broadcasts/{broadcast_id}` — Статус рассылки
<a id="get-cabinet-admin-broadcasts-broadcast-id"></a>

Для опроса прогресса: `total_count`/`sent_count`/`failed_count`/`blocked_count`, `status` (`in_progress`/`completed`/`partial`/`cancelled`/`interrupted`).

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `broadcast_id` | path | integer | да |  |

**Ответ 200:** [BroadcastOut](schemas.md#schema-broadcastout)

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 422 | Ошибка валидации параметров или тела запроса |

---

### POST `/cabinet/admin/broadcasts/{broadcast_id}/cancel` — Остановить рассылку
<a id="post-cabinet-admin-broadcasts-broadcast-id-cancel"></a>

Не откатывает уже отправленные сообщения — останавливает перед следующей пачкой. `409`, если рассылка уже не `in_progress`.

**Доступ:** администратор (`Authorization: Bearer`)

**Параметры**

| Имя | Где | Тип | Обязательный | Примечание |
|---|---|---|---|---|
| `broadcast_id` | path | integer | да |  |

**Ответ 200:** —

**Ошибки**

| Код | Когда |
|---|---|
| 401 | Требуется авторизация / невалидный или истёкший токен |
| 403 | Требуются права администратора / пользователь заблокирован |
| 422 | Ошибка валидации параметров или тела запроса |

---
