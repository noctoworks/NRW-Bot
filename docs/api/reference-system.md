# Справочник: служебные эндпоинты и вебхуки

Эндпоинты вне префикса `/cabinet`. Вебхуки вызывают платёжные провайдеры, а не клиентские приложения. Подробное описание — в [API.md](API.md).

## Содержание

- **Служебные**
  - [GET `/health`](#get-health) — Проверка живости
  - [GET `/platega-webhook`](#get-platega-webhook) — Проверка адреса вебхука Platega
  - [POST `/platega-webhook`](#post-platega-webhook) — Вебхук Platega
  - [POST `/cispay-webhook`](#post-cispay-webhook) — Вебхук cisPay

## Служебные

### GET `/health` — Проверка живости
<a id="get-health"></a>

Всегда `{"status": "ok"}`; базу данных и внешние сервисы не проверяет.

**Доступ:** не требуется

**Ответ 200:** object<string, string>

---

### GET `/platega-webhook` — Проверка адреса вебхука Platega
<a id="get-platega-webhook"></a>

Platega обращается к адресу при сохранении вебхука в кабинете — без `200` сохранить его нельзя.

**Доступ:** по заголовкам провайдера (см. `API.md`)

**Ответ 200:** —

---

### POST `/platega-webhook` — Вебхук Platega
<a id="post-platega-webhook"></a>

Подробности — в разделе «Вебхуки платёжных провайдеров» файла `API.md`.

**Доступ:** по заголовкам провайдера (см. `API.md`)

**Ответ 200:** —

**Ошибки**

| Код | Когда |
|---|---|
| 400 | invalid_json |
| 400 | no_subscription_id |
| 400 | no_transaction_id |
| 400 | payment_not_found |
| 400 | processing_failed |
| 400 | subscription_not_found |
| 400 | verification_failed |
| 401 | unauthorized |

---

### POST `/cispay-webhook` — Вебхук cisPay
<a id="post-cispay-webhook"></a>

Подробности — в разделе «Вебхуки платёжных провайдеров» файла `API.md`.

**Доступ:** по заголовкам провайдера (см. `API.md`)

**Ответ 200:** —

**Ошибки**

| Код | Когда |
|---|---|
| 400 | invalid_json |
| 400 | no_transaction_id |
| 400 | payment_not_found |
| 400 | processing_failed |
| 400 | verification_failed |
| 401 | unauthorized |

---
