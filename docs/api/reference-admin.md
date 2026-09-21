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

Поиск `query` — по `telegram_id` (если введено число) или по части username (без учёта регистра, `@` в начале игнорируется). Фильтр `filter`: `all`, `no_sub` (без подписки), `blocked`, `blocked_bot` (заблокировали бота). Размер страницы 20.

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
