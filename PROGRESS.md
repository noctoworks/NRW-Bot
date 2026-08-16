# Карта модулей и владения

Фундамент (config/models/mock-remnawave/payment-stub/dispatcher/miграции) — готов,
см. коммиты `Foundation scaffold`, `Add cross-module service contracts`, `Add seed script`.

| Модуль | Файлы | Статус | Зависит от |
|---|---|---|---|
| Регистрация/главное меню | `app/handlers/start.py` | Готово | `app/keyboards/main_menu.py`, `app/services/gift_service.py`, `app/services/referral_service.py` |
| Подписка (покупка/продление/устройства) | `app/handlers/subscription.py` | Готово | `app/external/remnawave`, `app/services/payment`, `app/services/referral_service.py`, `app/services/notification_service.py` |
| Реферал/промокод/подарок | `app/handlers/referral.py`, `app/handlers/promocode.py`, `app/handlers/gift.py`, + реализация `app/services/{referral,gift,promocode}_service.py` | Готово | — |
| Админка/поддержка/фон/уведомления | `app/handlers/admin.py`, `app/handlers/support.py`, `app/services/notification_service.py` (реализация), `app/services/background.py` (новый), хук в `main.py` | Готово | — |

## Известные ограничения (после сведения параллельной разработки)

- **Дублирование логики создания/продления Remnawave-пользователя**: `handlers/subscription.py` (покупка/продление владельцем) и `services/subscription_provisioning.py` (подарок/промокод-дни) реализуют одну и ту же операцию независимо, а не через общий хелпер. Не блокирует работу — обе ветки протестированы отдельно и после ревью синхронизированы по поведению (`enable_user` при продлении истёкшей подписки, сброс `reminder_*_sent`), но при будущих изменениях бизнес-правил продления нужно помнить про оба места.
- **Поддержка (`support.py`)**: ответ админа роутится только через сообщение, отправленное ПЕРВОМУ админу из `ADMIN_TELEGRAM_IDS` — если админов несколько, отвечать может только первый в списке.
- **`is_blocked`**: проверяется точечно внутри `support.py`; не централизовано в `AuthMiddleware` (осознанное решение агентов, чтобы не создавать конфликт правок общего файла). При добавлении новых чувствительных хендлеров проверку `db_user.is_blocked` нужно добавлять явно.
- **`payment_poll_loop`**: рабочий no-op при `PAYMENTS_MODE=stub` (это единственный поддерживаемый режим сейчас); логика опроса реальных pending-платежей помечена TODO, писать её нужно вместе с переводом `subscription.py` на `PAYMENTS_MODE=real`.

Единая точка регистрации хендлеров — `app/handlers/__init__.py`, каждый модуль
добавляет туда ровно одну строку (уже подготовлено).

Архитектурный документ (полная спецификация, все sequence-диаграммы):
https://claude.ai/code/artifact/3ec7e422-b599-49a8-b04d-f6514579382d
