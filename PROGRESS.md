# Карта модулей и владения

Фундамент (config/models/mock-remnawave/payment-stub/dispatcher/miграции) — готов,
см. коммиты `Foundation scaffold`, `Add cross-module service contracts`, `Add seed script`.

| Модуль | Файлы | Статус | Зависит от |
|---|---|---|---|
| Регистрация/главное меню | `app/handlers/start.py` | Готово | `app/keyboards/main_menu.py`, `app/services/gift_service.py`, `app/services/referral_service.py` |
| Подписка (покупка/продление/устройства) | `app/handlers/subscription.py` | Готово | `app/external/remnawave`, `app/services/payment`, `app/services/referral_service.py`, `app/services/notification_service.py` |
| Реферал/промокод/подарок | `app/handlers/referral.py`, `app/handlers/promocode.py`, `app/handlers/gift.py`, + реализация `app/services/{referral,gift,promocode}_service.py` | Готово | — |
| Админка/поддержка/фон/уведомления | `app/handlers/admin.py`, `app/handlers/support.py`, `app/services/notification_service.py` (реализация), `app/services/background.py` (новый), хук в `main.py` | Готово | — |
| Шаблоны автоматических сообщений | `app/services/message_templates/*`, `app/services/notification_service.py` (тонкие обёртки), `app/handlers/message_templates_admin.py`, `app/cabinet/notifications_{routes,schemas}.py`, таблица `message_templates` | Готово (2026-09-21) | `app/emoji.py`, `app/services/notification_service.py` |
| Атомарный баланс, надзор за задачами, HTTP-ретраи | `app/services/balance_service.py`, `app/runtime.py`, `app/external/http.py` | Готово | — |
| Центр аналитики (журнал событий, сверка cisPay, отчёты) | по плану `docs/superpowers/plans/2026-09-21-analytics-foundation.md` | **Не начато** (спека и план готовы) | — |

## Известные ограничения (после сведения параллельной разработки)

- **Шаблоны сообщений — отложенные мелочи** (не блокируют): при падении БД каждая отправка заново пробует читать правки (нет бэкоффа); после сохранения кэш правок может быть устаревшим до 60 с у другого читателя (принято в спеке); пустой `PUT` на шаблон создаёт строку; в редакторе бота команда `/admin` внутри ввода текста принимается как текст (выход — «Отмена»); у не-админов на кнопках редактора не гаснет «часики»; в `docs/api/reference-admin.md` нет кодов 404/502 в таблицах ошибок (ограничение генератора). Кастомные эмодзи требуют Premium у владельца бота — проверяется только вручную на живом боте.
- **SQLite и Alembic:** цепочка миграций рассчитана на Postgres; локально используйте `scripts/init_local_db.py`.

- **Дублирование логики создания/продления Remnawave-пользователя**: `handlers/subscription.py` (покупка/продление владельцем) и `services/subscription_provisioning.py` (подарок/промокод-дни) реализуют одну и ту же операцию независимо, а не через общий хелпер. Не блокирует работу — обе ветки протестированы отдельно и после ревью синхронизированы по поведению (`enable_user` при продлении истёкшей подписки, сброс `reminder_*_sent`), но при будущих изменениях бизнес-правил продления нужно помнить про оба места.
- **Поддержка (`support.py`)**: ответ админа роутится только через сообщение, отправленное ПЕРВОМУ админу из `ADMIN_TELEGRAM_IDS` — если админов несколько, отвечать может только первый в списке.
- **`is_blocked`**: по-прежнему не централизовано в `AuthMiddleware` (осознанное решение — не создавать конфликт правок общего файла); проверяется явно в каждом чувствительном хендлере. По итогам ревью (2026-08-19) закрыто во всех денежных/бонусных точках входа: `support.py`, `subscription.py` (`cb_sub_buy`/`cb_sub_renew`/`cb_confirm_purchase`), `gift.py` (`cb_gift_menu`), `promocode.py` (все три хендлера), `referral.py` (`cb_referral_menu`), плюс `referral_service.py::credit_referral_earning` теперь не начисляет комиссию заблокированному рефереру. При добавлении новых чувствительных хендлеров проверку `db_user.is_blocked` по-прежнему нужно добавлять явно.
- **`PAYMENTS_MODE=real`**: подключена только Platega (СБП/карты, `app/services/payment/platega.py`) — CryptoBot/Stars остаются `NotImplementedError`/заглушкой под stub. Подтверждение платежа — через поллинг (`payment_poll_loop`, интервал по умолчанию 600с), НЕ вебхук — у проекта нет публичного URL/домена (см. диалог). Контекст незавершённого платежа (какую подписку/подарок выдать) хранится в `Payment.raw_payload`, доводит до конца `app/services/payment_finalization.py::finalize_pending_payment`. Для быстрой проверки без ожидания интервала — `scripts/poll_payments_once.py`. `PLATEGA_PAYMENT_METHOD_CODE` — один непрозрачный код на всех платежеспособов (кнопка в боте по-прежнему одна — «🏦 Карты и СБП»), сверить с личным кабинетом Platega перед продакшеном.

Единая точка регистрации хендлеров — `app/handlers/__init__.py`, каждый модуль
добавляет туда ровно одну строку (уже подготовлено).

Архитектурный документ (полная спецификация, все sequence-диаграммы):
https://claude.ai/code/artifact/3ec7e422-b599-49a8-b04d-f6514579382d
